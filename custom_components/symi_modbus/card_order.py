"""The cards of the configuration carry the place they have in it.

The cards of an integration are shown in the order of their titles, so the
title carries the place: the slaves of the line first, then the panel buses,
then the links of the buttons, in the order of the relay they drive.
"""
from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigSubentry

from .const import CONF_SLAVE, SUBENTRY_LINKAGE, SUBENTRY_PANEL, SUBENTRY_SLAVE

# The number in front of the name of a card.
CARD_NUMBER = re.compile(r"^\d{2}\s+")

# The slave and the line of a relay entity, as the integration names them.
RELAY_NAME = re.compile(r"_([0-9a-f]{2})_line_(\d+)$")


def _slave_number(subentry: ConfigSubentry) -> int:
    """Return the address of a slave."""
    return int(subentry.data.get(CONF_SLAVE, 0))


def _relay_number(subentry: ConfigSubentry) -> tuple[int, int]:
    """Return the slave and the line of the relay a link drives."""
    relays = subentry.data.get("relay_entities") or []
    for relay in relays:
        found = RELAY_NAME.search(str(relay))
        if found:
            return int(found.group(1), 16), int(found.group(2))
    return 999, 999


def _sorted_subentries(entry: ConfigEntry) -> list[ConfigSubentry]:
    """Return the subentries in the order the cards are shown in."""
    slaves = sorted(
        entry.get_subentries_of_type(SUBENTRY_SLAVE), key=_slave_number
    )
    panels = list(entry.get_subentries_of_type(SUBENTRY_PANEL))
    links = sorted(entry.get_subentries_of_type(SUBENTRY_LINKAGE), key=_relay_number)
    return [*slaves, *panels, *links]


def card_titles(entry: ConfigEntry) -> dict[str, str]:
    """Return the title every card of the configuration should have."""
    titles: dict[str, str] = {}
    for number, subentry in enumerate(_sorted_subentries(entry), start=1):
        name = CARD_NUMBER.sub("", subentry.title or "")
        titles[subentry.subentry_id] = f"{number:02d} {name}"
    return titles


def _async_order_cards(hass: Any, entry: ConfigEntry) -> None:
    """Give every card of the configuration the title of its place."""
    for subentry_id, title in card_titles(entry).items():
        subentry = entry.subentries.get(subentry_id)
        if subentry is None or subentry.title == title:
            continue
        hass.config_entries.async_update_subentry(entry, subentry, title=title)
