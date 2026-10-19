"""Entities of each kind of console, commands, parental control and consumption."""

from __future__ import annotations

from datetime import timedelta
import json
from unittest.mock import AsyncMock, patch

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_mqtt_message,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.gaming_hub.const import DOMAIN, EVENT_PARENTAL
from custom_components.gaming_hub.protocols.psn import PsnAuthError, PsnSession, PsnStatus
from custom_components.gaming_hub.protocols.webman import WebmanError, WebmanStatus

from .conftest import ddp_response

STANDBY = "custom_components.gaming_hub.protocols.remoteplay.async_standby"
WEBMAN = "custom_components.gaming_hub.protocols.webman.WebmanClient"
PSN_STATUS = "custom_components.gaming_hub.protocols.psn.PsnClient.async_get_status"


async def _tick(hass: HomeAssistant, freezer: FrozenDateTimeFactory, seconds: float = 2) -> None:
    """Let time pass (polling, debounced refreshes)."""
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    if hass.config_entries.async_get_entry(entry.entry_id) is None:
        entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_ps5(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    mock_ddp["status"].return_value = ddp_response(620, **{"system-version": "09400001"})
    await _setup(hass, ps5_entry)
    state = hass.states.get("media_player.ps5_salon")
    assert (state.state, state.attributes["power_state"]) == ("off", "standby")
    assert state.attributes["supported_features"] == 384  # TURN_ON | TURN_OFF
    assert hass.states.get("sensor.ps5_salon_system_version").state == "9.40"
    # No smart plug linked: no power or energy sensor (no more estimates).
    assert hass.states.get("sensor.ps5_salon_power") is None
    assert hass.states.get("sensor.ps5_salon_energy") is None
    assert hass.states.get("binary_sensor.ps5_salon_playing").state == STATE_OFF

    await hass.services.async_call(
        "media_player", "turn_on", {ATTR_ENTITY_ID: "media_player.ps5_salon"}, blocking=True
    )
    mock_ddp["wake"].assert_awaited_once_with("192.168.1.20", "305441741")

    mock_ddp["status"].return_value = ddp_response(200)
    await _tick(hass, freezer, 11)  # next poll
    assert hass.states.get("media_player.ps5_salon").state == STATE_ON
    with patch(STANDBY, AsyncMock()) as standby:
        await hass.services.async_call(
            "media_player", "turn_off", {ATTR_ENTITY_ID: "media_player.ps5_salon"}, blocking=True
        )
    assert standby.await_args.args[0] == "192.168.1.20"

    assert await hass.config_entries.async_unload(ps5_entry.entry_id)
    assert ps5_entry.state is ConfigEntryState.NOT_LOADED


async def test_ps5_game_and_account_from_psn(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    """The built-in PlayStation Network account gives the game (DDP does not)."""
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps5_entry, data={**ps5_entry.data, "npsso": "npsso", "account_id": "1"}
    )
    status = PsnStatus(
        account_id="1",
        online_id="Steph66",
        online_status="online",
        avatar_url="https://psn/avatar.png",
        plus=True,
        trophy_level=312,
        trophy_progress=45,
        trophies={"platinum": 12, "gold": 80},
        sessions={
            "PS5": PsnSession("PS5", True, "Astro Bot", "PPSA01234_00", "https://psn/astro.png"),
            "PS4": PsnSession("PS4", True, "Ignored", None, None),
        },
    )
    with patch(PSN_STATUS, AsyncMock(return_value=status)) as psn:
        await _setup(hass, ps5_entry)
        state = hass.states.get("media_player.ps5_salon")
        assert state.state == "playing"
        assert state.attributes["media_title"] == "Astro Bot"
        assert state.attributes["title_id"] == "PPSA01234_00"
        entity = hass.data["media_player"].get_entity("media_player.ps5_salon")
        assert entity.media_image_url == "https://psn/astro.png"
        assert hass.states.get("sensor.ps5_salon_current_game").state == "Astro Bot"
        psn_state = hass.states.get("sensor.ps5_salon_playstation_network")
        assert (psn_state.state, psn_state.attributes["online_id"]) == ("online", "Steph66")
        trophies = hass.states.get("sensor.ps5_salon_trophy_level")
        assert (trophies.state, trophies.attributes["platinum"]) == ("312", 12)
        assert hass.states.get("binary_sensor.ps5_salon_playstation_plus").state == STATE_ON
        # PSN is polled once a minute while the console is on, not every 10 s.
        calls = psn.await_count
        await _tick(hass, freezer, 10)
        assert psn.await_count == calls
        await _tick(hass, freezer, 60)
        assert psn.await_count == calls + 1

    # Expired NPSSO: the console keeps working and Home Assistant asks for a new token.
    with patch(PSN_STATUS, AsyncMock(side_effect=PsnAuthError("expired"))):
        await _tick(hass, freezer, 61)
    assert hass.states.get("media_player.ps5_salon").state == STATE_ON
    flows = hass.config_entries.flow.async_progress()
    assert [flow["context"]["source"] for flow in flows] == ["reauth"]


async def test_ps3(hass: HomeAssistant, ps3_entry) -> None:
    status = WebmanStatus(
        cpu_temperature=62,
        rsx_temperature=55,
        fan_speed=39,
        in_game=True,
        title_id="BLES01807",
        title="Grand Theft Auto V",
        icon_path="/dev_hdd0/game/BLES01807/ICON0.PNG",
        firmware="4.91 CEX Cobra 8.4",
        play_time=3723,
        memory_free=109.7,
        hdd_free=117.5,
        fan_mode="dynamic",
        fan_target=68,
        uptime=3600,
    )
    with (
        patch(f"{WEBMAN}.async_get_status", AsyncMock(return_value=status)),
        patch(f"{WEBMAN}.async_quit_game", AsyncMock()) as quit_game,
        patch(f"{WEBMAN}.async_notify", AsyncMock()) as notify,
        patch(f"{WEBMAN}.async_restart", AsyncMock()) as restart,
        patch(f"{WEBMAN}.async_shutdown", AsyncMock()) as shutdown,
    ):
        await _setup(hass, ps3_entry)
        state = hass.states.get("media_player.ps3")
        assert state.state == "playing"
        assert state.attributes["media_title"] == "Grand Theft Auto V"
        assert state.attributes["supported_features"] == 256  # TURN_OFF only
        assert hass.states.get("sensor.ps3_cpu_temperature").state == "62"
        assert hass.states.get("sensor.ps3_rsx_temperature").state == "55"
        assert hass.states.get("sensor.ps3_fan_speed").state == "39"
        assert hass.states.get("sensor.ps3_firmware").state == "4.91 CEX Cobra 8.4"
        assert hass.states.get("sensor.ps3_fan_mode").state == "dynamic"
        assert hass.states.get("sensor.ps3_game_session").state == "62.0"
        assert hass.states.get("sensor.ps3_free_disk_space").state == "117.5"
        assert hass.states.get("sensor.ps3_free_memory").state == "109.7"
        assert hass.states.get("sensor.ps3_powered_on_at").state.endswith("+00:00")
        # Rarely useful diagnostics are created disabled.
        assert hass.states.get("sensor.ps3_ip_address") is None
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: "button.ps3_quit_game"}, blocking=True
        )
        quit_game.assert_awaited_once()
        entity = hass.data["media_player"].get_entity("media_player.ps3")
        assert entity.media_image_url == "http://192.168.1.30/dev_hdd0/game/BLES01807/ICON0.PNG"

        await hass.services.async_call(
            "notify",
            "send_message",
            {ATTR_ENTITY_ID: "notify.ps3_on_screen_message", "message": "À table !"},
            blocking=True,
        )
        notify.assert_awaited_once_with("À table !")
        await hass.services.async_call(
            "button", "press", {ATTR_ENTITY_ID: "button.ps3_restart"}, blocking=True
        )
        restart.assert_awaited_once()
        await hass.services.async_call(
            "media_player", "turn_off", {ATTR_ENTITY_ID: "media_player.ps3"}, blocking=True
        )
        shutdown.assert_awaited_once()

    with patch(f"{WEBMAN}.async_get_status", AsyncMock(side_effect=WebmanError("off"))):
        await hass.config_entries.async_reload(ps3_entry.entry_id)
        await hass.async_block_till_done()
    assert hass.states.get("media_player.ps3").state == STATE_OFF
    assert hass.states.get("button.ps3_restart").state == "unavailable"
    assert hass.states.get("button.ps3_quit_game").state == "unavailable"


