"""Export and import the configuration of the Symi Modbus integration."""
from __future__ import annotations

import pytest

from custom_components.symi_modbus.config_io import (
    ConfigImportError,
    button_entity_id,
    build_configuration,
    coil_entity_id,
    parse_configuration,
    plan_import,
)
from custom_components.symi_modbus.const import (
    CONF_BRAND,
    CONF_BUTTONS,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_COIL_COUNT,
    CONF_COIL_START,
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
    MODE_SWITCH,
    SUBENTRY_LINKAGE,
    SUBENTRY_PANEL,
    SUBENTRY_SLAVE,
)

ENTRY_ID = "01M5H3KV2X723TBMXYEM9KWNVE"
PANEL_ID = "01M5K54E7PQKNSYX1TM6JKZEY3"


class FakeSubentry:
    """A config subentry with the fields the export uses."""

    def __init__(self, subentry_id: str, subentry_type: str, title: str, data: dict):
        """Store the subentry."""
        self.subentry_id = subentry_id
        self.subentry_type = subentry_type
        self.title = title
        self.data = data


class FakeEntry:
    """A config entry with the fields the export and the import use."""

    def __init__(self, data: dict, options: dict, subentries: list[FakeSubentry]):
        """Store the entry."""
        self.entry_id = ENTRY_ID
        self.data = data
        self.options = options
        self.subentries = {subentry.subentry_id: subentry for subentry in subentries}

    def get_subentries_of_type(self, subentry_type: str) -> list[FakeSubentry]:
        """Return the subentries of one kind."""
        return [
            subentry
            for subentry in self.subentries.values()
            if subentry.subentry_type == subentry_type
        ]


class FakeRegistryEntry:
    """An entity of the registry with the fields the export uses."""

    def __init__(self, entity_id: str, unique_id: str):
        """Store the entity."""
        self.entity_id = entity_id
        self.unique_id = unique_id


def _entry() -> FakeEntry:
    """Return an entry with two slaves, a panel bus and a link."""
    return FakeEntry(
        {
            CONF_TYPE: "serial",
            CONF_PORT: "/dev/ttyS0",
            CONF_BAUDRATE: 9600,
            CONF_BYTESIZE: 8,
            CONF_PARITY: "N",
            CONF_STOPBITS: 1,
        },
        {CONF_SCAN_INTERVAL: 1.0},
        [
            FakeSubentry(
                "slave0A",
                SUBENTRY_SLAVE,
                "Slave 0A",
                {CONF_SLAVE: 10, CONF_COIL_START: 0, CONF_COIL_COUNT: 32},
            ),
            FakeSubentry(
                "slave0B",
                SUBENTRY_SLAVE,
                "Slave 0B",
                {CONF_SLAVE: 11, CONF_COIL_START: 0, CONF_COIL_COUNT: 32},
            ),
            FakeSubentry(
                PANEL_ID,
                SUBENTRY_PANEL,
                "SYMI /dev/ttyS1",
                {
                    CONF_PORT: "/dev/ttyS1",
                    CONF_BRAND: "symi",
                    CONF_BAUDRATE: 9600,
                    CONF_BYTESIZE: 8,
                    CONF_PARITY: "N",
                    CONF_STOPBITS: 1,
                    CONF_PANEL_IDS: [1],
                    CONF_BUTTONS: 8,
                },
            ),
            FakeSubentry(
                "link01",
                SUBENTRY_LINKAGE,
                "link",
                {
                    CONF_PANEL_ENTITIES: ["switch.symi_01_button_01"],
                    CONF_RELAY_ENTITIES: ["switch.serial_dev_ttys0_0a_line_01"],
                    CONF_MODE: MODE_SWITCH,
                },
            ),
        ],
    )


def _entities() -> dict[str, FakeRegistryEntry]:
    """Return the entities of the entry."""
    return {
        "switch.symi_01_button_01": FakeRegistryEntry(
            "switch.symi_01_button_01",
            f"{ENTRY_ID}_panel_{PANEL_ID}_1_1",
        ),
        "switch.serial_dev_ttys0_0a_line_01": FakeRegistryEntry(
            "switch.serial_dev_ttys0_0a_line_01",
            f"{ENTRY_ID}_10_0",
        ),
    }


def test_the_export_holds_the_configuration() -> None:
    """The export carries the connection, the slaves, the panels and the links."""
    config = build_configuration(_entry(), _entities())

    assert config["version"] == 1
    assert config["connection"]["port"] == "/dev/ttyS0"
    assert config["connection"]["scan_interval"] == 1.0
    assert config["slaves"] == [
        {"address": 10, "first_coil": 0, "coil_count": 32},
        {"address": 11, "first_coil": 0, "coil_count": 32},
    ]
    assert config["panel_buses"][0]["port"] == "/dev/ttyS1"
    assert config["panel_buses"][0]["panels"] == [1]


