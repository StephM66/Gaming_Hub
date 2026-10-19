"""On-screen message, for consoles that can display one (PS3, Switch)."""

from __future__ import annotations

from homeassistant.components.notify import NotifyEntity
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
    if entry.runtime_data.driver.can_notify:
        async_add_entities([ConsoleNotify(entry.runtime_data)])


class ConsoleNotify(GamingHubEntity, NotifyEntity):
    def __init__(self, coordinator: GamingHubCoordinator) -> None:
        super().__init__(coordinator, "message")

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.snapshot.is_on

    async def async_send_message(self, message: str, title: str | None = None) -> None:
        await self.coordinator.async_notify(message, title)
