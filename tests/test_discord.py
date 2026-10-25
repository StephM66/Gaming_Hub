"""PC games of any launcher through the Discord account (the player's own bot)."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.gaming_hub.const import DOMAIN
from custom_components.gaming_hub.protocols.discord import (
    DiscordAuthError,
    DiscordClient,
    DiscordGateway,
    DiscordIntentError,
    DiscordStatus,
    DiscordUserError,
    parse_presence,
)

from .test_entities import _setup

PLAYER = "123456789012345678"
OTHER = "223456789012345678"
GUILD = "323456789012345678"
WOW = "423456789012345678"  # Discord application of the game
CHECK = "custom_components.gaming_hub.protocols.discord.DiscordClient.async_check"


def presence(user: str = PLAYER, status: str = "online", *activities: dict) -> dict:
    return {
        "user": {"id": user},
        "guild_id": GUILD,
        "status": status,
        "activities": list(activities),
        "client_status": {"desktop": status} if status != "offline" else {},
    }


def playing(name: str = "World of Warcraft Classic", **extra) -> dict:
    return {"name": name, "type": 0, "application_id": WOW, "created_at": 1} | extra


def test_presence() -> None:
    assert parse_presence(None) == DiscordStatus()
    music = {"name": "Spotify", "type": 2}
    custom = {"name": "Custom Status", "type": 4, "state": "afk"}
    assert parse_presence(presence(PLAYER, "idle", music, custom)) == DiscordStatus("idle", True)
    status = parse_presence(
        presence(
            PLAYER,
            "dnd",
            music,
            playing(
                timestamps={"start": 1_790_000_000_000},
                assets={"large_image": "523456789012345678"},
            ),
        )
    )
    assert (status.status, status.game, status.game_id) == ("dnd", "World of Warcraft Classic", WOW)
    assert status.started.timestamp() == 1_790_000_000
    assert status.image == f"https://cdn.discordapp.com/app-assets/{WOW}/523456789012345678.png"
    external = playing(assets={"large_image": "mp:external/abc/https/example.com/a.png"})
    assert parse_presence(presence(PLAYER, "online", external)).image == (
        "https://media.discordapp.net/external/abc/https/example.com/a.png"
    )
    # Only on a phone: Discord is not open on the computer.
    phone = presence(PLAYER) | {"client_status": {"mobile": "online"}}
    assert parse_presence(phone) == DiscordStatus("online", False)
    # Anything can come in a presence, says Discord.
    assert parse_presence({"status": 3, "activities": "x", "client_status": []}) == DiscordStatus()


class FakeDiscord:
    """Discord's REST API and Gateway, enough for one bot in one server."""

    def __init__(self) -> None:
        self.flags = 1 << 13  # Presence Intent on (bot in under 100 servers)
        self.members = {PLAYER}
        self.sent: asyncio.Queue[dict] = asyncio.Queue()  # what the bot sends
        self.to_send: asyncio.Queue[dict | int] = asyncio.Queue()  # payloads, or a close code
        self.base = ""
        self.heartbeat = 41250  # milliseconds

    def _check(self, request: web.Request) -> None:
        if request.headers.get("Authorization") != "Bot TOKEN":
            raise web.HTTPUnauthorized

    async def application(self, request: web.Request) -> web.Response:
        self._check(request)
        return web.json_response({"id": "1", "flags": self.flags})

    async def user(self, request: web.Request) -> web.Response:
        self._check(request)
        if request.match_info["id"] not in (PLAYER, OTHER):
            raise web.HTTPNotFound
        return web.json_response(
            {"id": request.match_info["id"], "username": "steph", "global_name": "Steph"}
        )

    async def guilds(self, request: web.Request) -> web.Response:
        self._check(request)
        return web.json_response([{"id": GUILD, "name": "Maison"}])

    async def member(self, request: web.Request) -> web.Response:
        self._check(request)
        if request.match_info["user"] not in self.members:
            raise web.HTTPNotFound
        return web.json_response({"user": {"id": request.match_info["user"]}})

    async def gateway(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"op": 10, "d": {"heartbeat_interval": self.heartbeat}})

        async def receive() -> None:
            async for message in ws:
                payload = message.json()
                if payload["op"] == 1:
                    await ws.send_json({"op": 11})
                else:
                    await self.sent.put(payload)

        async def send() -> None:
            while True:
                item = await self.to_send.get()
                if isinstance(item, int):
                    await ws.close(code=item)
                    return
                await ws.send_json(item)

        # Until either side closes: a closed connection must not take what the next one sends.
        tasks = {asyncio.create_task(receive()), asyncio.create_task(send())}
        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        return ws

    def ready(self, *presences: dict) -> None:
        self.to_send.put_nowait(
            {
                "op": 0,
                "s": 1,
                "t": "READY",
                "d": {
                    "session_id": "S1",
                    "resume_gateway_url": self.base.replace("http", "ws") + "/resume",
                    "guilds": [{"id": GUILD, "unavailable": True}],
                },
            }
        )
        self.to_send.put_nowait(
            {"op": 0, "s": 2, "t": "GUILD_CREATE", "d": {"id": GUILD, "presences": list(presences)}}
        )

    def update(self, data: dict, seq: int = 3) -> None:
        self.to_send.put_nowait({"op": 0, "s": seq, "t": "PRESENCE_UPDATE", "d": data})


