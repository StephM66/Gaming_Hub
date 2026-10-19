"""Console buttons: restart, quit the running game."""

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
    coordinator = entry.runtime_data
    async_add_entities(ConsoleButton(coordinator, key) for key in coordinator.driver.buttons)


class ConsoleButton(GamingHubEntity, ButtonEntity):
    def __init__(self, coordinator: GamingHubCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._key = key
        if key == "restart":
            self._attr_device_class = ButtonDeviceClass.RESTART

    @property
    def available(self) -> bool:
        snapshot = self.coordinator.data.snapshot
        if self._key == "quit_game":
            return super().available and snapshot.playing
        return super().available and snapshot.is_on

    async def async_press(self) -> None:
        await self.coordinator.async_press(self._key)
