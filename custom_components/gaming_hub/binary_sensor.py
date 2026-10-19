"""Playing (every console) and charging (Switch)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity

PARALLEL_UPDATES = 0

DEVICE_CLASSES = {
    "playing": BinarySensorDeviceClass.RUNNING,
    "charging": BinarySensorDeviceClass.BATTERY_CHARGING,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    keys = ["playing", *coordinator.driver.binary_sensors]
    async_add_entities(HubBinarySensor(coordinator, key) for key in keys)


class HubBinarySensor(GamingHubEntity, BinarySensorEntity):
    def __init__(self, coordinator: GamingHubCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        self._attr_device_class = DEVICE_CLASSES.get(key)

    @property
    def is_on(self) -> bool | None:
        snapshot = self.coordinator.data.snapshot
        if self._key == "playing":
            return snapshot.playing
        return snapshot.attributes.get(self._key)
