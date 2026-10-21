"""PlayStation 4 or PlayStation 3 through the PlayStation Network account alone.

The coordinator reads the account: the console is on while the account is online on it, and
the game comes with it. No local protocol, so no power command. Nothing to install on the
console: it only has to sign in to the PlayStation Network when it starts.
"""

from __future__ import annotations

from datetime import timedelta

from ..models import ConsoleSnapshot
from .base import ConsoleDriver


class PlayStationAccountDriver(ConsoleDriver):
    update_interval = timedelta(seconds=60)
    power_from_psn = True
    native_state = False  # the account only knows when it is online on the console

    async def async_fetch(self) -> ConsoleSnapshot:
        return ConsoleSnapshot()  # off until the account says otherwise
