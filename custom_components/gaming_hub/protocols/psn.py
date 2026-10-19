"""PlayStation Network account: current game, online status, trophies, PlayStation Plus.

Built into the hub so no other integration is needed. Authentication uses the
NPSSO cookie of the account (https://ca.account.sony.com/api/v1/ssocookie once
signed in on playstation.com), exchanged for OAuth tokens like the PlayStation
App does. Endpoints follow psn-api (MIT, https://github.com/achievements-app/psn-api),
which PS5-MQTT also uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import aiohttp

AUTH_BASE = "https://ca.account.sony.com/api/authz/v3/oauth"
API_BASE = "https://m.np.playstation.com/api/userProfile/v1/internal/users"
LEGACY_BASE = "https://us-prof.np.community.playstation.net/userProfile/v1/users"
NPSSO_URL = "https://ca.account.sony.com/api/v1/ssocookie"

_CLIENT_ID = "09515159-7237-4370-9b40-3806e67c0891"
_BASIC_AUTH = "Basic MDk1MTUxNTktNzIzNy00MzcwLTliNDAtMzgwNmU2N2MwODkxOnVjUGprYTV0bnRCMktxc1A="
_REDIRECT = "com.scee.psxandroid.scecompcall://redirect"
_SCOPE = "psn:mobile.v2.core psn:clientapp"
_PROFILE_FIELDS = (
    "onlineId,accountId,avatarUrls,plus,"
    "trophySummary(@default,level,progress,earnedTrophies),"
    "primaryOnlineStatus,presences(@default,@titleInfo,platform,lastOnlineDate)"
)
_TIMEOUT = aiohttp.ClientTimeout(total=20)


class PsnError(Exception):
    """PlayStation Network unreachable or unexpected answer (temporary)."""


class PsnAuthError(PsnError):
    """The NPSSO token is no longer valid: a new one is needed."""


@dataclass(frozen=True, slots=True)
class PsnSession:
    """What the account plays on one platform."""

    platform: str  # PS5, PS4, PS3, PSVITA
    online: bool
    title: str | None = None
    title_id: str | None = None
    image: str | None = None


@dataclass(frozen=True, slots=True)
class PsnStatus:
    account_id: str
    online_id: str
    online_status: str = "offline"
    avatar_url: str | None = None
    plus: bool = False
    trophy_level: int | None = None
    trophy_progress: int | None = None
    trophies: dict[str, int] = field(default_factory=dict)
    sessions: dict[str, PsnSession] = field(default_factory=dict)


def parse_status(profile: dict[str, Any], presence: dict[str, Any] | None) -> PsnStatus:
    """Combine the legacy profile (PS3/PS4 presence, trophies) and the PS5-era presence."""
    data = profile.get("profile", profile)
    sessions: dict[str, PsnSession] = {}
    # Legacy presence: PS3, PS4 and PS Vita.
    for item in data.get("presences") or []:
        platform = str(item.get("platform", "")).upper()
        if not platform or platform in sessions:
            continue
        sessions[platform] = PsnSession(
            platform=platform,
            online=item.get("onlineStatus") not in (None, "offline"),
            title=item.get("titleName") or None,
            title_id=item.get("npTitleId") or None,
            image=item.get("npTitleIconUrl") or None,
        )
    # Current presence: PS5 (and PS4 when it is the primary platform).
    basic = (presence or {}).get("basicPresence") or {}
    primary = basic.get("primaryPlatformInfo") or {}
    if platform := str(primary.get("platform", "")).upper():
        game = next(iter(basic.get("gameTitleInfoList") or []), {})
        sessions[platform] = PsnSession(
            platform=platform,
            online=primary.get("onlineStatus") == "online",
            title=game.get("titleName") or None,
            title_id=game.get("npTitleId") or None,
            image=game.get("conceptIconUrl") or game.get("npTitleIconUrl") or None,
        )
    trophies = data.get("trophySummary") or {}
    avatars = sorted(
        data.get("avatarUrls") or [], key=lambda a: str(a.get("size", "")), reverse=True
    )

    def as_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    return PsnStatus(
        account_id=str(data.get("accountId", "")),
        online_id=str(data.get("onlineId", "")),
        online_status=str(data.get("primaryOnlineStatus") or "offline"),
        avatar_url=avatars[0].get("avatarUrl") if avatars else None,
        plus=bool(data.get("plus")),
        trophy_level=as_int(trophies.get("level")),
        trophy_progress=as_int(trophies.get("progress")),
        trophies={
            grade: int(count)
            for grade, count in (trophies.get("earnedTrophies") or {}).items()
            if isinstance(count, int)
        },
        sessions=sessions,
    )


class PsnClient:
    """Minimal PlayStation Network client; tokens can be persisted and restored."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        npsso: str,
        tokens: dict[str, Any] | None = None,
        *,
        auth_base: str = AUTH_BASE,
        api_base: str = API_BASE,
        legacy_base: str = LEGACY_BASE,
    ) -> None:
        self._session = session
        self._npsso = npsso.strip()
        self._tokens: dict[str, Any] = dict(tokens or {})
        self._auth_base = auth_base
        self._api_base = api_base
        self._legacy_base = legacy_base
        self.tokens_changed = False

    @property
    def tokens(self) -> dict[str, Any]:
        """Current OAuth tokens, to persist between restarts."""
        return dict(self._tokens)

    async def _request_tokens(self, form: dict[str, str]) -> None:
        try:
            async with self._session.post(
                f"{self._auth_base}/token",
                data=form,
                headers={"Authorization": _BASIC_AUTH},
                timeout=_TIMEOUT,
            ) as response:
                if response.status in (400, 401, 403):
                    raise PsnAuthError(f"token refused ({response.status})")
                if response.status != 200:
                    raise PsnError(f"token endpoint answered {response.status}")
                raw = await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise PsnError(str(err)) from err
        if not isinstance(raw, dict) or not raw.get("access_token"):
            raise PsnError("token endpoint answered without an access token")
        now = time.time()
        self._tokens = {
            "access_token": raw["access_token"],
            "access_expires": now + float(raw.get("expires_in", 3600)),
            "refresh_token": raw.get("refresh_token", self._tokens.get("refresh_token")),
            "refresh_expires": now + float(raw.get("refresh_token_expires_in", 0) or 0),
        }
        self.tokens_changed = True

    async def _authorize(self) -> str:
        """Exchange the NPSSO cookie for an authorization code."""
        params = {
            "access_type": "offline",
            "client_id": _CLIENT_ID,
            "redirect_uri": _REDIRECT,
            "response_type": "code",
            "scope": _SCOPE,
        }
        try:
            async with self._session.get(
                f"{self._auth_base}/authorize",
                params=params,
                headers={"Cookie": f"npsso={self._npsso}"},
                allow_redirects=False,
                timeout=_TIMEOUT,
            ) as response:
                location = response.headers.get("Location", "")
        except aiohttp.ClientError as err:
            raise PsnError(str(err)) from err
        code = parse_qs(urlsplit(location).query).get("code", [None])[0]
        if not code:
            raise PsnAuthError("NPSSO refused")
        return code

    async def _access_token(self) -> str:
        now = time.time()
        if self._tokens.get("access_token") and now < self._tokens.get("access_expires", 0) - 60:
            return self._tokens["access_token"]
        if self._tokens.get("refresh_token") and now < self._tokens.get("refresh_expires", 0):
            try:
                await self._request_tokens(
                    {
                        "refresh_token": self._tokens["refresh_token"],
                        "grant_type": "refresh_token",
                        "token_format": "jwt",
                        "scope": _SCOPE,
                    }
                )
                return self._tokens["access_token"]
            except PsnAuthError:
                self._tokens = {}
        code = await self._authorize()
        await self._request_tokens(
            {
                "code": code,
                "redirect_uri": _REDIRECT,
                "grant_type": "authorization_code",
                "token_format": "jwt",
            }
        )
        return self._tokens["access_token"]

    async def _get(self, url: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        for attempt in range(2):
            token = await self._access_token()
            try:
                async with self._session.get(
                    url,
                    params=params,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=_TIMEOUT,
                ) as response:
                    if response.status == 401 and attempt == 0:
                        self._tokens.pop("access_token", None)
                        continue
                    if response.status >= 400:
                        raise PsnError(f"{url} answered {response.status}")
                    return await response.json(content_type=None)
            except aiohttp.ClientError as err:
                raise PsnError(str(err)) from err
        raise PsnAuthError("access token refused")

    async def async_get_status(self) -> PsnStatus:
        """Profile, trophies and presence of the account (two requests)."""
        profile = await self._get(f"{self._legacy_base}/me/profile2", {"fields": _PROFILE_FIELDS})
        account_id = (profile.get("profile") or {}).get("accountId")
        presence = None
        if account_id:
            presence = await self._get(
                f"{self._api_base}/{account_id}/basicPresences", {"type": "primary"}
            )
        return parse_status(profile, presence)
