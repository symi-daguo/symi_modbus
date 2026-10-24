"""Export and import the configuration of the Symi Modbus integration.

The configuration is written as YAML, so it can be read, edited and kept under
version control. A link between a panel button and a relay is written as a
reference to the devices it belongs to and not as an entity id, so the text
stays readable and a link survives a change of the serial port.

The shape of the exported configuration:

```yaml
version: 1
connection:
  type: serial
  port: /dev/ttyS0
  baudrate: 9600
  bytesize: 8
  parity: N
  stopbits: 1
  scan_interval: 1.0
slaves:
  - address: 10
    first_coil: 0
    coil_count: 32
panel_buses:
  - port: /dev/ttyS1
    brand: symi
    baudrate: 9600
    bytesize: 8
    parity: N
    stopbits: 1
    panels: [1]
    buttons: 8
    led_frame: report
links:
  - mode: switch
    buttons:
      - bus: /dev/ttyS1
        panel: 1
        button: 1
    relays:
      - slave: 10
        coil: 0
```
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify
from homeassistant.util.yaml import dump as yaml_dump
from homeassistant.util.yaml import parse_yaml

from .const import (
    CONF_BRAND,
    CONF_BUTTONS,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_COIL_COUNT,
    CONF_COIL_START,
    CONF_FRAME,
    CONF_HOST,
    CONF_LED_FRAME_TYPE,
    CONF_LED_OFF_CODE,
    CONF_LED_ON_CODE,
    CONF_MODE,
    CONF_PANEL_ENTITIES,
    CONF_PANEL_IDS,
    CONF_PARITY,
    CONF_PORT,
    CONF_RELAY_ENTITIES,
    CONF_SCAN_INTERVAL,
    CONF_SLAVE,
    CONF_STOPBITS,
    CONF_TYPE,
    DEFAULT_COIL_COUNT,
    DEFAULT_SCAN_INTERVAL,
    FRAME_MBAP,
    LED_FRAME_REPORT,
    MODE_SWITCH,
    SUBENTRY_LINKAGE,
    SUBENTRY_PANEL,
    SUBENTRY_SLAVE,
)
from .panels import panel_keys

_LOGGER = logging.getLogger(__name__)

# The version of the format of the exported configuration.
CONFIG_VERSION: Final = 1

# The defaults of a connection, they are used when a field is left out.
DEFAULT_BAUDRATE: Final = 9600
DEFAULT_BYTESIZE: Final = 8
DEFAULT_PARITY: Final = "N"
DEFAULT_STOPBITS: Final = 1


class ConfigImportError(Exception):
    """The configuration that was handed in cannot be used."""


@dataclass
class ImportPlan:
    """What the configuration of the text means for the master."""

    connection: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)
    slaves: dict[int, dict[str, Any]] = field(default_factory=dict)
    panels: dict[str, dict[str, Any]] = field(default_factory=dict)
    links: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    """What the import did with the configuration."""

    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        """Return a readable summary of the import."""
        parts = []
        if self.created:
            parts.append(f"added {len(self.created)}")
        if self.updated:
            parts.append(f"changed {len(self.updated)}")
        if self.removed:
            parts.append(f"removed {len(self.removed)}")
        if not parts:
            return "nothing changed"
        return ", ".join(parts)


def button_entity_id(brand: str, panel_id: int, button: int) -> str:
    """Return the entity id a panel button gets.

    The name of the device and the name of the entity are put together the way
    Home Assistant does it, so the id of an imported button is the id the
    button gets when it is created.
    """
    return f"switch.{slugify(f'{brand.upper()} {panel_id:02X} Button {button:02d}')}"


def coil_entity_id(
    connection: dict[str, Any], slave: int, first_coil: int, address: int
) -> str:
    """Return the entity id a coil gets."""
    line = address - first_coil + 1
    return f"switch.{slugify(f'{_device_name(connection)} {slave:02X} Line {line:02d}')}"


def _device_name(connection: dict[str, Any]) -> str:
    """Return the name of the device the coils of a master belong to."""
    if connection.get("type") == "tcp":
        return f"TCP {connection.get('host')}:{connection.get('port')}"
    return f"Serial {connection.get('port')}"


def build_configuration(
    entry: ConfigEntry, entities: dict[str, er.RegistryEntry]
) -> dict[str, Any]:
    """Return the configuration of the entry."""
    connection = _export_connection(entry)
    slaves = [
        {
            "address": int(subentry.data[CONF_SLAVE]),
            "first_coil": int(subentry.data.get(CONF_COIL_START, 0)),
            "coil_count": int(
                subentry.data.get(CONF_COIL_COUNT, DEFAULT_COIL_COUNT)
            ),
        }
        for subentry in entry.get_subentries_of_type(SUBENTRY_SLAVE)
    ]
    panel_buses = [
        {
            "port": str(subentry.data[CONF_PORT]),
            "brand": str(subentry.data[CONF_BRAND]),
            "baudrate": int(subentry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)),
            "bytesize": int(subentry.data.get(CONF_BYTESIZE, DEFAULT_BYTESIZE)),
            "parity": str(subentry.data.get(CONF_PARITY, DEFAULT_PARITY)),
            "stopbits": int(subentry.data.get(CONF_STOPBITS, DEFAULT_STOPBITS)),
            "panels": [
                int(panel) for panel in subentry.data.get(CONF_PANEL_IDS, [])
            ],
            "buttons": panel_keys(
                str(subentry.data[CONF_BRAND]), subentry.data.get(CONF_BUTTONS)
            ),
            "led_frame": str(
                subentry.data.get(CONF_LED_FRAME_TYPE, LED_FRAME_REPORT)
            ),
            "led_on_code": subentry.data.get(CONF_LED_ON_CODE),
            "led_off_code": subentry.data.get(CONF_LED_OFF_CODE),
        }
        for subentry in entry.get_subentries_of_type(SUBENTRY_PANEL)
    ]
    links = _export_links(entry, entities, connection, slaves, panel_buses)

    return {
        "version": CONFIG_VERSION,
        "connection": connection,
        "slaves": slaves,
        "panel_buses": panel_buses,
        "links": links,
    }


def export_configuration(hass: HomeAssistant, entry: ConfigEntry) -> str:
    """Return the configuration of the entry as YAML."""
    registry = er.async_get(hass)
    entities = {
        item.entity_id: item
        for item in er.async_entries_for_config_entry(registry, entry.entry_id)
    }
    return yaml_dump(build_configuration(entry, entities))


def _export_connection(entry: ConfigEntry) -> dict[str, Any]:
    """Return the connection of the master."""
    data = entry.data
    connection: dict[str, Any] = {
        "type": str(data.get(CONF_TYPE, "")),
        "port": str(data.get(CONF_PORT, "")),
    }
    if connection["type"] == "tcp":
        connection["host"] = str(data.get(CONF_HOST, ""))
        connection["frame"] = str(data.get(CONF_FRAME, FRAME_MBAP))
    connection["baudrate"] = int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE))
    connection["bytesize"] = int(data.get(CONF_BYTESIZE, DEFAULT_BYTESIZE))
    connection["parity"] = str(data.get(CONF_PARITY, DEFAULT_PARITY))
    connection["stopbits"] = int(data.get(CONF_STOPBITS, DEFAULT_STOPBITS))
    connection["scan_interval"] = float(
        entry.options.get(
            CONF_SCAN_INTERVAL,
            data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
    )
    return connection


def _export_links(
    entry: ConfigEntry,
    entities: dict[str, er.RegistryEntry],
    connection: dict[str, Any],
    slaves: list[dict[str, Any]],
    panel_buses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the links of the entry, as references to the devices."""
    slave_map = {int(item["address"]): item for item in slaves}
    bus_map = {str(item["port"]): item for item in panel_buses}
    links = []
    for subentry in entry.get_subentries_of_type(SUBENTRY_LINKAGE):
        buttons = []
        for entity_id in subentry.data.get(CONF_PANEL_ENTITIES, []):
            reference = _button_reference(entry, entities.get(entity_id))
            if reference is None:
                _LOGGER.warning(
                    "The button %s is not known any more, it is left out of the export",
                    entity_id,
                )
                continue
            _check_button_id(entity_id, reference, bus_map)
            buttons.append(reference)
        relays = []
        for entity_id in subentry.data.get(CONF_RELAY_ENTITIES, []):
            reference = _relay_reference(entities.get(entity_id))
            if reference is None:
                _LOGGER.warning(
                    "The relay %s is not known any more, it is left out of the export",
                    entity_id,
                )
                continue
            _check_relay_id(entity_id, reference, connection, slave_map)
            relays.append(reference)
        if not buttons or not relays:
            continue
        links.append(
            {
                "mode": str(subentry.data.get(CONF_MODE, MODE_SWITCH)),
                "buttons": buttons,
                "relays": relays,
            }
        )
    return links


