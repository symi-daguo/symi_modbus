"""Tests for the configuration flows of the Symi Modbus integration."""
from __future__ import annotations

from custom_components.symi_modbus.config_flow import (
    LinkageSubentryFlow,
    PanelSubentryFlow,
    SlaveSubentryFlow,
    _serial_port_options,
    _slave_addresses,
)
from custom_components.symi_modbus.const import (
    CONF_BRAND,
    CONF_PORT,
    SERIAL_PORT_MANUAL_VALUE,
)


class FakeSubentry:
    """Minimal stand-in for a config subentry."""

    def __init__(self, title: str, data: dict | None = None) -> None:
        """Store the title and the data of the subentry."""
        self.title = title
        self.data = data or {}
        self.subentry_id = "fake"
        self.subentry_type = "fake"


class FakePort:
    """Minimal stand-in for a detected serial port."""

    def __init__(self, device: str) -> None:
        """Store the device path."""
        self.device = device
        self.description = ""
        self.manufacturer = ""
        self.product = ""
        self.vid = None
        self.pid = None


def test_a_batch_of_slaves_covers_the_addresses() -> None:
    """A batch starts at the first address and follows it."""
    assert _slave_addresses(10, 1) == [10]
    assert _slave_addresses(10, 4) == [10, 11, 12, 13]
    assert _slave_addresses(0x0A, 0) == [0x0A]


def test_the_port_picker_leaves_out_the_ports_in_use() -> None:
    """A port that is already used is not offered again."""
    ports = [FakePort("/dev/ttyS0"), FakePort("/dev/ttyUSB0")]
    options = _serial_port_options(ports, {"/dev/ttyS0"})

    assert "/dev/ttyS0" not in options
    assert "/dev/ttyUSB0" in options
    # A path that is not listed can always be entered by hand.
    assert SERIAL_PORT_MANUAL_VALUE in options


def test_a_port_that_nothing_holds_has_no_holder(tmp_path) -> None:
    """A serial port that no program holds is free."""
    from custom_components.symi_modbus.panels.connection import serial_port_holders

    assert serial_port_holders(str(tmp_path / "ttyNothing")) == 0


def test_a_renamed_slave_keeps_its_title() -> None:
    """A slave that was renamed keeps its name when it is changed."""
    renamed = FakeSubentry("客厅灯")
    assert SlaveSubentryFlow._slave_title(renamed, 11) is None

    default = FakeSubentry("Slave 0A")
    assert SlaveSubentryFlow._slave_title(default, 11) == "Slave 0B"


def test_a_renamed_panel_bus_keeps_its_title() -> None:
    """A panel bus that was renamed keeps its name when it is changed."""
    renamed = FakeSubentry("二楼面板", {"brand": "symi", "port": "/dev/ttyS0"})
    assert PanelSubentryFlow._panel_title(renamed, {CONF_BRAND: "symi"}) is None

    default = FakeSubentry("SYMI /dev/ttyS0", {"brand": "symi", "port": "/dev/ttyS0"})
    data = {CONF_BRAND: "symi", CONF_PORT: "/dev/ttyS1"}
    assert PanelSubentryFlow._panel_title(default, data) == "SYMI /dev/ttyS1"


def test_a_renamed_link_keeps_its_title() -> None:
    """A link that was renamed keeps its name when it is changed."""
    flow = LinkageSubentryFlow.__new__(LinkageSubentryFlow)
    flow.hass = None

    renamed = FakeSubentry("玄关灯")
    assert flow._link_title(renamed, {}) is None

    default = FakeSubentry("面板 → 继电器")
    assert flow._link_title(default, {}) is not None
