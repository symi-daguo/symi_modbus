"""Manages the panel buses of a config entry."""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import HomeAssistant

from . import PROTOCOLS
from ..const import LED_FRAME_REPORT
from .base import ButtonEvent, PanelProtocol
from .connection import PanelConnection

_LOGGER = logging.getLogger(__name__)

# Callbacks receive the id of the subentry the event belongs to and the event.
EventCallback = Callable[[str, ButtonEvent], None]
# Callbacks receive the new state of a button.
ButtonCallback = Callable[[Any], None]


class PanelManager:
    """Owns the panel buses of an entry and routes the button events.

    A panel bus is one serial line. Several panel subentries can share that
    line, because a RS485 bus carries the panels of one brand and every frame
    carries the address of the panel it belongs to. One connection serves all
    of them, so the bytes are never split between two readers.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._entry_id = entry_id
        # The open connections, one per serial port.
        self._buses: dict[str, PanelConnection] = {}
        self._protocols: dict[str, PanelProtocol] = {}
        # The panel subentries that use a port.
        self._members: dict[str, list[str]] = {}
        # The settings a port was opened with, a shared port has to use the
        # same ones.
        self._port_settings: dict[str, tuple[Any, ...]] = {}
        # The port a panel subentry uses.
        self._ports: dict[str, str] = {}
        self._panel_ids: dict[str, list[int]] = {}
        # The address of a button, learned from the button event of the
        # panel. Every button of a panel can use its own address.
        self._addresses: dict[tuple[str, int, int], tuple[int, int]] = {}
        self._buttons: dict[tuple[str, int, int], tuple[ButtonCallback, ButtonCallback]] = {}
        # The codes of the indicator light that were set by hand.
        self._manual_codes: dict[str, tuple[int | None, int | None]] = {}
        # What to tell in the log when a bus is up.
        self._bus_info: dict[str, tuple[str, str, str]] = {}
        self._event_listeners: list[EventCallback] = []

    @property
    def entry_id(self) -> str:
        """Return the id of the config entry the panels belong to."""
        return self._entry_id

    def add_event_listener(self, callback: EventCallback) -> None:
        """Register a listener for the button events."""
        self._event_listeners.append(callback)

    def add_button(
        self,
        subentry_id: str,
        panel_id: int,
        button: int,
        on_state: ButtonCallback,
        on_available: ButtonCallback,
    ) -> None:
        """Register the entity that shows a button."""
        self._buttons[(subentry_id, panel_id, button)] = (on_state, on_available)

    def remove_button(self, subentry_id: str, panel_id: int, button: int) -> None:
        """Remove the entity that shows a button."""
        self._buttons.pop((subentry_id, panel_id, button), None)

    async def async_add_bus(
        self,
        subentry_id: str,
        *,
        port: str,
        brand: str,
        panel_ids: list[int],
        led_frame_type: str = LED_FRAME_REPORT,
        led_codes: tuple[int | None, int | None] = (None, None),
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
    ) -> None:
        """Open a panel bus for a panel subentry.

        A port that is already open for another panel bus is shared, the
        panels of a line speak the same protocol and tell their address in
        every frame.
        """
        connection = self._buses.get(port)
        protocol = self._protocols.get(port)

        if connection is None:
            protocol = PROTOCOLS[brand](led_frame_type)
            connection = PanelConnection(
                hass=self._hass,
                port=port,
                protocol=protocol,
                on_event=self._make_handler(port),
                on_state=self._make_state_handler(port),
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
            )
            self._buses[port] = connection
            self._protocols[port] = protocol
            self._port_settings[port] = (
                brand,
                led_frame_type,
                baudrate,
                bytesize,
                parity,
                stopbits,
            )
            await connection.async_start()
        else:
            self._check_shared(
                port, brand, led_frame_type, baudrate, bytesize, parity, stopbits
            )

        self._members.setdefault(port, []).append(subentry_id)
        self._ports[subentry_id] = port
        self._panel_ids[subentry_id] = list(panel_ids)
        self._manual_codes[subentry_id] = led_codes
        self._bus_info[subentry_id] = (
            port,
            brand,
            ", ".join(f"{panel_id:02X}" for panel_id in panel_ids),
        )

        # Some brands only let the host drive the indicator lights after the
        # panel has been put into the right mode.
        for frame in protocol.prepare_frames(list(panel_ids)):
            await connection.async_write_raw(frame)

    def _check_shared(
        self,
        port: str,
        brand: str,
        led_frame_type: str,
        baudrate: int,
        bytesize: int,
        parity: str,
        stopbits: int,
    ) -> None:
        """Tell in the log when a shared port is used with other settings."""
        wanted = (brand, led_frame_type, baudrate, bytesize, parity, stopbits)
        if self._port_settings.get(port) != wanted:
            _LOGGER.error(
                "The panel bus %s is already open with other settings, the panel "
                "bus that uses it is served with the settings of the first one",
                port,
            )

    async def async_remove_bus(self, subentry_id: str) -> None:
        """Remove a panel bus."""
        port = self._ports.pop(subentry_id, None)
        self._panel_ids.pop(subentry_id, None)
        self._manual_codes.pop(subentry_id, None)
        self._bus_info.pop(subentry_id, None)
        for key in [key for key in self._addresses if key[0] == subentry_id]:
            self._addresses.pop(key, None)
        for key in [key for key in self._buttons if key[0] == subentry_id]:
            self._buttons.pop(key, None)

        if port is None:
            return
        members = self._members.get(port, [])
        if subentry_id in members:
            members.remove(subentry_id)
        if members:
            # Another panel bus still uses the port, it stays open.
            return
        self._members.pop(port, None)
        self._port_settings.pop(port, None)
        connection = self._buses.pop(port, None)
        self._protocols.pop(port, None)
        if connection is not None:
            await connection.async_stop()

    async def async_stop(self) -> None:
        """Close every panel bus."""
        for port in list(self._buses):
            connection = self._buses.pop(port, None)
            self._protocols.pop(port, None)
            self._members.pop(port, None)
            self._port_settings.pop(port, None)
            if connection is not None:
                await connection.async_stop()
        self._ports.clear()
        self._panel_ids.clear()
        self._manual_codes.clear()
        self._bus_info.clear()

    def panel_ids(self, subentry_id: str) -> list[int]:
        """Return the addresses of the panels on a bus."""
        return self._panel_ids.get(subentry_id, [])

    def own_handles(self) -> set[tuple[str, str]]:
        """Return the handles of the open panel buses.

        They belong to this integration, so they are left out when another
        program is looked for on the same serial port.
        """
        handles: set[tuple[str, str]] = set()
        for connection in self._buses.values():
            handles |= connection.own_handle()
        return handles

    def is_connected(self, subentry_id: str) -> bool:
        """Return whether the bus of a panel subentry is open."""
        connection = self._connection(subentry_id)
        return connection is not None and connection.is_connected

    def _connection(self, subentry_id: str) -> PanelConnection | None:
        """Return the connection a panel subentry uses."""
        port = self._ports.get(subentry_id)
        if port is None:
            return None
        return self._buses.get(port)

    async def async_set_button(
        self,
        subentry_id: str,
        panel_id: int,
        button: int,
        state: bool,
        code: int | None = None,
    ) -> None:
        """Write the indicator light of a button."""
        connection = self._connection(subentry_id)
        if connection is None:
            _LOGGER.warning(
                "No panel bus for %s, cannot set button %s of panel %s",
                subentry_id,
                button,
                panel_id,
            )
            return
        device_addr, channel = self._addresses.get(
            (subentry_id, panel_id, button), (1, button)
        )
        await connection.async_write_led(
            panel_id, button, state, device_addr, channel, code
        )

    def recent_traffic(self) -> dict[str, list[str]]:
        """Return the last chunks of every panel line."""
        return {
            port: connection.recent_traffic()
            for port, connection in self._buses.items()
        }

    def manual_codes(self, subentry_id: str) -> tuple[int | None, int | None]:
        """Return the codes of a panel bus that were set by hand.

        The first one is the code for the light on, the second one the code
        for the light off.
        """
        return self._manual_codes.get(subentry_id, (None, None))

    def _make_handler(self, port: str) -> Callable[[ButtonEvent], None]:
        """Return the handler that forwards the events of one port."""

        def handle(event: ButtonEvent) -> None:
            for subentry_id in self._members.get(port, []):
                if event.panel_id not in self._panel_ids.get(subentry_id, []):
                    # The panel belongs to another panel bus of this line.
                    continue
                self._handle_event(subentry_id, event)

        return handle

    def _make_state_handler(self, port: str) -> Callable[[bool], None]:
        """Return the handler that forwards the state of one port."""

        def handle(connected: bool) -> None:
            for subentry_id in self._members.get(port, []):
                self._handle_state(subentry_id, connected)

        return handle

    def _handle_event(self, subentry_id: str, event: ButtonEvent) -> None:
        """Forward a button event to the entities and the listeners."""
        if event.button:
            # The indicator light has to be written with the very address the
            # panel used in its button event, every button can use its own.
            key = (subentry_id, event.panel_id, event.button)
            self._addresses[key] = (event.device_addr, event.channel or event.button)

        _LOGGER.info(
            "Panel %s button %s reported %s",
            event.panel_id,
            event.button,
            "on" if event.state else "off",
        )

        callback = self._buttons.get((subentry_id, event.panel_id, event.button))
        if callback is not None:
            try:
                callback[0](event)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Panel button callback failed")

        for listener in self._event_listeners:
            try:
                listener(subentry_id, event)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Panel button listener failed")

    def _handle_state(self, subentry_id: str, connected: bool) -> None:
        """Tell the entities of a bus whether it is up."""
        if connected and (info := self._bus_info.get(subentry_id)) is not None:
            # The bus is only ready when its port is really open.
            _LOGGER.info("Panel bus on %s ready, brand %s, panel(s) %s", *info)
        for (button_subentry, _panel_id, _button), callbacks in self._buttons.items():
            if button_subentry != subentry_id:
                continue
            try:
                callbacks[1](connected)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Panel button callback failed")
