"""Restart, for consoles that support it."""

from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.runtime_data.driver.can_restart:
        async_add_entities([RestartButton(entry.runtime_data)])


class RestartButton(GamingHubEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART

    def __init__(self, coordinator: GamingHubCoordinator) -> None:
        super().__init__(coordinator, "restart")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.snapshot.is_on

    async def async_press(self) -> None:
        await self.coordinator.async_restart()
