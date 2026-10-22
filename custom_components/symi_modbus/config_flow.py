"""Config flow for Symi Modbus."""
from __future__ import annotations

import logging
import re
from types import MappingProxyType

import serial.tools.list_ports
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    ConfigSubentry,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
from serial.tools.list_ports_common import ListPortInfo

from .const import (
    BRAND_CLOWIRE,
    BRAND_LF,
    BRAND_SYMI,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_BRAND,
    CONF_BUTTONS,
    CONF_COIL_COUNT,
    CONF_FRAME,
    CONF_HOST,
    CONF_NAME,
    CONF_PANEL_ENTITIES,
    CONF_PANEL_IDS,
    CONF_PARITY,
    CONF_PORT,
    CONF_RELAY_ENTITIES,
    CONF_SCAN_INTERVAL,
    CONF_SERIAL,
    CONF_SLAVE,
    CONF_SLAVE_COUNT,
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
    MAX_COIL_COUNT,
    MAX_PANEL_BUTTONS,
    SERIAL_PORT_MANUAL_VALUE,
    SUBENTRY_LINKAGE,
    SUBENTRY_PANEL,
    SUBENTRY_SLAVE,
)
from .connection import ModbusConnection
from .frames import FUNCTION_READ_COILS, build_read_request

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
        vol.Optional(CONF_PORT, default=DEFAULT_TCP_PORT): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
        ),
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

# The first coil of a slave, most devices start at zero.
CONF_COIL_START = "start"

SLAVE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SLAVE, default=DEFAULT_SLAVE): NumberSelector(
            NumberSelectorConfig(min=0, max=247, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_SLAVE_COUNT, default=1): NumberSelector(
            NumberSelectorConfig(min=1, max=32, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_COIL_START, default=0): NumberSelector(
            NumberSelectorConfig(min=0, max=65535, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_COIL_COUNT, default=DEFAULT_COIL_COUNT): NumberSelector(
            NumberSelectorConfig(min=1, max=MAX_COIL_COUNT, mode=NumberSelectorMode.BOX)
        ),
    }
)

# The fields of a panel bus besides the serial port. The port itself is a
# picker that is built when the form is shown, because the detected ports are
# only known at that moment.
PANEL_FIELDS = {
    vol.Required(CONF_BRAND, default=BRAND_SYMI): SelectSelector(
        SelectSelectorConfig(
            options=[
                {"value": BRAND_SYMI, "label": "Symi (亖米)"},
                {"value": BRAND_CLOWIRE, "label": "Clowire (克伦威尔)"},
                {"value": BRAND_LF, "label": "LF (拉斐)"},
            ],
            mode=SelectSelectorMode.DROPDOWN,
        )
    ),
    vol.Optional(CONF_BAUDRATE, default=9600): cv.positive_int,
    vol.Optional(CONF_BYTESIZE, default=8): vol.In([5, 6, 7, 8]),
    vol.Optional(CONF_PARITY, default="N"): vol.In(["E", "O", "N", "None"]),
    vol.Optional(CONF_STOPBITS, default=1): vol.In([1, 2]),
    vol.Required("panel_start", default=1): NumberSelector(
        NumberSelectorConfig(min=1, max=247, mode=NumberSelectorMode.BOX)
    ),
    vol.Required("panel_count", default=1): NumberSelector(
        NumberSelectorConfig(min=1, max=64, mode=NumberSelectorMode.BOX)
    ),
    vol.Optional(CONF_BUTTONS, default=MAX_PANEL_BUTTONS): NumberSelector(
        NumberSelectorConfig(min=1, max=MAX_PANEL_BUTTONS, mode=NumberSelectorMode.BOX)
    ),
}

LINKAGE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PANEL_ENTITIES, default=list): EntitySelector(
            EntitySelectorConfig(
                multiple=True,
                filter={"domain": "switch", "integration": DOMAIN},
            )
        ),
        vol.Required(CONF_RELAY_ENTITIES, default=list): EntitySelector(
            EntitySelectorConfig(
                multiple=True,
                filter={"domain": "switch", "integration": DOMAIN},
            )
        ),
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


