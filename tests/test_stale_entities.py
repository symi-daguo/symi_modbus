"""The entities that are not configured any more have to go."""
from __future__ import annotations

from dataclasses import dataclass

from custom_components.symi_modbus.switch import _stale_entries

ENTRY = "01M5H3KV2X723TBMXYEM9KWNVE"


@dataclass
class FakeEntry:
    """A registry entry with the fields the cleanup looks at."""

    entity_id: str
    unique_id: str
    device_id: str | None = None


def test_an_entry_that_is_configured_is_kept() -> None:
    """The entities that are configured right now stay where they are."""
    entries = [FakeEntry("switch.a", f"{ENTRY}_10_5")]
    stale = _stale_entries(entries, f"{ENTRY}_", {f"{ENTRY}_10_5"})
    assert stale == []


def test_a_coil_that_was_taken_off_is_removed() -> None:
    """A coil that is not configured any more is not kept."""
    entries = [
        FakeEntry("switch.line_05", f"{ENTRY}_10_5"),
        FakeEntry("switch.line_06", f"{ENTRY}_10_6"),
    ]
    stale = _stale_entries(entries, f"{ENTRY}_", {f"{ENTRY}_10_5"})
    assert [entry.entity_id for entry in stale] == ["switch.line_06"]


def test_a_panel_that_was_taken_off_the_bus_is_removed() -> None:
    """A panel that is not on the bus any more is not kept."""
    entries = [
        FakeEntry("switch.button_01", f"{ENTRY}_panel_sub1_1_1"),
        FakeEntry("switch.button_02", f"{ENTRY}_panel_sub1_2_1"),
    ]
    stale = _stale_entries(entries, f"{ENTRY}_", {f"{ENTRY}_panel_sub1_1_1"})
    assert [entry.entity_id for entry in stale] == ["switch.button_02"]


def test_the_entities_of_another_entry_are_never_touched() -> None:
    """Only the entities of this entry are looked at."""
    entries = [FakeEntry("switch.other", "01OTHERENTRY_10_5")]
    stale = _stale_entries(entries, f"{ENTRY}_", set())
    assert stale == []
