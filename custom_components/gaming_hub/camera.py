"""Live picture of the console screen, when the console streams it (Switch Assistant)."""

from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
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
    if entry.runtime_data.driver.has_screen:
        async_add_entities([ScreenCamera(entry.runtime_data)])


class ScreenCamera(GamingHubEntity, Camera):
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(self, coordinator: GamingHubCoordinator) -> None:
        GamingHubEntity.__init__(self, coordinator, "screen")
        Camera.__init__(self)

    @property
    def _url(self) -> str | None:
        snapshot = self.coordinator.data.snapshot
        return snapshot.attributes.get("stream_url") if snapshot.is_on else None

    @property
    def available(self) -> bool:
        return super().available and self._url is not None

    @property
    def use_stream_for_stills(self) -> bool:
        # No still image endpoint: snapshots come from the stream.
        return True

    async def stream_source(self) -> str | None:
        return self._url
