"""Steam account through the official Steam Web API: online status and the game being played.

Needs the account owner's Web API key (https://steamcommunity.com/dev/apikey) and the account,
given as a SteamID64, a profile link or a custom profile name. The game is only reported when
the profile shows its game details publicly. Works for whatever runs Steam: PC, Steam Deck…
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import aiohttp

API_BASE = "https://api.steampowered.com"
KEY_URL = "https://steamcommunity.com/dev/apikey"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_TEXT = 255
_STEAM_ID = re.compile(r"7656119\d{10}")
_PROFILE = re.compile(r"steamcommunity\.com/(profiles|id)/([^/?#\s]+)")
_VANITY = re.compile(r"[A-Za-z0-9_-]{2,32}")
# personastate, in order.
STATUSES = ("offline", "online", "busy", "away", "snooze", "looking_to_trade", "looking_to_play")
_IMAGE = "https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"


class SteamError(Exception):
    """Steam unreachable or unexpected answer (temporary)."""


class SteamAuthError(SteamError):
    """The Web API key is refused."""


class SteamAccountError(SteamError):
    """No Steam account matches what was entered."""


def _text(value: Any) -> str | None:
    return value[:_MAX_TEXT] if isinstance(value, str) and value else None


@dataclass(frozen=True, slots=True)
class SteamStatus:
    steam_id: str
    name: str | None
    status: str  # one of STATUSES
    game: str | None = None
    game_id: str | None = None
    avatar: str | None = None

    @property
    def image(self) -> str | None:
        """Store artwork; none for a non-Steam game added to the library (64-bit ID)."""
        if self.game_id and self.game_id.isdigit() and int(self.game_id) < 2**32:
            return _IMAGE.format(app_id=self.game_id)
        return None


def parse_status(raw: dict[str, Any], steam_id: str) -> SteamStatus:
    players = (raw.get("response") or {}).get("players") or []
    player = next((p for p in players if p.get("steamid") == steam_id), None)
    if not isinstance(player, dict):
        raise SteamAccountError("unknown account")
    state = player.get("personastate")
    known = isinstance(state, int) and 0 <= state < len(STATUSES)
    avatar = player.get("avatarfull")
    game_id = str(player.get("gameid") or "")
    return SteamStatus(
        steam_id=steam_id,
        name=_text(player.get("personaname")),
        status=STATUSES[state] if known else "online",
        game=_text(player.get("gameextrainfo")),
        game_id=game_id if game_id.isdigit() else None,
        avatar=avatar if isinstance(avatar, str) and avatar.startswith("https://") else None,
    )


def account_input(text: str) -> tuple[str | None, str | None]:
    """SteamID64 or custom profile name from what the user typed (ID, profile link, name)."""
    text = text.strip()
    if match := _PROFILE.search(text):
        kind, value = match.groups()
        if kind == "profiles":
            return (value, None) if _STEAM_ID.fullmatch(value) else (None, None)
        text = value
    if _STEAM_ID.fullmatch(text):
        return text, None
    return (None, text) if _VANITY.fullmatch(text) else (None, None)


class SteamClient:
    def __init__(
        self, session: aiohttp.ClientSession, api_key: str, *, api_base: str = API_BASE
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._api_base = api_base

    async def _get(self, path: str, **params: str) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._api_base}{path}",
                params={"key": self._api_key, **params},
                timeout=_TIMEOUT,
            ) as response:
                if response.status in (401, 403):
                    raise SteamAuthError(f"key refused ({response.status})")
                if response.status != 200:
                    raise SteamError(f"Steam answered {response.status}")
                raw = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise SteamError(type(err).__name__) from err  # the URL would show the key
        except ValueError as err:
            raise SteamError("unexpected answer") from err
        if not isinstance(raw, dict):
            raise SteamError("unexpected answer")
        return raw

    async def async_resolve(self, text: str) -> str:
        """The SteamID64 of an account given as an ID, a profile link or a custom name."""
        steam_id, vanity = account_input(text)
        if steam_id:
            return steam_id
        if not vanity:
            raise SteamAccountError("not a Steam account")
        raw = await self._get("/ISteamUser/ResolveVanityURL/v1/", vanityurl=vanity)
        response = raw.get("response") or {}
        if response.get("success") != 1 or not _STEAM_ID.fullmatch(str(response.get("steamid"))):
            raise SteamAccountError("unknown custom profile name")
        return str(response["steamid"])

    async def async_status(self, steam_id: str) -> SteamStatus:
        raw = await self._get("/ISteamUser/GetPlayerSummaries/v2/", steamids=steam_id)
        return parse_status(raw, steam_id)
