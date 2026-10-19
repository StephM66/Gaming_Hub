"""Parental control, play time and energy logic (no Home Assistant needed)."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from custom_components.gaming_hub.models import ConsoleSnapshot, PowerState
from custom_components.gaming_hub.parental import (
    BlockReason,
    Notice,
    ParentalAction,
    ParentalController,
    ParentalSettings,
    ParentalStatus,
    schedule_remaining,
)
from custom_components.gaming_hub.usage import UsageTracker

DAY = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)


def at(hour: int, minute: int = 0, second: int = 0) -> datetime:
    return DAY.replace(hour=hour, minute=minute, second=second)


def test_playing() -> None:
    assert ConsoleSnapshot(PowerState.ON, title="Astro Bot").playing
    assert ConsoleSnapshot(PowerState.ON, in_game=True).playing
    assert not ConsoleSnapshot(PowerState.ON).playing
    # A title reported while the console is in standby does not mean playing.
    assert not ConsoleSnapshot(PowerState.STANDBY, title="x").playing


def test_usage_integrates_previous_state() -> None:
    usage = UsageTracker()
    usage.update(at(14), active=True, watts=200)
    usage.update(at(14, 1), active=True, watts=200)
    usage.update(at(14, 2), active=False, watts=2)
    usage.update(at(14, 3), active=False, watts=2)
    assert usage.playtime == 120
    assert abs(usage.energy - (200 * 120 + 2 * 60) / 3.6e6) < 1e-12
    # A long gap (Home Assistant restarted) is not counted.
    usage.update(at(15), active=True, watts=200)
    usage.update(at(15, 30), active=True, watts=200)
    assert usage.playtime == 120


def test_usage_resets_play_time_at_midnight() -> None:
    usage = UsageTracker()
    usage.update(DAY.replace(hour=23, minute=59), active=True, watts=100)
    usage.update(DAY.replace(hour=23, minute=59, second=30), active=True, watts=100)
    assert usage.playtime == 30
    next_day = DAY.replace(hour=0, minute=0, second=30) + timedelta(days=1)
    usage.update(next_day, active=True, watts=100)
    assert usage.day == next_day.date()
    assert usage.playtime == 30  # only the 30 s after midnight
    assert abs(usage.energy - 100 * 90 / 3.6e6) < 1e-12
    restored = UsageTracker.from_dict(usage.as_dict())
    assert (restored.day, restored.playtime, restored.energy) == (
        usage.day,
        usage.playtime,
        usage.energy,
    )


def test_schedule_remaining() -> None:
    assert schedule_remaining(at(14), time(9), time(20)) == 6 * 3600
    assert schedule_remaining(at(21), time(9), time(20)) == 0
    assert schedule_remaining(at(23), time(22), time(1)) == 2 * 3600  # overnight
    assert schedule_remaining(at(12), time(22), time(1)) == 0


def test_disabled_and_unlimited() -> None:
    controller = ParentalController(ParentalSettings())
    assert controller.evaluate(at(14), True, 10**6).status is ParentalStatus.DISABLED
    controller.settings.enabled = True
    decision = controller.evaluate(at(14), True, 10**6)
    assert (decision.status, decision.remaining) == (ParentalStatus.ALLOWED, None)


def test_daily_limit_warns_once_then_turns_off() -> None:
    controller = ParentalController(ParentalSettings(enabled=True, daily_limit=60, warning=5))
    decision = controller.evaluate(at(14), True, 30 * 60)
    assert (decision.status, decision.reason, decision.remaining) == (
        ParentalStatus.ALLOWED,
        BlockReason.LIMIT,
        30,
    )
    decision = controller.evaluate(at(14, 26), True, 56 * 60)
    assert (decision.status, decision.notice) == (ParentalStatus.WARNING, Notice.WARNING)
    assert controller.evaluate(at(14, 27), True, 57 * 60).notice is None
    decision = controller.evaluate(at(14, 30), True, 60 * 60)
    assert decision.status is ParentalStatus.BLOCKED
    assert (decision.notice, decision.enforce) == (Notice.BLOCKED, True)
    # Still on (command failed or console turned back on quickly): retry later.
    assert not controller.evaluate(at(14, 31), True, 61 * 60).enforce
    assert controller.evaluate(at(14, 32), True, 62 * 60).enforce


def test_turned_on_after_limit_gets_short_grace() -> None:
    controller = ParentalController(ParentalSettings(enabled=True, daily_limit=60))
    off = controller.evaluate(at(16), False, 60 * 60)
    assert (off.status, off.notice, off.enforce) == (ParentalStatus.BLOCKED, None, False)
    first = controller.evaluate(at(17), True, 60 * 60)
    assert (first.notice, first.enforce) == (Notice.BLOCKED, False)
    assert not controller.evaluate(at(17, 0, 30), True, 60 * 60).enforce
    assert controller.evaluate(at(17, 1), True, 60 * 60 + 60).enforce


def test_schedule_and_notify_only() -> None:
    settings = ParentalSettings(
        enabled=True, start=time(9), end=time(20), action=ParentalAction.NOTIFY
    )
    controller = ParentalController(settings)
    assert controller.evaluate(at(19, 50), True, 0).notice is None
    assert controller.evaluate(at(19, 56), True, 0).notice is Notice.WARNING
    blocked = controller.evaluate(at(20), True, 0)
    assert (blocked.status, blocked.reason, blocked.notice, blocked.enforce) == (
        ParentalStatus.BLOCKED,
        BlockReason.SCHEDULE,
        Notice.BLOCKED,
        False,
    )
    assert controller.evaluate(at(20, 5), True, 0).notice is None


def test_next_day_starts_fresh() -> None:
    controller = ParentalController(ParentalSettings(enabled=True, daily_limit=30))
    assert controller.evaluate(at(18), True, 30 * 60).status is ParentalStatus.BLOCKED
    tomorrow = at(10) + timedelta(days=1)
    assert controller.evaluate(tomorrow, True, 0).status is ParentalStatus.ALLOWED


def test_settings_round_trip() -> None:
    settings = ParentalSettings(True, 90, time(8, 30), time(21), ParentalAction.NOTIFY, 10)
    assert ParentalSettings.from_dict(settings.as_dict()) == settings
    assert ParentalSettings.from_dict(None) == ParentalSettings()
