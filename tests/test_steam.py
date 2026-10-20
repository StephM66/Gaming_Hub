"""PC, Steam Deck… through the Steam account (official Web API), inside Gaming Hub."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp import web
from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_hub.const import DOMAIN
from custom_components.gaming_hub.protocols.steam import (
    SteamAccountError,
    SteamAuthError,
    SteamClient,
    SteamStatus,
    account_input,
)

from .test_entities import _setup, _tick

STEAM_ID = "76561198000000001"
STATUS = "custom_components.gaming_hub.protocols.steam.SteamClient.async_status"
RESOLVE = "custom_components.gaming_hub.protocols.steam.SteamClient.async_resolve"


def test_account_as_typed() -> None:
    assert account_input(STEAM_ID) == (STEAM_ID, None)
    assert account_input(f"https://steamcommunity.com/profiles/{STEAM_ID}/") == (STEAM_ID, None)
    assert account_input("https://steamcommunity.com/id/steph66/") == (None, "steph66")
    assert account_input(" steph66 ") == (None, "steph66")
    assert account_input("https://example.com/?a=b c") == (None, None)


def test_artwork() -> None:
    assert SteamStatus(STEAM_ID, "S", "online", "Hades II", "1145350").image == (
        "https://cdn.akamai.steamstatic.com/steam/apps/1145350/header.jpg"
    )
    # A non-Steam game added to the library has a 64-bit ID and no store artwork.
    assert SteamStatus(STEAM_ID, "S", "online", "Emulator", "13286475839105916928").image is None


class FakeSteam:
    def __init__(self) -> None:
        self.player = {"steamid": STEAM_ID, "personaname": "Steph", "personastate": 1}

    def _check(self, request: web.Request) -> None:
        if request.query.get("key") != "KEY":
            raise web.HTTPForbidden

    async def resolve(self, request: web.Request) -> web.Response:
        self._check(request)
        if request.query["vanityurl"] == "steph66":
            return web.json_response({"response": {"steamid": STEAM_ID, "success": 1}})
        return web.json_response({"response": {"success": 42, "message": "No match"}})

    async def summaries(self, request: web.Request) -> web.Response:
        self._check(request)
        assert request.query["steamids"] == STEAM_ID
        return web.json_response({"response": {"players": [self.player]}})


@pytest.fixture
async def steam(socket_enabled):
    fake = FakeSteam()
    app = web.Application()
    app.router.add_get("/ISteamUser/ResolveVanityURL/v1/", fake.resolve)
    app.router.add_get("/ISteamUser/GetPlayerSummaries/v2/", fake.summaries)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    base = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    async with aiohttp.ClientSession() as session:
        yield fake, session, base
    await runner.cleanup()


async def test_client(steam) -> None:
    fake, session, base = steam
    client = SteamClient(session, "KEY", api_base=base)
    assert await client.async_resolve("https://steamcommunity.com/id/steph66") == STEAM_ID
    with pytest.raises(SteamAccountError):
        await client.async_resolve("nobody")
    assert await client.async_status(STEAM_ID) == SteamStatus(STEAM_ID, "Steph", "online")

    fake.player |= {"gameextrainfo": "Hades II", "gameid": "1145350", "personastate": 3}
    status = await client.async_status(STEAM_ID)
    assert (status.status, status.game, status.game_id) == ("away", "Hades II", "1145350")

    with pytest.raises(SteamAuthError):
        await SteamClient(session, "WRONG", api_base=base).async_status(STEAM_ID)


def _entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="PC",
        unique_id=f"steam_{STEAM_ID}",
        data={"kind": "steam", "api_key": "KEY", "steam_id": STEAM_ID, "name": "PC"},
    )


async def test_in_game_standby_and_offline(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """In game: on with the game; online without a game: standby; play time only in game."""
    freezer.move_to("2026-10-21 12:00:00-07:00")  # not near midnight: play time is daily
    online = SteamStatus(STEAM_ID, "Steph", "online")
    with patch(STATUS, AsyncMock(return_value=online)) as status:
        entry = _entry()
        await _setup(hass, entry)
        player = "media_player.pc"
        state = hass.states.get(player)
        assert (state.state, state.attributes["power_state"]) == ("off", "standby")
        assert hass.states.get("sensor.pc_steam").state == "online"
        device = hass.data["device_registry"].async_get_device({(DOMAIN, entry.entry_id)})
        assert (device.manufacturer, device.model) == ("Valve", "Steam")

        status.return_value = SteamStatus(STEAM_ID, "Steph", "online", "Hades II", "1145350")
        await _tick(hass, freezer, 31)
        state = hass.states.get(player)
        assert (state.state, state.attributes["media_title"]) == ("playing", "Hades II")
        for _ in range(6):
            await _tick(hass, freezer, 300)

        status.return_value = online  # back on the Steam library: not play time
        await _tick(hass, freezer, 31)
        for _ in range(6):
            await _tick(hass, freezer, 300)
        # 30 min in game, up to the read that saw the game end (half a minute later).
        assert float(hass.states.get("sensor.pc_play_time_today").state) == 30.5

        status.return_value = SteamStatus(STEAM_ID, "Steph", "offline")
        await _tick(hass, freezer, 31)
        state = hass.states.get(player)
        assert (state.state, state.attributes["power_state"]) == ("off", "off")


async def test_refused_key_asks_for_a_new_one(hass: HomeAssistant) -> None:
    entry = _entry()
    with patch(STATUS, AsyncMock(side_effect=SteamAuthError("403"))):
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    (flow,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert flow["step_id"] == "steam_reauth"

    with (
        patch(STATUS, AsyncMock(return_value=SteamStatus(STEAM_ID, "Steph", "online"))),
        patch("custom_components.gaming_hub.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_configure(flow["flow_id"], {"api_key": "NEW"})
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "reauth_successful")
    assert entry.data["api_key"] == "NEW"


async def test_add_a_steam_account(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "steam"}
    )
    assert result["step_id"] == "steam"
    assert result["description_placeholders"]["key_url"] == "https://steamcommunity.com/dev/apikey"

    form = {"api_key": "KEY", "account": "https://steamcommunity.com/id/steph66"}
    for error, expected in (
        (SteamAuthError("403"), "invalid_api_key"),
        (SteamAccountError("x"), "steam_account_not_found"),
    ):
        with patch(RESOLVE, AsyncMock(side_effect=error)):
            result = await hass.config_entries.flow.async_configure(result["flow_id"], form)
        assert result["errors"] == {"base": expected}

    with (
        patch(RESOLVE, AsyncMock(return_value=STEAM_ID)),
        patch(STATUS, AsyncMock(return_value=SteamStatus(STEAM_ID, "Steph", "online"))),
        patch("custom_components.gaming_hub.async_setup_entry", AsyncMock(return_value=True)),
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], form)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Steph"
    assert result["data"] == {
        "kind": "steam",
        "api_key": "KEY",
        "steam_id": STEAM_ID,
        "name": "Steph",
    }
    assert result["result"].unique_id == f"steam_{STEAM_ID}"
