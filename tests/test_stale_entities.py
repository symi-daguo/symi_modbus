"""The entities that are not configured any more have to go."""
from __future__ import annotations

from dataclasses import dataclass

from custom_components.symi_modbus.switch import _stale_entries, _stale_names

ENTRY = "01M5H3KV2X723TBMXYEM9KWNVE"


@dataclass
class FakeEntry:
    """A registry entry with the fields the cleanup looks at."""

    entity_id: str
    unique_id: str
    device_id: str | None = None
    name: str | None = None
    original_name: str | None = None


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


def test_a_name_of_an_earlier_version_is_reset() -> None:
    """An entity that carries the name of an earlier version is reset.

    The name is then the name of the device and the entity, so the entities
    stand in the order a person expects.
    """
    entries = [
        FakeEntry(
            "switch.serial_dev_ttys0_0b_line_01",
            f"{ENTRY}_11_1",
            name="0B 线路 01",
            original_name="0B 线路 01",
        )
    ]
    assert _stale_names(entries) == ["switch.serial_dev_ttys0_0b_line_01"]


def test_a_name_that_the_user_gave_stays() -> None:
    """A name that the user gave is not the name of the integration."""
    entries = [
        FakeEntry(
            "switch.button_01",
            f"{ENTRY}_panel_sub1_1_1",
            name="客厅的灯",
            original_name="按键 01",
        )
    ]
    assert _stale_names(entries) == []


def test_an_entity_without_a_name_of_its_own_is_left_alone() -> None:
    """An entity that has no name of its own keeps the name of the device."""
    entries = [
        FakeEntry(
            "switch.serial_dev_ttys0_0a_line_01",
            f"{ENTRY}_10_1",
            name=None,
            original_name="0A 线路 01",
        )
    ]
    assert _stale_names(entries) == []
