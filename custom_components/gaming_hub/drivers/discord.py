"""A player's PC games through their Discord account, whatever the launcher.

Playing (Discord shows a game): on, with the game. Discord open on a computer without a game:
standby, so the hub's play time only counts time in game. Otherwise: off. No power command.
Updates arrive as they happen (Gateway), with no polling of Discord.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import CONF_BOT_TOKEN, CONF_USER_ID, DOMAIN
from ..models import ConsoleSnapshot, PowerState
from ..protocols.discord import DiscordAuthError, DiscordGateway
from .base import ConsoleDriver

READY_TIMEOUT = 30  # seconds for Discord to send the bot's servers


@dataclass(slots=True)
class _Bot:
    gateway: DiscordGateway
    task: asyncio.Task[None]
    users: set[str] = field(default_factory=set)  # entries using this bot


def _bots(hass: HomeAssistant) -> dict[str, _Bot]:
    return hass.data.setdefault(f"{DOMAIN}_discord", {})


class DiscordDriver(ConsoleDriver):
    update_interval = timedelta(minutes=5)  # pushes do the work; this only refreshes play time
    sensors = ("discord_status",)
    native_state = False  # Discord does not know whether the computer is on
    account_console = True
    counts_game_time_only = True

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        self.token: str = entry.data[CONF_BOT_TOKEN]
        self.player: str = entry.data[CONF_USER_ID]
        self._unsubscribe: Callable[[], None] | None = None

    @property
    def gateway(self) -> DiscordGateway:
        return _bots(self.hass)[self.token].gateway

    async def async_start(self, on_change: Callable[[], None]) -> None:
        bots = _bots(self.hass)
        if (bot := bots.get(self.token)) is None:
            gateway = DiscordGateway(async_get_clientsession(self.hass), self.token)
            task = self.hass.async_create_background_task(
                gateway.async_run(), f"{DOMAIN} Discord gateway"
            )
            bot = bots[self.token] = _Bot(gateway, task)
        bot.users.add(self.entry.entry_id)
        self._unsubscribe = bot.gateway.subscribe(self.player, callback(on_change))
        try:
            async with asyncio.timeout(READY_TIMEOUT):
                await bot.gateway.ready.wait()
        except TimeoutError:
            self._release()
            raise ConfigEntryNotReady("Discord did not answer") from None
        except BaseException:
            self._release()
            raise
        if (err := bot.gateway.error) is not None:
            self._release()
            if isinstance(err, DiscordAuthError):
                raise ConfigEntryAuthFailed(str(err)) from err
            raise ConfigEntryNotReady(str(err)) from err

    async def async_stop(self) -> None:
        self._release()

    def _release(self) -> None:
        if self._unsubscribe is None:
            return
        self._unsubscribe()
        self._unsubscribe = None
        bots = _bots(self.hass)
        bot = bots[self.token]
        bot.users.discard(self.entry.entry_id)
        if not bot.users:
            del bots[self.token]
            bot.task.cancel()

    def _check(self) -> None:
        if isinstance(err := self.gateway.error, DiscordAuthError):
            raise ConfigEntryAuthFailed(str(err)) from err
        if err is not None:
            raise err  # Presence Intent turned off: entities unavailable until it is back

    async def async_fetch(self) -> ConsoleSnapshot:
        self._check()
        status = self.gateway.status(self.player)
        attributes = {"discord_status": status.status, "discord_since": status.started}
        if status.game:
            return ConsoleSnapshot(
                PowerState.ON,
                in_game=True,
                title=status.game,
                title_id=status.game_id,
                image_url=status.image,
                attributes=attributes,
            )
        state = PowerState.STANDBY if status.desktop else PowerState.OFF
        return ConsoleSnapshot(state, attributes=attributes)
