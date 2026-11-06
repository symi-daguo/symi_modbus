"""Keeps the panel buttons and the Modbus coils they control in sync."""
from __future__ import annotations

import asyncio
import logging
import time

from homeassistant.const import SERVICE_TURN_OFF, SERVICE_TURN_ON, STATE_OFF, STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import MODE_SCENE, MODE_SWITCH

_LOGGER = logging.getLogger(__name__)

# An entity of a fresh entry reports unavailable until the first poll of the
# bus answered. The write is tried again a few times instead of being lost.
APPLY_RETRY_DELAYS = (0.5, 1.0, 2.0)

# Several state changes of one press all want to write the same indicator
# light. Only the first one in the window reaches the bus.
LED_DEDUPE_WINDOW = 0.3

_UNAVAILABLE_STATES = ("unavailable", "unknown")


class LinkageGroup:
    """Mirrors the state between panel buttons and Modbus coils.

    A group holds any number of panel buttons and any number of coils. A
    change on one side is written to the other side, so one button can drive
    several coils and one coil can light up on several buttons.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        panels: list[str],
        relays: list[str],
        title: str = "",
        mode: str = MODE_SWITCH,
    ) -> None:
        """Initialize the group."""
        self._hass = hass
        self._panels = [entity_id for entity_id in panels if entity_id]
        self._relays = [entity_id for entity_id in relays if entity_id]
        self._title = title
        self._mode = mode
        self._unsub = None
        # The last write of an indicator light: entity, state, time.
        self._last_write: dict[tuple[str, str], float] = {}

    @property
    def entity_ids(self) -> list[str]:
        """Return every entity that belongs to this group."""
        return [*self._panels, *self._relays]

    async def async_start(self) -> None:
        """Start watching the entities of this group."""
        entity_ids = [
            entity_id
            for entity_id in self.entity_ids
            if self._hass.states.get(entity_id) is not None
        ]
        if not entity_ids:
            _LOGGER.warning("Linkage %s has no known entities", self._title)
            return
        self._unsub = async_track_state_change_event(
            self._hass, entity_ids, self._async_state_changed
        )
        await self._async_sync_start()

    async def _async_sync_start(self) -> None:
        """Nothing is written to a panel when the link starts.

        The light of a panel is lit by the panel itself when a key is used.
        A frame of the host would reach every panel of the bus, because the
        keys of the panels share the same device address. The state of a
        button follows the frame the panel sends, so there is nothing to push.
        """
        return

    async def async_stop(self) -> None:
        """Stop watching the entities of this group."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Write a change of one side to the other side."""
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state not in (STATE_ON, STATE_OFF):
            return

        source = event.data["entity_id"]
        if source in self._panels:
            # A press of a button flips the light of the panel itself, the
            # panel answers the press on its own. Writing the light again
            # would put a frame on the bus that every panel of the bus takes
            # for its own key, so only the relays of the link are written.
            relay_state = new_state.state
            targets = [(relay, relay_state) for relay in self._relays]
        elif source in self._relays:
            if self._mode == MODE_SCENE:
                # A scene is a single action without a lasting state, so the
                # indicator of the panel is not tied to it. Following the state
                # would switch the light off again right away.
                return
            targets = [(panel, new_state.state) for panel in self._panels]
        else:
            return

        for target, desired in targets:
            current = self._hass.states.get(target)
            if current is None:
                continue
            always = (
                # The button itself always gets the frame, so the light of the
                # panel answers the press at once.
                target == source
                # The relay changed, so the light of the panel is written again
                # even when the entity of the panel shows the wanted state
                # already. The light on the panel is the one that counts, the
                # entity can be out of step with it.
                or source in self._relays
                # A scene is triggered every time, so the frame goes out even
                # when the relay already shows the wanted state.
                or self._mode == MODE_SCENE
            )
            if not always and current.state == desired:
                # The target already shows the wanted state, writing it again
                # would only put another frame on the bus.
                continue
            self._hass.async_create_task(self._async_apply(target, desired))

    async def _async_apply(
        self, entity_id: str, state: str, attempt: int = 0
    ) -> None:
        """Turn an entity on or off, waiting for it to become available."""
        current = self._hass.states.get(entity_id)
        if current is None or current.state in _UNAVAILABLE_STATES:
            if attempt >= len(APPLY_RETRY_DELAYS):
                _LOGGER.debug(
                    "Linkage %s gave up on %s -> %s (still not available)",
                    self._title,
                    entity_id,
                    state,
                )
                return
            _LOGGER.debug(
                "Linkage %s defers %s -> %s (entity not available, retry %s)",
                self._title,
                entity_id,
                state,
                attempt + 1,
            )
            await asyncio.sleep(APPLY_RETRY_DELAYS[attempt])
            await self._async_apply(entity_id, state, attempt + 1)
            return

        if entity_id in self._panels:
            key = (entity_id, state)
            now = time.monotonic()
            last = self._last_write.get(key)
            if last is not None and now - last < LED_DEDUPE_WINDOW:
                _LOGGER.debug(
                    "Linkage %s skips duplicate LED write %s -> %s",
                    self._title,
                    entity_id,
                    state,
                )
                return
            self._last_write[key] = now

        _LOGGER.debug(
            "Linkage %s sets %s to %s", self._title, entity_id, state
        )
        try:
            await self._hass.services.async_call(
                "switch",
                SERVICE_TURN_ON if state == STATE_ON else SERVICE_TURN_OFF,
                {"entity_id": entity_id},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "Linkage %s could not set %s", self._title, entity_id
            )
