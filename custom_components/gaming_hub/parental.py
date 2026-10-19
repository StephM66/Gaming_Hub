"""Parental control shared by every console: daily limit and allowed hours.

Pure logic, evaluated on each coordinator refresh. The coordinator turns a
decision into notifications, events and power-off commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from typing import Any

# Delay before a console turned on while play is already blocked is powered off.
REACTIVATION_GRACE = timedelta(minutes=1)
# Repeat the power-off if the console is still on (failed command, turned back on).
RETRY_AFTER = timedelta(minutes=2)


class ParentalStatus(StrEnum):
    DISABLED = "disabled"
    ALLOWED = "allowed"
    WARNING = "warning"
    BLOCKED = "blocked"


class ParentalAction(StrEnum):
    NOTIFY = "notify"
    TURN_OFF = "turn_off"


class BlockReason(StrEnum):
    LIMIT = "limit"
    SCHEDULE = "schedule"


class Notice(StrEnum):
    WARNING = "warning"
    BLOCKED = "blocked"


@dataclass(slots=True)
class ParentalSettings:
    enabled: bool = False
    daily_limit: int = 0  # minutes, 0 = no daily limit
    start: time | None = None  # play allowed from…
    end: time | None = None  # …until (overnight ranges allowed)
    action: ParentalAction = ParentalAction.TURN_OFF
    warning: int = 5  # minutes of notice before the limit

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "daily_limit": self.daily_limit,
            "start": self.start.isoformat() if self.start else None,
            "end": self.end.isoformat() if self.end else None,
            "action": self.action.value,
            "warning": self.warning,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ParentalSettings:
        data = data or {}
        defaults = cls()
        return cls(
            enabled=bool(data.get("enabled", defaults.enabled)),
            daily_limit=int(data.get("daily_limit", defaults.daily_limit)),
            start=time.fromisoformat(data["start"]) if data.get("start") else None,
            end=time.fromisoformat(data["end"]) if data.get("end") else None,
            action=ParentalAction(data.get("action", defaults.action)),
            warning=int(data.get("warning", defaults.warning)),
        )


@dataclass(frozen=True, slots=True)
class ParentalDecision:
    status: ParentalStatus
    reason: BlockReason | None = None
    remaining: float | None = None  # minutes before play is blocked, None = unlimited
    notice: Notice | None = None  # message to deliver now
    enforce: bool = False  # power the console off now


def schedule_remaining(now: datetime, start: time, end: time) -> float:
    """Seconds left in the allowed range, 0 outside of it."""
    current = now.time().replace(tzinfo=None)
    inside = start <= current < end if start < end else (current >= start or current < end)
    if not inside:
        return 0.0
    until = datetime.combine(now.date(), end, now.tzinfo)
    if until <= now:
        until += timedelta(days=1)
    return (until - now).total_seconds()


class ParentalController:
    """Turns settings, play time and console state into decisions."""

    def __init__(self, settings: ParentalSettings) -> None:
        self.settings = settings
        self._day = None
        self._was_active = False
        self._session_warned = False
        self._blocked_since: datetime | None = None
        self._deadline: datetime | None = None
        self._block_notified = False
        self._enforced_at: datetime | None = None

    def _remaining(self, now: datetime, playtime: float) -> tuple[float, BlockReason] | None:
        settings = self.settings
        limits: list[tuple[float, BlockReason]] = []
        if settings.daily_limit > 0:
            limits.append((settings.daily_limit * 60 - playtime, BlockReason.LIMIT))
        if settings.start and settings.end and settings.start != settings.end:
            limits.append(
                (schedule_remaining(now, settings.start, settings.end), BlockReason.SCHEDULE)
            )
        return min(limits, key=lambda item: item[0]) if limits else None

    def _clear_block(self) -> None:
        self._blocked_since = self._deadline = self._enforced_at = None
        self._block_notified = False

    def evaluate(self, now: datetime, active: bool, playtime: float) -> ParentalDecision:
        """Decide for ``now``; ``active`` is the console being on, ``playtime`` in seconds."""
        settings = self.settings
        if not settings.enabled:
            self._clear_block()
            self._was_active = active
            return ParentalDecision(ParentalStatus.DISABLED)
        if self._day != now.date():
            self._day = now.date()
            self._clear_block()
        if active and not self._was_active:
            self._session_warned = False
        self._was_active = active

        if (limit := self._remaining(now, playtime)) is None:
            self._clear_block()
            return ParentalDecision(ParentalStatus.ALLOWED)
        seconds, reason = limit
        if seconds > 0:
            self._clear_block()
            minutes = seconds / 60
            if active and settings.warning > 0 and minutes <= settings.warning:
                notice = None if self._session_warned else Notice.WARNING
                self._session_warned = True
                return ParentalDecision(ParentalStatus.WARNING, reason, minutes, notice)
            return ParentalDecision(ParentalStatus.ALLOWED, reason, minutes)

        if not active:
            # Off and out of time: the next power-on gets a fresh grace period.
            self._clear_block()
            return ParentalDecision(ParentalStatus.BLOCKED, reason, 0)

        if self._blocked_since is None:
            self._blocked_since = now
            # Warned during this session: enforce now; otherwise give a short grace.
            self._deadline = now if self._session_warned else now + REACTIVATION_GRACE
        notice = None
        if not self._block_notified:
            notice = Notice.BLOCKED
            self._block_notified = True
        enforce = (
            settings.action is ParentalAction.TURN_OFF
            and now >= self._deadline
            and (self._enforced_at is None or now - self._enforced_at >= RETRY_AFTER)
        )
        if enforce:
            self._enforced_at = now
        return ParentalDecision(ParentalStatus.BLOCKED, reason, 0, notice, enforce)
