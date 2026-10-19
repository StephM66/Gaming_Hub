"""Nintendo Switch and Switch 2 through the Nintendo account: games and play time, no modification.

The console reports its play activity to Nintendo, which the "Nintendo Switch Parental
Controls" app shows; this client reads the same data. Sign-in is the app's own: open the
login link, sign in, copy the link of the "Select this person" button and paste it. Client
ID, endpoints and headers follow pynintendoauth and pynintendoparental (MIT,
https://github.com/pantherale0), used by Home Assistant's nintendo_parental_controls.

Read only. Nintendo gives no live power state and no way to turn a console on or off.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from datetime import date
import hashlib
import re
import secrets
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

import aiohttp

CLIENT_ID = "54789befb391a838"
ACCOUNTS_BASE = "https://accounts.nintendo.com/connect/1.0.0"
API_BASE = "https://app.lp1.znma.srv.nintendo.net"
_REDIRECT = f"npf{CLIENT_ID}://auth"
_SCOPES = (
    "openid user moonUser:administration moonDevice:create moonOwnedDevice:administration "
    "moonParentalControlSetting moonParentalControlSetting:update "
    "moonParentalControlSettingState moonPairingState moonSmartDevice:administration "
    "moonDailySummary moonMonthlySummary"
)
_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer-session-token"
_APP_VERSION, _APP_BUILD = "2.4.0", "660"
_USER_AGENT = f"moon_ANDROID/{_APP_VERSION} (com.nintendo.znma; build:{_APP_BUILD}; ANDROID 34)"
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_TEXT = 255
_DEVICE_ID = re.compile(r"[0-9A-Fa-f]{16}")
MODELS = {"P00": "Switch", "P01": "Switch 2"}


class NintendoError(Exception):
    """Nintendo unreachable or unexpected answer (temporary)."""


class NintendoAuthError(NintendoError):
    """The link or the session is no longer valid: sign in again."""


def _text(value: Any) -> str | None:
    return value[:_MAX_TEXT] if isinstance(value, str) and value else None


def _image(value: Any) -> str | None:
    """Artwork URL (HTTPS only); the API gives either a URL or one URL per size."""
    if isinstance(value, dict):
        value = value.get("large") or value.get("medium") or value.get("small")
    return value if isinstance(value, str) and value.startswith("https://") else None


def _minutes(value: Any) -> float:
    return float(value) if isinstance(value, int | float) and value > 0 else 0.0


@dataclass(frozen=True, slots=True)
class NintendoLogin:
    """Link to open, and the secret that goes with it until the pasted link comes back."""

    url: str
    verifier: str


def login(*, accounts_base: str = ACCOUNTS_BASE) -> NintendoLogin:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    query = {
        "client_id": CLIENT_ID,
        "redirect_uri": _REDIRECT,
        "response_type": "session_token_code",
        "scope": _SCOPES,
        "session_token_code_challenge": challenge.decode().rstrip("="),
        "session_token_code_challenge_method": "S256",
        "state": secrets.token_urlsafe(32),
        "theme": "login_form",
    }
    return NintendoLogin(f"{accounts_base}/authorize?{urlencode(query)}", verifier)


def session_token_code(link: str) -> str:
    """The code carried by the pasted "Select this person" link."""
    parts = urlsplit(link.strip())
    codes = parse_qs(parts.fragment).get("session_token_code")
    if not parts.scheme.startswith("npf") or not codes or not codes[0]:
        raise NintendoAuthError("not a Nintendo account selection link")
    return codes[0]


async def async_session_token(
    session: aiohttp.ClientSession,
    link: str,
    verifier: str,
    *,
    accounts_base: str = ACCOUNTS_BASE,
) -> str:
    """Exchange the pasted link for a long-lived session token."""
    form = {
        "client_id": CLIENT_ID,
        "session_token_code": session_token_code(link),
        "session_token_code_verifier": verifier,
    }
    try:
        async with session.post(
            f"{accounts_base}/api/session_token", data=form, timeout=_TIMEOUT
        ) as response:
            if response.status in (400, 401, 403):
                raise NintendoAuthError(f"link refused ({response.status})")
            if response.status != 200:
                raise NintendoError(f"session token endpoint answered {response.status}")
            raw = await response.json(content_type=None)
    except aiohttp.ClientError as err:
        raise NintendoError(str(err)) from err
    if not isinstance(raw, dict) or not isinstance(token := raw.get("session_token"), str):
        raise NintendoError("no session token in the answer")
    return token


@dataclass(frozen=True, slots=True)
class NintendoDevice:
    device_id: str
    name: str
    model: str  # Switch, Switch 2
    system_version: str | None = None


@dataclass(frozen=True, slots=True)
class GameTime:
    title_id: str
    title: str | None
    image: str | None
    minutes: float


@dataclass(frozen=True, slots=True)
class PlayDay:
    day: date
    minutes: float
    games: dict[str, GameTime] = field(default_factory=dict)  # by title ID, all players
    players: dict[str, float] = field(default_factory=dict)  # nickname: minutes


def parse_devices(raw: dict[str, Any]) -> list[NintendoDevice]:
    devices = []
    for owned in raw.get("ownedDevices") or []:
        if not isinstance(owned, dict) or not _DEVICE_ID.fullmatch(str(owned.get("deviceId"))):
            continue
        device = owned.get("device") or {}
        devices.append(
            NintendoDevice(
                device_id=owned["deviceId"],
                name=_text(owned.get("label")) or "Nintendo Switch",
                model=MODELS.get(device.get("platformGeneration"), "Switch"),
                system_version=_text((device.get("firmwareVersion") or {}).get("displayedVersion")),
            )
        )
    return devices


def parse_titles(raw: dict[str, Any]) -> dict[str, GameTime]:
    """Names and artwork of the games known to the console (parental control setting)."""
    setting = raw.get("parentalControlSetting") or {}
    return {
        app["applicationId"]: GameTime(
            app["applicationId"], _text(app.get("title")), _image(app.get("imageUri")), 0.0
        )
        for app in setting.get("whitelistedApplicationList") or []
        if isinstance(app, dict) and isinstance(app.get("applicationId"), str)
    }


def parse_daily_summaries(raw: dict[str, Any]) -> list[PlayDay]:
    """One entry per day, most recent first, games summed over the console's players.

    Switch 2 summaries may leave out the game's name: see ``parse_titles``.
    """
    days = []
    for summary in raw.get("dailySummaries") or []:
        try:
            day = date.fromisoformat(summary["date"])
        except (KeyError, TypeError, ValueError):
            continue
        games: dict[str, GameTime] = {}
        players: dict[str, float] = {}
        for player in summary.get("players") or []:
            nickname = _text((player.get("profile") or {}).get("nickname"))
            if nickname:
                players[nickname] = players.get(nickname, 0.0) + _minutes(player.get("playingTime"))
            for played in player.get("playedGames") or []:
                meta = played.get("meta") or {}
                title_id = played.get("applicationId") or meta.get("applicationId")
                if not isinstance(title_id, str):
                    continue
                previous = games.get(title_id)
                games[title_id] = GameTime(
                    title_id,
                    _text(meta.get("title")) or (previous.title if previous else None),
                    _image(meta.get("imageUri")) or (previous.image if previous else None),
                    (previous.minutes if previous else 0.0) + _minutes(played.get("playingTime")),
                )
        days.append(PlayDay(day, _minutes(summary.get("playingTime")), games, players))
    return days


class NintendoClient:
    """Read-only client of the Parental Controls API for one Nintendo account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        session_token: str,
        *,
        time_zone: str = "UTC",
        language: str = "en-GB",
        accounts_base: str = ACCOUNTS_BASE,
        api_base: str = API_BASE,
    ) -> None:
        self._session = session
        self._session_token = session_token
        self._time_zone = time_zone
        self._language = language
        self._accounts_base = accounts_base
        self._api_base = api_base
        self._id_token: str | None = None
        self._expires = 0.0

    async def _token(self) -> str:
        if self._id_token and time.time() < self._expires - 60:
            return self._id_token
        body = {"client_id": CLIENT_ID, "grant_type": _GRANT, "session_token": self._session_token}
        try:
            async with self._session.post(
                f"{self._accounts_base}/api/token", json=body, timeout=_TIMEOUT
            ) as response:
                if response.status in (400, 401, 403):
                    raise NintendoAuthError(f"session refused ({response.status})")
                if response.status != 200:
                    raise NintendoError(f"token endpoint answered {response.status}")
                raw = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise NintendoError(str(err)) from err
        if not isinstance(raw, dict) or not isinstance(token := raw.get("id_token"), str):
            raise NintendoError("no id token in the answer")
        self._id_token = token
        self._expires = time.time() + float(raw.get("expires_in", 900))
        return token

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "User-Agent": _USER_AGENT,
            "X-Moon-App-Id": "com.nintendo.znma",
            "X-Moon-Os": "ANDROID",
            "X-Moon-Os-Version": "34",
            "X-Moon-Model": "Pixel 4 XL",
            "X-Moon-App-Display-Version": _APP_VERSION,
            "X-Moon-App-Internal-Version": _APP_BUILD,
            "X-Moon-TimeZone": self._time_zone,
            "X-Moon-Os-Language": self._language,
            "X-Moon-App-Language": self._language,
            "Authorization": f"Bearer {token}",
        }

    async def _get(self, path: str, **params: str) -> dict[str, Any]:
        for attempt in range(2):
            token = await self._token()
            try:
                async with self._session.get(
                    f"{self._api_base}{path}",
                    params=params or None,
                    headers=self._headers(token),
                    timeout=_TIMEOUT,
                ) as response:
                    if response.status == 401 and attempt == 0:
                        self._id_token = None  # renewed once from the session token
                        continue
                    if response.status in (401, 403):
                        raise NintendoAuthError(f"Nintendo answered {response.status}")
                    if response.status >= 400:
                        raise NintendoError(f"Nintendo answered {response.status}")
                    raw = await response.json(content_type=None)
            except aiohttp.ClientError as err:
                raise NintendoError(str(err)) from err
            if not isinstance(raw, dict):
                raise NintendoError("unexpected answer")
            return raw
        raise NintendoAuthError("access refused")

    async def async_devices(self) -> list[NintendoDevice]:
        return parse_devices(await self._get("/v2/actions/user/fetchOwnedDevices"))

    async def async_titles(self, device_id: str) -> dict[str, GameTime]:
        return parse_titles(
            await self._get(
                "/v2/actions/parentalControlSetting/fetchParentalControlSetting",
                deviceId=device_id,
            )
        )

    async def async_play_days(self, device_id: str) -> list[PlayDay]:
        """The last 31 days of the console, most recent first."""
        raw = await self._get("/v2/actions/playSummary/fetchDailySummaries", deviceId=device_id)
        return parse_daily_summaries(raw)
