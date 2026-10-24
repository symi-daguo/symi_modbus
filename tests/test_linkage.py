"""Tests for the link between the panel buttons and the Modbus coils."""
from __future__ import annotations

import asyncio

import pytest

from custom_components.symi_modbus import linkage as linkage_module
from custom_components.symi_modbus.const import MODE_SCENE
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

    # The relay is driven and the button gets the frame for its own light.
    assert {call[2]["entity_id"] for call in hass.services.calls} == {
        "switch.relay",
        "switch.panel",
    }


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
        "switch.panel",
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

    # The relay already shows the wanted state, only the light of the button
    # is written.
    assert {call[2]["entity_id"] for call in hass.services.calls} == {"switch.panel"}


@pytest.mark.asyncio
async def test_an_unknown_target_is_skipped() -> None:
    """A target that no longer exists is skipped."""
    hass = FakeHass({"switch.panel": FakeState("on")})
    group = LinkageGroup(hass, ["switch.panel"], ["switch.gone"], "test")
    await group.async_start()

    await _trigger(hass, group, "switch.panel", "on")

    # The relay already shows the wanted state, only the light of the button
    # is written.
    assert {call[2]["entity_id"] for call in hass.services.calls} == {"switch.panel"}


@pytest.mark.asyncio
async def test_a_scene_link_does_not_follow_the_relay() -> None:
    """A scene has no lasting state, so the light of the panel stays on.

    A relay that only triggers a scene falls back to off right away. Following
    that would switch the light of the panel off again at once.
    """
    panel_entity = "switch.symi_01_button_01"
    relay_entity = "switch.serial_dev_ttys0_0a_line_01"
    hass = FakeHass(
        {panel_entity: FakeState("on"), relay_entity: FakeState("off")}
    )

    link = LinkageGroup(
        hass, [panel_entity], [relay_entity], "test", mode=MODE_SCENE
    )
    await link.async_start()

    # The relay falls back to off, the light of the panel keeps its state.
    hass.states[relay_entity] = "off"
    await _trigger(hass, link, relay_entity, "off")
    assert hass.services.calls == []


@pytest.mark.asyncio
async def test_a_scene_link_still_drives_the_relay() -> None:
    """A press of the button still triggers the scene of the relay."""
    panel_entity = "switch.symi_01_button_01"
    relay_entity = "switch.serial_dev_ttys0_0a_line_01"
    hass = FakeHass(
        {panel_entity: FakeState("off"), relay_entity: FakeState("off")}
    )

    link = LinkageGroup(
        hass, [panel_entity], [relay_entity], "test", mode=MODE_SCENE
    )
    await link.async_start()

    hass.states[panel_entity] = "on"
    await _trigger(hass, link, panel_entity, "on")
    assert ("switch", "turn_on", {"entity_id": relay_entity}) in hass.services.calls
    # The light of the button answers the press at once.
    assert ("switch", "turn_on", {"entity_id": panel_entity}) in hass.services.calls


@pytest.mark.asyncio
async def test_the_light_of_a_panel_is_written_again_when_the_relay_changes() -> None:
    """The light on the panel is written again when the relay changes.

    The entity of the panel can be out of step with the light on the panel, so
    the frame goes out even when the entity already shows the wanted state.
    """
    hass = FakeHass(
        {"switch.panel": FakeState("on"), "switch.relay": FakeState("off")}
    )
    group = LinkageGroup(hass, ["switch.panel"], ["switch.relay"], "test")
    await group.async_start()

    hass.states["switch.relay"] = "on"
    await _trigger(hass, group, "switch.relay", "on")

    assert hass.services.calls == [
        ("switch", "turn_on", {"entity_id": "switch.panel"})
    ]


@pytest.mark.asyncio
async def test_a_scene_takes_the_state_the_press_flipped() -> None:
    """A scene is triggered by the press, the relay takes the new state.

    A key of a panel that is a trigger flips the light of the button on every
    press, so the relay of the scene follows that state. The light of the
    button is not switched off again when the relay falls back.
    """
    panel_entity = "switch.symi_01_button_01"
    relay_entity = "switch.serial_dev_ttys0_0a_line_01"
    hass = FakeHass(
        {panel_entity: FakeState("off"), relay_entity: FakeState("on")}
    )

    link = LinkageGroup(
        hass, [panel_entity], [relay_entity], "test", mode=MODE_SCENE
    )
    await link.async_start()

    # The press flipped the light of the button on, the relay follows.
    await _trigger(hass, link, panel_entity, "on")
    assert ("switch", "turn_on", {"entity_id": relay_entity}) in hass.services.calls
    # The light of the button still follows the button itself.
    assert ("switch", "turn_on", {"entity_id": panel_entity}) in hass.services.calls


@pytest.mark.asyncio
async def test_the_light_of_a_scene_is_not_switched_off_by_the_relay() -> None:
    """The relay of a scene does not drive the light of the button."""
    panel_entity = "switch.symi_01_button_01"
    relay_entity = "switch.serial_dev_ttys0_0a_line_01"
    hass = FakeHass(
        {panel_entity: FakeState("on"), relay_entity: FakeState("off")}
    )

    link = LinkageGroup(
        hass, [panel_entity], [relay_entity], "test", mode=MODE_SCENE
    )
    await link.async_start()

    await _trigger(hass, link, relay_entity, "off")
    assert hass.services.calls == []
