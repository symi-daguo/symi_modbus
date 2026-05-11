"""Support for Symi Modbus switches."""
from __future__ import annotations

import logging
from typing import Any, Optional

import voluptuous as vol

from homeassistant.components.switch import PLATFORM_SCHEMA, SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_DEVICE_CLASS, CONF_SLAVE, CONF_UNIQUE_ID
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SWITCHS, CONF_TCP, DEFAULT_SLAVE, DOMAIN
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)

ENTITY_ID_FORMAT = DOMAIN + ".{}"

SWITCH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADDRESS): cv.positive_int,
        vol.Required(CONF_NAME): cv.string,
        vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): cv.positive_int,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
        vol.Optional(CONF_UNIQUE_ID): cv.string,
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SWITCHS): vol.All(cv.ensure_list, [SWITCH_SCHEMA]),
    }
)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Modbus switch entities."""
    hub = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[ModbusSwitch] = []

    slave = int(config_entry.data.get(CONF_SLAVE, DEFAULT_SLAVE))
    addresses = list(range(32))

    hub.register_slaves_to_poll(slave, addresses)

    for i, address in enumerate(addresses):
        display_number = i + 1
        name = f"{slave:02X}switch{display_number:02d}"
        unique_id = f"{config_entry.entry_id}_{slave}_{address}"

        entities.append(
            ModbusSwitch(
                hub,
                slave,
                address,
                name,
                unique_id,
                display_number,
            )
        )

    async_add_entities(entities)


class ModbusSwitch(SwitchEntity):
    """Representation of a Modbus switch."""

    def __init__(
        self,
        hub: ModbusHub,
        slave: int,
        address: int,
        name: str,
        unique_id: str,
        display_number: int,
        device_class: Optional[str] = None,
    ) -> None:
        """Initialize the Modbus switch."""
        self._hub = hub
        self._slave = slave
        self._address = address
        self._display_number = display_number
        self._attr_name = f"{self._hub.name} 线路 {self._display_number}"
        self._attr_unique_id = unique_id
        if device_class is not None:
            self._attr_device_class = device_class
        self._is_on = False
        self._attr_available = True

        self._hub.add_callback(self.async_on_state_change)
        self._hub.add_availability_callback(self._on_hub_available)

        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, f"{name}_{slave}_{address}", hass=hub._hass
        )

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        conn = "TCP" if self._hub.connection_type == CONF_TCP else "Serial"
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._hub.name}_{self._slave}")},
            name=f"Modbus {conn} {self._slave:02X}",
            manufacturer="Symi",
            model="Modbus Switch Module",
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._attr_available

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @callback
    def _on_hub_available(self, available: bool) -> None:
        """Mirror transport availability on the entity."""
        if self._attr_available == available:
            return
        self._attr_available = available
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        ok = await self._hub.write_coil(self._slave, self._address, True)
        if ok:
            self._is_on = True
            self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        ok = await self._hub.write_coil(self._slave, self._address, False)
        if ok:
            self._is_on = False
            self.async_write_ha_state()

    @callback
    def async_on_state_change(self, data: dict[int, bool], slave: int) -> None:
        """Update state when state changes."""
        if slave != self._slave:
            return

        if not self._attr_available:
            self._attr_available = True

        if self._address in data:
            new_state = data[self._address]
            if new_state != self._is_on:
                self._is_on = new_state
                self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore state from hub cache."""
        if self._slave in self._hub._slave_data:
            data = self._hub._slave_data[self._slave]
            if self._address in data:
                self._is_on = data[self._address]
                self._attr_available = True

    async def async_will_remove_from_hass(self) -> None:
        """Detach hub listeners."""
        self._hub.remove_callback(self.async_on_state_change)
        self._hub.remove_availability_callback(self._on_hub_available)
