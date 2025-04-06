"""Config flow for Symi Modbus integration."""
import ipaddress
import logging
from typing import Any, Dict, Optional

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PORT,
    CONF_TYPE,
    CONF_SLAVE,
    CONF_SCAN_INTERVAL,
    CONF_DEVICE,
    CONF_METHOD,
)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TCP_PORT,
    DEFAULT_SLAVE,
    CONF_SERIAL,
    CONF_TCP,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_PARITY,
    CONF_STOPBITS,
    CONF_RTUOVERTCP,
)

_LOGGER = logging.getLogger(__name__)

# Define configuration schemas
SERIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TYPE): CONF_SERIAL,
        vol.Required(CONF_PORT): cv.string,
        vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): cv.positive_int,
        vol.Optional(CONF_BAUDRATE, default=9600): cv.positive_int,
        vol.Optional(CONF_BYTESIZE, default=8): vol.In([5, 6, 7, 8]),
        vol.Optional(CONF_PARITY, default="N"): vol.In(["E", "O", "N"]),
        vol.Optional(CONF_STOPBITS, default=1): vol.In([1, 2]),
        vol.Optional(CONF_METHOD, default="rtu"): vol.In(["rtu", "ascii"]),
        vol.Optional(CONF_SCAN_INTERVAL, default=1): cv.positive_int,
    }
)

TCP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TYPE): CONF_TCP,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_TCP_PORT): cv.port,
        vol.Optional(CONF_SLAVE, default=DEFAULT_SLAVE): cv.positive_int,
        vol.Optional(CONF_RTUOVERTCP, default=False): cv.boolean,
        vol.Optional(CONF_SCAN_INTERVAL, default=1): cv.positive_int,
    }
)

class SymiModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Symi Modbus."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return SymiModbusOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            conn_type = user_input[CONF_TYPE]
            slave = user_input[CONF_SLAVE]
            
            # Generate a unique name based on the connection details and slave address
            if conn_type == CONF_TCP:
                name = f"Modbus TCP {slave:02X}"
                unique_id = f"modbus_tcp_{user_input[CONF_HOST]}_{user_input[CONF_PORT]}_{slave:02X}"
            else:  # CONF_SERIAL
                name = f"Modbus Serial {slave:02X}"
                unique_id = f"modbus_serial_{user_input[CONF_PORT]}_{slave:02X}"
            
            # Add name to user_input
            user_input[CONF_NAME] = name
            
            # Check if entry already exists with same unique_id
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()
            
            # Validate connection parameters
            if conn_type == CONF_TCP:
                try:
                    ipaddress.ip_address(user_input[CONF_HOST])
                except ValueError:
                    errors["base"] = "invalid_host"
            
            if not errors:
                return self.async_create_entry(
                    title=name,
                    data=user_input,
                )

        # If there is no user input or there were errors, show the form again
        if user_input is None or user_input.get(CONF_TYPE) == CONF_TCP:
            schema = TCP_SCHEMA
        else:
            schema = SERIAL_SCHEMA

        return self.async_show_form(
            step_id="user", 
            data_schema=schema,
            errors=errors,
        )

class SymiModbusOptionsFlow(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = {
            vol.Optional(
                CONF_SCAN_INTERVAL,
                default=self.config_entry.options.get(
                    CONF_SCAN_INTERVAL, 1
                ),
            ): cv.positive_int,
        }

        return self.async_show_form(step_id="init", data_schema=vol.Schema(options)) 