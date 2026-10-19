"""Console state from any entity, and an unmodified PS3 followed through it and the PSN."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_hub.const import DOMAIN
from custom_components.gaming_hub.presence import is_present
from custom_components.gaming_hub.protocols.psn import PsnSession, PsnStatus, parse_status

from .test_entities import PSN_STATUS, _setup, _tick


@pytest.mark.parametrize(
    ("entity_id", "value", "threshold", "expected"),
    [
        ("binary_sensor.ping_console", "on", None, True),
        ("binary_sensor.ping_console", "off", None, False),
        ("device_tracker.console", "home", None, True),
        ("device_tracker.console", "not_home", None, False),
        ("sensor.sync_box_hdmi2_status", "linked", None, True),  # HDMI signal present
        ("sensor.sync_box_hdmi2_status", "plugged", None, False),
        ("sensor.sync_box_hdmi2_status", "unplugged", None, False),
        ("media_player.tv_source", "playing", None, True),
        ("sensor.plug_power", "42.5", 5, True),
        ("sensor.plug_power", "0.4", 5, False),
        ("sensor.sync_box_hdmi2_status", "linked", 5, True),  # threshold only for numbers
        ("binary_sensor.ping_console", "unavailable", None, None),
        ("binary_sensor.ping_console", "unknown", None, None),
    ],
)
def test_presence_from_any_entity(
    entity_id: str, value: str, threshold: float | None, expected: bool | None
) -> None:
    assert is_present(State(entity_id, value), threshold) is expected
    assert is_present(None) is None


def test_ps3_game_icon_from_the_title_id() -> None:
    status = parse_status(
        {
            "profile": {
                "accountId": "1",
                "presences": [
                    {
                        "onlineStatus": "online",
                        "platform": "PS3",
                        "npTitleId": "NPEB01234_00",
                        "titleName": "Journey",
                    }
                ],
            }
        },
        None,
    )
    image = status.sessions["PS3"].image
    assert image.startswith("https://tmdb.np.dl.playstation.net/tmdb/NPEB01234_00_")
    assert image.endswith("/ICON0.PNG")


async def test_unmodified_ps3(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """State from an HDMI input, game from the PSN account: no console modification."""
    hdmi = "sensor.sync_box_hdmi2_status"
    hass.states.async_set(hdmi, "plugged")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PS3",
        data={
            "kind": "linked",
            "preset": "ps3",
            "source_entity": hdmi,
            "name": "PS3",
            "npsso": "npsso",
            "account_id": "1",
        },
    )
    status = PsnStatus(
        account_id="1",
        online_id="Steph66",
        online_status="online",
        sessions={"PS3": PsnSession("PS3", True, "Journey", "NPEB01234_00", "https://x/i.png")},
    )
    with patch(PSN_STATUS, AsyncMock(return_value=status)):
        await _setup(hass, entry)
        player = "media_player.ps3"
        assert hass.states.get(player).state == "off"
        device = hass.data["device_registry"].async_get_device({(DOMAIN, entry.entry_id)})
        assert (device.manufacturer, device.model) == ("Sony", "PlayStation 3")

        hass.states.async_set(hdmi, "linked")  # the PS3 sends a picture
        await _tick(hass, freezer)
        state = hass.states.get(player)
        assert (state.state, state.attributes["media_title"]) == ("playing", "Journey")


async def test_steam_account(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    """Home Assistant's Steam integration: in game with the game, standby while only online."""
    steam = (
        er.async_get(hass)
        .async_get_or_create(
            "sensor", "steam_online", "76561198000000000", suggested_object_id="steam_steph"
        )
        .entity_id
    )
    hass.states.async_set(steam, "online", {"level": 12})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="PC",
        data={"kind": "linked", "preset": "pc", "source_entity": steam, "name": "PC"},
    )
    await _setup(hass, entry)
    player = "media_player.pc"
    state = hass.states.get(player)
    assert (state.state, state.attributes["power_state"]) == ("off", "standby")

    hass.states.async_set(steam, "online", {"game": "Hades II", "game_id": "1145350", **IMAGES})
    await _tick(hass, freezer)
    state = hass.states.get(player)
    assert (state.state, state.attributes["media_title"]) == ("playing", "Hades II")
    assert state.attributes["entity_picture"].startswith("/api/media_player_proxy/")
    for _ in range(6):
        await _tick(hass, freezer, 300)  # only time in game is play time
    hass.states.async_set(steam, "away")
    await _tick(hass, freezer)
    for _ in range(6):
        await _tick(hass, freezer, 300)
    assert float(hass.states.get("sensor.pc_play_time_today").state) == 30

    hass.states.async_set(steam, "offline")
    await _tick(hass, freezer)
    state = hass.states.get(player)
    assert (state.state, state.attributes["power_state"]) == ("off", "off")


IMAGES = {
    "game_image_main": "https://steamcdn-a.akamaihd.net/steam/apps/1145350/capsule_616x353.jpg",
    "game_image_header": "https://steamcdn-a.akamaihd.net/steam/apps/1145350/header.jpg",
}