def _check_button_id(
    entity_id: str, reference: dict[str, Any], buses: dict[str, dict[str, Any]]
) -> None:
    """Tell in the log when the name of a button does not follow the naming.

    The id of a button is worked out from the names of the device and the
    entity, so a change of one of them would break the import.
    """
    bus = buses.get(str(reference["bus"]))
    if bus is None:
        return
    expected = button_entity_id(
        str(bus["brand"]), int(reference["panel"]), int(reference["button"])
    )
    if expected != entity_id:
        _LOGGER.warning(
            "The button %s is not named the way the import expects it (%s)",
            entity_id,
            expected,
        )


def _check_relay_id(
    entity_id: str,
    reference: dict[str, Any],
    connection: dict[str, Any],
    slaves: dict[int, dict[str, Any]],
) -> None:
    """Tell in the log when the name of a relay does not follow the naming."""
    slave = slaves.get(int(reference["slave"]))
    if slave is None:
        return
    expected = coil_entity_id(
        connection,
        int(reference["slave"]),
        int(slave["first_coil"]),
        int(reference["coil"]),
    )
    if expected != entity_id:
        _LOGGER.warning(
            "The relay %s is not named the way the import expects it (%s)",
            entity_id,
            expected,
        )


def _button_reference(
    entry: ConfigEntry, item: er.RegistryEntry | None
) -> dict[str, Any] | None:
    """Return the reference to the panel button of an entity."""
    if item is None:
        return None
    parts = item.unique_id.split("_")
    # <entry id> _ panel _ <subentry id> _ <panel> _ <button>
    if len(parts) != 5 or parts[1] != "panel":
        return None
    subentry = entry.subentries.get(parts[2])
    if subentry is None or subentry.subentry_type != SUBENTRY_PANEL:
        return None
    return {
        "bus": str(subentry.data[CONF_PORT]),
        "panel": int(parts[3]),
        "button": int(parts[4]),
    }


