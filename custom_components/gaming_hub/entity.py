"""Base entity: one device per console, profile or household (the coordinator's)."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import GamingHubCoordinator


class GamingHubEntity[CoordinatorT: Any = GamingHubCoordinator](CoordinatorEntity[CoordinatorT]):
    """``coordinator`` gives ``unique_prefix`` and ``device_info``."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CoordinatorT, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.unique_prefix}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = coordinator.device_info
