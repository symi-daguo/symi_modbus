"""The log of a panel bus has to tell the truth."""
from __future__ import annotations

import logging

from custom_components.symi_modbus.panels.manager import PanelManager


def _manager() -> PanelManager:
    """Return a manager with one bus and no buttons."""
    manager = PanelManager.__new__(PanelManager)
    manager._bus_info = {"bus": ("/dev/ttyS1", "symi", "01")}
    manager._buttons = {}
    return manager


def test_a_bus_is_only_ready_when_it_is_open(caplog) -> None:
    """The bus is reported as ready when its port is really open."""
    manager = _manager()

    with caplog.at_level(logging.INFO):
        manager._handle_state("bus", connected=True)

    assert "Panel bus on /dev/ttyS1 ready" in caplog.text


def test_a_bus_that_is_not_open_is_not_ready(caplog) -> None:
    """A bus that is down is not reported as ready."""
    manager = _manager()

    with caplog.at_level(logging.INFO):
        manager._handle_state("bus", connected=False)

    assert "ready" not in caplog.text
