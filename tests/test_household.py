"""Household and profiles in the "Gaming Hub" entry, and consoles completed with entities."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import SOURCE_RECONFIGURE, SOURCE_USER
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_mock_service,
)

from custom_components.gaming_hub.const import DOMAIN, EVENT_PARENTAL
from custom_components.gaming_hub.household import ProfileRules, attribute
from custom_components.gaming_hub.protocols.steam import SteamStatus

from .test_entities import STANDBY, _setup, _tick

STEAM_STATUS = "custom_components.gaming_hub.protocols.steam.SteamClient.async_status"
STEAM_ID = "76561198000000000"
NOON = "2026-10-21 12:00:00-07:00"  # not near midnight: play time is daily


def _console(entry_id: str, by: dict[str, float], playing: tuple[str, ...], game=None):
    """A running console as the hub sees it (seconds today; week and month the same)."""
    data = SimpleNamespace(
        playtime=sum(by.values()),
        playtime_week=sum(by.values()),
        playtime_month=sum(by.values()),
        playtime_by={identity: (s, s, s) for identity, s in by.items()},
        playing_as=playing,
        snapshot=SimpleNamespace(title=game),
    )
    return SimpleNamespace(
        config_entry=SimpleNamespace(entry_id=entry_id, title=entry_id), data=data
    )


def test_play_time_goes_to_the_right_profile() -> None:
    rules = {
        "lea": ProfileRules(
            accounts=frozenset({"pc"}),
            players=frozenset({"switch|Lea"}),
            consoles=frozenset({"ps5"}),
        ),
        "tom": ProfileRules(players=frozenset({"switch|Tom"})),
    }
    consoles = [
        _console("pc", {"account": 1800}, ("account",), "Hades II"),  # Léa's Steam account
        # A PSN account nobody claimed, then anyone: both go to the PS5's main player.
        _console("ps5", {"account": 600, "console": 1200}, ("console",)),
        # Switch players; the rest of the Switch's time has no main player.
        _console("switch", {"player:Lea": 300, "player:Tom": 900, "console": 60}, ("player:Tom",)),
    ]
    household, owners = attribute(consoles, rules)
    assert household.playtime == 4860
    assert owners["lea"].playtime == 1800 + 600 + 1200 + 300
    assert owners["lea"].consoles == {
        "pc": [1800, 1800, 1800],
        "ps5": [1800, 1800, 1800],
        "switch": [300, 300, 300],
    }
    assert owners["lea"].playing == {"pc": "Hades II", "ps5": None}
    assert (owners["tom"].playtime, owners["tom"].playing) == (900, {"switch": None})
    assert owners[None].playtime == 60  # unattributed: household only
    assert list(household.playing) == ["pc", "ps5", "switch"]


async def test_profile_and_household_limit(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    freezer.move_to(NOON)
    pc = MockConfigEntry(
        domain=DOMAIN,
        title="PC",
        data={"kind": "steam", "api_key": "key", "steam_id": STEAM_ID, "name": "PC"},
    )
    in_game = SteamStatus(STEAM_ID, "Steph", "online", "Halo Infinite", "1240440")
    with patch(STEAM_STATUS, AsyncMock(return_value=in_game)), patch(STANDBY, AsyncMock()):
        await _setup(hass, ps5_entry)  # creates the "Gaming Hub" entry
        await _setup(hass, pc)
        (hub,) = [e for e in hass.config_entries.async_entries(DOMAIN) if e.unique_id == "summary"]

        # A profile, from the "Gaming Hub" entry: Léa's Steam account, and the PS5's main player.
        result = await hass.config_entries.subentries.async_init(
            (hub.entry_id, "profile"), context={"source": SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"name": "Léa", "accounts": [pc.entry_id], "consoles": [ps5_entry.entry_id]},
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

        for _ in range(6):  # 30 minutes on both consoles
            await _tick(hass, freezer, 300)
        assert float(hass.states.get("sensor.lea_play_time_today").state) == 60
        today = hass.states.get("sensor.lea_play_time_today")
        assert (today.attributes["PS5 Salon"], today.attributes["PC"]) == (30, 30)
        assert hass.states.get("sensor.lea_playing_on").state == "PS5 Salon, Halo Infinite"
        assert hass.states.get("sensor.lea_parental_control").state == "disabled"
        # No limit for Léa: no "play time left" counting down for nothing.
        assert hass.states.get("sensor.lea_play_time_left") is None

        # A household limit of 30 minutes, already used: every console playing is concerned.
        events = async_capture_events(hass, EVENT_PARENTAL)
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: "number.gaming_hub_daily_play_time", "value": 30},
            blocking=True,
        )
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: "switch.gaming_hub_parental_control"},
            blocking=True,
        )
        await hass.async_block_till_done()
        assert hass.states.get("sensor.gaming_hub_parental_control").state == "blocked"
        assert float(hass.states.get("sensor.gaming_hub_play_time_left").state) == 0
        household = [e.data for e in events if e.data.get("scope") == "household"]
        assert household[0]["type"] == "blocked"
        assert household[0]["consoles"] == ["PS5 Salon", "PC"]
        assert household[0]["message"] == "Daily play time is over for the household."
        # Léa's own rules are untouched.
        assert hass.states.get("sensor.lea_parental_control").state == "disabled"


async def test_profile_can_be_changed(hass: HomeAssistant, mock_ddp, ps5_entry) -> None:
    await _setup(hass, ps5_entry)
    (hub,) = [e for e in hass.config_entries.async_entries(DOMAIN) if e.unique_id == "summary"]
    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "profile"), context={"source": SOURCE_USER}
    )
    await hass.config_entries.subentries.async_configure(result["flow_id"], {"name": "Tom"})
    await hass.async_block_till_done()
    (subentry,) = hub.subentries.values()
    # A console chosen before, and removed since.
    hass.config_entries.async_update_subentry(
        hub, subentry, data={"consoles": [ps5_entry.entry_id, "removed"], "players": ["x|Tom"]}
    )
    result = await hass.config_entries.subentries.async_init(
        (hub.entry_id, "profile"),
        context={"source": SOURCE_RECONFIGURE, "subentry_id": subentry.subentry_id},
    )
    suggested = {
        str(key): key.description["suggested_value"]
        for key in result["data_schema"].schema
        if key.description
    }
    assert suggested == {"name": "Tom", "consoles": [ps5_entry.entry_id]}
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Tom", "consoles": [ps5_entry.entry_id]}
    )
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "reconfigure_successful")
    assert hub.subentries[subentry.subentry_id].data["consoles"] == [ps5_entry.entry_id]


async def test_pc_switch_completes_steam(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    """Steam does not know whether the computer is on: the PC's switch tells, and powers it."""
    freezer.move_to(NOON)
    hass.states.async_set("switch.pc_windows", "off")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PC",
        data={"kind": "steam", "api_key": "key", "steam_id": STEAM_ID, "name": "PC"},
        options={"state_entity": "switch.pc_windows"},
    )
    online = SteamStatus(STEAM_ID, "Steph", "online")
    with patch(STEAM_STATUS, AsyncMock(return_value=online)) as status:
        await _setup(hass, entry)
        state = hass.states.get("media_player.pc")
        assert (state.state, state.attributes["power_state"]) == ("off", "off")

        hass.states.async_set("switch.pc_windows", "on")
        await _tick(hass, freezer)
        state = hass.states.get("media_player.pc")
        assert (state.state, state.attributes["power_state"]) == ("on", "on")
        for _ in range(3):
            await _tick(hass, freezer, 300)  # on, no game: not play time

        status.return_value = SteamStatus(STEAM_ID, "Steph", "online", "Hades II", "1145350")
        await _tick(hass, freezer, 31)
        assert hass.states.get("media_player.pc").state == "playing"
        for _ in range(2):
            await _tick(hass, freezer, 300)
        assert float(hass.states.get("sensor.pc_play_time_today").state) == 10

        turn_off = async_mock_service(hass, "homeassistant", "turn_off")
        await entry.runtime_data.async_turn_off()
        assert turn_off[0].data == {ATTR_ENTITY_ID: "switch.pc_windows"}


async def test_options_only_offer_what_is_missing(hass: HomeAssistant, mock_ddp, ps5_entry) -> None:
    pc = MockConfigEntry(
        domain=DOMAIN,
        title="PC",
        data={"kind": "steam", "api_key": "key", "steam_id": STEAM_ID, "name": "PC"},
    )
    with patch(STEAM_STATUS, AsyncMock(return_value=SteamStatus(STEAM_ID, "S", "online"))):
        await _setup(hass, ps5_entry)
        await _setup(hass, pc)

        def fields(result) -> set[str]:
            return {str(key) for key in result["data_schema"].schema}

        result = await hass.config_entries.options.async_init(pc.entry_id)
        assert fields(result) == {
            "power_entity",
            "state_entity",
            "turn_on_entity",
            "turn_off_entity",
            "restart_entity",
            "block_entity",
        }
        # A paired PS5 tells its state and turns on and off by itself.
        result = await hass.config_entries.options.async_init(ps5_entry.entry_id)
        assert fields(result) == {"power_entity", "restart_entity", "block_entity"}
