"""The cards of the configuration carry the place they have in it."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from custom_components.symi_modbus.card_order import card_titles


@dataclass
class FakeSubentry:
    """A subentry with the fields the order looks at."""

    subentry_id: str
    title: str
    data: dict = field(default_factory=dict)


@dataclass
class FakeEntry:
    """A config entry with the subentries of a person."""

    subentries: dict = field(default_factory=dict)

    def get_subentries_of_type(self, kind: str) -> list:
        return [s for s in self.subentries.values() if s.data.get("kind") == kind]


def _entry() -> FakeEntry:
    """Return an entry with a slave, a panel bus and two links."""
    return FakeEntry(
        {
            "link2": FakeSubentry(
                "link2",
                "SYMI 02 按键 01 → 0B 线路 01",
                {"kind": "linkage", "relay_entities": ["switch.serial_dev_ttys0_0b_line_01"]},
            ),
            "slave1": FakeSubentry(
                "slave1", "Slave 0B", {"kind": "slave", "slave": 11}
            ),
            "link1": FakeSubentry(
                "link1",
                "SYMI 01 按键 01 → 0A 线路 02",
                {"kind": "linkage", "relay_entities": ["switch.serial_dev_ttys0_0a_line_02"]},
            ),
            "panel": FakeSubentry("panel", "SYMI /dev/ttyS1", {"kind": "panel"}),
            "slave0": FakeSubentry(
                "slave0", "客厅中控", {"kind": "slave", "slave": 10}
            ),
        }
    )


def test_the_cards_carry_the_place_they_have() -> None:
    """The slaves come first, then the panel buses, then the links."""
    titles = card_titles(_entry())

    assert titles == {
        "slave0": "01 客厅中控",
        "slave1": "02 Slave 0B",
        "panel": "03 SYMI /dev/ttyS1",
        "link1": "04 SYMI 01 按键 01 → 0A 线路 02",
        "link2": "05 SYMI 02 按键 01 → 0B 线路 01",
    }


def test_the_links_are_ordered_by_the_relay_they_drive() -> None:
    """A link that drives the first coil of the first slave comes first."""
    entry = _entry()
    entry.subentries["link1"].data["relay_entities"] = [
        "switch.serial_dev_ttys0_0a_line_01"
    ]
    entry.subentries["link2"].data["relay_entities"] = [
        "switch.serial_dev_ttys0_0b_line_01"
    ]

    titles = card_titles(entry)

    assert titles["link1"].startswith("04 ")
    assert titles["link2"].startswith("05 ")


def test_a_number_that_is_already_there_is_not_added_twice() -> None:
    """The number of a card is written once."""
    entry = _entry()
    entry.subentries["slave0"].title = "01 客厅中控"

    titles = card_titles(entry)

    assert titles["slave0"] == "01 客厅中控"
