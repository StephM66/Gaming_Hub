"""PlayStation 3 running webMAN MOD (custom firmware or PS3HEN).

webMAN MOD serves an HTTP API on port 80. Status comes from ``/cpursx.ps3``
(HTML; the patterns below follow webMAN's ``include/cpursx.h``), commands are
plain GET requests. The console cannot be powered on over the network.
"""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from urllib.parse import quote

import aiohttp

DEFAULT_PORT = 80

_CPU = re.compile(r"CPU:\s*(\d+)\s*(?:°|&deg;|&#176;)\s*C", re.IGNORECASE)
_RSX = re.compile(r"RSX:\s*(\d+)\s*(?:°|&deg;|&#176;)\s*C", re.IGNORECASE)
_FAN = re.compile(r"cpursx\.ps3\?mode\"[^>]*>[^<]*?(\d+)\s*%")
_TITLE_ID = re.compile(r"/tpl/np/([A-Z0-9]{9})/")
_TITLE = re.compile(r"/tpl/np/[A-Z0-9]{9}/[^\"]*\"[^>]*>[^<]*</a>\s*<a href=\"[^\"]*\">([^<]*)</a>")
_ICON = re.compile(r"<img src=\"([^\"]+/ICON0\.PNG)\"", re.IGNORECASE)
_PLAY = re.compile(
    r"title=\"Play\">[^<]*</label>\s*(?:[^:<\d]*:\s*)?(?:(\d+)d\s*)?(\d+):(\d{2}):(\d{2})"
)
_FIRMWARE = re.compile(r"href=\"/setup\.ps3\">\s*(?:NAND|NOR)?\s*([^<]*?)\s*<br>")
_MAC = re.compile(r"MAC Addr\s*:\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})")
_VERSION_SUFFIX = re.compile(r"\s+\d{2}\.\d{2}$")


class WebmanError(Exception):
    """webMAN MOD did not answer (console off, or webMAN not running)."""


@dataclass(frozen=True, slots=True)
class WebmanStatus:
    """What ``/cpursx.ps3`` tells about the console."""

    cpu_temperature: int | None = None
    rsx_temperature: int | None = None
    fan_speed: int | None = None
    in_game: bool = False
    title_id: str | None = None
    title: str | None = None
    icon_path: str | None = None
    play_time: int | None = None
    firmware: str | None = None
    mac: str | None = None


def parse_cpursx(page: str) -> WebmanStatus:
    """Parse the HTML of ``/cpursx.ps3``."""

    def number(pattern: re.Pattern[str]) -> int | None:
        match = pattern.search(page)
        return int(match.group(1)) if match else None

    play_time = None
    if match := _PLAY.search(page):
        days, hours, minutes, seconds = match.groups()
        play_time = int(days or 0) * 86400 + int(hours) * 3600 + int(minutes) * 60 + int(seconds)

    title = None
    if match := _TITLE.search(page):
        title = _VERSION_SUFFIX.sub("", html.unescape(match.group(1)).strip()) or None

    firmware = None
    if match := _FIRMWARE.search(page):
        firmware = html.unescape(match.group(1)).split(": ", 1)[-1].strip() or None

    title_id = match.group(1) if (match := _TITLE_ID.search(page)) else None
    icon = _ICON.search(page)
    mac = _MAC.search(page)
    return WebmanStatus(
        cpu_temperature=number(_CPU),
        rsx_temperature=number(_RSX),
        fan_speed=number(_FAN),
        in_game=title_id is not None or play_time is not None,
        title_id=title_id,
        title=title,
        icon_path=html.unescape(icon.group(1)) if icon else None,
        play_time=play_time,
        firmware=firmware,
        mac=mac.group(1).upper() if mac else None,
    )


class WebmanClient:
    """Minimal webMAN MOD client."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int = DEFAULT_PORT,
        *,
        timeout: float = 8.0,
    ) -> None:
        self._session = session
        self.base_url = f"http://{host}" if port == DEFAULT_PORT else f"http://{host}:{port}"
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    def file_url(self, path: str) -> str:
        """Absolute URL of a file served by the console (e.g. a game icon)."""
        return f"{self.base_url}{quote(path)}"

    async def _get(self, path: str, *, tolerate_disconnect: bool = False) -> str:
        url = f"{self.base_url}{path}"
        try:
            async with self._session.get(url, timeout=self._timeout) as response:
                if response.status != 200:
                    raise WebmanError(f"HTTP {response.status} on {path}")
                return (await response.read()).decode("utf-8", "replace")
        except aiohttp.ServerDisconnectedError:
            # Shutdown and restart may drop the connection before answering.
            if tolerate_disconnect:
                return ""
            raise WebmanError(f"disconnected on {path}") from None
        except (aiohttp.ClientError, TimeoutError) as err:
            raise WebmanError(f"{type(err).__name__} on {path}") from err

    async def async_get_status(self) -> WebmanStatus:
        """Full status (temperatures, fan, running game)."""
        return parse_cpursx(await self._get("/cpursx.ps3"))

    async def async_ping(self) -> bool:
        """Cheap reachability test (``/cpursx_ps3`` only holds the temperatures)."""
        try:
            await self._get("/cpursx_ps3")
        except WebmanError:
            return False
        return True

    async def async_notify(self, message: str) -> None:
        """Show a notification on screen."""
        await self._get(f"/popup.ps3?{quote(message, safe='')}")

    async def async_shutdown(self) -> None:
        """Shut down through the system menu (same as the power button)."""
        await self._get("/shutdown.ps3", tolerate_disconnect=True)

    async def async_restart(self) -> None:
        """Restart with webMAN's default mode."""
        await self._get("/restart.ps3", tolerate_disconnect=True)

    async def async_quit_game(self) -> None:
        """Leave the running game and go back to the XMB."""
        await self._get("/xmb.ps3$exit", tolerate_disconnect=True)
