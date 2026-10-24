"""The Symi Modbus integration."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypeAlias

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr
import voluptuous as vol

from .card_order import _async_order_cards
from .const import (
    ATTR_ADDRESS,
    ATTR_HUB,
    ATTR_SLAVE,
    ATTR_STATE,
    ATTR_VALUE,
    CONF_BRAND,
    CONF_BAUDRATE,
    CONF_BYTESIZE,
    CONF_COIL_COUNT,
    CONF_LED_FRAME_TYPE,
    CONF_LED_OFF_CODE,
    CONF_LED_ON_CODE,
    CONF_MODE,
    CONF_PANEL_ENTITIES,
    CONF_PANEL_IDS,
    CONF_PARITY,
    CONF_PORT,
    CONF_RELAY_ENTITIES,
    CONF_SLAVE,
    CONF_STOPBITS,
    DOMAIN,
    DEFAULT_LED_FRAME_TYPE,
    MODE_SWITCH,
    SERVICE_WRITE_COIL,
    SERVICE_WRITE_REGISTER,
    SUBENTRY_LINKAGE,
    SUBENTRY_PANEL,
    SUBENTRY_SLAVE,
)
from .linkage import LinkageGroup
from .modbus import ModbusHub
from .panels.manager import PanelManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SWITCH]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The first coil of a slave.
CONF_COIL_START = "start"


@dataclass
class SymiModbusRuntimeData:
    """The parts of an entry that are alive while the entry is loaded."""

    hub: ModbusHub
    """The Modbus master with its connection and its polling."""

    panels: PanelManager
    """The panel buses with the wall panels behind them."""

    linkages: list[LinkageGroup] = field(default_factory=list)
    """The links between the panel buttons and the Modbus coils."""


# The runtime data of an entry is kept in its runtime data.
SymiModbusConfigEntry: TypeAlias = ConfigEntry

# The reload of an entry is delayed a moment, so a few changes that follow
# each other result in one reload.
RELOAD_DELAY = 0.5

# The pending reload of every entry.
_RELOAD_TASKS: dict[str, asyncio.Task] = {}


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when something changes.

    Several subentries can be added in one go, so the reloads are merged into
    one. Otherwise the entry is set up again for every single subentry, and a
    device can end up in the wrong subentry while the entry is half set up.
    """
    entry_id = entry.entry_id
    pending = _RELOAD_TASKS.pop(entry_id, None)
    if pending is not None:
        pending.cancel()
    _RELOAD_TASKS[entry_id] = hass.async_create_task(
        _async_reload_later(hass, entry_id)
    )


async def _async_reload_later(hass: HomeAssistant, entry_id: str) -> None:
    """Reload the entry once the changes have settled."""
    await asyncio.sleep(RELOAD_DELAY)
    if _RELOAD_TASKS.get(entry_id) is asyncio.current_task():
        _RELOAD_TASKS.pop(entry_id, None)
    if hass.config_entries.async_get_entry(entry_id) is None:
        # The entry was removed while the reload was waiting.
        return
    await hass.config_entries.async_reload(entry_id)


def _device_subentry_id(device, entry_id: str) -> str | None:
    """Return the subentry a device belongs to.

    Home Assistant 2026.9 keeps the owner of a device in a single field,
    before that a device carried a mapping of entries and subentries.
    """
    subentry_id = getattr(device, "config_subentry_id", None)
    if subentry_id is not None:
        return subentry_id
    subentries = device.config_entries_subentries.get(entry_id)
    if not subentries:
        return None
    return next(iter(subentries))


