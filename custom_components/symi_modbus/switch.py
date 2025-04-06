"""Support for Symi Modbus switches."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant.components.switch import (
    PLATFORM_SCHEMA,
    SwitchEntity,
)
from homeassistant.const import (
    CONF_ADDRESS,
    CONF_DEVICE_CLASS,
    CONF_NAME,
    CONF_SLAVE,
    CONF_UNIQUE_ID,
    STATE_ON,
)
from homeassistant.core import HomeAssistant, callback
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import generate_entity_id

from .const import (
    CONF_SWITCHS,
    DEFAULT_SLAVE,
    DOMAIN,
)
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)

ENTITY_ID_FORMAT = DOMAIN + ".{}"

# Config validation schema for YAML configuration
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
    
    entities = []
    
    # Get slave address from config entry
    slave = config_entry.data.get(CONF_SLAVE, DEFAULT_SLAVE)
    addresses = list(range(32))  # 0-31
    
    # Register these addresses for polling
    hub.register_slaves_to_poll(slave, addresses)
    
    # Create entities
    for address in addresses:
        # Format: 0Aswitch01, 0Aswitch02, etc.
        name = f"{slave:02X}switch{address:02d}"
        unique_id = f"{config_entry.entry_id}_{slave}_{address}"
        
        entities.append(
            ModbusSwitch(
                hub,
                slave,
                address,
                name,
                unique_id,
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
        device_class: Optional[str] = None,
    ) -> None:
        """Initialize the Modbus switch."""
        self._hub = hub
        self._slave = slave
        self._address = address
        self._name = name
        self._unique_id = unique_id
        self._device_class = device_class
        self._is_on = False
        self._available = True
        
        # Register callback for state updates
        self._hub.add_callback(self.async_on_state_change)
        
        # Generate entity ID
        self.entity_id = generate_entity_id(
            ENTITY_ID_FORMAT, f"{name}_{slave}_{address}", hass=hub._hass
        )

    @property
    def name(self) -> str:
        """Return the name of the switch."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self._hub.name}_{self._slave}")},
            name=f"Symi Modbus Slave {self._slave}",
            manufacturer="Symi",
            model="Modbus Switch Module",
        )

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self._is_on

    @property
    def device_class(self) -> Optional[str]:
        """Return the device class."""
        return self._device_class

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._hub.write_coil(self._slave, self._address, True)
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._hub.write_coil(self._slave, self._address, False)
        self._is_on = False
        self.async_write_ha_state()

    @callback
    def async_on_state_change(self, data, slave):
        """Update state when state changes."""
        if slave != self._slave:
            return
            
        if not self._available:
            self._available = True
            
        if self._address in data:
            new_state = data[self._address]
            if new_state != self._is_on:
                self._is_on = new_state
                self.async_write_ha_state()
                
    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        # Initial update
        if self._slave in self._hub._slave_data:
            data = self._hub._slave_data[self._slave]
            if self._address in data:
                self._is_on = data[self._address]
                self._available = True 