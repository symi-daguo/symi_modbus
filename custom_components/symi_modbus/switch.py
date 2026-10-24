"""Support for the Symi Modbus switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_BRAND,
    CONF_BUTTONS,
    CONF_COIL_COUNT,
    CONF_PANEL_IDS,
    CONF_SLAVE,
    DEFAULT_COIL_COUNT,
    DOMAIN,
    SUBENTRY_PANEL,
    SUBENTRY_SLAVE,
)
from .modbus import ModbusHub
from .panels.base import ButtonEvent
from .panels.manager import PanelManager

_LOGGER = logging.getLogger(__name__)

# The slaves share one serial line, so they are polled one after the other.
PARALLEL_UPDATES = 0

# Key of the first coil of a slave.
CONF_COIL_START = "start"


def _codes_from_options(options: dict[str, Any]) -> dict[str, int]:
    """Return the codes of a panel that are kept with the entity.

    The codes live in the options of the entity, under the domain of the
    integration, the way Home Assistant keeps the options of an entity.
    """
    own = options.get(DOMAIN) or {}
    codes: dict[str, int] = {}
    if "on_code" in own:
        codes["on"] = int(own["on_code"])
    if "off_code" in own:
        codes["off"] = int(own["off_code"])
    return codes


def _options_with_codes(options: dict[str, Any], codes: dict[str, int]) -> dict[str, Any]:
    """Return the options of the entity with the learned codes.

    Only the codes that were learned are kept. A code that was not learned
    must not be written as a zero, the panel would read the zero as the code
    of the other state.
    """
    own = dict(options.get(DOMAIN) or {})
    own.pop("on_code", None)
    own.pop("off_code", None)
    if "on" in codes:
        own["on_code"] = codes["on"]
    if "off" in codes:
        own["off_code"] = codes["off"]
    return own


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches of every slave and every panel of this entry."""
    hub: ModbusHub = config_entry.runtime_data.hub
    panels: PanelManager = config_entry.runtime_data.panels

    # The unique ids of the entities that are configured right now. Everything
    # else that belongs to this entry was taken out of the configuration and
    # has to go, otherwise it stays behind as a ghost.
    expected: set[str] = set()

    for subentry in config_entry.get_subentries_of_type(SUBENTRY_SLAVE):
        slave = int(subentry.data[CONF_SLAVE])
        start = int(subentry.data.get(CONF_COIL_START, 0))
        count = int(subentry.data.get(CONF_COIL_COUNT, DEFAULT_COIL_COUNT))

        entities = [
            ModbusCoilSwitch(
                hub,
                slave,
                start + offset,
                offset + 1,
                f"{config_entry.entry_id}_{slave}_{start + offset}",
            )
            for offset in range(count)
        ]
        expected.update(entity.unique_id for entity in entities)
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)

    for subentry in config_entry.get_subentries_of_type(SUBENTRY_PANEL):
        brand = str(subentry.data[CONF_BRAND])
        buttons = int(subentry.data.get(CONF_BUTTONS, 8))

        entities = []
        for panel_id in subentry.data.get(CONF_PANEL_IDS, []):
            for button in range(1, buttons + 1):
                entities.append(
                    PanelButtonSwitch(
                        panels,
                        subentry.subentry_id,
                        int(panel_id),
                        button,
                        brand,
                        f"{config_entry.entry_id}_panel_"
                        f"{subentry.subentry_id}_{panel_id}_{button}",
                    )
                )
        expected.update(entity.unique_id for entity in entities)
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)

    _async_remove_stale(hass, config_entry, expected)
    _async_reset_stale_names(hass, config_entry.entry_id)


def _stale_names(entries: list[Any]) -> list[str]:
    """Return the entities that carry a name of an earlier version.

    An entity that an earlier version of the integration created has a name
    of its own in the registry. The name of such an entity is then not the
    name of the device and the entity, and the entities do not stand in the
    order a person expects: the coils of the slaves first, then the buttons
    of the panels. A name that the user gave stays as it is.
    """
    return [
        entry.entity_id
        for entry in entries
        if entry.name is not None
        and entry.original_name is not None
        and entry.name == entry.original_name
    ]


def _async_reset_stale_names(hass: HomeAssistant, entry_id: str) -> None:
    """Give the entities that carry a name of their own the name of the device."""
    registry = er.async_get(hass)
    for entity_id in _stale_names(
        er.async_entries_for_config_entry(registry, entry_id)
    ):
        _LOGGER.debug(
            "The entity %s carries the name of an earlier version, it is reset "
            "to the name of the device and the entity",
            entity_id,
        )
        registry.async_update_entity(entity_id, name=None)


def _stale_entries(entries: list[Any], prefix: str, expected: set[str]) -> list[Any]:
    """Return the entries of this integration that are not configured any more.

    Only the entries whose unique id starts with the prefix of the entry belong
    to this integration, the ones that are configured right now are kept.
    """
    return [
        entry
        for entry in entries
        if entry.unique_id.startswith(prefix) and entry.unique_id not in expected
    ]