@pytest.fixture
async def discord(socket_enabled):
    fake = FakeDiscord()
    app = web.Application()
    app.router.add_get("/applications/@me", fake.application)
    app.router.add_get("/users/@me/guilds", fake.guilds)
    app.router.add_get("/users/{id}", fake.user)
    app.router.add_get("/guilds/{guild}/members/{user}", fake.member)
    app.router.add_get("/gateway", fake.gateway)
    app.router.add_get("/resume/", fake.gateway)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    fake.base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    async with aiohttp.ClientSession() as session:
        yield fake, session
    fake.to_send.put_nowait(1000)  # a connection still open closes, so the server can stop
    await runner.cleanup()


async def test_client(discord) -> None:
    fake, session = discord
    client = DiscordClient(session, "TOKEN", api_base=fake.base)
    assert await client.async_check(PLAYER) == "Steph"
    with pytest.raises(DiscordUserError):  # exists, but in no server of the bot
        await client.async_check(OTHER)
    with pytest.raises(DiscordUserError):
        await client.async_check("999999999999999999")
    with pytest.raises(DiscordAuthError):
        await DiscordClient(session, "WRONG", api_base=fake.base).async_check(PLAYER)
    fake.flags = 0
    with pytest.raises(DiscordIntentError):
        await client.async_check(PLAYER)