def _entity_kind(hass, entity_id: str, entry_id: str) -> str | None:
    """Return whether an entity is a panel button or a Modbus coil."""
    registry = er.async_get(hass)
    registry_entry = registry.async_get(entity_id)
    if registry_entry is None:
        return None
    if registry_entry.config_entry_id != entry_id:
        return None
    unique_id = registry_entry.unique_id or ""
    if "_panel_" in unique_id:
        return "panel"
    return "coil"


def _friendly_name(hass, entity_id: str) -> str:
    """Return the name of an entity as it is shown in the interface."""
    state = hass.states.get(entity_id)
    if state is not None and state.name:
        return state.name
    return entity_id


def _slave_addresses(first: int, count: int) -> list[int]:
    """Return the addresses of a batch of slaves.

    The batch starts at the first address and the addresses follow it.
    """
    return list(range(first, first + max(int(count), 1)))


def _ports_in_use(hass, skip_subentry_id: str | None = None) -> set[str]:
    """Return the serial ports this integration already uses.

    Two connections cannot share a serial port, the bytes would be split
    between them.
    """
    used: set[str] = set()
    for config_entry in hass.config_entries.async_entries(DOMAIN):
        if config_entry.data.get(CONF_TYPE) == CONF_SERIAL:
            port = config_entry.data.get(CONF_PORT)
            if port:
                used.add(str(port))
        for subentry in config_entry.get_subentries_of_type(SUBENTRY_PANEL):
            if subentry.subentry_id == skip_subentry_id:
                continue
            port = subentry.data.get(CONF_PORT)
            if port:
                used.add(str(port))
    return used


def _serial_port_options(ports: list[ListPortInfo], used: set[str]) -> dict[str, str]:
    """Return the selectable serial ports without the ones already in use."""
    options: dict[str, str] = {}
    for info in sorted(ports, key=lambda port: port.device):
        if info.device in used:
            continue
        options[info.device] = _format_serial_port_label(info)
    options[SERIAL_PORT_MANUAL_VALUE] = (
        "未列出 - 手动输入路径 (Not listed - enter the path manually)"
    )
    return options


class SymiModbusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Symi Modbus.

    One config entry describes one Modbus master (a serial port or a TCP
    endpoint). The slaves behind it, the wall panels and the links between the
    panel buttons and the coils are subentries of that entry, so the user can
    add, change and remove them on their own.
    """

    VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._connection_type: str | None = None
        self._connection_data: dict = {}
        self._slave: dict | None = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> SymiModbusOptionsFlow:
        """Get the options flow for this handler."""
        return SymiModbusOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return the subentry types this integration supports."""
        return {
            SUBENTRY_SLAVE: SlaveSubentryFlow,
            SUBENTRY_PANEL: PanelSubentryFlow,
            SUBENTRY_LINKAGE: LinkageSubentryFlow,
        }

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
        # A serial port that is already used by another connection would
        # split the bytes between them, so it is not offered.
        options = _serial_port_options(ports, _ports_in_use(self.hass))
        default_port: str | None = next(
            (device for device in options if device != SERIAL_PORT_MANUAL_VALUE),
            SERIAL_PORT_MANUAL_VALUE,
        )

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
        """Ask for the first slave of this master.

        More slaves are added on the page of the config entry.
        """
        if user_input is not None:
            self._slave = dict(user_input)
            return await self._async_create_entry()

        return self.async_show_form(
            step_id="slave",
            data_schema=SLAVE_SCHEMA,
        )

    async def _async_create_entry(self) -> config_entries.ConfigFlowResult:
        """Create the config entry for this master and its first slave."""
        if self._slave is None:
            return self.async_show_form(
                step_id="slave",
                data_schema=SLAVE_SCHEMA,
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
            # A serial line always uses RTU frames.
            CONF_FRAME: (
                FRAME_RTU
                if self._connection_type == CONF_SERIAL
                else self._connection_data.get(CONF_FRAME, FRAME_MBAP)
            ),
            CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
            **self._connection_data,
        }

        if not await self._async_test_connection(entry_data, self._slave):
            return self.async_show_form(
                step_id="slave",
                data_schema=SLAVE_SCHEMA,
                errors={"base": "cannot_connect"},
            )

        first = int(self._slave[CONF_SLAVE])
        slave_data = {
            key: value for key, value in self._slave.items() if key != CONF_SLAVE_COUNT
        }
        subentries = [
            {
                "data": {**slave_data, CONF_SLAVE: address},
                "subentry_type": SUBENTRY_SLAVE,
                "title": f"Slave {address:02X}",
                "unique_id": str(address),
            }
            for address in _slave_addresses(first, self._slave.get(CONF_SLAVE_COUNT, 1))
        ]

        return self.async_create_entry(
            title=name, data=entry_data, subentries=subentries
        )

    async def _async_test_connection(self, entry_data: dict, slave_data: dict) -> bool:
        """Ask the slave for its coils before the entry is created."""
        slave = int(slave_data[CONF_SLAVE])

        connection = ModbusConnection(
            connection_type=entry_data[CONF_TYPE],
            host=entry_data.get(CONF_HOST),
            port=entry_data[CONF_PORT],
            baudrate=int(entry_data.get(CONF_BAUDRATE, 9600)),
            bytesize=int(entry_data.get(CONF_BYTESIZE, 8)),
            parity=str(entry_data.get(CONF_PARITY, "N")),
            stopbits=int(entry_data.get(CONF_STOPBITS, 1)),
            frame=entry_data[CONF_FRAME],
        )

        try:
            request = build_read_request(
                slave,
                FUNCTION_READ_COILS,
                int(slave_data.get(CONF_COIL_START, 0)),
                int(slave_data.get(CONF_COIL_COUNT, DEFAULT_COIL_COUNT)),
                entry_data[CONF_FRAME],
            )
            payload = await connection.async_request(request, FUNCTION_READ_COILS)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Connection test failed", exc_info=True)
            return False
        finally:
            await connection.async_close()

        return payload is not None