async def test_ps3_power_on_script(hass: HomeAssistant, ps3_entry) -> None:
    calls = async_mock_service(hass, "script", "turn_on")
    ps3_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps3_entry, options={"turn_on_entity": "script.ps3_cec_on"}
    )
    with patch(f"{WEBMAN}.async_get_status", AsyncMock(side_effect=WebmanError("off"))):
        await _setup(hass, ps3_entry)
        assert hass.states.get("media_player.ps3").attributes["supported_features"] == 384
        await hass.services.async_call(
            "media_player", "turn_on", {ATTR_ENTITY_ID: "media_player.ps3"}, blocking=True
        )
    assert calls[0].data == {ATTR_ENTITY_ID: "script.ps3_cec_on"}


async def test_switch_over_mqtt(
    hass: HomeAssistant, mqtt_mock, freezer: FrozenDateTimeFactory
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Switch",
        unique_id="switch_ha_1a2b",
        data={
            "kind": "switch",
            "client_id": "switch_ha_1a2b",
            "discovery_prefix": "homeassistant",
            "name": "Switch",
        },
    )
    await _setup(hass, entry)
    coordinator = entry.runtime_data
    assert hass.states.get("media_player.switch").state == STATE_OFF

    base = "switch_ha/switch_ha_1a2b/"
    async_fire_mqtt_message(hass, base + "battery", "87", retain=True)
    async_fire_mqtt_message(hass, base + "charging", "ON", retain=True)
    async_fire_mqtt_message(hass, base + "game_running", "ON", retain=True)
    async_fire_mqtt_message(hass, base + "current_game", "Mario Kart 8 Deluxe", retain=True)
    async_fire_mqtt_message(hass, base + "current_game_id", "0100152000022000", retain=True)
    async_fire_mqtt_message(hass, base + "battery_health", "92.5", retain=True)
    async_fire_mqtt_message(hass, base + "charger_type", "enough_power", retain=True)
    async_fire_mqtt_message(hass, base + "brightness", "60", retain=True)
    async_fire_mqtt_message(hass, base + "backlight", "ON", retain=True)
    async_fire_mqtt_message(hass, base + "volume", "35", retain=True)
    async_fire_mqtt_message(hass, base + "audio_target", "tv", retain=True)
    async_fire_mqtt_message(hass, base + "controller_count", "2", retain=True)
    async_fire_mqtt_message(hass, base + "player_1_controller", "pro", retain=True)
    async_fire_mqtt_message(hass, base + "player_2_controller", "joydual", retain=True)
    async_fire_mqtt_message(
        hass, base + "screen_rtsp_url", "rtsp://192.168.1.40:6666/", retain=True
    )
    await _tick(hass, freezer)
    assert hass.states.get("camera.switch_screen").state == "unavailable"
    # current_game_id also feeds MQTT discovery, which must not reload the entry.
    assert entry.runtime_data is coordinator
    # Retained values alone do not mean the console is awake.
    assert hass.states.get("media_player.switch").state == STATE_OFF
    assert hass.states.get("sensor.switch_battery").state == "87.0"

    heartbeat = json.dumps({"client_id": "switch-ha-1a2b", "status": "online"})
    async_fire_mqtt_message(hass, "homeassistant/status", heartbeat)
    await _tick(hass, freezer)
    state = hass.states.get("media_player.switch")
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Mario Kart 8 Deluxe"
    assert hass.states.get("binary_sensor.switch_charging").state == STATE_ON
    assert hass.states.get("binary_sensor.switch_screen").state == STATE_ON
    assert hass.states.get("sensor.switch_battery_health").state == "92.5"
    assert hass.states.get("sensor.switch_charger").state == "enough_power"
    assert hass.states.get("sensor.switch_screen_brightness").state == "60.0"
    assert hass.states.get("sensor.switch_volume").state == "35.0"
    assert hass.states.get("sensor.switch_audio_output").state == "tv"
    controllers = hass.states.get("sensor.switch_controllers")
    assert (controllers.state, controllers.attributes["player_2"]) == ("2", "joydual")
    camera = hass.data["camera"].get_entity("camera.switch_screen")
    assert await camera.stream_source() == "rtsp://192.168.1.40:6666/"
    entity = hass.data["media_player"].get_entity("media_player.switch")
    assert entity.media_image_url == "https://tinfoil.media/ti/0100152000022000/256/256/"

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call(
        "notify",
        "send_message",
        {ATTR_ENTITY_ID: "notify.switch_on_screen_message", "message": "Dodo", "title": "Papa"},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player", "turn_off", {ATTR_ENTITY_ID: "media_player.switch"}, blocking=True
    )
    published = [call.args[:2] for call in mqtt_mock.async_publish.call_args_list]
    assert published == [
        ("switch_ha/switch_ha_1a2b/notify/popup", json.dumps({"title": "Papa", "message": "Dodo"})),
        ("homeassistant/command", "shutdown"),
    ]


