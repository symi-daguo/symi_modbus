"""Tests for the link between the panel buttons and the Modbus coils."""
from __future__ import annotations

import asyncio

import pytest

from custom_components.symi_modbus import linkage as linkage_module
from custom_components.symi_modbus.linkage import LinkageGroup


class FakeState:
    """The part of a Home Assistant state the link uses."""

    def __init__(self, state: str) -> None:
        """Store the state of the entity."""
        self.state = state


class FakeStates(dict):
    """A stand-in for the state machine."""

    def get(self, entity_id, default=None):  # type: ignore[override]
        """Return the state of an entity."""
        return dict.get(self, entity_id, default)


class FakeServices:
    """Records the service calls the link makes."""

    def __init__(self) -> None:
        """Prepare the record."""
        self.calls: list[tuple[str, str, dict]] = []

    async def async_call(self, domain, service, data, blocking=True):
        """Record the call."""
        self.calls.append((domain, service, data))


class FakeHass:
    """A stand-in for the Home Assistant core object."""

    def __init__(self, states: dict[str, FakeState]) -> None:
        """Prepare the states and the services."""
        self.states = FakeStates(states)
        self.services = FakeServices()
        self.tasks: list = []

    def async_create_task(self, coro, *args, **kwargs):
        """Keep the task so the test can run it."""
        self.tasks.append(coro)
        return coro

    async def async_drain(self) -> None:
        """Run the tasks the link scheduled."""
        while self.tasks:
            await asyncio.gather(*self.tasks)
            self.tasks.clear()


class FakeEvent:
    """A stand-in for a state changed event."""

    def __init__(self, entity_id: str, new_state: str) -> None:
        """Store the data of the event."""
        self.data = {"entity_id": entity_id, "new_state": FakeState(new_state)}


@pytest.fixture(autouse=True)
def _no_tracking(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the link from touching the real event bus."""
    monkeypatch.setattr(
        linkage_module,
        "async_track_state_change_event",
        lambda *args, **kwargs: (lambda: None),
    )


async def _trigger(hass: FakeHass, group: LinkageGroup, entity_id: str, state: str) -> None:
    """Fire a state change and run the work it schedules."""
    group._async_state_changed(FakeEvent(entity_id, state))
    await hass.async_drain()


@pytest.mark.asyncio
async def test_a_panel_button_drives_the_relay() -> None:
    """Turning a panel button on turns the relay on."""
    hass = FakeHass(
        {"switch.panel": FakeState("on"), "switch.relay": FakeState("off")}
    )
    group = LinkageGroup(hass, ["switch.panel"], ["switch.relay"], "test")
    await group.async_start()

    await _trigger(hass, group, "switch.panel", "on")

    assert hass.services.calls == [
        ("switch", "turn_on", {"entity_id": "switch.relay"})
    ]


@pytest.mark.asyncio
async def test_the_relay_lights_up_the_panel_button() -> None:
    """The state of the relay is written back to the panel."""
    hass = FakeHass(
        {"switch.panel": FakeState("off"), "switch.relay": FakeState("on")}
    )
    group = LinkageGroup(hass, ["switch.panel"], ["switch.relay"], "test")
    await group.async_start()

    await _trigger(hass, group, "switch.relay", "on")

    assert hass.services.calls == [
        ("switch", "turn_on", {"entity_id": "switch.panel"})
    ]


@pytest.mark.asyncio
async def test_one_button_drives_several_relays() -> None:
    """A button can be linked to more than one relay."""
    hass = FakeHass(
        {
            "switch.panel": FakeState("on"),
            "switch.relay_a": FakeState("off"),
            "switch.relay_b": FakeState("off"),
        }
    )
    group = LinkageGroup(
        hass, ["switch.panel"], ["switch.relay_a", "switch.relay_b"], "test"
    )
    await group.async_start()

    await _trigger(hass, group, "switch.panel", "on")

    assert {call[2]["entity_id"] for call in hass.services.calls} == {
        "switch.relay_a",
        "switch.relay_b",
    }


@pytest.mark.asyncio
async def test_one_relay_lights_up_several_buttons() -> None:
    """A relay can be linked to more than one button."""
    hass = FakeHass(
        {
            "switch.panel_a": FakeState("off"),
            "switch.panel_b": FakeState("off"),
            "switch.relay": FakeState("on"),
        }
    )
    group = LinkageGroup(
        hass, ["switch.panel_a", "switch.panel_b"], ["switch.relay"], "test"
    )
    await group.async_start()

    await _trigger(hass, group, "switch.relay", "on")

    assert {call[2]["entity_id"] for call in hass.services.calls} == {
        "switch.panel_a",
        "switch.panel_b",
    }


@pytest.mark.asyncio
async def test_a_target_with_the_wanted_state_is_left_alone() -> None:
    """A target that already shows the state is not written again."""
    hass = FakeHass(
        {"switch.panel": FakeState("on"), "switch.relay": FakeState("on")}
    )
    group = LinkageGroup(hass, ["switch.panel"], ["switch.relay"], "test")
    await group.async_start()

    await _trigger(hass, group, "switch.panel", "on")

    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_an_unknown_target_is_skipped() -> None:
    """A target that no longer exists is skipped."""
    hass = FakeHass({"switch.panel": FakeState("on")})
    group = LinkageGroup(hass, ["switch.panel"], ["switch.gone"], "test")
    await group.async_start()

    await _trigger(hass, group, "switch.panel", "on")

    assert hass.services.calls == []
