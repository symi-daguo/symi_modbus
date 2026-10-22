"""Config flow for Symi Modbus."""
from __future__ import annotations

import logging
import re

import serial.tools.list_ports
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from serial.tools.list_ports_common import ListPortInfo

from .const import (
    ADD_MORE_SLAVES,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_COIL_COUNT,
    CONF_FRAME,
    CONF_HOST,
    CONF_NAME,
    CONF_PARITY,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SLAVE,
    CONF_SLAVES,
    CONF_STOPBITS,
    CONF_TCP,
    CONF_TYPE,
    DEFAULT_COIL_COUNT,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_SLAVE,
    DEFAULT_TCP_PORT,
    DOMAIN,
    FRAME_MBAP,
    FRAME_RTU,
    SERIAL_PORT_MANUAL_VALUE,
)

_LOGGER = logging.getLogger(__name__)

CONNECTION_TYPE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_TYPE, default=CONF_TCP): vol.In(
            {CONF_TCP: "TCP", CONF_SERIAL: "Serial"}
        )
    }
)

TCP_CONNECTION_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_TCP_PORT): cv.port,
        vol.Required(CONF_FRAME, default=FRAME_MBAP): vol.In(
            {FRAME_MBAP: "Modbus TCP (MBAP)", FRAME_RTU: "Modbus RTU over TCP"}
        ),
    }
)

SERIAL_PARAMS_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BAUDRATE, default=9600): cv.positive_int,
        vol.Optional(CONF_BYTESIZE, default=8): vol.In([5, 6, 7, 8]),
        vol.Optional(CONF_PARITY, default="N"): vol.In(["E", "O", "N", "None"]),
        vol.Optional(CONF_STOPBITS, default=1): vol.In([1, 2]),
    }
)

SERIAL_MANUAL_PATH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PORT): cv.string,
    }
)


def _list_serial_ports() -> list[ListPortInfo]:
    """Enumerate serial ports on the machine running Home Assistant."""
    try:
        return list(serial.tools.list_ports.comports())
    except Exception:  # noqa: BLE001
        _LOGGER.debug("Serial port enumeration failed", exc_info=True)
        return []


def _format_serial_port_label(info: ListPortInfo) -> str:
    """Human-readable label for a list_ports entry (USB / UART)."""
    device = info.device
    desc = (info.description or "").strip()
    manufacturer = (getattr(info, "manufacturer", None) or "").strip()
    product = (getattr(info, "product", None) or "").strip()
    vid = getattr(info, "vid", None)
    pid = getattr(info, "pid", None)
    usb_bits = []
    if manufacturer:
        usb_bits.append(manufacturer)
    if product:
        usb_bits.append(product)
    if vid is not None and pid is not None:
        usb_bits.append(f"VID:PID {vid:04X}:{pid:04X}")
    usb = " · ".join(usb_bits) if usb_bits else ""

    if "ttyUSB" in device or "ttyACM" in device or "usb" in desc.lower():
        kind = "USB"
    elif device.startswith("COM") or "ttyS" in device:
        kind = "Serial"
    else:
        kind = "Port"

    if usb and desc and desc not in usb:
        text = f"{kind}: {usb} - {desc} ({device})"
    elif usb:
        text = f"{kind}: {usb} ({device})"
    elif desc:
        text = f"{kind}: {desc} ({device})"
    else:
        text = f"{kind}: {device}"

    return text[:120]


class SymiModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Symi Modbus.

    One config entry describes one Modbus master (a serial port or a TCP
    endpoint) together with the slaves that hang behind it.
    """

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._connection_type: str | None = None
        self._connection_data: dict = {}
        self._slaves: dict[int, dict] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SymiModbusOptionsFlow:
        """Get the options flow for this handler."""
        return SymiModbusOptionsFlow()

    async def async_step_user(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Handle the initial step - select connection type."""
        if user_input is not None:
            self._connection_type = user_input[CONF_TYPE]
            self._connection_data = {}

            if self._connection_type == CONF_TCP:
                return await self.async_step_tcp()
            return await self.async_step_serial_pick()

        return self.async_show_form(
            step_id="user",
            data_schema=CONNECTION_TYPE_SCHEMA,
        )

    async def async_step_tcp(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Handle TCP connection configuration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = (user_input.get(CONF_HOST) or "").strip()
            if not host:
                errors[CONF_HOST] = "invalid_host"
            else:
                self._connection_data = {**user_input, CONF_HOST: host}
                return await self.async_step_slave()

        return self.async_show_form(
            step_id="tcp",
            data_schema=TCP_CONNECTION_SCHEMA,
            errors=errors,
        )

    async def async_step_serial_pick(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Pick a detected serial device or choose manual path entry."""
        if user_input is not None:
            choice = user_input[CONF_PORT]
            if choice == SERIAL_PORT_MANUAL_VALUE:
                return await self.async_step_serial_manual()
            self._connection_data = {CONF_PORT: choice}
            return await self.async_step_serial_params()

        ports = await self.hass.async_add_executor_job(_list_serial_ports)
        options: dict[str, str] = {}
        default_port: str | None = None

        for info in sorted(ports, key=lambda p: p.device):
            options[info.device] = _format_serial_port_label(info)
            if default_port is None:
                default_port = info.device

        options[SERIAL_PORT_MANUAL_VALUE] = (
            "Not listed / enter path manually (未列出-手动输入)"
        )

        if default_port is None:
            default_port = SERIAL_PORT_MANUAL_VALUE

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=default_port): vol.In(options),
            }
        )

        return self.async_show_form(
            step_id="serial_pick",
            data_schema=schema,
        )

    async def async_step_serial_manual(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Enter serial device path manually (USB or on-board UART)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            path = (user_input.get(CONF_PORT) or "").strip()
            if not path:
                errors[CONF_PORT] = "invalid_serial_path"
            else:
                self._connection_data = {CONF_PORT: path}
                return await self.async_step_serial_params()

        return self.async_show_form(
            step_id="serial_manual",
            data_schema=SERIAL_MANUAL_PATH_SCHEMA,
            errors=errors,
        )

    async def async_step_serial_params(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Serial port parameters (baudrate, parity, etc.)."""
        if user_input is not None:
            data = dict(user_input)
            parity = str(data.get(CONF_PARITY, "N")).strip()
            if parity.lower() == "none":
                data[CONF_PARITY] = "N"
            self._connection_data.update(data)
            return await self.async_step_slave()

        return self.async_show_form(
            step_id="serial_params",
            data_schema=SERIAL_PARAMS_SCHEMA,
        )

    async def async_step_slave(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Add a slave to this master.

        The form carries the slave address and a checkbox that asks for one
        more slave, so adding several slaves takes a single step per slave.
        """
        if user_input is not None:
            slave = int(user_input[CONF_SLAVE])
            if slave in self._slaves:
                return self.async_show_form(
                    step_id="slave",
                    data_schema=self._slave_schema(user_input),
                    errors={"base": "slave_already_added"},
                )
            self._slaves[slave] = {"start": 0, "count": DEFAULT_COIL_COUNT}

            if not user_input.get(ADD_MORE_SLAVES):
                return await self._async_create_entry()
            return await self.async_step_slave()

        return self.async_show_form(
            step_id="slave",
            data_schema=self._slave_schema(),
        )

    def _slave_schema(self, user_input: dict | None = None) -> vol.Schema:
        """Build the schema of the slave step."""
        add_more = bool((user_input or {}).get(ADD_MORE_SLAVES))
        return vol.Schema(
            {
                vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=247)
                ),
                vol.Optional(ADD_MORE_SLAVES, default=add_more): cv.boolean,
            }
        )

    async def _async_create_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry for this master and its slaves."""
        if not self._slaves:
            return self.async_show_form(
                step_id="slave",
                data_schema=self._slave_schema(),
                errors={"base": "no_slaves"},
            )

        if self._connection_type == CONF_TCP:
            host = self._connection_data[CONF_HOST]
            port = self._connection_data[CONF_PORT]
            name = f"Modbus TCP {host}:{port}"
            unique_id = f"modbus_tcp_{host}_{port}"
        else:
            port = self._connection_data[CONF_PORT]
            safe_port = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(port)).strip("_")
            name = f"Modbus Serial {port}"
            unique_id = f"modbus_serial_{safe_port}"

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        entry_data = {
            CONF_TYPE: self._connection_type,
            CONF_NAME: name,
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            CONF_COIL_COUNT: DEFAULT_COIL_COUNT,
            CONF_SLAVES: {str(slave): options for slave, options in self._slaves.items()},
            **self._connection_data,
        }

        return self.async_create_entry(title=name, data=entry_data)


class SymiModbusOptionsFlow(config_entries.OptionsFlow):
    """Handle options for an existing master."""

    async def async_step_init(self, user_input: dict | None = None) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry = self.config_entry
        scan_default = entry.options.get(
            CONF_SCAN_INTERVAL,
            entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        options = {
            vol.Optional(CONF_SCAN_INTERVAL, default=scan_default): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=3600)
            ),
        }

        return self.async_show_form(step_id="init", data_schema=vol.Schema(options))
