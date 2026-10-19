"""Hostile input: what a device on the local network or an MQTT client could send."""

from __future__ import annotations

import asyncio
import json
import time

import aiohttp
from aiohttp import web
import pytest

from custom_components.gaming_hub.protocols import ddp, remoteplay, webman
from custom_components.gaming_hub.protocols import switch_assistant as sa
from custom_components.gaming_hub.protocols.psn import parse_status

from .test_protocol_ps5 import CREDS, FakeDdpConsole

network = pytest.mark.usefixtures("socket_enabled")


# --- PS3: webMAN page ------------------------------------------------------


@pytest.mark.parametrize(
    "prefix",
    [
        'href="/setup.ps3">',  # used to backtrack for minutes (event loop frozen)
        "MEM:",
        "HDD:",
        'cpursx.ps3?mode">',
        'cpursx.ps3?up">',
        "Runtime:",
        'title="Play">',
        '<img src="',
        "",
    ],
)
@pytest.mark.parametrize("filler", [" ", "1 ", "1", "a<"])
def test_cpursx_parsing_stays_fast_on_hostile_pages(prefix: str, filler: str) -> None:
    page = (prefix + filler * webman.MAX_PAGE)[: webman.MAX_PAGE] + prefix
    start = time.perf_counter()
    webman.parse_cpursx(page)
    assert time.perf_counter() - start < 2


@network
async def test_webman_rejects_huge_pages_and_command_chaining() -> None:
    calls: list[str] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        calls.append(request.raw_path)
        if request.path == "/cpursx.ps3":
            return web.Response(body=b"x" * (webman.MAX_PAGE + 1))
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
            client = webman.WebmanClient(session, "127.0.0.1", port)
            with pytest.raises(webman.WebmanError):
                await client.async_get_status()
            await client.async_notify("Coucou;/shutdown.ps3" + "!" * 500)
    finally:
        await runner.cleanup()
    popup = calls[-1]  # as sent on the wire
    assert ";" not in popup and "%3B" not in popup.upper()
    assert popup.startswith("/popup.ps3?Coucou,/shutdown.ps3")
    assert popup.count("!") == webman.MAX_POPUP - len("Coucou;/shutdown.ps3")


# --- PS5: DDP and Remote Play ------------------------------------------------


@network
async def test_ddp_ignores_answers_from_another_address() -> None:
    """The console is queried on 127.0.0.2; an answer coming from 127.0.0.1 is ignored."""
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: FakeDdpConsole("200 Ok"), local_addr=("0.0.0.0", 0)
    )
    port = transport.get_extra_info("sockname")[1]
    try:
        assert await ddp.async_get_status("127.0.0.2", port=port, timeout=0.5) is None
        assert await ddp.async_get_status("127.0.0.1", port=port, timeout=1) is not None
    finally:
        transport.close()


def test_ddp_answer_is_bounded() -> None:
    lines = [f"field-{index}:{'v' * 1000}" for index in range(100)]
    response = ddp.parse_response(("HTTP/1.1 200 Ok\n" + "\n".join(lines)).encode(), "10.0.0.5")
    assert response is not None
    assert len(response.fields) == 32
    assert max(len(value) for value in response.fields.values()) == 255


@network
@pytest.mark.parametrize(
    "answer",
    [
        b"HTTP/1.1 200 OK\r\nRP-Nonce: AAAA\r\nContent-Length: 99999999\r\n\r\n",
        b"HTTP/1.1 200 OK\r\nContent-Length: -1\r\n\r\n",
        b"HTTP/1.1 200 OK\r\n" + b"X: " + b"y" * 100_000 + b"\r\n\r\n",
    ],
)
async def test_remote_play_refuses_oversized_answers(answer: bytes) -> None:
    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await reader.readuntil(b"\r\n\r\n")
        writer.write(answer)
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        with pytest.raises(remoteplay.RemotePlayError) as err:
            await remoteplay.async_standby("127.0.0.1", CREDS, port=port, timeout=2)
    finally:
        server.close()
        await server.wait_closed()
    assert err.value.reason == "protocol"


# --- Switch: MQTT ------------------------------------------------------------


def test_switch_ignores_unknown_topics_and_bounds_values() -> None:
    state = sa.SwitchAssistantState("switch-ha-1a2b")
    base = "switch_ha/switch_ha_1a2b/"
    for index in range(1000):
        assert not state.handle_state(base + f"junk_{index}", "x", retained=False, now=0)
    assert state.values == {}
    state.handle_state(base + "current_game", "x" * 10_000, retained=False, now=0)
    assert len(state.values["current_game"]) == sa.MAX_VALUE


@pytest.mark.parametrize(
    ("title_id", "expected"),
    [
        ("0100152000022000", "0100152000022000"),
        ("0100abcdef012345", "0100ABCDEF012345"),
        ("../../admin", None),
        ("0100152000022000/../x", None),
        ("123", None),
    ],
)
def test_switch_title_id_must_be_an_application_id(title_id: str, expected: str | None) -> None:
    state = sa.SwitchAssistantState("s")
    state.handle_state("switch_ha/s/game_running", "ON", retained=False, now=0)
    state.handle_state("switch_ha/s/current_game_id", title_id, retained=False, now=0)
    assert state.title_id == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("rtsp://192.168.1.40:6666/", True),
        ("http://192.168.1.40/", False),
        ("file:///etc/passwd", False),
        ("rtsp://user:secret@192.168.1.40/", False),
        ("rtsp://192.168.1.40/ -i file:/etc/passwd", False),
        ("rtsp:///nohost", False),
        ("rtsp://192.168.1.40/\nx", False),
    ],
)
def test_switch_stream_url_is_plain_rtsp(url: str, expected: bool) -> None:
    state = sa.SwitchAssistantState("s")
    state.handle_state("switch_ha/s/screen_rtsp_url", url, retained=False, now=0)
    assert (state.stream_url == url) is expected


def test_switch_popup_is_valid_json() -> None:
    payload = sa.popup_payload('a"}, "x": {"', 'b\n"c')
    assert json.loads(payload) == {"title": 'b\n"c', "message": 'a"}, "x": {"'}


# --- PlayStation Network -------------------------------------------------------


def test_psn_artwork_must_be_https_and_text_is_bounded() -> None:
    status = parse_status(
        {
            "profile": {
                "accountId": "1",
                "avatarUrls": [{"size": "l", "avatarUrl": "http://x/a.png"}],
            }
        },
        {
            "basicPresence": {
                "primaryPlatformInfo": {"onlineStatus": "online", "platform": "PS5"},
                "gameTitleInfoList": [
                    {
                        "titleName": "t" * 1000,
                        "conceptIconUrl": "http://192.168.1.1/admin",
                        "npTitleIconUrl": "file:///etc/passwd",
                    }
                ],
            }
        },
    )
    session = status.sessions["PS5"]
    assert session.image is None
    assert status.avatar_url is None
    assert len(session.title) == 255
