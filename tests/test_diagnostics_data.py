"""The raw data of the bus is kept for the diagnostics."""
from __future__ import annotations

from custom_components.symi_modbus.connection import ModbusConnection
from custom_components.symi_modbus.panels.connection import PanelConnection
from custom_components.symi_modbus.panels.symi import SymiProtocol


def test_the_frames_of_the_master_line_are_kept() -> None:
    """The last frames of the master line are kept."""
    connection = ModbusConnection(connection_type="serial", port="/dev/ttyS0")

    connection._remember(">", b"\x0a\x01")
    connection._remember("<", b"\x0a\x02")

    assert connection.recent_traffic() == ["> 0A 01", "< 0A 02"]


def test_only_the_last_frames_are_kept() -> None:
    """The buffer of the frames does not grow without limit."""
    connection = ModbusConnection(connection_type="serial", port="/dev/ttyS0")

    for index in range(100):
        connection._remember(">", bytes([index % 256]))

    traffic = connection.recent_traffic()
    assert len(traffic) == 40
    assert traffic[-1] == "> 63"


def test_the_chunks_of_a_panel_line_are_kept() -> None:
    """The last chunks of a panel line are kept."""
    connection = PanelConnection(
        hass=None,
        port="/dev/ttyS1",
        protocol=SymiProtocol(),
        on_event=lambda event: None,
    )

    connection._remember("<", b"\x7e\x02")

    assert connection.recent_traffic() == ["< 7E 02"]


def test_only_the_last_chunks_are_kept() -> None:
    """The buffer of the chunks does not grow without limit."""
    connection = PanelConnection(
        hass=None,
        port="/dev/ttyS1",
        protocol=SymiProtocol(),
        on_event=lambda event: None,
    )

    for index in range(100):
        connection._remember("<", bytes([index % 256]))

    traffic = connection.recent_traffic()
    assert len(traffic) == 40
    assert traffic[-1] == "< 63"
