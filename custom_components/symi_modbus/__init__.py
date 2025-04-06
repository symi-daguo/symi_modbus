"""The Symi Modbus integration."""
import asyncio
import logging
from typing import Dict, Optional

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE,
    CONF_HOST,
    CONF_METHOD,
    CONF_NAME,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    CONF_TIMEOUT,
    CONF_TYPE,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from datetime import timedelta

from .const import (
    ATTR_ADDRESS,
    ATTR_HUB,
    ATTR_SLAVE,
    ATTR_STATE,
    ATTR_VALUE,
    CALL_TYPE_WRITE_COIL,
    CALL_TYPE_WRITE_COILS,
    CALL_TYPE_WRITE_REGISTER,
    CALL_TYPE_WRITE_REGISTERS,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_CLOSE_COMM_ON_ERROR,
    CONF_PARITY,
    CONF_RETRIES,
    CONF_RETRY_ON_EMPTY,
    CONF_RTUOVERTCP,
    CONF_SERIAL,
    CONF_STOPBITS,
    CONF_TCP,
    DEFAULT_HUB,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    SERVICE_WRITE_COIL,
    SERVICE_WRITE_REGISTER,
)
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SWITCH]

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Symi Modbus component."""
    hass.data[DOMAIN] = {}
    return True

def setup_services(hass):
    """Set up services for Modbus integration."""
    async def async_write_register(service):
        """Write Modbus registers."""
        hub_name = service.data[ATTR_HUB]
        unit = service.data[ATTR_SLAVE]
        address = service.data[ATTR_ADDRESS]
        value = service.data[ATTR_VALUE]
        
        # Find hub by name
        for hub_id, hub in hass.data[DOMAIN].items():
            if hub.name == hub_name:
                await hub.async_pymodbus_call(
                    unit, address, int(value), CALL_TYPE_WRITE_REGISTER
                )
                return
        
        _LOGGER.error("Hub %s not found", hub_name)

    async def async_write_coil(service):
        """Write Modbus coil."""
        hub_name = service.data[ATTR_HUB]
        unit = service.data[ATTR_SLAVE]
        address = service.data[ATTR_ADDRESS]
        state = service.data[ATTR_STATE]
        
        # Find hub by name
        for hub_id, hub in hass.data[DOMAIN].items():
            if hub.name == hub_name:
                await hub.async_pymodbus_call(
                    unit, address, state, CALL_TYPE_WRITE_COIL
                )
                return
        
        _LOGGER.error("Hub %s not found", hub_name)

    # Register services if they don't already exist
    if SERVICE_WRITE_REGISTER not in hass.services.async_services().get(DOMAIN, {}):
        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_REGISTER,
            async_write_register,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_HUB): cv.string,
                    vol.Required(ATTR_SLAVE): cv.positive_int,
                    vol.Required(ATTR_ADDRESS): cv.positive_int,
                    vol.Required(ATTR_VALUE): cv.positive_int,
                }
            ),
        )

    if SERVICE_WRITE_COIL not in hass.services.async_services().get(DOMAIN, {}):
        hass.services.async_register(
            DOMAIN,
            SERVICE_WRITE_COIL,
            async_write_coil,
            schema=vol.Schema(
                {
                    vol.Required(ATTR_HUB): cv.string,
                    vol.Required(ATTR_SLAVE): cv.positive_int,
                    vol.Required(ATTR_ADDRESS): cv.positive_int,
                    vol.Required(ATTR_STATE): cv.boolean,
                }
            ),
        )

async def update_listener(hass, entry):
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a Modbus device from a config entry."""
    name = entry.data[CONF_NAME]
    slave = entry.data[CONF_SLAVE]
    
    # Check if this hub already exists
    hub_id = f"{name}_{slave}"
    if hub_id in hass.data.setdefault(DOMAIN, {}):
        # Update existing hub with new entry
        hub = hass.data[DOMAIN][hub_id]
        hass.config_entries.async_update_entry(entry)
        await hass.config_entries.async_reload(entry.entry_id)
        return True
    
    # Create a new hub
    hub = ModbusHub(hass, entry)
    
    # Try to connect to the Modbus device
    if not await hub.async_setup():
        _LOGGER.error("Could not connect to Modbus device %s", name)
        return False
    
    # Register hub
    hass.data[DOMAIN][hub_id] = hub
    
    # Set up supported platforms
    for platform in PLATFORMS:
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(entry, platform)
        )
    
    # Define update listener for config entry changes
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # Register services
    setup_services(hass)
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        name = entry.data[CONF_NAME]
        slave = entry.data[CONF_SLAVE]
        hub_id = f"{name}_{slave}"
        if hub_id in hass.data[DOMAIN]:
            hub = hass.data[DOMAIN].pop(hub_id)
            await hub.async_close()
    
    return unload_ok 