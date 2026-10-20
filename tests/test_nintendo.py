"""Nintendo Switch and Switch 2 through the Nintendo account, without modifying the console."""

from __future__ import annotations

import base64
from datetime import date
import hashlib
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

import aiohttp
from aiohttp import web
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_hub.const import DOMAIN
from custom_components.gaming_hub.protocols.nintendo import (
    GameTime,
    NintendoAuthError,
    NintendoClient,
    NintendoDevice,
    NintendoError,
    PlayDay,
    async_session_token,
    login,
    parse_daily_summaries,
    session_token_code,
)

from .test_entities import _setup, _tick

DEVICE_ID = "567D0B5EA9582FB7"
MARIO_KART = "0100152000022000"
ZELDA = "01007EF00011E000"
CLIENT = "custom_components.gaming_hub.protocols.nintendo.NintendoClient"


def _summary(day: str, games: dict[str, tuple[str | None, int]], **players: int) -> dict:
    """A daily summary as Nintendo sends it; a game without name is a Switch 2 one."""
    played = [
        {
            "meta": {
                "applicationId": title_id,
                "title": title,
                "imageUri": {"large": f"https://img/{title_id}"},
            },
            "playingTime": minutes,
        }
        if title
        else {"applicationId": title_id, "playingTime": minutes}
        for title_id, (title, minutes) in games.items()
    ]
    return {
        "date": day,
        "playingTime": sum(minutes for _, minutes in games.values()),
        "players": [
            {
                "profile": {"nickname": nickname},
                "playingTime": minutes,
                "playedGames": played if i == 0 else [],
            }
            for i, (nickname, minutes) in enumerate(players.items())
        ],
    }


# --- Protocol ----------------------------------------------------------------


def test_login_link_and_pasted_link() -> None:
    start = login()
    query = parse_qs(urlsplit(start.url).query)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(start.verifier.encode()).digest())
    assert query["session_token_code_challenge"] == [challenge.decode().rstrip("=")]
    assert query["redirect_uri"] == ["npf54789befb391a838://auth"]
    assert "moonDailySummary" in query["scope"][0]

    link = "npf54789befb391a838://auth#session_state=x&session_token_code=CODE&state=y"
    assert session_token_code(f"  {link} ") == "CODE"
    for wrong in (
        "https://example.com/#session_token_code=CODE",
        "npf54789befb391a838://auth#state=y",
        "",
    ):
        with pytest.raises(NintendoAuthError):
            session_token_code(wrong)


def test_daily_summaries() -> None:
    raw = {
        "dailySummaries": [
            _summary(
                "2026-10-21",
                {MARIO_KART: ("Mario Kart 8 Deluxe", 30), ZELDA: (None, 15)},
                Lea=40,
                Tom=5,
            ),
            {"date": "not a date"},
            _summary("2026-10-20", {}),
        ]
    }
    today, yesterday = parse_daily_summaries(raw)
    assert (today.day, today.minutes, today.players) == (
        date(2026, 10, 21),
        45,
        {"Lea": 40, "Tom": 5},
    )
    assert today.games[MARIO_KART] == GameTime(
        MARIO_KART, "Mario Kart 8 Deluxe", f"https://img/{MARIO_KART}", 30
    )
    assert today.games[ZELDA] == GameTime(ZELDA, None, None, 15)  # named from the console's list
    assert (yesterday.minutes, yesterday.games) == (0, {})


