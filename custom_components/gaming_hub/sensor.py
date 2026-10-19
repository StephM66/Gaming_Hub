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
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ConsoleData, GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity
from .parental import ParentalStatus

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
        attributes_fn=lambda data: {"source": "measured" if data.power_measured else "estimated"},
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
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    descriptions = [d for d in HUB_SENSORS if d.exists_fn(coordinator)]
    descriptions += [DRIVER_SENSORS[key] for key in coordinator.driver.sensors]
    async_add_entities(HubSensor(coordinator, description) for description in descriptions)


class HubSensor(GamingHubEntity, SensorEntity):
    entity_description: HubSensorDescription

    def __init__(
        self, coordinator: GamingHubCoordinator, description: HubSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)
