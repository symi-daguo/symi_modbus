"""Panel buses can share a serial port."""
from __future__ import annotations

import pytest

from custom_components.symi_modbus.panels.base import ButtonEvent
from custom_components.symi_modbus.panels.manager import PanelManager
from custom_components.symi_modbus.panels.symi import SymiProtocol


class FakeConnection:
    """A connection that only remembers what it was told to do."""

    def __init__(self) -> None:
        """Initialize the fake."""
        self.started = False
        self.stopped = False
        self.frames: list[bytes] = []

    async def async_start(self) -> None:
        """Remember that the bus was started."""
        self.started = True

    async def async_stop(self) -> None:
        """Remember that the bus was stopped."""
        self.stopped = True

    async def async_write_raw(self, frame: bytes) -> None:
        """Keep the frame."""
        self.frames.append(frame)

    def own_handle(self) -> set[tuple[str, str]]:
        """Return no handle."""
        return set()


def _manager() -> PanelManager:
    """Return a manager without any bus."""
    manager = PanelManager.__new__(PanelManager)
    manager._buses = {}
    manager._protocols = {}
    manager._members = {}
    manager._ports = {}
    manager._port_settings = {}
    manager._panel_ids = {}
    manager._addresses = {}
    manager._buttons = {}
    manager._manual_codes = {}
    manager._bus_info = {}
    manager._event_listeners = []
    return manager


async def test_a_second_panel_bus_shares_the_port() -> None:
    """A panel bus that uses a port of another one does not open it again."""
    manager = _manager()
    connection = FakeConnection()
    manager._buses["/dev/ttyS1"] = connection
    manager._protocols["/dev/ttyS1"] = SymiProtocol()
    manager._port_settings["/dev/ttyS1"] = ("symi", "report", 9600, 8, "N", 1)

    await manager.async_add_bus(
        "bus2",
        port="/dev/ttyS1",
        brand="symi",
        panel_ids=[2],
    )

    # The port is still the same connection.
    assert manager._buses["/dev/ttyS1"] is connection
    assert manager._members["/dev/ttyS1"] == ["bus2"]
    assert manager._ports["bus2"] == "/dev/ttyS1"


async def test_the_port_stays_open_for_the_other_panel_bus() -> None:
    """The port is only closed when the last panel bus that uses it is gone."""
    manager = _manager()
    connection = FakeConnection()
    manager._buses["/dev/ttyS1"] = connection
    manager._protocols["/dev/ttyS1"] = SymiProtocol()
    manager._port_settings["/dev/ttyS1"] = ("symi", "report", 9600, 8, "N", 1)
    manager._members["/dev/ttyS1"] = ["bus1"]
    manager._ports["bus1"] = "/dev/ttyS1"
    manager._panel_ids["bus1"] = [1]

    await manager.async_add_bus(
        "bus2", port="/dev/ttyS1", brand="symi", panel_ids=[2]
    )
    await manager.async_remove_bus("bus2")

    assert connection.stopped is False
    assert "/dev/ttyS1" in manager._buses

    await manager.async_remove_bus("bus1")

    assert connection.stopped is True
    assert manager._buses == {}


def test_an_event_goes_to_the_panel_bus_of_its_panel() -> None:
    """A button event is only given to the panel bus that carries the panel."""
    manager = _manager()
    manager._members["/dev/ttyS1"] = ["bus1", "bus2"]
    manager._panel_ids["bus1"] = [1]
    manager._panel_ids["bus2"] = [2]

    seen: list[str] = []
    manager._handle_event = lambda subentry_id, event: seen.append(subentry_id)

    handle = manager._make_handler("/dev/ttyS1")
    handle(ButtonEvent(panel_id=1, button=1, state=True))
    handle(ButtonEvent(panel_id=2, button=1, state=True))
    handle(ButtonEvent(panel_id=3, button=1, state=True))

    assert seen == ["bus1", "bus2"]


def test_the_state_is_told_to_every_panel_bus_of_the_port() -> None:
    """The state of the port is told to all the panel buses that use it."""
    manager = _manager()
    manager._members["/dev/ttyS1"] = ["bus1", "bus2"]

    seen: list[str] = []
    manager._handle_state = lambda subentry_id, connected: seen.append(subentry_id)

    manager._make_state_handler("/dev/ttyS1")(True)

    assert seen == ["bus1", "bus2"]


@pytest.mark.parametrize("brand", ["symi"])
def test_the_panel_of_a_shared_port_is_found(brand: str) -> None:
    """A panel bus knows the panels it carries."""
    manager = _manager()
    manager._panel_ids["bus1"] = [1, 2]

    assert manager.panel_ids("bus1") == [1, 2]
    assert manager.panel_ids("bus2") == []
