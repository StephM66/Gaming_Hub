"""Take over the energy meter a smart plug already had, so nothing is counted twice.

With a plug linked, the console's Energy sensor integrates the plug's power. The plug (or a
helper built on it) often has its own energy meter, sometimes on the Energy dashboard. When
the user names that meter, the console replaces it: its long-term statistics move to the
console's Energy sensor (the dashboard history stays), the Energy dashboard points to the
console, and the plug's sensors are hidden. Unlinking the plug shows them again.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import get_metadata
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.const import ATTR_UNIT_OF_MEASUREMENT, Platform, UnitOfEnergy
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import EnergyConverter

from .const import CONF_ENERGY_SOURCE, CONF_HIDE_SOURCES, CONF_POWER_ENTITY, DOMAIN

if TYPE_CHECKING:
    from .coordinator import GamingHubConfigEntry

_LOGGER = logging.getLogger(__name__)
RECORDER_TIMEOUT = 60
HIDDEN_BY_HUB = er.RegistryEntryHider.INTEGRATION


def plug_energy_sensor(hass: HomeAssistant, power_entity: str) -> str | None:
    """Energy meter on the same device as the plug's power sensor (the suggested takeover)."""
    registry = er.async_get(hass)
    if (power := registry.async_get(power_entity)) is None or power.device_id is None:
        return None
    for entry in er.async_entries_for_device(registry, power.device_id):
        device_class = entry.device_class or entry.original_device_class
        if entry.domain == Platform.SENSOR and device_class == SensorDeviceClass.ENERGY:
            return entry.entity_id
    return None


async def async_apply(hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
    """Hide or show the plug's sensors, take over the named energy meter once."""
    coordinator = entry.runtime_data
    power = entry.options.get(CONF_POWER_ENTITY)
    source = entry.options.get(CONF_ENERGY_SOURCE) if power else None
    hide = {entity for entity in (power, source) if entity}
    if not entry.options.get(CONF_HIDE_SOURCES, True):
        hide = set()
    coordinator.hidden_entities = _hide(hass, coordinator.hidden_entities, hide)
    if source and source != coordinator.energy_taken_over:
        target = er.async_get(hass).async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{entry.entry_id}_energy"
        )
        if target is None:
            return
        try:
            await _async_move_history(
                hass, source, target, first=coordinator.energy_taken_over is None
            )
        except TimeoutError:
            _LOGGER.warning("History of %s not moved yet, retried at the next start", source)
            return
        await _async_swap_dashboard(hass, source, target)
        coordinator.energy_taken_over = source
        if (total := _kilowatt_hours(hass.states.get(source))) is not None:
            # The console's meter continues from the replaced one.
            coordinator.usage.energy = total
        await coordinator.async_refresh()
    coordinator.save_soon()


async def async_restore(hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
    """The console is deleted: show the plug's sensors again."""
    options = entry.options
    _hide(hass, [options.get(CONF_POWER_ENTITY), options.get(CONF_ENERGY_SOURCE)], set())


def _hide(hass: HomeAssistant, hidden: list[str | None], wanted: set[str]) -> list[str]:
    """Hide ``wanted``, show what the hub hid before and no longer wants; return what it hides."""
    registry = er.async_get(hass)
    for entity_id in set(filter(None, hidden)) - wanted:
        if (entry := registry.async_get(entity_id)) and entry.hidden_by == HIDDEN_BY_HUB:
            registry.async_update_entity(entity_id, hidden_by=None)
    hub_hidden = []
    for entity_id in sorted(wanted):
        if (entry := registry.async_get(entity_id)) is None:
            continue  # without a unique ID an entity cannot be hidden
        if entry.hidden_by is None:
            registry.async_update_entity(entity_id, hidden_by=HIDDEN_BY_HUB)
        elif entry.hidden_by != HIDDEN_BY_HUB or entity_id not in hidden:
            continue  # hidden by the user or another integration: not ours to show again
        hub_hidden.append(entity_id)
    return hub_hidden


async def _async_move_history(
    hass: HomeAssistant, source: str, target: str, *, first: bool
) -> None:
    """Rename the source's long-term statistics to the console's Energy sensor."""
    if "recorder" not in hass.config.components:
        return
    instance = get_instance(hass)
    known = await instance.async_add_executor_job(
        partial(get_metadata, hass, statistic_ids={source, target})
    )
    if source not in known:
        return
    if target in known:
        if not first:
            # The console already holds a meter it took over: never drop that history.
            _LOGGER.warning("%s already has a history, %s keeps its own", target, source)
            return
        # Only the few hours since the plug was linked: the replaced meter's history wins.
        await _async_recorder_task(hass, partial(instance.async_clear_statistics, [target]))
    # A Wh meter keeps its Wh statistics: the recorder converts the console's kWh states.
    await _async_recorder_task(
        hass, partial(instance.async_update_statistics_metadata, source, new_statistic_id=target)
    )


async def _async_recorder_task(hass: HomeAssistant, queue: Callable[..., None]) -> None:
    done = hass.loop.create_future()

    def on_done() -> None:  # recorder thread
        hass.loop.call_soon_threadsafe(lambda: done.done() or done.set_result(None))

    queue(on_done=on_done)
    async with asyncio.timeout(RECORDER_TIMEOUT):
        await done


async def _async_swap_dashboard(hass: HomeAssistant, source: str, target: str) -> None:
    """Point the Energy dashboard's individual devices to the console instead of the source."""
    manager = await async_get_manager(hass)
    if not manager.data:
        return
    devices: list[Any] = []
    seen: set[str] = set()
    changed = False
    for device in manager.data.get("device_consumption", []):
        device = dict(device)
        for key in ("stat_consumption", "included_in_stat"):
            if device.get(key) == source:
                device[key] = target
                changed = True
        if device["stat_consumption"] in seen:
            changed = True  # the console was already listed
            continue
        seen.add(device["stat_consumption"])
        devices.append(device)
    if changed:
        await manager.async_update({"device_consumption": devices})


def _kilowatt_hours(state: State | None) -> float | None:
    if state is None:
        return None
    try:
        return EnergyConverter.convert(
            float(state.state),
            state.attributes.get(ATTR_UNIT_OF_MEASUREMENT),
            UnitOfEnergy.KILO_WATT_HOUR,
        )
    except (ValueError, HomeAssistantError):
        return None
