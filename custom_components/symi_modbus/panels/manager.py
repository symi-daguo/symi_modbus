"""Manages the panel buses of a config entry."""
from __future__ import annotations

import logging
from collections.abc import Callable

from homeassistant.core import HomeAssistant

from . import PROTOCOLS
from .base import ButtonEvent, PanelProtocol
from .connection import PanelConnection

_LOGGER = logging.getLogger(__name__)

# Callbacks receive the id of the subentry the event belongs to and the event.
EventCallback = Callable[[str, ButtonEvent], None]
# Callbacks receive the new state of a button.
ButtonCallback = Callable[[bool], None]


class PanelManager:
    """Owns the panel buses of an entry and routes the button events.

    Every panel subentry is one serial line with one brand. The manager keeps
    those lines open, hands the button events to the entities and writes the
    indicator lights back to the panels.
    """

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize the manager."""
        self._hass = hass
        self._entry_id = entry_id
        self._buses: dict[str, PanelConnection] = {}
        self._protocols: dict[str, PanelProtocol] = {}
        self._panel_ids: dict[str, list[int]] = {}
        self._device_addrs: dict[tuple[str, int], int] = {}
        self._buttons: dict[tuple[str, int, int], tuple[ButtonCallback, ButtonCallback]] = {}
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
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
    ) -> None:
        """Open a panel bus for a panel subentry."""
        protocol = PROTOCOLS[brand]()
        connection = PanelConnection(
            hass=self._hass,
            port=port,
            protocol=protocol,
            on_event=self._make_handler(subentry_id),
            on_state=self._make_state_handler(subentry_id),
            baudrate=baudrate,
            bytesize=bytesize,
            parity=parity,
            stopbits=stopbits,
        )

        self._buses[subentry_id] = connection
        self._protocols[subentry_id] = protocol
        self._panel_ids[subentry_id] = list(panel_ids)

        await connection.async_start()

        # Some brands only let the host drive the indicator lights after the
        # panel has been put into the right mode.
        for frame in protocol.prepare_frames(list(panel_ids)):
            await connection.async_write_raw(frame)

        _LOGGER.info(
            "Panel bus on %s ready, brand %s, panel(s) %s",
            port,
            brand,
            ", ".join(f"{panel_id:02X}" for panel_id in panel_ids),
        )

    async def async_remove_bus(self, subentry_id: str) -> None:
        """Close a panel bus."""
        connection = self._buses.pop(subentry_id, None)
        self._protocols.pop(subentry_id, None)
        self._panel_ids.pop(subentry_id, None)
        for key in [key for key in self._device_addrs if key[0] == subentry_id]:
            self._device_addrs.pop(key, None)
        for key in [key for key in self._buttons if key[0] == subentry_id]:
            self._buttons.pop(key, None)
        if connection is not None:
            await connection.async_stop()

    async def async_stop(self) -> None:
        """Close every panel bus."""
        for subentry_id in list(self._buses):
            await self.async_remove_bus(subentry_id)

    def panel_ids(self, subentry_id: str) -> list[int]:
        """Return the addresses of the panels on a bus."""
        return self._panel_ids.get(subentry_id, [])

    def is_connected(self, subentry_id: str) -> bool:
        """Return whether the bus of a panel subentry is open."""
        connection = self._buses.get(subentry_id)
        return connection is not None and connection.is_connected

    async def async_set_button(
        self, subentry_id: str, panel_id: int, button: int, state: bool
    ) -> None:
        """Write the indicator light of a button."""
        connection = self._buses.get(subentry_id)
        if connection is None:
            _LOGGER.warning(
                "No panel bus for %s, cannot set button %s of panel %s",
                subentry_id,
                button,
                panel_id,
            )
            return
        device_addr = self._device_addrs.get((subentry_id, panel_id), 1)
        await connection.async_write_led(panel_id, button, state, device_addr)

    def _make_handler(self, subentry_id: str) -> Callable[[ButtonEvent], None]:
        """Return the handler that forwards the events of one bus."""

        def handle(event: ButtonEvent) -> None:
            self._handle_event(subentry_id, event)

        return handle

    def _make_state_handler(self, subentry_id: str) -> Callable[[bool], None]:
        """Return the handler that forwards the state of one bus."""

        def handle(connected: bool) -> None:
            self._handle_state(subentry_id, connected)

        return handle

    def _handle_event(self, subentry_id: str, event: ButtonEvent) -> None:
        """Forward a button event to the entities and the listeners."""
        if event.button:
            # Remember the logical device address, the indicator light has to
            # be written with the same address the panel used.
            self._device_addrs[(subentry_id, event.panel_id)] = event.device_addr

        _LOGGER.debug(
            "Panel %s button %s reported %s",
            event.panel_id,
            event.button,
            "on" if event.state else "off",
        )

        callback = self._buttons.get((subentry_id, event.panel_id, event.button))
        if callback is not None:
            try:
                callback[0](event.state)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Panel button callback failed")

        for listener in self._event_listeners:
            try:
                listener(subentry_id, event)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Panel button listener failed")

    def _handle_state(self, subentry_id: str, connected: bool) -> None:
        """Tell the entities of a bus whether it is up."""
        for (button_subentry, _panel_id, _button), callbacks in self._buttons.items():
            if button_subentry != subentry_id:
                continue
            try:
                callbacks[1](connected)
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Panel button callback failed")
