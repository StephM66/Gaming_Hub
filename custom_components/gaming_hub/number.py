"""Parental control: daily play time and warning delay."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry
from .entity import GamingHubEntity
from .household import parental_owners

PARALLEL_UPDATES = 0

NUMBERS = (
    # 0 means no daily limit.
    NumberEntityDescription(
        key="daily_limit",
        native_min_value=0,
        native_max_value=24 * 60,
        native_step=5,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="warning",
        native_min_value=0,
        native_max_value=30,
        native_step=1,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    for owner, subentry_id in parental_owners(entry):
        async_add_entities(
            [ParentalNumber(owner, description) for description in NUMBERS],
            config_subentry_id=subentry_id,
        )


class ParentalNumber(GamingHubEntity, NumberEntity):
    def __init__(self, coordinator, description: NumberEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return getattr(self.coordinator.parental.settings, self.entity_description.key)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_update_parental(**{self.entity_description.key: int(value)})
