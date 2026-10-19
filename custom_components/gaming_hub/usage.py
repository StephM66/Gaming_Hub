"""Play time of the day and cumulative energy, integrated between refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

# Longer gaps (Home Assistant stopped, console unreachable) are not counted.
MAX_GAP = timedelta(minutes=5)


@dataclass(slots=True)
class UsageTracker:
    day: date | None = None
    playtime: float = 0.0  # seconds the console was on today
    energy: float = 0.0  # kWh since the console was added
    _last_time: datetime | None = None
    _last_active: bool = False
    _last_watts: float | None = None

    def update(self, now: datetime, active: bool, watts: float | None) -> None:
        """Account for the time since the previous call, using the previous state."""
        start = self._last_time
        counted = start is not None and timedelta(0) < now - start <= MAX_GAP
        if self.day != now.date():
            self.day = now.date()
            self.playtime = 0.0
            midnight = datetime.combine(now.date(), time(), now.tzinfo)
            if counted and start < midnight:
                # Energy keeps accumulating; play time before midnight was yesterday's.
                if self._last_watts:
                    self.energy += self._last_watts * (midnight - start).total_seconds() / 3.6e6
                start = midnight
        if counted:
            elapsed = (now - start).total_seconds()
            if self._last_active:
                self.playtime += elapsed
            if self._last_watts:
                self.energy += self._last_watts * elapsed / 3.6e6
        self._last_time = now
        self._last_active = active
        self._last_watts = watts

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat() if self.day else None,
            "playtime": round(self.playtime, 1),
            "energy": self.energy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UsageTracker:
        data = data or {}
        return cls(
            day=date.fromisoformat(data["day"]) if data.get("day") else None,
            playtime=float(data.get("playtime", 0.0)),
            energy=float(data.get("energy", 0.0)),
        )