def _align_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Put the device of a slave into the subentry of that slave.

    A device belongs to exactly one subentry. The devices of an entry that was
    created before the subentries were introduced still point at the entry
    itself, so they show up twice in the device list: once under the entry and
    once under the subentry of their slave.
    """
    registry = dr.async_get(hass)
    for subentry in entry.get_subentries_of_type(SUBENTRY_SLAVE):
        slave = int(subentry.data[CONF_SLAVE])
        device = registry.async_get_device(
            identifiers={(DOMAIN, f"{entry.entry_id}_{slave}")}
        )
        if device is None:
            continue
        if _device_subentry_id(device, entry.entry_id) == subentry.subentry_id:
            continue

        _LOGGER.debug("Moving the device of slave %s into its subentry", slave)
        try:
            registry.async_update_device(
                device.id, new_config_subentry_id=subentry.subentry_id
            )
        except TypeError:
            # Home Assistant before 2026.9 moves a device by adding the
            # subentry and removing the entry it was attached to.
            registry.async_update_device(
                device.id,
                add_config_entry_id=entry.entry_id,
                add_config_subentry_id=subentry.subentry_id,
            )
            registry.async_update_device(
                device.id,
                remove_config_entry_id=entry.entry_id,
                remove_config_subentry_id=None,
            )


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Symi Modbus component."""
    _LOGGER.debug("Symi Modbus component setup, domain=%s", DOMAIN)
    register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SymiModbusConfigEntry) -> bool:
    """Set up Symi Modbus from a config entry."""
    _LOGGER.debug("Symi Modbus setting up entry %s", entry.entry_id)
    _align_devices(hass, entry)

    hub = ModbusHub(hass, entry)

    if not await hub.async_setup():
        return False

    panels = PanelManager(hass, entry.entry_id)
    for subentry in entry.get_subentries_of_type(SUBENTRY_PANEL):
        await panels.async_add_bus(
            subentry.subentry_id,
            port=str(subentry.data[CONF_PORT]),
            brand=str(subentry.data[CONF_BRAND]),
            panel_ids=[int(panel) for panel in subentry.data.get(CONF_PANEL_IDS, [])],
            led_frame_type=str(
                subentry.data.get(CONF_LED_FRAME_TYPE, DEFAULT_LED_FRAME_TYPE)
            ),
            led_codes=(
                subentry.data.get(CONF_LED_ON_CODE),
                subentry.data.get(CONF_LED_OFF_CODE),
            ),
            baudrate=int(subentry.data.get(CONF_BAUDRATE, 9600)),
            bytesize=int(subentry.data.get(CONF_BYTESIZE, 8)),
            parity=str(subentry.data.get(CONF_PARITY, "N")),
            stopbits=int(subentry.data.get(CONF_STOPBITS, 1)),
        )

    entry.runtime_data = SymiModbusRuntimeData(hub=hub, panels=panels)
    _LOGGER.debug("Symi Modbus forwarding platforms for %s", entry.entry_id)

    _async_order_cards(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Symi Modbus platforms ready for %s", entry.entry_id)

    # The links start after the entities exist, so the state of the entities
    # is known when the links begin to watch them.
    for subentry in entry.get_subentries_of_type(SUBENTRY_LINKAGE):
        group = LinkageGroup(
            hass,
            [str(entity) for entity in subentry.data.get(CONF_PANEL_ENTITIES, [])],
            [str(entity) for entity in subentry.data.get(CONF_RELAY_ENTITIES, [])],
            title=subentry.title,
            mode=str(subentry.data.get(CONF_MODE, MODE_SWITCH)),
        )
        await group.async_start()
        entry.runtime_data.linkages.append(group)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: SymiModbusConfigEntry) -> bool:
    """Unload a config entry."""
    runtime: SymiModbusRuntimeData | None = entry.runtime_data

    pending = _RELOAD_TASKS.pop(entry.entry_id, None)
    if pending is not None:
        pending.cancel()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok and runtime is not None:
        for group in runtime.linkages:
            await group.async_stop()
        await runtime.panels.async_stop()
        await runtime.hub.async_stop()

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old entry to the layout with subentries.

    Version 1 held a single slave on the entry, version 2 held a list of
    slaves on the entry. Version 3 keeps every slave as a subentry, so the
    user can add, change and remove them on their own.
    """
    if entry.version >= 3:
        return True

    _LOGGER.debug("Migrating %s from version %s", entry.title, entry.version)

    slaves = entry.data.get("slaves")
    if entry.version < 2:
        # Version 1 stored a single slave id on the entry itself.
        slave = entry.data.get("slave", 0x0A)
        slaves = {str(int(slave)): {"start": 0, "count": 32}}

    new_data = {**entry.data}
    new_data.pop("slaves", None)
    new_data.pop("slave", None)
    hass.config_entries.async_update_entry(entry, data=new_data, version=3)

    for key, options in (slaves or {}).items():
        slave = int(key)
        data = {
            CONF_SLAVE: slave,
            CONF_COIL_START: int(options.get("start", 0)),
            CONF_COIL_COUNT: int(options.get("count", 32)),
        }
        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(data),
                subentry_type=SUBENTRY_SLAVE,
                title=f"Slave {slave:02X}",
                unique_id=str(slave),
            ),
        )

    return True


def _find_hub(hass: HomeAssistant, hub_name: str | None) -> ModbusHub | None:
    """Find the hub matching an entry title, or the only hub when unset."""
    hubs = [
        entry.runtime_data.hub
        for entry in hass.config_entries.async_entries(DOMAIN)
        if isinstance(entry.runtime_data, SymiModbusRuntimeData)
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
