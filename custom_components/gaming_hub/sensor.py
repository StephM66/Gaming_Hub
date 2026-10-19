"""Current game, consumption, play time, parental status and console sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    Platform,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_KIND, SUMMARY
from .coordinator import ConsoleData, GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity
from .parental import ParentalStatus
from .summary import SUMMARY_SENSORS, SummarySensor

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ConsoleData], Any]
    exists_fn: Callable[[GamingHubCoordinator], bool] = lambda _: True
    attributes_fn: Callable[[ConsoleData], dict[str, Any]] | None = None


def _attribute(key: str) -> Callable[[ConsoleData], Any]:
    return lambda data: data.snapshot.attributes.get(key)


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    HubSensorDescription(
        key="game",
        value_fn=lambda data: data.snapshot.title if data.snapshot.is_on else None,
        attributes_fn=lambda data: {"title_id": data.snapshot.title_id},
    ),
    HubSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        value_fn=lambda data: data.power,
        exists_fn=lambda coordinator: coordinator.has_power,
    ),
    HubSensorDescription(
        key="energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.energy, 4),
        exists_fn=lambda coordinator: coordinator.has_power,
    ),
    HubSensorDescription(
        key="playtime_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: round(data.playtime / 60, 1),
        # Games and players of the day, when the console's maker gives them (Nintendo).
        attributes_fn=lambda data: data.snapshot.attributes.get("playtime_today"),
    ),
    HubSensorDescription(
        key="playtime_week",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda data: round(data.playtime_week / 3600, 2),
    ),
    HubSensorDescription(
        key="playtime_month",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda data: round(data.playtime_month / 3600, 2),
    ),
    HubSensorDescription(
        key="parental_status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in ParentalStatus],
        value_fn=lambda data: data.parental.status.value,
        attributes_fn=lambda data: {"reason": data.parental.reason and data.parental.reason.value},
    ),
    HubSensorDescription(
        key="parental_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: (
            None if data.parental.remaining is None else round(max(data.parental.remaining, 0), 1)
        ),
    ),
)

# Console-specific values, created when the driver lists them.
DRIVER_SENSORS: dict[str, HubSensorDescription] = {
    description.key: description
    for description in (
        HubSensorDescription(
            key="cpu_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            value_fn=_attribute("cpu_temperature"),
        ),
        HubSensorDescription(
            key="rsx_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            value_fn=_attribute("rsx_temperature"),
        ),
        HubSensorDescription(
            key="fan_speed",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("fan_speed"),
        ),
        HubSensorDescription(
            key="firmware",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("firmware"),
        ),
        HubSensorDescription(
            key="system_version",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("system_version"),
        ),
        HubSensorDescription(
            key="battery",
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("battery"),
        ),
        HubSensorDescription(
            key="battery_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("battery_temperature"),
        ),
        HubSensorDescription(
            key="controllers",
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_attribute("controllers"),
            attributes_fn=lambda data: data.snapshot.attributes.get("players") or {},
        ),
        # PlayStation 3 (webMAN MOD)
        HubSensorDescription(
            key="fan_mode",
            device_class=SensorDeviceClass.ENUM,
            options=["syscon", "auto", "dynamic", "manual", "ps2"],
            value_fn=_attribute("fan_mode"),
        ),
        HubSensorDescription(
            key="fan_target",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("fan_target"),
        ),
        HubSensorDescription(
            key="session_time",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=0,
            value_fn=_attribute("session_time"),
        ),
        HubSensorDescription(
            key="memory_free",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfInformation.MEGABYTES,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("memory_free"),
        ),
        HubSensorDescription(
            key="hdd_free",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfInformation.GIGABYTES,
            suggested_display_precision=1,
            value_fn=_attribute("hdd_free"),
        ),
        HubSensorDescription(
            key="started_at",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("started_at"),
        ),
        HubSensorDescription(
            key="network",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("network"),
        ),
        HubSensorDescription(
            key="ip_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("ip_address"),
        ),
        HubSensorDescription(
            key="runtime",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfTime.HOURS,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("runtime"),
        ),
        HubSensorDescription(
            key="power_on_count",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("power_on_count"),
        ),
        # Nintendo Switch (Switch Assistant)
        HubSensorDescription(
            key="battery_health",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("battery_health"),
        ),
        HubSensorDescription(
            key="battery_voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("battery_voltage"),
        ),
        HubSensorDescription(
            key="charger",
            device_class=SensorDeviceClass.ENUM,
            options=["unconnected", "enough_power", "low_power", "not_supported", "unknown"],
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("charger"),
        ),
        HubSensorDescription(
            key="brightness",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("brightness"),
        ),
        HubSensorDescription(
            key="volume",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("volume"),
        ),
        HubSensorDescription(
            key="audio_output",
            device_class=SensorDeviceClass.ENUM,
            options=["speaker", "headphone", "tv", "usb", "bluetooth", "unknown"],
            value_fn=_attribute("audio_output"),
        ),
        # PlayStation Network account
        HubSensorDescription(
            key="psn_status",
            value_fn=_attribute("psn_status"),
            attributes_fn=lambda data: {
                "online_id": data.snapshot.attributes.get("psn_online_id"),
                "avatar": data.snapshot.attributes.get("psn_avatar"),
            },
        ),
        HubSensorDescription(
            key="trophy_level",
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_attribute("trophy_level"),
            attributes_fn=lambda data: {
                "progress": data.snapshot.attributes.get("trophy_progress"),
                **(data.snapshot.attributes.get("trophies") or {}),
            },
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.data.get(CONF_KIND) == SUMMARY:
        async_add_entities(SummarySensor(entry, description) for description in SUMMARY_SENSORS)
        return
    coordinator = entry.runtime_data
    descriptions = [d for d in HUB_SENSORS if d.exists_fn(coordinator)]
    descriptions += [DRIVER_SENSORS[key] for key in coordinator.sensor_keys]
    entities = [HubSensor(coordinator, description) for description in descriptions]
    # Sensors no longer provided (power and energy once the plug is unlinked) are removed.
    registry = er.async_get(hass)
    wanted = {entity.unique_id for entity in entities}
    for stale in er.async_entries_for_config_entry(registry, entry.entry_id):
        if stale.domain == Platform.SENSOR and stale.unique_id not in wanted:
            registry.async_remove(stale.entity_id)
    async_add_entities(entities)


class HubSensor(GamingHubEntity, SensorEntity):
    entity_description: HubSensorDescription

    def __init__(
        self, coordinator: GamingHubCoordinator, description: HubSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator.data)
        # States are limited to 255 characters; text comes from the consoles.
        return value[:255] if isinstance(value, str) else value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
