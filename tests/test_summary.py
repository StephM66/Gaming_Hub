"""Statistics across the consoles: one "Gaming Hub" device adding them up."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_hub.const import DOMAIN
from custom_components.gaming_hub.protocols.steam import SteamStatus

from .test_entities import _setup, _tick

GAMES = "sensor.gaming_hub_games_being_played"
ON = "sensor.gaming_hub_consoles_on"
TODAY = "sensor.gaming_hub_play_time_today"
WEEK = "sensor.gaming_hub_play_time_this_week"
STEAM_STATUS = "custom_components.gaming_hub.protocols.steam.SteamClient.async_status"
STEAM_ID = "76561198000000000"


async def test_summary_of_all_consoles(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to("2026-10-21 12:00:00-07:00")  # not near midnight: play time is daily
    pc = MockConfigEntry(
        domain=DOMAIN,
        title="PC",
        data={"kind": "steam", "api_key": "key", "steam_id": STEAM_ID, "name": "PC"},
    )
    summary = MockConfigEntry(
        domain=DOMAIN, title="Gaming Hub", unique_id="summary", data={"kind": "summary"}
    )
    in_game = SteamStatus(STEAM_ID, "Steph", "online", "Halo Infinite", "1240440")
    with patch(STEAM_STATUS, AsyncMock(return_value=in_game)):
        await _setup(hass, ps5_entry)  # awake, no game
        await _setup(hass, pc)
        await _setup(hass, summary)

        assert hass.states.get(ON).state == "2"
        assert hass.states.get(ON).attributes["consoles"] == ["PS5 Salon", "PC"]
        games = hass.states.get(GAMES)
        assert (games.state, games.attributes["PC"]) == ("Halo Infinite", "Halo Infinite")

        # 30 minutes of play on both consoles.
        for _ in range(6):
            await _tick(hass, freezer, 300)
    today = hass.states.get(TODAY)
    assert float(today.state) == 60
    assert (today.attributes["PS5 Salon"], today.attributes["PC"]) == (30, 30)
    assert float(hass.states.get(WEEK).state) == 1  # hours
    # Totals reset with the day, week and month (a sum that grows back after a restart is
    # not a new cycle).
    assert hass.states.get(TODAY).attributes["state_class"] == "total"
    assert (
        hass.states.get(TODAY).attributes["last_reset"] == dt_util.start_of_local_day().isoformat()
    )
    assert float(hass.states.get("sensor.gaming_hub_play_time_this_month").state) == 1
    assert float(hass.states.get("sensor.ps5_salon_play_time_this_week").state) == 0.5

    # A console removed from the hub leaves the totals.
    await hass.config_entries.async_unload(pc.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(ON).state == "1"
    assert hass.states.get(GAMES).state == "unknown"
    assert float(hass.states.get(TODAY).state) == 30
