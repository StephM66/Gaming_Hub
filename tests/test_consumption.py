"""Taking over a plug's energy meter: history moved, Energy dashboard updated, sensors hidden."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.components.energy.data import async_get_manager
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    get_metadata,
    statistics_during_period,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_wait_recording_done,
)

from custom_components.gaming_hub.consumption import plug_energy_sensor

from .test_entities import _setup

HUB_ENERGY = "sensor.ps5_salon_energy"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock: Recorder, enable_custom_integrations: None):
    """The recorder has to start before Home Assistant itself."""


def _plug(hass: HomeAssistant) -> tuple[str, str]:
    """A smart plug with power and energy sensors, the energy meter in Wh."""
    plug_entry = MockConfigEntry(domain="plug")
    plug_entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=plug_entry.entry_id, identifiers={("plug", "1")}
    )
    registry = er.async_get(hass)
    power = registry.async_get_or_create(
        "sensor", "plug", "power", device_id=device.id, original_device_class="power"
    ).entity_id
    energy = registry.async_get_or_create(
        "sensor", "plug", "energy", device_id=device.id, original_device_class="energy"
    ).entity_id
    hass.states.async_set(power, "100", {"unit_of_measurement": "W"})
    hass.states.async_set(energy, "1500", {"unit_of_measurement": "Wh"})
    return power, energy


async def test_take_over_the_plug_meter(
    recorder_mock: Recorder, hass: HomeAssistant, mock_ddp, ps5_entry
) -> None:
    power, energy = _plug(hass)
    assert plug_energy_sensor(hass, power) == energy  # suggested in the options
    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    async_import_statistics(
        hass,
        {
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": None,
            "source": "recorder",
            "statistic_id": energy,
            "unit_class": "energy",
            "unit_of_measurement": "Wh",
        },
        [
            {"start": start + timedelta(hours=h), "state": 1200 + 100 * h, "sum": 100 * h}
            for h in range(3)
        ],
    )
    manager = await async_get_manager(hass)
    await manager.async_update({"device_consumption": [{"stat_consumption": energy}]})
    await async_wait_recording_done(hass)

    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps5_entry, options={"power_entity": power, "energy_source": energy, "hide_sources": True}
    )
    await _setup(hass, ps5_entry)
    await async_wait_recording_done(hass)

    # The meter's history now belongs to the console, which continues from its total.
    known = await recorder_mock.async_add_executor_job(
        lambda: get_metadata(hass, statistic_ids={energy, HUB_ENERGY})
    )
    assert set(known) == {HUB_ENERGY}
    rows = await recorder_mock.async_add_executor_job(
        lambda: statistics_during_period(hass, start, None, {HUB_ENERGY}, "hour", None, {"sum"})
    )
    # Stored in Wh like the plug's meter, read in the console's unit (kWh).
    assert [row["sum"] for row in rows[HUB_ENERGY]] == [0, 0.1, 0.2]
    assert hass.states.get(HUB_ENERGY).state == "1.5"
    # The Energy dashboard counts the console instead of the plug, and the plug is hidden.
    assert manager.data["device_consumption"] == [{"stat_consumption": HUB_ENERGY}]
    registry = er.async_get(hass)
    hidden = er.RegistryEntryHider.INTEGRATION
    assert registry.async_get(power).hidden_by == hidden
    assert registry.async_get(energy).hidden_by == hidden

    # Once done, a restart does not take it over again.
    await hass.config_entries.async_reload(ps5_entry.entry_id)
    await async_wait_recording_done(hass)
    assert ps5_entry.runtime_data.energy_taken_over == energy

    # Plug unlinked: its sensors show again.
    hass.config_entries.async_update_entry(ps5_entry, options={})
    await hass.async_block_till_done()
    assert registry.async_get(power).hidden_by is None
    assert registry.async_get(energy).hidden_by is None


async def test_sensors_shown_again_when_the_console_is_deleted(
    hass: HomeAssistant, mock_ddp, ps5_entry
) -> None:
    power, energy = _plug(hass)
    registry = er.async_get(hass)
    registry.async_update_entity(energy, hidden_by=er.RegistryEntryHider.USER)
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps5_entry, options={"power_entity": power, "hide_sources": True}
    )
    await _setup(hass, ps5_entry)
    assert registry.async_get(power).hidden_by == er.RegistryEntryHider.INTEGRATION
    await hass.config_entries.async_remove(ps5_entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get(power).hidden_by is None
    # Hidden by the user, not by the hub: left as it was.
    assert registry.async_get(energy).hidden_by == er.RegistryEntryHider.USER