def _async_remove_stale(
    hass: HomeAssistant, config_entry: ConfigEntry, expected: set[str]
) -> None:
    """Remove the entities that are not configured any more.

    Home Assistant keeps the entities of a config entry in its registry, also
    when the integration does not add them any more. A panel that was taken
    off the bus, or a coil that was taken off a slave, would stay behind as a
    device that shows nothing but unavailable switches.
    """
    registry = er.async_get(hass)
    prefix = f"{config_entry.entry_id}_"

    stale = _stale_entries(
        er.async_entries_for_config_entry(registry, config_entry.entry_id),
        prefix,
        expected,
    )
    if not stale:
        return

    devices = dr.async_get(hass)
    device_ids = {entry.device_id for entry in stale if entry.device_id}

    for entry in stale:
        _LOGGER.debug(
            "Removing the entity %s, it is not configured any more", entry.entity_id
        )
        registry.async_remove(entry.entity_id)

    for device_id in device_ids:
        if er.async_entries_for_device(registry, device_id, include_disabled_entities=True):
            continue
        device = devices.async_get(device_id)
        if device is not None:
            _LOGGER.debug("Removing the device %s, it has no entities left", device.name)
            devices.async_remove_device(device_id)


class ModbusCoilSwitch(SwitchEntity):
    """Representation of a single Modbus coil."""

    _attr_has_entity_name = True
    _attr_translation_key = "coil"
    _attr_device_class = "switch"

    def __init__(
        self,
        hub: ModbusHub,
        slave: int,
        address: int,
        line_number: int,
        unique_id: str,
    ) -> None:
        """Initialize the Modbus switch."""
        self._hub = hub
        self._slave = slave
        self._address = address
        self._line_number = line_number
        self._attr_unique_id = unique_id
        self._attr_translation_placeholders = {
            "slave": f"{slave:02X}",
            "line": f"{line_number:02d}",
        }
        self._is_on = False
        # The slave has not answered yet, so the state is not confirmed.
        self._attr_available = False

        self._hub.add_callback(self.async_on_state_change)
        self._hub.add_availability_callback(self._on_hub_available)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device this coil belongs to."""
        conn = "TCP" if self._hub.connection_type == "tcp" else "Serial"
        return DeviceInfo(
            # The entry id keeps the device stable even when the title changes.
            identifiers={(DOMAIN, f"{self._hub.entry_id}_{self._slave}")},
            # The slave id is part of the entity name, so it stays readable in
            # the entity list.
            name=f"{conn} {self._hub.endpoint}",
            manufacturer="Symi",
            model="Modbus Relay Module",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the coil is on."""
        return self._is_on

    @callback
    def _on_hub_available(self, available: bool, slave: int) -> None:
        """Mirror the availability of this slave on the entity."""
        if slave != self._slave:
            return
        if self._attr_available == available:
            return
        self._attr_available = available
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the coil on."""
        ok = await self._hub.write_coil(self._slave, self._address, True)
        if ok:
            self._is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the coil off."""
        ok = await self._hub.write_coil(self._slave, self._address, False)
        if ok:
            self._is_on = False
            self.async_write_ha_state()

    @callback
    def async_on_state_change(self, data: dict[int, bool], slave: int) -> None:
        """Update the state when the hub reports new values."""
        if slave != self._slave:
            return

        if self._address not in data:
            return

        new_state = data[self._address]
        changed = new_state != self._is_on
        self._is_on = new_state
        if changed:
            _LOGGER.debug(
                "Coil %s of slave %s is %s", self._address, self._slave, new_state
            )
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last known state from the hub cache."""
        state = self._hub.get_state(self._slave, self._address)
        if state is not None:
            self._is_on = state
        # The slave may have answered before this entity was added, so the
        # current availability is read instead of waiting for a change.
        if self._hub.is_slave_available(self._slave):
            self._attr_available = True


class PanelButtonSwitch(SwitchEntity):
    """Representation of a button of a wall panel.

    The state of the entity is the state of the indicator light of the
    button. A press of the button is reported by the panel bus and a change
    of the entity writes the indicator light back to the panel.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "panel_button"
    _attr_device_class = "switch"

    def __init__(
        self,
        panels: PanelManager,
        subentry_id: str,
        panel_id: int,
        button: int,
        brand: str,
        unique_id: str,
    ) -> None:
        """Initialize the panel button."""
        self._panels = panels
        self._subentry_id = subentry_id
        self._panel_id = panel_id
        self._button = button
        self._brand = brand
        self._attr_unique_id = unique_id
        self._attr_translation_placeholders = {
            "brand": brand,
            "panel": f"{panel_id:02X}",
            "button": f"{button:02d}",
        }
        self._is_on = False
        # The codes the panel uses for the state it reports, learned from the
        # frames of the panel and kept, so the light is driven with the codes
        # the panel understands.
        self._codes: dict[str, int] = {}
        self._attr_available = panels.is_connected(subentry_id)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device this button belongs to."""
        return DeviceInfo(
            identifiers={
                (
                    DOMAIN,
                    f"{self._panels.entry_id}_panel_{self._subentry_id}_{self._panel_id}",
                )
            },
            name=f"{self._brand.upper()} {self._panel_id:02X}",
            manufacturer="Symi",
            model=f"{self._brand} Wall Panel",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the indicator light is on."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Start listening for the button of this panel."""
        self._panels.add_button(
            self._subentry_id,
            self._panel_id,
            self._button,
            self._async_button_event,
            self._async_bus_state,
        )
        self._async_load_codes()
        self._attr_available = self._panels.is_connected(self._subentry_id)

    def _async_load_codes(self) -> None:
        """Read the codes that were learned before."""
        registry = er.async_get(self.hass)
        registry_entry = registry.async_get(self.entity_id)
        if registry_entry is None:
            return
        self._codes.update(_codes_from_options(registry_entry.options or {}))

    def _async_save_codes(self) -> None:
        """Keep the learned codes, they survive a restart."""
        registry = er.async_get(self.hass)
        registry_entry = registry.async_get(self.entity_id)
        if registry_entry is None:
            return
        registry.async_update_entity_options(
            self.entity_id,
            DOMAIN,
            _options_with_codes(registry_entry.options or {}, self._codes),
        )

    def _state_of(self, code: int) -> bool | None:
        """Return the state a code stands for, None when it is unknown."""
        # A code that was set by hand is the most certain one.
        manual_on, manual_off = self._panels.manual_codes(self._subentry_id)
        if manual_on != manual_off:
            if code == manual_on:
                return True
            if code == manual_off:
                return False
        on = self._codes.get("on")
        off = self._codes.get("off")
        if on is not None and on == off:
            # The two codes cannot be told apart, so neither of them is used.
            return None
        if on == code:
            return True
        if off == code:
            return False
        return None

    def _press_state(self, event: ButtonEvent) -> tuple[bool, bool]:
        """Return the state a press goes to and whether the code is new.

        A code that is known tells the state, also when the entity is out of
        step because the relay wrote the light. A code that is not known yet
        is read the way the brand of the panel reads it, so the state of the
        entity is not used for it.
        """
        if event.is_toggle:
            # The panel does not tell which state the button goes to, the
            # light of the button is toggled and there is no code to learn.
            return not self._is_on, False
        known = self._state_of(event.code)
        if known is not None:
            return known, False
        return event.state, True

    def _async_learn(self, code: int, state: bool) -> None:
        """Remember the code the panel uses for this state."""
        key = "on" if state else "off"
        if self._codes.get(key) == code:
            return
        self._codes[key] = code
        _LOGGER.info(
            "Panel %s button %s uses the code %s for %s",
            self._panel_id,
            self._button,
            code,
            key,
        )
        self._async_save_codes()

    def _learned_code(self, state: bool) -> int | None:
        """Return the learned code for this state, None when it cannot be used.

        Two codes that are the same cannot be told apart, so neither of them
        is used. A state whose code was never learned has no code either.
        """
        on = self._codes.get("on")
        off = self._codes.get("off")
        if on is not None and off is not None and on == off:
            return None
        return on if state else off

    def _code_for(self, state: bool) -> int:
        """Return the code the panel uses for this state."""
        manual_on, manual_off = self._panels.manual_codes(self._subentry_id)
        if manual_on != manual_off:
            code = manual_on if state else manual_off
            if code is not None:
                return code
        learned = self._learned_code(state)
        if learned is not None:
            return learned
        return 1 if state else 0

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening for the button of this panel."""
        self._panels.remove_button(self._subentry_id, self._panel_id, self._button)

    @callback
    def _async_button_event(self, event: ButtonEvent) -> None:
        """Handle what the panel reported for this button.

        A set frame is the press of a button, so the code of the frame belongs
        to the state the button goes to. When that code is known, it tells the
        state, also when the entity is out of step because the relay wrote the
        light. When the code is new, the brand of the panel says how the
        state is read.

        The other frames report the state of the panel, they are only used
        when their code is known.
        """
        if event.is_state:
            state = self._state_of(event.code)
            if state is None:
                _LOGGER.debug(
                    "Panel %s reports the unknown code %s for button %s",
                    event.panel_id,
                    event.code,
                    event.button,
                )
                return
        else:
            state, is_new = self._press_state(event)
            if is_new and event.is_state_code:
                # A code that is not the code of a state, a double click for
                # example, is not learned.
                self._async_learn(event.code, state)

        if state == self._is_on:
            return
        self._is_on = state
        self.async_write_ha_state()

    @callback
    def _async_bus_state(self, connected: bool) -> None:
        """Handle the panel bus going up or down."""
        if self._attr_available == connected:
            return
        self._attr_available = connected
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the indicator light on."""
        await self._panels.async_set_button(
            self._subentry_id,
            self._panel_id,
            self._button,
            True,
            self._code_for(True),
        )
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the indicator light off."""
        await self._panels.async_set_button(
            self._subentry_id,
            self._panel_id,
            self._button,
            False,
            self._code_for(False),
        )
        self._is_on = False
        self.async_write_ha_state()
