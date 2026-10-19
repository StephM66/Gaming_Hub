"""Console drivers, imported on demand so unused protocols cost nothing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

from ..const import CONF_KIND, ConsoleKind
from .base import ConsoleDriver

if TYPE_CHECKING:
    from ..coordinator import GamingHubConfigEntry


def create_driver(hass: HomeAssistant, entry: GamingHubConfigEntry) -> ConsoleDriver:
    kind = ConsoleKind(entry.data[CONF_KIND])
    if kind is ConsoleKind.PS5:
        from .ps5 import Ps5Driver

        return Ps5Driver(hass, entry)
    if kind is ConsoleKind.PS3:
        from .ps3 import Ps3Driver

        return Ps3Driver(hass, entry)
    if kind is ConsoleKind.SWITCH:
        from .switch import SwitchDriver

        return SwitchDriver(hass, entry)
    from .linked import LinkedDriver

    return LinkedDriver(hass, entry)
