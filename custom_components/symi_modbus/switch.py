"""Support for the Symi Modbus switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
from .panels.manager import PanelManager

_LOGGER = logging.getLogger(__name__)

# The slaves share one serial line, so they are polled one after the other.
PARALLEL_UPDATES = 0

# Key of the first coil of a slave.
CONF_COIL_START = "start"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switches of every slave and every panel of this entry."""
    hub: ModbusHub = config_entry.runtime_data.hub
    panels: PanelManager = config_entry.runtime_data.panels

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
        async_add_entities(entities, config_subentry_id=subentry.subentry_id)


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
        self._attr_available = self._panels.is_connected(self._subentry_id)

    async def async_will_remove_from_hass(self) -> None:
        """Stop listening for the button of this panel."""
        self._panels.remove_button(self._subentry_id, self._panel_id, self._button)

    @callback
    def _async_button_event(self, state: bool) -> None:
        """Handle a button press reported by the panel."""
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
            self._subentry_id, self._panel_id, self._button, True
        )
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the indicator light off."""
        await self._panels.async_set_button(
            self._subentry_id, self._panel_id, self._button, False
        )
        self._is_on = False
        self.async_write_ha_state()
