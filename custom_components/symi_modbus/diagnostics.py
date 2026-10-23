"""Diagnostics support for Symi Modbus.

The diagnostics hold the raw data of the bus. A customer who wants to see
what goes over the 485 line downloads them from the page of the integration,
the log stays quiet.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, SUBENTRY_PANEL

# Nothing in the configuration of this integration is a secret, the fields are
# listed anyway so a new one is not published by accident.
TO_REDACT = {"password", "username", "token", "api_key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of a config entry."""
    runtime = getattr(entry, "runtime_data", None)

    diagnostics: dict[str, Any] = {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "subentries": [
            {
                "type": subentry.subentry_type,
                "title": subentry.title,
                "data": async_redact_data(dict(subentry.data), TO_REDACT),
            }
            for subentry in entry.subentries.values()
        ],
        "codes": _learned_codes(hass, entry),
    }

    if runtime is None:
        # The entry is not set up, there is nothing to show.
        return diagnostics

    diagnostics["master"] = {
        "connected": runtime.hub.is_connected,
        "lines": runtime.hub.recent_traffic(),
    }
    diagnostics["panel_lines"] = runtime.panels.recent_traffic()
    diagnostics["panel_buses"] = [
        {
            "port": subentry.data.get("port"),
            "brand": subentry.data.get("brand"),
            "panels": subentry.data.get("panel_ids"),
            "connected": runtime.panels.is_connected(subentry.subentry_id),
        }
        for subentry in entry.get_subentries_of_type(SUBENTRY_PANEL)
    ]

    return diagnostics


def _learned_codes(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Return the codes the panels use, as they are kept with the entities."""
    registry = er.async_get(hass)
    codes: dict[str, Any] = {}
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        own = (item.options or {}).get(DOMAIN)
        if own:
            codes[item.entity_id] = own
    return codes
