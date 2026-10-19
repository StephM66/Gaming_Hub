"""Play time (day, week, month) and cumulative energy, integrated between refreshes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

# Longer gaps (Home Assistant stopped, console unreachable) are not counted.
MAX_GAP = timedelta(minutes=5)


def week_of(day: date) -> str:
    """ISO week (Monday to Sunday), e.g. ``2026-W43``."""
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


def month_of(day: date) -> str:
    return f"{day.year}-{day.month:02d}"


@dataclass(slots=True)
class UsageTracker:
    day: date | None = None
    playtime: float = 0.0  # seconds the console was on today
    week: str | None = None
    week_playtime: float = 0.0  # seconds this week
    month: str | None = None
    month_playtime: float = 0.0  # seconds this month
    energy: float = 0.0  # kWh since the console was added
    _last_time: datetime | None = None
    _last_active: bool = False
    _last_watts: float | None = None

    def update(self, now: datetime, active: bool, watts: float | None) -> None:
        """Account for the time since the previous call, using the previous state."""
        start = self._last_time
        counted = start is not None and timedelta(0) < now - start <= MAX_GAP
        if self.day != now.date():
            midnight = datetime.combine(now.date(), time(), now.tzinfo)
            if counted and start < midnight:
                # Time before midnight belongs to the previous day, week and month.
                self._account(start, midnight)
                start = midnight
            self.day = now.date()
            self.playtime = 0.0
        # A new week or month, or none yet (data saved before they existed): what is known
        # of it is today's play time.
        if self.week != (week := week_of(self.day)):
            self.week, self.week_playtime = week, self.playtime
        if self.month != (month := month_of(self.day)):
            self.month, self.month_playtime = month, self.playtime
        if counted:
            self._account(start, now)
        self._last_time = now
        self._last_active = active
        self._last_watts = watts

    def _account(self, start: datetime, end: datetime) -> None:
        elapsed = (end - start).total_seconds()
        if self._last_active:
            self.playtime += elapsed
            self.week_playtime += elapsed
            self.month_playtime += elapsed
        if self._last_watts:
            self.energy += self._last_watts * elapsed / 3.6e6

    def as_dict(self) -> dict[str, Any]:
        return {
            "day": self.day.isoformat() if self.day else None,
            "playtime": round(self.playtime, 1),
            "week": self.week,
            "week_playtime": round(self.week_playtime, 1),
            "month": self.month,
            "month_playtime": round(self.month_playtime, 1),
            "energy": self.energy,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> UsageTracker:
        data = data or {}
        return cls(
            day=date.fromisoformat(data["day"]) if data.get("day") else None,
            playtime=float(data.get("playtime", 0.0)),
            week=data.get("week"),
            week_playtime=float(data.get("week_playtime", 0.0)),
            month=data.get("month"),
            month_playtime=float(data.get("month_playtime", 0.0)),
            energy=float(data.get("energy", 0.0)),
        )
