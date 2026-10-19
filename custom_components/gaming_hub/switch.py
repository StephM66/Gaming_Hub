"""Parental control on/off."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ParentalControlSwitch(entry.runtime_data)])


class ParentalControlSwitch(GamingHubEntity, SwitchEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: GamingHubCoordinator) -> None:
        super().__init__(coordinator, "parental_control")

    @property
    def is_on(self) -> bool:
        return self.coordinator.parental.settings.enabled

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_parental(enabled=True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_update_parental(enabled=False)
