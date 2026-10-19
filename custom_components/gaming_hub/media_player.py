"""The console itself: power, current game and artwork."""

from __future__ import annotations

from typing import Any

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity
from .models import PowerState

PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ConsoleMediaPlayer(entry.runtime_data)])


class ConsoleMediaPlayer(GamingHubEntity, MediaPlayerEntity):
    _attr_name = None
    _attr_media_content_type = MediaType.GAME
    _attr_media_image_remotely_accessible = False

    def __init__(self, coordinator: GamingHubCoordinator) -> None:
        super().__init__(coordinator, "console")

    @property
    def state(self) -> MediaPlayerState:
        snapshot = self.coordinator.data.snapshot
        if snapshot.power is PowerState.OFF:
            return MediaPlayerState.OFF
        if snapshot.power is PowerState.STANDBY:
            return MediaPlayerState.STANDBY
        return MediaPlayerState.PLAYING if snapshot.playing else MediaPlayerState.ON

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        features = MediaPlayerEntityFeature(0)
        if self.coordinator.can_turn_on:
            features |= MediaPlayerEntityFeature.TURN_ON
        if self.coordinator.can_turn_off:
            features |= MediaPlayerEntityFeature.TURN_OFF
        return features

    @property
    def media_title(self) -> str | None:
        return (
            self.coordinator.data.snapshot.title if self.coordinator.data.snapshot.is_on else None
        )

    @property
    def media_content_id(self) -> str | None:
        return (
            self.coordinator.data.snapshot.title_id
            if self.coordinator.data.snapshot.is_on
            else None
        )

    @property
    def media_image_url(self) -> str | None:
        snapshot = self.coordinator.data.snapshot
        return snapshot.image_url if snapshot.is_on else None

    @property
    def entity_picture(self) -> str | None:
        snapshot = self.coordinator.data.snapshot
        if snapshot.is_on and snapshot.entity_picture:
            return snapshot.entity_picture
        return super().entity_picture

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"title_id": self.media_content_id}

    async def async_turn_on(self) -> None:
        await self.coordinator.async_turn_on()

    async def async_turn_off(self) -> None:
        await self.coordinator.async_turn_off()
