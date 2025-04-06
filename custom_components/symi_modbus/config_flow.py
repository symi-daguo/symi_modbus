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
CONNECTION_TYPE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TYPE, default=CONF_TCP): vol.In(
            {
                CONF_TCP: "TCP",
                CONF_SERIAL: "Serial",
            }
        ),
    }
)

TCP_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_TCP_PORT): cv.port,
        vol.Optional(CONF_RTUOVERTCP, default=False): cv.boolean,
    }
)

SERIAL_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PORT): cv.string,
        vol.Optional(CONF_BAUDRATE, default=9600): cv.positive_int,
        vol.Optional(CONF_BYTESIZE, default=8): vol.In([5, 6, 7, 8]),
        vol.Optional(CONF_PARITY, default="N"): vol.In(["E", "O", "N"]),
        vol.Optional(CONF_STOPBITS, default=1): vol.In([1, 2]),
        vol.Optional(CONF_METHOD, default="rtu"): vol.In(["rtu", "ascii"]),
    }
)

SLAVE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): cv.positive_int,
    }
)

class SymiModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Symi Modbus."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize the config flow."""
        self._connection_type = None
        self._connection_data = {}
        self._slaves = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return SymiModbusOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step - select connection type."""
        if user_input is not None:
            self._connection_type = user_input[CONF_TYPE]
            if self._connection_type == CONF_TCP:
                return await self.async_step_tcp()
            else:
                return await self.async_step_serial()

        return self.async_show_form(
            step_id="user",
            data_schema=CONNECTION_TYPE_SCHEMA,
        )

    async def async_step_tcp(self, user_input=None):
        """Handle TCP connection configuration."""
        errors = {}
        if user_input is not None:
            try:
                ipaddress.ip_address(user_input[CONF_HOST])
            except ValueError:
                errors["base"] = "invalid_host"
            
            if not errors:
                self._connection_data = user_input
                return await self.async_step_slave()

        return self.async_show_form(
            step_id="tcp",
            data_schema=TCP_CONNECTION_SCHEMA,
            errors=errors,
        )

    async def async_step_serial(self, user_input=None):
        """Handle Serial connection configuration."""
        if user_input is not None:
            self._connection_data = user_input
            return await self.async_step_slave()

        return self.async_show_form(
            step_id="serial",
            data_schema=SERIAL_CONNECTION_SCHEMA,
        )

    async def async_step_slave(self, user_input=None):
        """Handle slave configuration."""
        errors = {}
        if user_input is not None:
            slave = user_input[CONF_SLAVE]
            
            # Check if this slave is already added
            if slave in self._slaves:
                errors["base"] = "slave_already_added"
            
            # Check if we have too many slaves
            elif len(self._slaves) >= 10:
                errors["base"] = "too_many_slaves"
            
            if not errors:
                self._slaves.append(slave)
                
                # Generate unique ID and name for this connection + slave
                if self._connection_type == CONF_TCP:
                    name = f"Modbus TCP {slave:02X}"
                    host = self._connection_data[CONF_HOST]
                    port = self._connection_data[CONF_PORT]
                    unique_id = f"modbus_tcp_{host}_{port}_{slave:02X}"
                else:
                    name = f"Modbus Serial {slave:02X}"
                    port = self._connection_data[CONF_PORT]
                    unique_id = f"modbus_serial_{port}_{slave:02X}"
                
                # Create connection for this slave
                connection_data = {
                    CONF_TYPE: self._connection_type,
                    CONF_NAME: name,
                    CONF_SLAVE: slave,
                    CONF_SCAN_INTERVAL: 1,  # Always 1 second
                    **self._connection_data,
                }
                
                # Check if entry already exists
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                
                # Ask if user wants to add another slave
                return await self.async_step_add_another_slave(connection_data)

        return self.async_show_form(
            step_id="slave",
            data_schema=SLAVE_SCHEMA,
            errors=errors,
            description_placeholders={
                "current_slaves": ", ".join([f"0x{s:02X}" for s in self._slaves]),
                "slave_count": len(self._slaves),
            },
        )

    async def async_step_add_another_slave(self, connection_data):
        """Ask if user wants to add another slave."""
        # Create entry for the current slave
        return self.async_create_entry(
            title=connection_data[CONF_NAME],
            data=connection_data,
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