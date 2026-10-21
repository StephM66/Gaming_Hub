"""Parental control: allowed play hours (same start and end = no restriction)."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry
from .entity import GamingHubEntity
from .household import parental_owners

PARALLEL_UPDATES = 0

# Entity key → ParentalSettings field.
FIELDS = {"allowed_from": "start", "allowed_until": "end"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for owner, subentry_id in parental_owners(entry):
        async_add_entities(
            [ParentalTime(owner, key) for key in FIELDS], config_subentry_id=subentry_id
        )


class ParentalTime(GamingHubEntity, TimeEntity):
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator, key: str) -> None:
        super().__init__(coordinator, key)
        self._field = FIELDS[key]

    @property
    def native_value(self) -> time | None:
        return getattr(self.coordinator.parental.settings, self._field)

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_update_parental(**{self._field: value})