def _relay_reference(item: er.RegistryEntry | None) -> dict[str, Any] | None:
    """Return the reference to the relay of an entity."""
    if item is None:
        return None
    parts = item.unique_id.split("_")
    # <entry id> _ <slave> _ <address>
    if len(parts) != 3:
        return None
    try:
        return {"slave": int(parts[1]), "coil": int(parts[2])}
    except ValueError:
        return None


def parse_configuration(text: str) -> dict[str, Any]:
    """Return the configuration of the text.

    Raises ConfigImportError when the text cannot be used.
    """
    try:
        parsed = parse_yaml(text)
    except HomeAssistantError as err:
        raise ConfigImportError(f"The configuration is not valid YAML: {err}") from err

    if not isinstance(parsed, dict):
        raise ConfigImportError("The configuration has to be a mapping")
    if parsed.get("version") != CONFIG_VERSION:
        raise ConfigImportError(
            f"The configuration has the version {parsed.get('version')}, "
            f"the version {CONFIG_VERSION} is needed"
        )
    connection = parsed.get("connection")
    if not isinstance(connection, dict):
        raise ConfigImportError("The configuration has no connection")
    if not connection.get("port"):
        raise ConfigImportError("The configuration has no port")
    for name in ("slaves", "panel_buses", "links"):
        if name in parsed and not isinstance(parsed[name], list):
            raise ConfigImportError(f"The {name} of the configuration have to be a list")
    # A master always has at least one slave, so a configuration without one
    # was cut short and would take the slaves away.
    if not parsed.get("slaves"):
        raise ConfigImportError("The configuration has no slave")
    return parsed