class FakeNintendo:
    """Nintendo account and Parental Controls API, as far as the hub uses them."""

    def __init__(self) -> None:
        self.verifier = ""
        self.session_tokens = {"SESSION"}
        self.id_tokens: set[str] = set()
        self.issued = 0
        self.summaries = [_summary("2026-10-21", {MARIO_KART: ("Mario Kart 8 Deluxe", 30)}, Lea=30)]

    async def session_token(self, request: web.Request) -> web.Response:
        form = await request.post()
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(str(form["session_token_code_verifier"]).encode()).digest()
        )
        if form["session_token_code"] != "CODE" or challenge.decode().rstrip("=") != self.verifier:
            return web.json_response({"error": "invalid_grant"}, status=400)
        return web.json_response({"session_token": "SESSION", "code": "CODE"})

    async def token(self, request: web.Request) -> web.Response:
        body = await request.json()
        if body["session_token"] not in self.session_tokens:
            return web.json_response({"error": "invalid_grant"}, status=400)
        self.issued += 1
        token = f"ID{self.issued}"
        self.id_tokens.add(token)
        return web.json_response({"id_token": token, "access_token": "x", "expires_in": 900})

    def _check(self, request: web.Request) -> None:
        assert request.headers["X-Moon-App-Id"] == "com.nintendo.znma"
        if request.headers["Authorization"].removeprefix("Bearer ") not in self.id_tokens:
            raise web.HTTPUnauthorized

    async def devices(self, request: web.Request) -> web.Response:
        self._check(request)
        device = {"platformGeneration": "P01", "firmwareVersion": {"displayedVersion": "21.0.1"}}
        return web.json_response(
            {
                "ownedDevices": [
                    {"deviceId": DEVICE_ID, "label": "Salon", "device": device},
                    {"deviceId": "bad"},
                ]
            }
        )

    async def daily(self, request: web.Request) -> web.Response:
        self._check(request)
        assert request.query["deviceId"] == DEVICE_ID
        return web.json_response({"dailySummaries": self.summaries})

    async def setting(self, request: web.Request) -> web.Response:
        self._check(request)
        apps = [{"applicationId": ZELDA, "title": "Zelda", "imageUri": "https://img/zelda"}]
        return web.json_response({"parentalControlSetting": {"whitelistedApplicationList": apps}})


@pytest.fixture
async def nintendo(socket_enabled):
    fake = FakeNintendo()
    app = web.Application()
    app.router.add_post("/connect/api/session_token", fake.session_token)
    app.router.add_post("/connect/api/token", fake.token)
    app.router.add_get("/moon/v2/actions/user/fetchOwnedDevices", fake.devices)
    app.router.add_get("/moon/v2/actions/playSummary/fetchDailySummaries", fake.daily)
    app.router.add_get(
        "/moon/v2/actions/parentalControlSetting/fetchParentalControlSetting", fake.setting
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    async with aiohttp.ClientSession() as session:
        yield fake, session, {"accounts_base": f"{base}/connect", "api_base": f"{base}/moon"}
    await runner.cleanup()


async def test_sign_in_then_read(nintendo) -> None:
    fake, session, bases = nintendo
    start = login(accounts_base=bases["accounts_base"])
    fake.verifier = parse_qs(urlsplit(start.url).query)["session_token_code_challenge"][0]
    with pytest.raises(NintendoAuthError):
        await async_session_token(
            session,
            "npf54789befb391a838://auth#session_token_code=OLD",
            start.verifier,
            accounts_base=bases["accounts_base"],
        )
    link = "npf54789befb391a838://auth#session_token_code=CODE&state=x"
    token = await async_session_token(
        session, link, start.verifier, accounts_base=bases["accounts_base"]
    )

    client = NintendoClient(session, token, time_zone="Europe/Paris", language="fr-FR", **bases)
    assert await client.async_devices() == [
        NintendoDevice(DEVICE_ID, "Salon", "Switch 2", "21.0.1")
    ]
    (today,) = await client.async_play_days(DEVICE_ID)
    assert today.games[MARIO_KART].minutes == 30
    assert (await client.async_titles(DEVICE_ID))[ZELDA].title == "Zelda"
    assert fake.issued == 1  # the id token is reused

    fake.id_tokens.clear()  # expired early: renewed once from the session token
    await client.async_play_days(DEVICE_ID)
    assert fake.issued == 2

    fake.session_tokens.clear()  # signed out from the Nintendo account
    fake.id_tokens.clear()
    with pytest.raises(NintendoAuthError):
        await client.async_play_days(DEVICE_ID)


# --- In Home Assistant ---------------------------------------------------------


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Switch",
        unique_id=f"nintendo_{DEVICE_ID}",
        data={
            "kind": "nintendo",
            "session_token": "SESSION",
            "device_id": DEVICE_ID,
            "model": "Switch 2",
            "name": "Switch",
        },
    )


