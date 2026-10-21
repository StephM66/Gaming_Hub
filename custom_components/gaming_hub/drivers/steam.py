"""PC, Steam Deck or anything running Steam, through the Steam account (official Web API).

In a game: on, with the game and its artwork. Online without a game: standby, so the hub's
play time only counts time in game. Offline: off. Steam gives no power command.
"""

from __future__ import annotations

from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import CONF_API_KEY, CONF_STEAM_ID
from ..models import ConsoleSnapshot, PowerState
from ..protocols.steam import SteamAuthError, SteamClient
from .base import ConsoleDriver


class SteamDriver(ConsoleDriver):
    update_interval = timedelta(seconds=30)
    sensors = ("steam_status",)
    native_state = False  # Steam does not know whether the computer is on
    account_console = True
    counts_game_time_only = True

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        self.steam_id: str = entry.data[CONF_STEAM_ID]
        self.client = SteamClient(async_get_clientsession(hass), entry.data[CONF_API_KEY])

    async def async_fetch(self) -> ConsoleSnapshot:
        try:
            status = await self.client.async_status(self.steam_id)
        except SteamAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        attributes = {"steam_status": status.status, "steam_name": status.name}
        attributes["steam_avatar"] = status.avatar
        if status.status == "offline":
            return ConsoleSnapshot(PowerState.OFF, attributes=attributes)
        if not status.game:
            return ConsoleSnapshot(PowerState.STANDBY, attributes=attributes)
        return ConsoleSnapshot(
            PowerState.ON,
            in_game=True,
            title=status.game,
            title_id=status.game_id,
            image_url=status.image,
            attributes=attributes,
        )
