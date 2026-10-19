"""Data shared by drivers, the coordinator and the entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PowerState(StrEnum):
    """Console power state as the hub sees it."""

    OFF = "off"  # fully off, asleep without network, or unreachable
    STANDBY = "standby"  # rest mode, reachable on the network
    ON = "on"


@dataclass(slots=True)
class ConsoleSnapshot:
    """What a driver knows about its console at one point in time."""

    power: PowerState = PowerState.OFF
    in_game: bool = False
    title: str | None = None
    title_id: str | None = None
    image_url: str | None = None  # fetched by Home Assistant (media proxy)
    entity_picture: str | None = None  # already a frontend path (linked media player)
    attributes: dict[str, Any] = field(default_factory=dict)
    # Seconds played today, this week and this month as counted by the console's maker,
    # used instead of the hub's own count.
    playtime: tuple[float, float, float] | None = None

    @property
    def is_on(self) -> bool:
        return self.power is PowerState.ON

    @property
    def playing(self) -> bool:
        return self.is_on and (self.in_game or self.title is not None)
