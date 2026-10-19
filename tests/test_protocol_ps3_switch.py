"""PS3 (webMAN MOD) and Switch (Switch Assistant) protocols."""

from __future__ import annotations

import json
from pathlib import Path

import aiohttp
from aiohttp import web
import pytest

from custom_components.gaming_hub.protocols import switch_assistant as sa
from custom_components.gaming_hub.protocols.webman import (
    WebmanClient,
    WebmanError,
    parse_cpursx,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_cpursx_in_game() -> None:
    status = parse_cpursx((FIXTURES / "webman_cpursx_ingame.html").read_text())
    assert status.in_game
    assert (status.title_id, status.title) == ("BLES01807", "Grand Theft Auto V")
    assert status.icon_path == "/dev_hdd0/game/BLES01807/ICON0.PNG"
    assert (status.cpu_temperature, status.rsx_temperature, status.fan_speed) == (62, 55, 39)
    assert status.play_time == 3723
    assert status.firmware == "4.91 CEX Cobra 8.4"
    assert status.mac == "00:1F:A7:12:34:56"
    assert (status.ip, status.network) == ("192.168.1.30", "LAN")
    assert (status.memory_free, status.hdd_free) == (109.7, 117.5)
    assert (status.fan_mode, status.fan_target) == ("dynamic", 68)
    assert status.uptime == 1 * 86400 + 2 * 3600 + 10 * 60
    assert status.runtime == 12 * 86400 + 3 * 3600 + 4 * 60 + 5
    assert status.power_on_count == 1234


def test_parse_cpursx_on_xmb() -> None:
    status = parse_cpursx((FIXTURES / "webman_cpursx_xmb.html").read_text())
    assert not status.in_game
    assert status.title is None and status.title_id is None and status.icon_path is None
    assert (status.cpu_temperature, status.rsx_temperature, status.fan_speed) == (48, 44, 25)
    assert status.play_time is None
    assert status.firmware == "4.91 CEX PS3HEN 3.4.0"
    assert status.mac == "00:1F:A7:AB:CD:EF"
    assert status.network == "WLAN"
    assert (status.fan_mode, status.fan_target) == ("syscon", None)
    assert status.uptime == 600


def test_parse_cpursx_tolerates_garbage() -> None:
    assert parse_cpursx("<html>nothing</html>") == parse_cpursx("")


@pytest.mark.usefixtures("socket_enabled")
async def test_webman_client_commands() -> None:
    calls: list[str] = []
    page = (FIXTURES / "webman_cpursx_ingame.html").read_text()

    async def handler(request: web.Request) -> web.StreamResponse:
        calls.append(request.path_qs)
        if request.path == "/cpursx.ps3":
            return web.Response(text=page, content_type="text/html")
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/{tail:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            client = WebmanClient(session, "127.0.0.1", port)
            assert (await client.async_get_status()).title == "Grand Theft Auto V"
            assert await client.async_ping()
            await client.async_notify("Plus que 5 min & au lit")
            await client.async_shutdown()
            await client.async_restart()
            assert client.file_url("/dev_hdd0/game/A B/ICON0.PNG") == (
                f"http://127.0.0.1:{port}/dev_hdd0/game/A%20B/ICON0.PNG"
            )
    finally:
        await runner.cleanup()
    assert calls == [
        "/cpursx.ps3",
        "/cpursx_ps3",
        "/popup.ps3?Plus%20que%205%20min%20%26%20au%20lit",
        "/shutdown.ps3",
        "/restart.ps3",
    ]


@pytest.mark.usefixtures("socket_enabled")
async def test_webman_client_offline() -> None:
    async with aiohttp.ClientSession() as session:
        client = WebmanClient(session, "127.0.0.1", 9, timeout=1)
        with pytest.raises(WebmanError):
            await client.async_get_status()
        assert not await client.async_ping()


def test_switch_topics() -> None:
    assert sa.sanitize_client_id("switch-ha-1a2b") == "switch_ha_1a2b"
    assert sa.state_topic("switch-ha-1a2b", "battery") == "switch_ha/switch_ha_1a2b/battery"
    assert sa.popup_topic("switch-ha-1a2b") == "switch_ha/switch_ha_1a2b/notify/popup"
    assert sa.command_topic("homeassistant") == "homeassistant/command"
    assert sa.client_id_from_topic("switch_ha/switch_ha_1a2b/current_game_id") == "switch_ha_1a2b"
    assert sa.client_id_from_topic("homeassistant/status") is None
    assert json.loads(sa.popup_payload("Dodo")) == {"title": "Home Assistant", "message": "Dodo"}


def test_switch_state_values_and_liveness() -> None:
    state = sa.SwitchAssistantState("switch-ha-1a2b")
    base = "switch_ha/switch_ha_1a2b/"
    # Retained values from the broker give data but not liveness.
    assert state.handle_state(base + "game_running", "ON", retained=True, now=0)
    state.handle_state(base + "current_game", "Mario Kart 8 Deluxe", retained=True, now=0)
    state.handle_state(base + "current_game_id", "0100152000022000", retained=True, now=0)
    state.handle_state(base + "battery", "87", retained=True, now=0)
    state.handle_state(base + "charging", "ON", retained=True, now=0)
    assert not state.is_online(0)
    assert (state.title, state.title_id) == ("Mario Kart 8 Deluxe", "0100152000022000")
    assert (state.battery, state.charging) == (87.0, True)
    # Other consoles, HA birth messages and retained heartbeats are ignored.
    assert not state.handle_state("switch_ha/other/battery", "1", retained=False, now=1)
    assert not state.handle_status("online", retained=False, now=1)
    heartbeat = json.dumps({"client_id": "switch-ha-1a2b", "status": "online"})
    assert not state.handle_status(heartbeat, retained=True, now=1)
    assert not state.is_online(1)
    # A live heartbeat brings it online until three heartbeats are missed.
    assert state.handle_status(heartbeat, retained=False, now=10)
    assert state.is_online(10 + sa.HEARTBEAT_TIMEOUT)
    assert not state.is_online(11 + sa.HEARTBEAT_TIMEOUT)
    offline = json.dumps({"client_id": "switch-ha-1a2b", "status": "offline"})
    state.handle_status(heartbeat, retained=False, now=20)
    assert state.handle_status(offline, retained=False, now=21)
    assert not state.is_online(21)
    # Everything else the sysmodule publishes.
    for sensor, value in (
        ("battery_health", "92.5"),
        ("battery_voltage", "4123"),
        ("charger_type", "enough_power"),
        ("backlight", "OFF"),
        ("volume", "40"),
        ("audio_target", "headphone"),
        ("player_1_controller", "handheld"),
        ("player_2_controller", "none"),
        ("screen_rtsp_url", "unknown"),
    ):
        state.handle_state(base + sensor, value, retained=True, now=22)
    assert (state.battery_health, state.battery_voltage, state.charger) == (
        92.5,
        4123.0,
        "enough_power",
    )
    assert (state.screen_on, state.volume, state.audio_output) == (False, 40.0, "headphone")
    assert state.players == {"player_1": "handheld"}
    assert state.stream_url is None
    state.handle_state(base + "screen_rtsp_url", "rtsp://10.0.0.4:6666/", retained=False, now=23)
    assert state.stream_url == "rtsp://10.0.0.4:6666/"
    # Back on the home menu: no game.
    state.handle_state(base + "game_running", "OFF", retained=False, now=30)
    assert state.is_online(30)
    assert state.title is None and state.title_id is None
