"""The Symi Modbus integration."""
from __future__ import annotations

import logging
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ADDRESS,
    ATTR_HUB,
    ATTR_SLAVE,
    ATTR_STATE,
    ATTR_VALUE,
    DEFAULT_HUB,
    DOMAIN,
    SERVICE_WRITE_COIL,
    SERVICE_WRITE_REGISTER,
)
from .modbus import ModbusHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH]


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when options change (e.g. scan interval)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Symi Modbus component."""
    hass.data.setdefault(DOMAIN, {})
    register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Symi Modbus from a config entry."""
    hub = ModbusHub(hass, entry)

    if not await hub.async_setup():
        return False

    hass.data[DOMAIN][entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub = hass.data[DOMAIN].get(entry.entry_id)

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and hub is not None:
        await hub.async_stop()
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


def register_services(hass: HomeAssistant) -> None:
    """Register Modbus services once per Home Assistant run."""

    if hass.services.has_service(DOMAIN, SERVICE_WRITE_COIL):
        return

    async def async_write_register(service: ServiceCall) -> None:
        """Write Modbus registers (not implemented for this device profile)."""
        hub_name = service.data.get(ATTR_HUB, DEFAULT_HUB)
        for _entry_id, hub in hass.data[DOMAIN].items():
            if isinstance(hub, ModbusHub) and hub.name == hub_name:
                _LOGGER.debug("Write register is not implemented for hub %s", hub_name)
                return
        _LOGGER.warning("Hub %s not found for write_register", hub_name)

    async def async_write_coil(service: ServiceCall) -> None:
        """Write Modbus coil."""
        unit = service.data[ATTR_SLAVE]
        address = service.data[ATTR_ADDRESS]
        state = service.data[ATTR_STATE]
        hub_name = service.data.get(ATTR_HUB, DEFAULT_HUB)

        for _entry_id, hub in hass.data[DOMAIN].items():
            if isinstance(hub, ModbusHub) and hub.name == hub_name:
                await hub.write_coil(unit, address, state)
                return
        _LOGGER.warning("Hub %s not found for write_coil", hub_name)

    service_write_register_schema = vol.Schema(
        {
            vol.Required(ATTR_ADDRESS): cv.positive_int,
            vol.Required(ATTR_VALUE): vol.Any(cv.positive_int, [cv.positive_int]),
            vol.Required(ATTR_SLAVE): cv.positive_int,
            vol.Optional(ATTR_HUB, default=DEFAULT_HUB): cv.string,
        }
    )

    service_write_coil_schema = vol.Schema(
        {
            vol.Required(ATTR_ADDRESS): cv.positive_int,
            vol.Required(ATTR_STATE): vol.Any(cv.boolean, [cv.boolean]),
            vol.Required(ATTR_SLAVE): cv.positive_int,
            vol.Optional(ATTR_HUB, default=DEFAULT_HUB): cv.string,
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