class Account:
    """What the Nintendo account answers, changed by the tests."""

    def __init__(self) -> None:
        self.days = [
            PlayDay(
                date(2026, 10, 21),
                30,
                {MARIO_KART: GameTime(MARIO_KART, "Mario Kart 8 Deluxe", "https://img/mk", 30)},
                {"Lea": 30},
            ),
            PlayDay(date(2026, 10, 19), 60, {}),  # Monday, same week
            PlayDay(date(2026, 10, 12), 120, {}),  # previous week, same month
            PlayDay(date(2026, 9, 30), 90, {}),  # previous month
        ]
        self.calls = 0

    def play(self, title_id: str, title: str | None, minutes: float) -> None:
        today = self.days[0]
        games = dict(today.games)
        before = games[title_id].minutes if title_id in games else 0
        games[title_id] = GameTime(title_id, title, None, before + minutes)
        self.days[0] = PlayDay(today.day, today.minutes + minutes, games, today.players)

    async def play_days(self, device_id: str) -> list[PlayDay]:
        assert device_id == DEVICE_ID
        self.calls += 1
        return list(self.days)

    def patches(self):
        return (
            patch(f"{CLIENT}.async_play_days", AsyncMock(side_effect=self.play_days)),
            patch(
                f"{CLIENT}.async_devices",
                AsyncMock(return_value=[NintendoDevice(DEVICE_ID, "Salon", "Switch 2", "21.0.1")]),
            ),
            patch(
                f"{CLIENT}.async_titles",
                AsyncMock(return_value={ZELDA: GameTime(ZELDA, "Zelda", "https://img/zelda", 0)}),
            ),
        )


@pytest.fixture
def account():
    account = Account()
    days, devices, titles = account.patches()
    with days, devices, titles:
        yield account


PLAYER = "media_player.switch"


