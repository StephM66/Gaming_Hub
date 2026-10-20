"""Nintendo Switch and Switch 2 through the Nintendo account, without modifying the console.

Nintendo publishes each console's play time per game (the Parental Controls app). From it:
the official play time of the day, week and month, the games played today, and the current
game, deduced from the minutes that grow between two polls.

Nintendo gives no power state and no command: the console counts as on while its play time
grows, with the delay of its reports to Nintendo, wherever it is played (TV, handheld, Lite).
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
import logging
import time

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util

from ..const import CONF_DEVICE_ID, CONF_SESSION_TOKEN
from ..models import ConsoleSnapshot, PowerState
from ..protocols.nintendo import (
    GameTime,
    NintendoAuthError,
    NintendoClient,
    NintendoError,
    PlayDay,
)
from ..usage import month_of, week_of
from .base import ConsoleDriver

_LOGGER = logging.getLogger(__name__)
# Nintendo is read at each refresh (just under its interval).
POLL_INTERVAL = 55
CATALOG_INTERVAL = 3600  # console information and game names
CATALOG_RETRY = 15 * 60  # a game played today that the console's list does not name yet
# No minute added for that long: off, no current game.
ACTIVE_WINDOW = timedelta(minutes=30)


def _language(language: str, country: str | None) -> str:
    return language if "-" in language else f"{language}-{country or language.upper()}"


class NintendoDriver(ConsoleDriver):
    update_interval = timedelta(seconds=60)
    sensors = ("system_version",)

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        self.device_id: str = entry.data[CONF_DEVICE_ID]
        self.client = NintendoClient(
            async_get_clientsession(hass),
            entry.data[CONF_SESSION_TOKEN],
            time_zone=hass.config.time_zone,
            language=_language(hass.config.language, hass.config.country),
        )
        self._days: list[PlayDay] | None = None  # None until Nintendo first answers
        self._titles: dict[str, GameTime] = {}
        self._system_version: str | None = None
        self._next_poll = 0.0
        self._next_catalog = 0.0
        # Today's minutes per game at the previous poll (None until a first poll).
        self._minutes: dict[str, float] | None = None
        self._minutes_day: date | None = None
        self._current: GameTime | None = None
        self._grew_at: datetime | None = None

    async def async_fetch(self) -> ConsoleSnapshot:
        now = dt_util.now()
        try:
            await self._async_poll(now)
        except NintendoAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except NintendoError as err:
            if self._days is None:
                raise  # nothing known yet: setting up is retried later
            # Nintendo unreachable: keep what is known.
            _LOGGER.debug("Nintendo account unavailable: %s", err)
        on = self._grew_at is not None and now - self._grew_at <= ACTIVE_WINDOW
        snapshot = ConsoleSnapshot(
            PowerState.ON if on else PowerState.OFF,
            attributes={"system_version": self._system_version},
            playtime=self._playtime(now.date()),
        )
        if today := self._today(now.date()):
            snapshot.attributes["playtime_today"] = {
                "games": {
                    (self._named(game).title or title_id): game.minutes
                    for title_id, game in today.games.items()
                },
                "players": today.players,
            }
        if on and self._current:
            game = self._named(self._current)
            snapshot.in_game = True
            snapshot.title = game.title
            snapshot.title_id = game.title_id
            snapshot.image_url = game.image
        return snapshot

    async def _async_poll(self, now: datetime) -> None:
        if time.monotonic() < self._next_poll:
            return
        self._next_poll = time.monotonic() + POLL_INTERVAL
        if time.monotonic() >= self._next_catalog:
            self._next_catalog = time.monotonic() + CATALOG_INTERVAL
            for device in await self.client.async_devices():
                if device.device_id == self.device_id:
                    self._system_version = device.system_version
            self._titles = await self.client.async_titles(self.device_id)
        self._days = await self.client.async_play_days(self.device_id)
        if any(self._named(game).title is None for game in self._today_games(now.date())):
            self._next_catalog = min(self._next_catalog, time.monotonic() + CATALOG_RETRY)
        self._follow(now)

    def _named(self, game: GameTime) -> GameTime:
        """Name and artwork from the console's game list when the summary has none (Switch 2)."""
        if (game.title and game.image) or not (known := self._titles.get(game.title_id)):
            return game
        return replace(game, title=game.title or known.title, image=game.image or known.image)

    def _today(self, day: date) -> PlayDay | None:
        # Nintendo leaves today out until the console has reported it.
        return next((summary for summary in self._days or () if summary.day == day), None)

    def _today_games(self, day: date) -> list[GameTime]:
        return list(today.games.values()) if (today := self._today(day)) else []

    def _follow(self, now: datetime) -> None:
        """The current game is the one whose minutes grew since the previous poll."""
        today = self._today(now.date())
        minutes = {
            title_id: game.minutes for title_id, game in (today.games if today else {}).items()
        }
        if self._minutes is not None:
            previous = self._minutes if self._minutes_day == now.date() else {}
            grown = {
                title_id: value - previous.get(title_id, 0.0)
                for title_id, value in minutes.items()
                if value > previous.get(title_id, 0.0)
            }
            if grown and today:
                self._current = today.games[max(grown, key=grown.__getitem__)]
                self._grew_at = now
        self._minutes, self._minutes_day = minutes, now.date()

    def _playtime(self, day: date) -> tuple[float, float, float]:
        days = self._days or []
        week, month = week_of(day), month_of(day)
        today = self._today(day)
        return (
            (today.minutes if today else 0.0) * 60,
            sum(d.minutes for d in days if week_of(d.day) == week) * 60,
            sum(d.minutes for d in days if month_of(d.day) == month) * 60,
        )
