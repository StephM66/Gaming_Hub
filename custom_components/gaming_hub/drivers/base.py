"""Driver interface: one implementation per kind of console."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from ..const import DOMAIN
from ..models import ConsoleSnapshot

if TYPE_CHECKING:
    from ..coordinator import GamingHubConfigEntry


class ConsoleDriver:
    """Reads a console's state and sends it commands.

    ``async_fetch`` must not raise for an unreachable console: an off console
    is a normal state, reported as ``PowerState.OFF``.
    """

    update_interval = timedelta(seconds=15)
    # Keys of ``ConsoleSnapshot.attributes`` exposed as sensors / binary sensors.
    sensors: tuple[str, ...] = ()
    binary_sensors: tuple[str, ...] = ()
    can_restart = False
    can_notify = False
    configuration_url: str | None = None  # console web page, shown on the device

    def __init__(self, hass: HomeAssistant, entry: GamingHubConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

    @property
    def can_turn_on(self) -> bool:
        return False

    @property
    def can_turn_off(self) -> bool:
        return False

    async def async_start(self, on_change: Callable[[], None]) -> None:
        """Subscribe to push updates; ``on_change`` asks for a refresh."""

    async def async_stop(self) -> None:
        """Undo ``async_start``."""

    async def async_fetch(self) -> ConsoleSnapshot:
        raise NotImplementedError

    async def async_turn_on(self) -> None:
        raise unsupported("turn_on")

    async def async_turn_off(self) -> None:
        raise unsupported("turn_off")

    async def async_restart(self) -> None:
        raise unsupported("restart")

    async def async_notify(self, message: str, title: str | None = None) -> None:
        raise unsupported("notify")


def unsupported(command: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="unsupported",
        translation_placeholders={"command": command},
    )


def command_failed(reason: str) -> HomeAssistantError:
    return HomeAssistantError(
        translation_domain=DOMAIN,
        translation_key="command_failed",
        translation_placeholders={"reason": reason},
    )