async def test_linked_xbox(hass: HomeAssistant, freezer: FrozenDateTimeFactory) -> None:
    hass.states.async_set("media_player.xbox", "off", {"supported_features": 384})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Xbox",
        data={
            "kind": "linked",
            "preset": "xbox",
            "source_entity": "media_player.xbox",
            "name": "Xbox",
        },
    )
    await _setup(hass, entry)
    hub = "media_player.xbox_2"
    assert hass.states.get(hub).state == STATE_OFF
    device = hass.data["device_registry"].async_get_device({(DOMAIN, entry.entry_id)})
    assert (device.manufacturer, device.model) == ("Microsoft", "Xbox")

    hass.states.async_set(
        "media_player.xbox",
        "playing",
        {
            "supported_features": 384,
            "media_title": "Forza Horizon 5",
            "entity_picture": "/api/media_player_proxy/media_player.xbox?token=abc",
        },
    )
    await _tick(hass, freezer)
    state = hass.states.get(hub)
    assert state.state == "playing"
    assert state.attributes["media_title"] == "Forza Horizon 5"
    assert (
        state.attributes["entity_picture"] == "/api/media_player_proxy/media_player.xbox?token=abc"
    )

    # Registered after setup so it replaces the real media_player service.
    turn_on = async_mock_service(hass, "media_player", "turn_on")
    await entry.runtime_data.async_turn_on()
    assert turn_on[0].data == {ATTR_ENTITY_ID: "media_player.xbox"}