def plan_import(entry: ConfigEntry, text: str) -> ImportPlan:
    """Return what the configuration of the text means for the master."""
    config = parse_configuration(text)
    plan = ImportPlan()
    connection = config["connection"]

    data = dict(entry.data)
    data[CONF_TYPE] = str(connection.get("type", "serial"))
    data[CONF_PORT] = str(connection.get("port", ""))
    if data[CONF_TYPE] == "tcp":
        data[CONF_HOST] = str(connection.get("host", ""))
        data[CONF_FRAME] = str(connection.get("frame", FRAME_MBAP))
    data[CONF_BAUDRATE] = int(connection.get("baudrate", DEFAULT_BAUDRATE))
    data[CONF_BYTESIZE] = int(connection.get("bytesize", DEFAULT_BYTESIZE))
    data[CONF_PARITY] = str(connection.get("parity", DEFAULT_PARITY))
    data[CONF_STOPBITS] = int(connection.get("stopbits", DEFAULT_STOPBITS))
    plan.connection = data

    options = dict(entry.options)
    if "scan_interval" in connection:
        options[CONF_SCAN_INTERVAL] = float(connection["scan_interval"])
    plan.options = options

    for item in config.get("slaves", []):
        try:
            slave_data = _slave_data(item)
        except (KeyError, TypeError, ValueError):
            plan.problems.append(f"The slave {item} cannot be read")
            continue
        plan.slaves[int(slave_data[CONF_SLAVE])] = slave_data

    for item in config.get("panel_buses", []):
        try:
            panel_data = _panel_data(item)
        except (KeyError, TypeError, ValueError):
            plan.problems.append(f"The panel bus {item} cannot be read")
            continue
        plan.panels[panel_data[CONF_PORT]] = panel_data

    for item in config.get("links", []):
        link_data = _link_data(item, connection, plan.slaves, plan.panels, plan.problems)
        if link_data is not None:
            plan.links.append(link_data)

    return plan


def _slave_data(item: dict[str, Any]) -> dict[str, Any]:
    """Return the data of a slave of the configuration."""
    return {
        CONF_SLAVE: int(item["address"]),
        CONF_COIL_START: int(item.get("first_coil", 0)),
        CONF_COIL_COUNT: int(item.get("coil_count", DEFAULT_COIL_COUNT)),
    }


def _panel_data(item: dict[str, Any]) -> dict[str, Any]:
    """Return the data of a panel bus of the configuration."""
    brand = str(item["brand"])
    data: dict[str, Any] = {
        CONF_PORT: str(item["port"]),
        CONF_BRAND: brand,
        CONF_BAUDRATE: int(item.get("baudrate", DEFAULT_BAUDRATE)),
        CONF_BYTESIZE: int(item.get("bytesize", DEFAULT_BYTESIZE)),
        CONF_PARITY: str(item.get("parity", DEFAULT_PARITY)),
        CONF_STOPBITS: int(item.get("stopbits", DEFAULT_STOPBITS)),
        CONF_PANEL_IDS: [int(panel) for panel in item.get("panels", [])],
        # A panel has as many keys as its protocol says, never more.
        CONF_BUTTONS: panel_keys(brand, item.get("buttons")),
        CONF_LED_FRAME_TYPE: str(item.get("led_frame", LED_FRAME_REPORT)),
    }
    if item.get("led_on_code") is not None:
        data[CONF_LED_ON_CODE] = int(item["led_on_code"])
    if item.get("led_off_code") is not None:
        data[CONF_LED_OFF_CODE] = int(item["led_off_code"])
    return data


def _link_data(
    item: dict[str, Any],
    connection: dict[str, Any],
    slaves: dict[int, dict[str, Any]],
    buses: dict[str, dict[str, Any]],
    problems: list[str],
) -> dict[str, Any] | None:
    """Return the data of a link of the configuration.

    The entity ids of the buttons and the relays are worked out from the
    devices they belong to, so a link keeps working when the serial port of
    the master changes.
    """
    buttons = []
    for reference in item.get("buttons", []):
        bus = buses.get(str(reference.get("bus")))
        if bus is None:
            problems.append(f"The panel bus {reference.get('bus')} is not configured")
            continue
        panel_id = int(reference["panel"])
        button = int(reference["button"])
        if panel_id not in bus[CONF_PANEL_IDS]:
            problems.append(f"The panel {panel_id:02X} is not on the bus {bus[CONF_PORT]}")
            continue
        buttons.append(button_entity_id(str(bus[CONF_BRAND]), panel_id, button))

    relays = []
    for reference in item.get("relays", []):
        slave = int(reference["slave"])
        address = int(reference["coil"])
        options = slaves.get(slave)
        if options is None:
            problems.append(f"The slave {slave} is not configured")
            continue
        first = int(options.get(CONF_COIL_START, 0))
        count = int(options.get(CONF_COIL_COUNT, DEFAULT_COIL_COUNT))
        if not first <= address < first + count:
            problems.append(f"The coil {address} is not on the slave {slave:02X}")
            continue
        relays.append(coil_entity_id(connection, slave, first, address))

    if not buttons or not relays:
        return None
    return {
        CONF_PANEL_ENTITIES: buttons,
        CONF_RELAY_ENTITIES: relays,
        CONF_MODE: str(item.get("mode", MODE_SWITCH)),
    }


