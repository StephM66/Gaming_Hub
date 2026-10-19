"""PlayStation 3 with webMAN MOD."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..const import CONF_HOST, CONF_PORT
from ..models import ConsoleSnapshot, PowerState
from ..protocols.webman import DEFAULT_PORT, WebmanClient, WebmanError
from .base import ConsoleDriver, command_failed


class Ps3Driver(ConsoleDriver):
    sensors = ("cpu_temperature", "rsx_temperature", "fan_speed", "firmware")
    can_restart = True
    can_notify = True

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        self.client = WebmanClient(
            async_get_clientsession(hass),
            entry.data[CONF_HOST],
            entry.data.get(CONF_PORT, DEFAULT_PORT),
        )
        self.configuration_url = self.client.base_url  # webMAN MOD web interface

    @property
    def can_turn_off(self) -> bool:
        return True

    async def async_fetch(self) -> ConsoleSnapshot:
        try:
            status = await self.client.async_get_status()
        except WebmanError:
            return ConsoleSnapshot(PowerState.OFF)
        return ConsoleSnapshot(
            PowerState.ON,
            in_game=status.in_game,
            title=status.title,
            title_id=status.title_id,
            image_url=self.client.file_url(status.icon_path) if status.icon_path else None,
            attributes={
                "cpu_temperature": status.cpu_temperature,
                "rsx_temperature": status.rsx_temperature,
                "fan_speed": status.fan_speed,
                "firmware": status.firmware,
                "session_time": status.play_time,
            },
        )

    async def _run(self, command) -> None:
        try:
            await command
        except WebmanError as err:
            raise command_failed(str(err)) from err

    async def async_turn_off(self) -> None:
        await self._run(self.client.async_shutdown())

    async def async_restart(self) -> None:
        await self._run(self.client.async_restart())

    async def async_notify(self, message: str, title: str | None = None) -> None:
        await self._run(self.client.async_notify(f"{title}: {message}" if title else message))