async def test_measured_power_and_energy(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    hass.states.async_set("sensor.prise_ps5", "100")
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(ps5_entry, options={"power_entity": "sensor.prise_ps5"})
    await _setup(hass, ps5_entry)
    assert hass.states.get("sensor.ps5_salon_power").state == "100.0"
    for _ in range(6):
        freezer.tick(timedelta(seconds=10))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    # 100 W during 60 s
    assert float(hass.states.get("sensor.ps5_salon_energy").state) == round(100 * 60 / 3.6e6, 4)
    assert float(hass.states.get("sensor.ps5_salon_play_time_today").state) == 1.0

    # Plug unlinked: power and energy disappear, from the entity registry too.
    hass.config_entries.async_update_entry(ps5_entry, options={})
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get("sensor.ps5_salon_power") is None
    assert registry.async_get("sensor.ps5_salon_energy") is None
    assert registry.async_get("sensor.ps5_salon_play_time_today") is not None


async def test_parental_control_turns_console_off(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    events = async_capture_events(hass, EVENT_PARENTAL)
    await _setup(hass, ps5_entry)
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.ps5_salon_daily_play_time", "value": 5},
        blocking=True,
    )
    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.ps5_salon_warning_before_limit", "value": 2},
        blocking=True,
    )
    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.ps5_salon_parental_control"}, blocking=True
    )
    assert hass.states.get("sensor.ps5_salon_parental_control").state == "allowed"

    with patch(STANDBY, AsyncMock()) as standby:
        for _ in range(4 * 6):  # 4 minutes
            freezer.tick(timedelta(seconds=10))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
        assert hass.states.get("sensor.ps5_salon_parental_control").state == "warning"
        assert [event.data["type"] for event in events] == ["warning"]
        assert events[0].data["message"].startswith("2 min of play left")
        standby.assert_not_awaited()
        for _ in range(7):
            freezer.tick(timedelta(seconds=10))
            async_fire_time_changed(hass)
            await hass.async_block_till_done()
        standby.assert_awaited_once()
    assert hass.states.get("sensor.ps5_salon_parental_control").state == "blocked"
    assert [event.data["type"] for event in events] == ["warning", "enforced"]
    assert "turning off" in events[1].data["message"]

    # Settings survive a reload.
    await hass.config_entries.async_reload(ps5_entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.ps5_salon_daily_play_time").state == "5"
    assert hass.states.get("switch.ps5_salon_parental_control").state == STATE_ON


async def test_parental_block_entity_and_schedule(
    hass: HomeAssistant, mock_ddp, ps5_entry, freezer: FrozenDateTimeFactory
) -> None:
    """Outside the allowed hours, the linked block entity is used instead of standby."""
    freezer.move_to("2026-10-19 21:30:00+00:00")
    suspend = async_mock_service(hass, "homeassistant", "turn_on")
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps5_entry, options={"block_entity": "switch.suspendre_le_jeu"}
    )
    await hass.config.async_set_time_zone("UTC")
    await _setup(hass, ps5_entry)
    for key, value in (("allowed_from", "09:00:00"), ("allowed_until", "21:00:00")):
        await hass.services.async_call(
            "time",
            "set_value",
            {ATTR_ENTITY_ID: f"time.ps5_salon_play_{key}", "time": value},
            blocking=True,
        )
    with patch(STANDBY, AsyncMock()) as standby:
        await hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: "switch.ps5_salon_parental_control"},
            blocking=True,
        )
        assert hass.states.get("sensor.ps5_salon_parental_control").state == "blocked"
        freezer.tick(timedelta(seconds=70))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    standby.assert_not_awaited()
    assert suspend[0].data == {ATTR_ENTITY_ID: "switch.suspendre_le_jeu"}


async def test_usage_is_saved_while_running(
    hass: HomeAssistant, mock_ddp, ps5_entry, hass_storage, freezer: FrozenDateTimeFactory
) -> None:
    await _setup(hass, ps5_entry)
    key = f"{DOMAIN}.{ps5_entry.entry_id}"
    await _tick(hass, freezer, 1)
    assert hass_storage[key]["data"]["usage"]["playtime"] == 0
    for _ in range(31):  # polls every 10 s; writes are throttled to every 5 min
        await _tick(hass, freezer, 10)
    assert hass_storage[key]["data"]["usage"]["playtime"] >= 290


async def test_power_sensor_in_kilowatts(hass: HomeAssistant, mock_ddp, ps5_entry) -> None:
    hass.states.async_set("sensor.prise_ps5", "0.2", {"unit_of_measurement": "kW"})
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(ps5_entry, options={"power_entity": "sensor.prise_ps5"})
    await _setup(hass, ps5_entry)
    assert hass.states.get("sensor.ps5_salon_power").state == "200.0"