async def test_gateway(discord) -> None:
    fake, session = discord
    gateway = DiscordGateway(session, "TOKEN", url=fake.base.replace("http", "ws") + "/gateway")
    changes: list[str] = []
    gateway.subscribe(PLAYER, partial(changes.append, "player"))
    task = asyncio.create_task(gateway.async_run())
    try:
        identify = await asyncio.wait_for(fake.sent.get(), 5)
        assert identify["op"] == 2
        assert identify["d"]["token"] == "TOKEN"
        assert identify["d"]["intents"] == 1 << 0 | 1 << 8
        fake.ready(presence(PLAYER, "online", playing()), presence(OTHER))
        await asyncio.wait_for(gateway.ready.wait(), 5)
        assert gateway.status(PLAYER).game == "World of Warcraft Classic"

        fake.update(presence(PLAYER, "offline"))
        for _ in range(50):
            if gateway.status(PLAYER).status == "offline":
                break
            await asyncio.sleep(0.02)
        assert gateway.status(PLAYER) == DiscordStatus()
        assert changes.count("player") == 2  # all servers received, then the update

        # Connection lost: the bot resumes its session where it was.
        fake.to_send.put_nowait(4900)
        resume = await asyncio.wait_for(fake.sent.get(), 5)
        assert resume == {"op": 6, "d": {"token": "TOKEN", "session_id": "S1", "seq": 3}}

        # The token was reset: no more attempts, the error tells why.
        fake.to_send.put_nowait(4004)
        await asyncio.wait_for(task, 5)
        assert isinstance(gateway.error, DiscordAuthError)
    finally:
        task.cancel()


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float) -> None:
    """Let time pass; the Discord connection runs on, so background tasks are not awaited."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


async def _until(hass: HomeAssistant, done: Callable[[], bool]) -> None:
    """Until an update from Discord has gone through (time is frozen: no sleeping)."""
    for _ in range(1000):
        await hass.async_block_till_done()
        if done():
            return
        await asyncio.sleep(0)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="PC de Léa",
        unique_id=f"discord_{PLAYER}",
        data={"kind": "discord", "bot_token": "TOKEN", "user_id": PLAYER, "name": "PC de Léa"},
    )


async def test_playing_standby_and_off(
    hass: HomeAssistant, discord, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-10-21 12:00:00-07:00")
    fake, _ = discord
    fake.heartbeat = 10**10  # time is frozen and jumps: no heartbeat in the way
    gateway = partial(DiscordGateway, url=fake.base.replace("http", "ws") + "/gateway")
    fake.ready(presence(PLAYER, "online", playing()))
    with patch("custom_components.gaming_hub.drivers.discord.DiscordGateway", gateway):
        entry = _entry()
        await _setup(hass, entry)
        state = hass.states.get("media_player.pc_de_lea")
        assert (state.state, state.attributes["media_title"]) == (
            "playing",
            "World of Warcraft Classic",
        )
        assert hass.states.get("sensor.pc_de_lea_discord").state == "online"
        for _ in range(4):
            await _tick(hass, freezer, 300)
        assert float(hass.states.get("sensor.pc_de_lea_play_time_today").state) == 20

        # Discord open on the computer, no game: standby, play time stops.
        fake.update(presence(PLAYER, "online"))
        await _until(hass, lambda: hass.states.get("media_player.pc_de_lea").state != "playing")
        state = hass.states.get("media_player.pc_de_lea")
        assert (state.state, state.attributes["power_state"]) == ("off", "standby")
        for _ in range(2):
            await _tick(hass, freezer, 300)
        assert float(hass.states.get("sensor.pc_de_lea_play_time_today").state) == 20

        fake.update(presence(PLAYER, "offline"), seq=4)
        await _until(hass, lambda: hass.states.get("media_player.pc_de_lea").state == "off")
        assert hass.states.get("media_player.pc_de_lea").state == "off"

        assert await hass.config_entries.async_unload(entry.entry_id)
        assert hass.data[f"{DOMAIN}_discord"] == {}  # last player gone: connection closed


async def test_refused_token_asks_for_a_new_one(hass: HomeAssistant, discord) -> None:
    fake, _ = discord
    gateway = partial(DiscordGateway, url=fake.base.replace("http", "ws") + "/gateway")
    fake.to_send.put_nowait(4004)
    with patch("custom_components.gaming_hub.drivers.discord.DiscordGateway", gateway):
        entry = _entry()
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    (flow,) = hass.config_entries.flow.async_progress()
    assert flow["step_id"] == "discord_reauth"


async def test_add_a_discord_account(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert "discord" in result["menu_options"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "discord"}
    )
    with patch(CHECK, AsyncMock(side_effect=DiscordIntentError)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"bot_token": "TOKEN", "user_id": PLAYER}
        )
    assert result["errors"] == {"base": "discord_presence_intent"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"bot_token": "TOKEN", "user_id": "steph"}
    )
    assert result["errors"] == {"base": "discord_user_not_found"}
    with (
        patch(CHECK, AsyncMock(return_value="Steph")),
        patch("custom_components.gaming_hub.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"bot_token": " TOKEN ", "user_id": PLAYER}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Steph"
    assert result["data"] == {
        "kind": "discord",
        "bot_token": "TOKEN",
        "user_id": PLAYER,
        "name": "Steph",
    }