def test_a_link_is_written_as_a_reference() -> None:
    """A link is written as the devices it belongs to, not as an entity id."""
    config = build_configuration(_entry(), _entities())

    assert config["links"] == [
        {
            "mode": "switch",
            "buttons": [{"bus": "/dev/ttyS1", "panel": 1, "button": 1}],
            "relays": [{"slave": 10, "coil": 0}],
        }
    ]


def test_the_codes_of_the_light_are_written_out() -> None:
    """The codes of the indicator light are part of the configuration."""
    entry = _entry()
    entry.subentries[PANEL_ID].data[CONF_LED_ON_CODE] = 17

    config = build_configuration(entry, _entities())

    assert config["panel_buses"][0]["led_on_code"] == 17
    assert config["panel_buses"][0]["led_off_code"] is None


def test_the_entity_ids_follow_the_naming() -> None:
    """The ids of the entities are worked out the way Home Assistant makes them."""
    assert button_entity_id("symi", 1, 1) == "switch.symi_01_button_01"
    assert (
        coil_entity_id({"type": "serial", "port": "/dev/ttyS0"}, 10, 0, 0)
        == "switch.serial_dev_ttys0_0a_line_01"
    )
    assert (
        coil_entity_id({"type": "serial", "port": "/dev/ttyS0"}, 10, 0, 4)
        == "switch.serial_dev_ttys0_0a_line_05"
    )


def test_a_configuration_that_is_broken_is_refused() -> None:
    """A configuration that cannot be read is refused."""
    with pytest.raises(ConfigImportError):
        parse_configuration("version: 1\nconnection:\n  port: /dev/ttyS0\n")

    with pytest.raises(ConfigImportError):
        parse_configuration("this is not yaml: [")

    with pytest.raises(ConfigImportError):
        parse_configuration("version: 9\nconnection:\n  port: /dev/ttyS0\n")


def test_the_import_plans_what_the_configuration_means() -> None:
    """The plan tells what the configuration means for the master."""
    text = """
version: 1
connection:
  type: serial
  port: /dev/ttyS0
  baudrate: 9600
  bytesize: 8
  parity: N
  stopbits: 1
  scan_interval: 2.0
slaves:
  - address: 10
    first_coil: 0
    coil_count: 32
  - address: 12
    first_coil: 0
    coil_count: 16
panel_buses:
  - port: /dev/ttyS1
    brand: symi
    baudrate: 9600
    bytesize: 8
    parity: N
    stopbits: 1
    panels: [1, 2]
    buttons: 8
    led_frame: report
links:
  - mode: switch
    buttons:
      - bus: /dev/ttyS1
        panel: 1
        button: 1
    relays:
      - slave: 12
        coil: 3
"""

    plan = plan_import(_entry(), text)

    assert plan.slaves[10][CONF_COIL_COUNT] == 32
    assert plan.slaves[12][CONF_COIL_COUNT] == 16
    assert plan.panels["/dev/ttyS1"][CONF_PANEL_IDS] == [1, 2]
    assert plan.options[CONF_SCAN_INTERVAL] == 2.0
    assert plan.links[0][CONF_PANEL_ENTITIES] == ["switch.symi_01_button_01"]
    assert plan.links[0][CONF_RELAY_ENTITIES] == [
        "switch.serial_dev_ttys0_0c_line_04"
    ]


def test_a_link_that_points_at_nothing_is_reported() -> None:
    """A link that points at a device that is not configured is reported."""
    text = """
version: 1
connection:
  type: serial
  port: /dev/ttyS0
slaves:
  - address: 10
    first_coil: 0
    coil_count: 32
panel_buses:
  - port: /dev/ttyS1
    brand: symi
    panels: [1]
    buttons: 8
links:
  - mode: switch
    buttons:
      - bus: /dev/ttyS1
        panel: 3
        button: 1
    relays:
      - slave: 10
        coil: 0
"""

    plan = plan_import(_entry(), text)

    assert plan.links == []
    assert any("panel 03" in problem for problem in plan.problems)


def test_a_link_survives_a_change_of_the_port() -> None:
    """The entity ids of a link follow the port of the configuration."""
    text = """
version: 1
connection:
  type: serial
  port: /dev/ttyUSB0
slaves:
  - address: 10
    first_coil: 0
    coil_count: 32
panel_buses:
  - port: /dev/ttyS1
    brand: symi
    panels: [1]
    buttons: 8
links:
  - mode: switch
    buttons:
      - bus: /dev/ttyS1
        panel: 1
        button: 1
    relays:
      - slave: 10
        coil: 0
"""

    plan = plan_import(_entry(), text)

    assert plan.links[0][CONF_RELAY_ENTITIES] == [
        "switch.serial_dev_ttyusb0_0a_line_01"
    ]
