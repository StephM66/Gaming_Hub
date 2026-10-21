"""Gaming Hub: game consoles in Home Assistant, one integration for all of them."""

from __future__ import annotations

from functools import partial
import logging

from homeassistant.config_entries import SOURCE_IMPORT
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers.dispatcher import async_dispatcher_send

from . import consumption
from .const import CONF_KIND, DOMAIN, REMOVED_KINDS, SIGNAL_CONSOLES_UPDATED, SUMMARY
from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .drivers import create_driver
from .household import GamingHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.MEDIA_PLAYER,
    Platform.NOTIFY,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]

# The "Gaming Hub" entry: statistics, household and profiles (parental settings).
SUMMARY_PLATFORMS = [
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.TIME,
]


def _platforms(coordinator: GamingHubCoordinator) -> list[Platform]:
    # The camera platform (and its image libraries) only loads for a console with a screen feed.
    return [*PLATFORMS, Platform.CAMERA] if coordinator.driver.has_screen else PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: GamingHubConfigEntry) -> bool:
    if entry.data.get(CONF_KIND) == SUMMARY:
        hub = GamingHub(hass, entry)
        await hub.async_start()
        entry.runtime_data = hub
        await hass.config_entries.async_forward_entry_setups(entry, SUMMARY_PLATFORMS)
        # A profile added, changed or removed: rebuild the profiles.
        entry.async_on_unload(entry.add_update_listener(_async_reload))
        return True
    if entry.data.get(CONF_KIND) in REMOVED_KINDS:
        # Everything goes through Gaming Hub: following another integration's entity is gone.
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="removed_kind")
    coordinator = GamingHubCoordinator(hass, entry, create_driver(hass, entry))
    await coordinator.async_start()
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await coordinator.driver.async_stop()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, _platforms(coordinator))
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    # Each refresh feeds the cross-console statistics.
    entry.async_on_unload(
        coordinator.async_add_listener(
            partial(async_dispatcher_send, hass, SIGNAL_CONSOLES_UPDATED)
        )
    )
    _ensure_hub(hass)
    async_dispatcher_send(hass, SIGNAL_CONSOLES_UPDATED)  # the new console joins the totals
    try:
        await consumption.async_apply(hass, entry)
    except Exception:
        # Taking over another meter is a convenience: it never stops the console.
        _LOGGER.exception("Could not take over the energy meter of %s", entry.title)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GamingHubConfigEntry) -> bool:
    if entry.data.get(CONF_KIND) == SUMMARY:
        if unloaded := await hass.config_entries.async_unload_platforms(entry, SUMMARY_PLATFORMS):
            await entry.runtime_data.async_stop()
        return unloaded
    platforms = _platforms(entry.runtime_data)
    if unloaded := await hass.config_entries.async_unload_platforms(entry, platforms):
        await entry.runtime_data.async_stop()
        async_dispatcher_send(hass, SIGNAL_CONSOLES_UPDATED)  # the summary drops this console
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
    await consumption.async_restore(hass, entry)


async def _async_options_updated(hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
    # Discovery also updates the entry (discovery keys): reload only for new options.
    if entry.options != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)


async def _async_reload(hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _ensure_hub(hass: HomeAssistant) -> None:
    """Create the "Gaming Hub" entry (statistics, household, profiles) with the first console."""
    if any(
        entry.data.get(CONF_KIND) == SUMMARY for entry in hass.config_entries.async_entries(DOMAIN)
    ):
        return
    if any(
        flow["context"].get("source") == SOURCE_IMPORT
        for flow in hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    ):
        return
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_IMPORT}, data={CONF_KIND: SUMMARY}
        ),
        f"{DOMAIN} create the Gaming Hub entry",
    )
