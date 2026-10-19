"""PlayStation Network client against a simulated Sony API."""

from __future__ import annotations

import time

import aiohttp
from aiohttp import web
import pytest

from custom_components.gaming_hub.protocols.psn import (
    PsnAuthError,
    PsnClient,
    PsnStatus,
    parse_status,
)

PROFILE = {
    "profile": {
        "onlineId": "Steph66",
        "accountId": "1234567890123456789",
        "avatarUrls": [
            {"size": "s", "avatarUrl": "https://psn/avatar_s.png"},
            {"size": "xl", "avatarUrl": "https://psn/avatar_xl.png"},
        ],
        "plus": 1,
        "trophySummary": {
            "level": 312,
            "progress": 45,
            "earnedTrophies": {"bronze": 1200, "silver": 300, "gold": 80, "platinum": 12},
        },
        "primaryOnlineStatus": "online",
        "presences": [
            {
                "onlineStatus": "online",
                "platform": "PS3",
                "npTitleId": "NPEB01234_00",
                "titleName": "Journey",
            }
        ],
    }
}
PRESENCE = {
    "basicPresence": {
        "availability": "availableToPlay",
        "primaryPlatformInfo": {"onlineStatus": "online", "platform": "PS5"},
        "gameTitleInfoList": [
            {
                "npTitleId": "PPSA01521_00",
                "titleName": "Horizon Forbidden West",
                "format": "PS5",
                "launchPlatform": "PS5",
                "conceptIconUrl": "https://image.api.playstation.com/horizon.png",
            }
        ],
    }
}


def test_parse_status() -> None:
    status = parse_status(PROFILE, PRESENCE)
    assert (status.online_id, status.account_id, status.plus) == (
        "Steph66",
        "1234567890123456789",
        True,
    )
    assert status.avatar_url == "https://psn/avatar_xl.png"
    assert (status.trophy_level, status.trophy_progress) == (312, 45)
    assert status.trophies == {"bronze": 1200, "silver": 300, "gold": 80, "platinum": 12}
    ps5 = status.sessions["PS5"]
    assert (ps5.online, ps5.title, ps5.title_id) == (True, "Horizon Forbidden West", "PPSA01521_00")
    assert ps5.image == "https://image.api.playstation.com/horizon.png"
    assert status.sessions["PS3"].title == "Journey"
    # Playing on a PS5: the legacy profile says offline, the current presence is right.
    legacy_offline = {"profile": {**PROFILE["profile"], "primaryOnlineStatus": "offline"}}
    assert parse_status(legacy_offline, PRESENCE).online_status == "online"
    assert parse_status(legacy_offline, None).online_status == "offline"
    offline = parse_status({"profile": {"accountId": "1"}}, None)
    assert offline == PsnStatus(account_id="1", online_id="")


class FakeSony:
    """Sony OAuth and profile endpoints, with a valid NPSSO and expiring tokens."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.npsso = "good-npsso"
        self.issued = 0

    async def authorize(self, request: web.Request) -> web.Response:
        self.calls.append("authorize")
        cookie = request.headers.get("Cookie", "")
        query = "code=v3.CODE&cid=1" if cookie == f"npsso={self.npsso}" else "error=login_required"
        return web.Response(
            status=302,
            headers={"Location": f"com.scee.psxandroid.scecompcall://redirect/?{query}"},
        )

    async def token(self, request: web.Request) -> web.Response:
        form = await request.post()
        self.calls.append(f"token:{form['grant_type']}")
        assert request.headers["Authorization"].startswith("Basic ")
        if form["grant_type"] == "refresh_token" and form["refresh_token"] != "refresh-1":
            return web.json_response({"error": "invalid_grant"}, status=400)
        self.issued += 1
        return web.json_response(
            {
                "access_token": f"access-{self.issued}",
                "expires_in": 3600,
                "refresh_token": f"refresh-{self.issued}",
                "refresh_token_expires_in": 5184000,
            }
        )

    def _authorized(self, request: web.Request) -> bool:
        return request.headers.get("Authorization", "").startswith("Bearer access-")

    async def profile(self, request: web.Request) -> web.Response:
        self.calls.append("profile")
        if not self._authorized(request):
            return web.json_response({}, status=401)
        assert "trophySummary" in request.query["fields"]
        return web.json_response(PROFILE)

    async def presence(self, request: web.Request) -> web.Response:
        self.calls.append(f"presence:{request.match_info['account']}")
        if not self._authorized(request):
            return web.json_response({}, status=401)
        return web.json_response(PRESENCE)


@pytest.fixture
async def sony(socket_enabled):
    fake = FakeSony()
    app = web.Application()
    app.router.add_get("/oauth/authorize", fake.authorize)
    app.router.add_post("/oauth/token", fake.token)
    app.router.add_get("/legacy/me/profile2", fake.profile)
    app.router.add_get("/users/{account}/basicPresences", fake.presence)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    async with aiohttp.ClientSession() as session:
        yield (
            fake,
            session,
            {
                "auth_base": f"{base}/oauth",
                "api_base": f"{base}/users",
                "legacy_base": f"{base}/legacy",
            },
        )
    await runner.cleanup()


async def test_npsso_login_then_status(sony) -> None:
    fake, session, urls = sony
    client = PsnClient(session, " good-npsso ", **urls)
    status = await client.async_get_status()
    assert status.sessions["PS5"].title == "Horizon Forbidden West"
    assert fake.calls == [
        "authorize",
        "token:authorization_code",
        "profile",
        "presence:1234567890123456789",
    ]
    assert client.tokens_changed and client.tokens["refresh_token"] == "refresh-1"
    # The access token is reused while valid.
    fake.calls.clear()
    await client.async_get_status()
    assert fake.calls == ["profile", "presence:1234567890123456789"]


async def test_restored_tokens_are_refreshed(sony) -> None:
    fake, session, urls = sony
    tokens = {
        "access_token": "expired",
        "access_expires": time.time() - 10,
        "refresh_token": "refresh-1",
        "refresh_expires": time.time() + 3600,
    }
    client = PsnClient(session, "good-npsso", tokens, **urls)
    await client.async_get_status()
    assert fake.calls[0] == "token:refresh_token"
    assert "authorize" not in fake.calls


async def test_refused_refresh_falls_back_to_npsso(sony) -> None:
    fake, session, urls = sony
    tokens = {"refresh_token": "revoked", "refresh_expires": time.time() + 3600}
    client = PsnClient(session, "good-npsso", tokens, **urls)
    await client.async_get_status()
    assert fake.calls[:3] == ["token:refresh_token", "authorize", "token:authorization_code"]


async def test_expired_npsso(sony) -> None:
    _, session, urls = sony
    client = PsnClient(session, "expired-npsso", **urls)
    with pytest.raises(PsnAuthError):
        await client.async_get_status()


async def test_rejected_access_token_is_renewed_once(sony) -> None:
    fake, session, urls = sony
    tokens = {"access_token": "revoked", "access_expires": time.time() + 3600}
    client = PsnClient(session, "good-npsso", tokens, **urls)
    status = await client.async_get_status()
    assert status.online_id == "Steph66"
    assert fake.calls[:3] == ["profile", "authorize", "token:authorization_code"]