async def test_game_and_official_play_time(
    hass: HomeAssistant, account: Account, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-10-21 20:00:00-07:00")  # Wednesday, Home Assistant's time zone
    entry = _entry()
    await _setup(hass, entry)

    device = dr.async_get(hass).async_get_device({(DOMAIN, entry.entry_id)})
    assert (device.manufacturer, device.model) == ("Nintendo", "Switch 2")
    assert hass.states.get(PLAYER).state == "off"  # earlier play is not a current game
    assert hass.states.get("sensor.switch_system_version").state == "21.0.1"
    # Play time counted by Nintendo: today, the week (Monday on) and the month.
    today = hass.states.get("sensor.switch_play_time_today")
    assert float(today.state) == 30
    assert today.attributes["games"] == {"Mario Kart 8 Deluxe": 30}
    assert today.attributes["players"] == {"Lea": 30}
    assert float(hass.states.get("sensor.switch_play_time_this_week").state) == 1.5
    assert float(hass.states.get("sensor.switch_play_time_this_month").state) == 3.5

    # Minutes added: on, with the game (a Switch 2 one, named from the console's list).
    account.play(ZELDA, None, 5)
    await _tick(hass, freezer, 61)
    state = hass.states.get(PLAYER)
    assert (state.state, state.attributes["media_title"]) == ("playing", "Zelda")
    assert float(hass.states.get("sensor.switch_play_time_today").state) == 35

    # Another game later on.
    account.play(MARIO_KART, "Mario Kart 8 Deluxe", 2)
    await _tick(hass, freezer, 61)
    assert hass.states.get(PLAYER).attributes["media_title"] == "Mario Kart 8 Deluxe"

    # Nothing added for 30 minutes: off.
    for _ in range(31):
        await _tick(hass, freezer, 61)
    assert hass.states.get(PLAYER).state == "off"


async def test_today_not_reported_yet(
    hass: HomeAssistant, account: Account, freezer: FrozenDateTimeFactory
) -> None:
    """Nintendo leaves today out until the console reports: no time today, the week stays."""
    freezer.move_to("2026-10-22 08:00:00-07:00")
    await _setup(hass, _entry())
    assert float(hass.states.get("sensor.switch_play_time_today").state) == 0
    assert float(hass.states.get("sensor.switch_play_time_this_week").state) == 1.5


async def test_nintendo_unreachable(
    hass: HomeAssistant, account: Account, freezer: FrozenDateTimeFactory
) -> None:
    """Retried until a first answer, then the last known data stays."""
    freezer.move_to("2026-10-21 20:00:00-07:00")
    entry = _entry()
    with patch(f"{CLIENT}.async_play_days", AsyncMock(side_effect=NintendoError("down"))):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    with patch(f"{CLIENT}.async_play_days", AsyncMock(side_effect=NintendoError("down"))):
        await _tick(hass, freezer, 61)
    assert float(hass.states.get("sensor.switch_play_time_today").state) == 30


async def test_signed_out_asks_to_sign_in_again(hass: HomeAssistant, account: Account) -> None:
    entry = _entry()
    with patch(f"{CLIENT}.async_play_days", AsyncMock(side_effect=NintendoAuthError("400"))):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["step_id"] == "nintendo_reauth"


# --- Configuration -------------------------------------------------------------

SETUP = "custom_components.gaming_hub.async_setup_entry"
SESSION = "custom_components.gaming_hub.protocols.nintendo.async_session_token"
LINK = "npf54789befb391a838://auth#session_token_code=CODE"
CONSOLES = [
    NintendoDevice(DEVICE_ID, "Salon", "Switch 2", "21.0.1"),
    NintendoDevice("0123456789ABCDEF", "Chambre", "Switch", "20.1.0"),
]


async def test_add_a_console_from_the_nintendo_account(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "nintendo"}
    )
    assert result["step_id"] == "nintendo"
    assert result["description_placeholders"]["login_url"].startswith(
        "https://accounts.nintendo.com/"
    )

    with patch(SESSION, AsyncMock(side_effect=NintendoAuthError("used"))):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"link": LINK})
    assert result["errors"] == {"base": "invalid_link"}

    with (
        patch(SESSION, AsyncMock(return_value="SESSION")),
        patch(f"{CLIENT}.async_devices", AsyncMock(return_value=CONSOLES)),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"link": LINK})
    assert result["step_id"] == "nintendo_console"  # several consoles on the account
    with patch(SETUP, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"device_id": DEVICE_ID}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Salon"
    assert result["data"] == {
        "kind": "nintendo",
        "session_token": "SESSION",
        "device_id": DEVICE_ID,
        "model": "Switch 2",
        "name": "Salon",
    }
    assert result["result"].unique_id == f"nintendo_{DEVICE_ID}"


async def test_account_without_console(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "nintendo"}
    )
    with (
        patch(SESSION, AsyncMock(return_value="SESSION")),
        patch(f"{CLIENT}.async_devices", AsyncMock(return_value=[])),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"link": LINK})
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "no_nintendo_console")


async def test_sign_in_again(hass: HomeAssistant) -> None:
    entry = _entry()
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "nintendo_reauth"
    with (
        patch(SESSION, AsyncMock(return_value="NEW")),
        patch(f"{CLIENT}.async_devices", AsyncMock(return_value=CONSOLES[1:])),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"link": LINK})
    assert result["errors"] == {"base": "nintendo_console_missing"}  # another account
    with (
        patch(SESSION, AsyncMock(return_value="NEW")),
        patch(f"{CLIENT}.async_devices", AsyncMock(return_value=CONSOLES)),
        patch(SETUP, AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"link": LINK})
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "reauth_successful")
    assert entry.data["session_token"] == "NEW"
