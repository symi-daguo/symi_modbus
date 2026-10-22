"""Support for Symi Modbus switches."""
from __future__ import annotations

import logging
from typing import Any, Optional

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_COIL_COUNT, CONF_SLAVES, CONF_TCP, DOMAIN
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Modbus switch entities for every slave of this master."""
    hub: ModbusHub = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[ModbusSwitch] = []
    slaves = config_entry.data.get(CONF_SLAVES, {})
    default_count = int(config_entry.data.get(CONF_COIL_COUNT, hub.coil_count))

    for slave_key, options in slaves.items():
        # Slave keys are stored as strings in the config entry.
        slave = int(slave_key)
        start = int(options.get("start", 0))
        count = int(options.get("count", default_count))

        for offset in range(count):
            address = start + offset
            entities.append(
                ModbusSwitch(
                    hub,
                    slave,
                    address,
                    offset + 1,
                    f"{config_entry.entry_id}_{slave}_{address}",
                )
            )

    async_add_entities(entities)


class ModbusSwitch(SwitchEntity):
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
        device_class: Optional[str] = None,
    ) -> None:
        """Initialize the Modbus switch."""
        self._hub = hub
        self._slave = slave
        self._address = address
        self._line_number = line_number
        self._attr_unique_id = unique_id
        self._attr_translation_placeholders = {"line": f"{line_number:02d}"}
        if device_class is not None:
            self._attr_device_class = device_class
        self._is_on = False
        self._attr_available = True

        self._hub.add_callback(self.async_on_state_change)
        self._hub.add_availability_callback(self._on_hub_available)

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device this coil belongs to."""
        conn = "TCP" if self._hub.connection_type == CONF_TCP else "Serial"
        return DeviceInfo(
            # The entry id keeps the device stable even when the title changes.
            identifiers={(DOMAIN, f"{self._hub.entry_id}_{self._slave}")},
            name=f"{conn} Slave {self._slave:02X}",
            manufacturer="Symi",
            model="Modbus Relay Module",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the coil is on."""
        return self._is_on

    @callback
    def _on_hub_available(self, available: bool) -> None:
        """Mirror transport availability on the entity."""
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
        if changed or not self._attr_available:
            self._attr_available = True
            self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore the last known state from the hub cache."""
        state = self._hub.get_state(self._slave, self._address)
        if state is not None:
            self._is_on = state
            self._attr_available = True