class SlaveSubentryFlow(ConfigSubentryFlow):
    """Add and change a Modbus slave behind the master.

    Several slaves can be added in one go, the form carries the first address
    and the number of slaves that follow it.
    """

    async def async_step_user(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Add one or more slaves."""
        if user_input is not None:
            base = {key: value for key, value in user_input.items() if key != CONF_SLAVE_COUNT}
            first = int(base[CONF_SLAVE])
            addresses = _slave_addresses(first, user_input.get(CONF_SLAVE_COUNT, 1))

            if any(self._slave_taken(address, None) for address in addresses):
                return self.async_show_form(
                    step_id="user",
                    data_schema=SLAVE_SCHEMA,
                    errors={"base": "slave_already_added"},
                )

            entry = self._get_entry()
            # The flow creates the last slave, the ones before it are added
            # here, so the list keeps the order of the addresses.
            for address in addresses[:-1]:
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType({**base, CONF_SLAVE: address}),
                        subentry_type=SUBENTRY_SLAVE,
                        title=f"Slave {address:02X}",
                        unique_id=str(address),
                    ),
                )

            last = addresses[-1]
            return self.async_create_entry(
                title=f"Slave {last:02X}",
                data={**base, CONF_SLAVE: last},
                unique_id=str(last),
            )

        return self.async_show_form(step_id="user", data_schema=SLAVE_SCHEMA)

    async def async_step_reconfigure(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Change a slave."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            base = {key: value for key, value in user_input.items() if key != CONF_SLAVE_COUNT}
            slave = int(base[CONF_SLAVE])
            if self._slave_taken(slave, subentry.subentry_id):
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=self._reconfigure_schema(subentry),
                    errors={"base": "slave_already_added"},
                )
            update = {"data": {**base, CONF_SLAVE: slave}, "unique_id": str(slave)}
            title = self._slave_title(subentry, slave)
            if title is not None:
                update["title"] = title
            return self.async_update_and_abort(entry, subentry, **update)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self._reconfigure_schema(subentry),
        )

    def _reconfigure_schema(self, subentry) -> vol.Schema:
        """Return the form of the reconfigure step with the current values."""
        suggested = dict(subentry.data)
        suggested[CONF_SLAVE_COUNT] = 1
        return self.add_suggested_values_to_schema(SLAVE_SCHEMA, suggested)

    @staticmethod
    def _slave_title(subentry, slave: int) -> str | None:
        """Return the new title, unless the user has renamed the slave.

        A renamed slave keeps its name, so a change of the configuration does
        not undo it.
        """
        if subentry.title.startswith("Slave "):
            # The title still carries the default, it may follow the address.
            return f"Slave {slave:02X}"
        return None

    def _slave_taken(self, slave: int, own_subentry_id: str | None) -> bool:
        """Return whether another slave of this master uses the address."""
        for subentry in self._get_entry().get_subentries_of_type(SUBENTRY_SLAVE):
            if subentry.subentry_id == own_subentry_id:
                continue
            if int(subentry.data.get(CONF_SLAVE, -1)) == slave:
                return True
        return False


class PanelSubentryFlow(ConfigSubentryFlow):
    """Add and change a bus with wall panels.

    The serial port is picked from the devices that are detected on the system.
    A port that is not listed can be entered by hand, the form comes back with
    that path filled in.
    """

    def __init__(self) -> None:
        """Initialize the flow."""
        self._suggested: dict = {}
        self._own_subentry_id: str | None = None

    async def async_step_user(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Add a panel bus."""
        if user_input is not None:
            if user_input.get(CONF_PORT) == SERIAL_PORT_MANUAL_VALUE:
                self._suggested = {
                    key: value for key, value in user_input.items() if key != CONF_PORT
                }
                return await self.async_step_port_manual()
            data = self._build_data(user_input)
            return self.async_create_entry(title=self._build_title(data), data=data)

        return self.async_show_form(
            step_id="user", data_schema=await self._async_schema(self._suggested)
        )

    async def async_step_port_manual(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Enter the path of a serial port that is not listed."""
        if user_input is not None:
            path = (user_input.get(CONF_PORT) or "").strip()
            if not path:
                return self.async_show_form(
                    step_id="port_manual",
                    data_schema=SERIAL_MANUAL_PATH_SCHEMA,
                    errors={"base": "invalid_serial_path"},
                )
            self._suggested = {**self._suggested, CONF_PORT: path}
            return await self.async_step_user(self._suggested)

        return self.async_show_form(
            step_id="port_manual", data_schema=SERIAL_MANUAL_PATH_SCHEMA
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Change a panel bus."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()

        if user_input is not None:
            if user_input.get(CONF_PORT) == SERIAL_PORT_MANUAL_VALUE:
                self._suggested = {
                    key: value for key, value in user_input.items() if key != CONF_PORT
                }
                return await self.async_step_port_manual()
            data = self._build_data(user_input)
            update = {"data": data}
            title = self._panel_title(subentry, data)
            if title is not None:
                update["title"] = title
            return self.async_update_and_abort(entry, subentry, **update)

        suggested = dict(subentry.data)
        panel_ids = suggested.get(CONF_PANEL_IDS) or [1]
        suggested["panel_start"] = min(panel_ids)
        suggested["panel_count"] = len(panel_ids)
        suggested.pop(CONF_PANEL_IDS, None)

        self._suggested = suggested
        self._own_subentry_id = subentry.subentry_id

        return self.async_show_form(
            step_id="reconfigure", data_schema=await self._async_schema(suggested)
        )

    async def _async_schema(self, suggested: dict) -> vol.Schema:
        """Build the form with the serial ports that are detected."""
        ports = await self.hass.async_add_executor_job(_list_serial_ports)
        used = _ports_in_use(self.hass, self._own_subentry_id)
        options = _serial_port_options(ports, used)

        current = suggested.get(CONF_PORT)
        if current and current not in options:
            # A path that was entered by hand stays selectable.
            options = {current: current, **options}

        default = current
        if default not in options:
            default = next(
                (
                    device
                    for device in options
                    if device != SERIAL_PORT_MANUAL_VALUE
                ),
                SERIAL_PORT_MANUAL_VALUE,
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=default): vol.In(options),
                **PANEL_FIELDS,
            }
        )
        if suggested:
            schema = self.add_suggested_values_to_schema(schema, suggested)
        return schema

    @staticmethod
    def _build_data(user_input: dict) -> dict:
        """Turn the form values into the data of the subentry."""
        data = dict(user_input)
        start = int(data.pop("panel_start", 1))
        count = int(data.pop("panel_count", 1))
        data[CONF_PANEL_IDS] = list(range(start, start + count))
        return data

    @staticmethod
    def _build_title(data: dict) -> str:
        """Return the title of the panel bus."""
        brand = str(data.get(CONF_BRAND, ""))
        port = data.get(CONF_PORT, "")
        return f"{brand.upper()} {port}"

    @staticmethod
    def _panel_title(subentry, data: dict) -> str | None:
        """Return the new title, unless the user has renamed the panel bus."""
        default = PanelSubentryFlow._build_title(data)
        if subentry.title.startswith(default.split(" ")[0].upper()):
            # The title still carries the default, it may follow the port.
            return default
        return None


class LinkageSubentryFlow(ConfigSubentryFlow):
    """Add and change a link between panel buttons and Modbus coils."""

    async def async_step_user(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Add a link."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=self._build_title(user_input),
                    data={
                        CONF_PANEL_ENTITIES: list(user_input[CONF_PANEL_ENTITIES]),
                        CONF_RELAY_ENTITIES: list(user_input[CONF_RELAY_ENTITIES]),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=LINKAGE_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict | None = None) -> SubentryFlowResult:
        """Change a link."""
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = self._validate(user_input)
            if not errors:
                update = {
                    "data": {
                        CONF_PANEL_ENTITIES: list(user_input[CONF_PANEL_ENTITIES]),
                        CONF_RELAY_ENTITIES: list(user_input[CONF_RELAY_ENTITIES]),
                    }
                }
                title = self._link_title(subentry, user_input)
                if title is not None:
                    update["title"] = title
                return self.async_update_and_abort(entry, subentry, **update)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                LINKAGE_SCHEMA, subentry.data
            ),
            errors=errors,
        )

    def _validate(self, user_input: dict) -> dict[str, str]:
        """Check that the picked entities are of the right kind."""
        errors: dict[str, str] = {}

        panels = list(user_input.get(CONF_PANEL_ENTITIES) or [])
        relays = list(user_input.get(CONF_RELAY_ENTITIES) or [])

        if not panels or not relays:
            errors["base"] = "linkage_empty"
            return errors

        entry_id = self._get_entry().entry_id
        for entity_id in panels:
            if _entity_kind(self.hass, entity_id, entry_id) != "panel":
                errors[CONF_PANEL_ENTITIES] = "not_a_panel_button"
                break
        for entity_id in relays:
            if _entity_kind(self.hass, entity_id, entry_id) != "coil":
                errors[CONF_RELAY_ENTITIES] = "not_a_coil"
                break

        return errors

    def _build_title(self, user_input: dict) -> str:
        """Return the title of the link."""
        panels = list(user_input.get(CONF_PANEL_ENTITIES) or [])
        relays = list(user_input.get(CONF_RELAY_ENTITIES) or [])
        panel = _friendly_name(self.hass, panels[0]) if panels else "?"
        relay = _friendly_name(self.hass, relays[0]) if relays else "?"
        return f"{panel} → {relay}"

    def _link_title(self, subentry, user_input: dict) -> str | None:
        """Return the new title, unless the user has renamed the link."""
        if " → " in subentry.title:
            # The title still carries the default, it may follow the entities.
            return self._build_title(user_input)
        return None


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
            vol.Optional(CONF_SCAN_INTERVAL, default=scan_default): NumberSelector(
                NumberSelectorConfig(
                    min=0.1, max=3600, step=0.1, mode=NumberSelectorMode.BOX
                )
            ),
        }

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options),
        )
