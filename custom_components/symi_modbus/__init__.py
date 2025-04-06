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

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Symi Modbus from a config entry."""
    hub = ModbusHub(hass, entry)
    
    # Check if connection is successful
    if not await hub.async_setup():
        return False
    
    hass.data[DOMAIN][entry.entry_id] = hub
    
    # Register service calls
    register_services(hass)
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register a callback for when Home Assistant stops
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, hub.async_stop)
    )
    
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        hub = hass.data[DOMAIN].pop(entry.entry_id)
        await hub.async_close()
    
    return unload_ok

def register_services(hass):
    """Register Modbus services."""
    
    async def async_write_register(service):
        """Write Modbus registers."""
        unit = service.data[ATTR_SLAVE]
        address = service.data[ATTR_ADDRESS]
        value = service.data[ATTR_VALUE]
        hub_name = service.data.get(ATTR_HUB, DEFAULT_HUB)
        
        # Find hub by name
        for entry_id, hub in hass.data[DOMAIN].items():
            if hub.name == hub_name:
                if isinstance(value, list):
                    await hub.async_pymodbus_call(
                        unit, address, [int(float(i)) for i in value], CALL_TYPE_WRITE_REGISTERS
                    )
                else:
                    await hub.async_pymodbus_call(
                        unit, address, int(float(value)), CALL_TYPE_WRITE_REGISTER
                    )
                break
        else:
            _LOGGER.error("Hub %s not found", hub_name)

    async def async_write_coil(service):
        """Write Modbus coil."""
        unit = service.data[ATTR_SLAVE]
        address = service.data[ATTR_ADDRESS]
        state = service.data[ATTR_STATE]
        hub_name = service.data.get(ATTR_HUB, DEFAULT_HUB)
        
        # Find hub by name
        for entry_id, hub in hass.data[DOMAIN].items():
            if hub.name == hub_name:
                if isinstance(state, list):
                    await hub.async_pymodbus_call(
                        unit, address, state, CALL_TYPE_WRITE_COILS
                    )
                else:
                    await hub.async_pymodbus_call(
                        unit, address, state, CALL_TYPE_WRITE_COIL
                    )
                break
        else:
            _LOGGER.error("Hub %s not found", hub_name)

    service_write_register_schema = vol.Schema(
        {
            vol.Required(ATTR_ADDRESS): cv.positive_int,
            vol.Required(ATTR_VALUE): vol.Any(cv.positive_int, [cv.positive_int]),
            vol.Required(ATTR_SLAVE): cv.positive_int,
            vol.Optional(ATTR_HUB, default=DEFAULT_HUB): cv.string,
        }
    )

    service_write_coil_schema = vol.Schema(
        {
            vol.Required(ATTR_ADDRESS): cv.positive_int,
            vol.Required(ATTR_STATE): vol.Any(cv.boolean, [cv.boolean]),
            vol.Required(ATTR_SLAVE): cv.positive_int,
            vol.Optional(ATTR_HUB, default=DEFAULT_HUB): cv.string,
        }
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_REGISTER,
        async_write_register,
        schema=service_write_register_schema,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_COIL,
        async_write_coil,
        schema=service_write_coil_schema,
    ) 