def _link_title(data: dict[str, Any]) -> str:
    """Return the title of a link."""
    return f"{data[CONF_PANEL_ENTITIES][0]} → {data[CONF_RELAY_ENTITIES][0]}"


async def import_configuration(
    hass: HomeAssistant, entry: ConfigEntry, text: str
) -> ImportResult:
    """Bring the configuration of the entry in line with the configuration.

    The parts that are already there are changed, the parts that are new are
    added and the parts that are not in the configuration any more are removed.
    """
    plan = plan_import(entry, text)
    result = ImportResult(problems=list(plan.problems))

    if plan.connection != dict(entry.data):
        hass.config_entries.async_update_entry(entry, data=plan.connection)
        result.updated.append("connection")
    if plan.options != dict(entry.options):
        hass.config_entries.async_update_entry(entry, options=plan.options)
        result.updated.append("options")

    # The slaves.
    for subentry in entry.get_subentries_of_type(SUBENTRY_SLAVE):
        address = int(subentry.data[CONF_SLAVE])
        if address in plan.slaves:
            continue
        hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
        result.removed.append(f"slave {address:02X}")
    for address, slave_data in plan.slaves.items():
        existing = next(
            (
                subentry
                for subentry in entry.get_subentries_of_type(SUBENTRY_SLAVE)
                if int(subentry.data[CONF_SLAVE]) == address
            ),
            None,
        )
        if existing is None:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=slave_data,
                    subentry_type=SUBENTRY_SLAVE,
                    title=f"Slave {address:02X}",
                    unique_id=str(address),
                ),
            )
            result.created.append(f"slave {address:02X}")
        elif dict(existing.data) != slave_data:
            hass.config_entries.async_update_subentry(entry, existing, data=slave_data)
            result.updated.append(f"slave {address:02X}")

    # The panel buses.
    for subentry in entry.get_subentries_of_type(SUBENTRY_PANEL):
        port = str(subentry.data[CONF_PORT])
        if port in plan.panels:
            continue
        hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
        result.removed.append(f"panel bus {port}")
    for port, panel_data in plan.panels.items():
        existing = next(
            (
                subentry
                for subentry in entry.get_subentries_of_type(SUBENTRY_PANEL)
                if str(subentry.data[CONF_PORT]) == port
            ),
            None,
        )
        if existing is None:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=panel_data,
                    subentry_type=SUBENTRY_PANEL,
                    title=f"{str(panel_data[CONF_BRAND]).upper()} {port}",
                    unique_id=port,
                ),
            )
            result.created.append(f"panel bus {port}")
        elif dict(existing.data) != panel_data:
            hass.config_entries.async_update_subentry(entry, existing, data=panel_data)
            result.updated.append(f"panel bus {port}")

    # The links.
    existing_links = {
        tuple(subentry.data.get(CONF_PANEL_ENTITIES, [])): subentry
        for subentry in entry.get_subentries_of_type(SUBENTRY_LINKAGE)
    }
    for buttons, subentry in existing_links.items():
        if any(link[CONF_PANEL_ENTITIES] == list(buttons) for link in plan.links):
            continue
        hass.config_entries.async_remove_subentry(entry, subentry.subentry_id)
        result.removed.append(f"link {subentry.title}")
    for link_data in plan.links:
        buttons = link_data[CONF_PANEL_ENTITIES]
        existing = existing_links.get(tuple(buttons))
        if existing is None:
            hass.config_entries.async_add_subentry(
                entry,
                ConfigSubentry(
                    data=link_data,
                    subentry_type=SUBENTRY_LINKAGE,
                    title=_link_title(link_data),
                    unique_id=None,
                ),
            )
            result.created.append(f"link {_link_title(link_data)}")
        elif dict(existing.data) != link_data:
            hass.config_entries.async_update_subentry(entry, existing, data=link_data)
            result.updated.append(f"link {existing.title}")

    return result
