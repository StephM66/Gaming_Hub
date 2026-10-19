"""PlayStation 5: status and wake-up over DDP, standby over Remote Play."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.core import HomeAssistant

from ..const import CONF_HOST, CONF_PASSCODE, CONF_REGIST_KEY, CONF_RP_KEY
from ..models import ConsoleSnapshot, PowerState
from ..protocols import ddp, remoteplay
from .base import ConsoleDriver, command_failed, unsupported

_LOGGER = logging.getLogger(__name__)


def format_system_version(value: str | None) -> str | None:
    """``"09400001"`` → ``"9.40"``; other formats are returned as is."""
    if value and len(value) == 8 and value.isdigit():
        return f"{int(value[:2])}.{value[2:4]}"
    return value


class Ps5Driver(ConsoleDriver):
    update_interval = timedelta(seconds=10)
    sensors = ("system_version",)

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        data = entry.data
        self._host: str = data[CONF_HOST]
        self._passcode: str | None = data.get(CONF_PASSCODE) or None
        self._creds = (
            remoteplay.Ps5Credentials(data[CONF_REGIST_KEY], data[CONF_RP_KEY])
            if data.get(CONF_REGIST_KEY) and data.get(CONF_RP_KEY)
            else None
        )

    @property
    def can_turn_on(self) -> bool:
        return self._creds is not None

    @property
    def can_turn_off(self) -> bool:
        return self._creds is not None

    async def async_fetch(self) -> ConsoleSnapshot:
        try:
            response = await ddp.async_get_status(self._host)
        except OSError as err:
            _LOGGER.debug("DDP status of %s failed: %s", self._host, err)
            response = None
        if response is None:
            return ConsoleSnapshot(PowerState.OFF)
        snapshot = ConsoleSnapshot(
            PowerState.ON if response.awake else PowerState.STANDBY,
            attributes={"system_version": format_system_version(response.system_version)},
        )
        if response.awake and response.running_app_name:
            snapshot.in_game = True
            snapshot.title = response.running_app_name
            snapshot.title_id = response.running_app_titleid
        return snapshot

    async def async_turn_on(self) -> None:
        if self._creds is None:
            raise unsupported("turn_on")
        try:
            await ddp.async_wake(self._host, self._creds.user_credential)
        except OSError as err:
            raise command_failed(str(err)) from err

    async def async_turn_off(self) -> None:
        if self._creds is None:
            raise unsupported("turn_off")
        try:
            await remoteplay.async_standby(self._host, self._creds, self._passcode)
        except remoteplay.RemotePlayError as err:
            raise command_failed(err.reason) from err
