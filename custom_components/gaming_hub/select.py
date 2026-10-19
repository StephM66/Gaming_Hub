"""Parental control: what happens when play time is over."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity
from .parental import ParentalAction

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ParentalActionSelect(entry.runtime_data)])


class ParentalActionSelect(GamingHubEntity, SelectEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GamingHubCoordinator) -> None:
        super().__init__(coordinator, "parental_action")
        self._attr_options = [action.value for action in ParentalAction]

    @property
    def current_option(self) -> str:
        return self.coordinator.parental.settings.action.value

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_update_parental(action=ParentalAction(option))
