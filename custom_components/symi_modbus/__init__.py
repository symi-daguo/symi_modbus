"""The Symi Modbus integration."""
from __future__ import annotations

import logging
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    ATTR_ADDRESS,
    ATTR_HUB,
    ATTR_SLAVE,
    ATTR_STATE,
    ATTR_VALUE,
    DOMAIN,
    SERVICE_WRITE_COIL,
    SERVICE_WRITE_REGISTER,
)
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The hub of an entry is kept in its runtime data.
SymiModbusConfigEntry: TypeAlias = ConfigEntry

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change (e.g. scan interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Symi Modbus component."""
    _LOGGER.debug("Symi Modbus component setup, domain=%s", DOMAIN)
    register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SymiModbusConfigEntry) -> bool:
    """Set up Symi Modbus from a config entry."""
    _LOGGER.debug("Symi Modbus setting up entry %s", entry.entry_id)
    hub = ModbusHub(hass, entry)

    if not await hub.async_setup():
        return False

    entry.runtime_data = hub
    _LOGGER.debug("Symi Modbus forwarding platforms for %s", entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Symi Modbus platforms ready for %s", entry.entry_id)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SymiModbusConfigEntry) -> bool:
    """Unload a config entry."""
    hub: ModbusHub | None = entry.runtime_data

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and hub is not None:
        await hub.async_stop()

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old entry (one slave per entry) to the multi-slave layout."""
    if entry.version >= 2:
        return True

    _LOGGER.debug("Migrating %s from version %s", entry.title, entry.version)

    slaves = entry.data.get("slaves")
    if slaves is None:
        # Version 1 stored a single slave id on the entry itself.
        slave = entry.data.get("slave", 0x0A)
        slaves = {str(int(slave)): {"start": 0, "count": 32}}

    new_data = {**entry.data, "slaves": slaves}
    new_data.pop("slave", None)

    hass.config_entries.async_update_entry(entry, data=new_data, version=2)
    return True


def _find_hub(hass: HomeAssistant, hub_name: str | None) -> ModbusHub | None:
    """Find the hub matching an entry title, or the only hub when unset."""
    hubs = [
        entry.runtime_data
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(entry.runtime_data, ModbusHub)
    ]
    if not hubs:
        return None
    if not hub_name:
        return hubs[0] if len(hubs) == 1 else None
    for hub in hubs:
        if hub.name == hub_name:
            return hub
    return None


def register_services(hass: HomeAssistant) -> None:
    """Register Modbus services once per Home Assistant run."""

    if hass.services.has_service(DOMAIN, SERVICE_WRITE_COIL):
        return

    async def async_write_register(service: ServiceCall) -> None:
        """Write Modbus registers (not implemented for this device profile)."""
        _LOGGER.warning(
            "write_register is not supported by this integration; use write_coil instead"
        )

    async def async_write_coil(service: ServiceCall) -> None:
        """Write Modbus coil."""
        unit = int(service.data[ATTR_SLAVE])
        address = int(service.data[ATTR_ADDRESS])
        state = service.data[ATTR_STATE]
        hub_name = service.data.get(ATTR_HUB)

        hub = _find_hub(hass, hub_name)
        if hub is None:
            _LOGGER.warning(
                "No Modbus hub found for '%s'; pass the entry title as hub", hub_name
            )
            return

        await hub.write_coil(unit, address, bool(state))

    service_write_register_schema = vol.Schema(
        {
            vol.Required(ATTR_ADDRESS): vol.Coerce(int),
            vol.Required(ATTR_VALUE): vol.Coerce(int),
            vol.Required(ATTR_SLAVE): vol.Coerce(int),
            vol.Optional(ATTR_HUB): cv.string,
        }
    )

    service_write_coil_schema = vol.Schema(
        {
            vol.Required(ATTR_ADDRESS): vol.Coerce(int),
            vol.Required(ATTR_STATE): cv.boolean,
            vol.Required(ATTR_SLAVE): vol.Coerce(int),
            vol.Optional(ATTR_HUB): cv.string,
        }
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_REGISTER,
        async_write_register,
        schema=service_write_register_schema,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_WRITE_COIL,
        async_write_coil,
        schema=service_write_coil_schema,
    )
