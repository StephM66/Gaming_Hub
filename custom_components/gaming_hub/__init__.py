"""Gaming Hub: game consoles in Home Assistant, one integration for all of them."""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .drivers import create_driver

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


async def async_setup_entry(hass: HomeAssistant, entry: GamingHubConfigEntry) -> bool:
    coordinator = GamingHubCoordinator(hass, entry, create_driver(hass, entry))
    await coordinator.async_start()
    try:
        await coordinator.async_config_entry_first_refresh()
    except BaseException:
        await coordinator.driver.async_stop()
        raise
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GamingHubConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()
    return unloaded


async def _async_options_updated(hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
    # Discovery also updates the entry (discovery keys): reload only for new options.
    if entry.options != entry.runtime_data.options:
        await hass.config_entries.async_reload(entry.entry_id)
