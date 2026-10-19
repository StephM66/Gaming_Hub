"""PS5 protocols: byte-exact against playactor, then against a simulated console."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
from pathlib import Path
import struct

import pytest

from custom_components.gaming_hub.protocols import ddp, remoteplay
from custom_components.gaming_hub.protocols.remoteplay import (
    AuthCodec,
    Ps5Credentials,
    RemotePlayError,
)

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "remoteplay_vectors.json").read_text())
INPUTS = VECTORS["inputs"]
CLIENT_NONCE = bytes.fromhex(INPUTS["client_nonce"])
SERVER_NONCE = bytes.fromhex(INPUTS["server_nonce"])
CREDS = Ps5Credentials(regist_key=INPUTS["regist_key"], rp_key=INPUTS["rp_key"])


# --- Byte-exact port --------------------------------------------------------


def test_crypto_primitives_match_playactor() -> None:
    assert remoteplay._iv(CLIENT_NONCE, 0).hex() == VECTORS["iv0"]
    assert remoteplay._iv(SERVER_NONCE, 5).hex() == VECTORS["iv5"]
    assert remoteplay.pin_seed(12345678, 1).hex() == VECTORS["pin_seed"]
    assert remoteplay.auth_nonce(SERVER_NONCE).hex() == VECTORS["auth_nonce"]
    assert (
        remoteplay.auth_seed(bytes.fromhex(INPUTS["rp_key"]), SERVER_NONCE).hex()
        == VECTORS["auth_seed"]
    )


def test_registration_body_matches_playactor() -> None:
    body, key, iv = remoteplay.build_registration_body(
        INPUTS["account_id"], INPUTS["pin"], CLIENT_NONCE
    )
    assert body.hex() == VECTORS["regist_body"]
    answer = remoteplay._cfb(key, iv, bytes.fromhex(VECTORS["regist_response"]), decrypt=True)
    assert answer.hex() == VECTORS["regist_response_plain"]


def test_control_headers_and_packets_match_playactor() -> None:
    codec = AuthCodec(bytes.fromhex(INPUTS["rp_key"]), SERVER_NONCE)
    headers = remoteplay.control_headers(codec, CREDS)
    assert headers["RP-Auth"] == VECTORS["rp_auth"]
    assert headers["RP-Did"] == VECTORS["rp_did"]
    assert headers["RP-OSType"] == VECTORS["rp_ostype"]
    assert headers["RP-StartBitrate"] == VECTORS["rp_startbitrate"]
    assert headers["RP-StreamingType"] == VECTORS["rp_streamingtype"]
    assert codec.packet(remoteplay.PACKET_PASSCODE, b"1234").hex() == VECTORS["passcode_packet"]
    assert codec.packet(remoteplay.PACKET_STANDBY).hex() == VECTORS["standby_packet"]


def test_credentials_and_account_id() -> None:
    assert CREDS.user_credential == VECTORS["credential"]
    assert ddp.regist_key_to_credential(INPUTS["regist_key"]) == VECTORS["credential"]
    assert remoteplay.parse_account_id(INPUTS["user_id"]) == VECTORS["account_b64"]
    assert remoteplay.parse_account_id(VECTORS["account_b64"]) == VECTORS["account_b64"]
    with pytest.raises(RemotePlayError):
        remoteplay.parse_account_id("not an id")
    with pytest.raises(RemotePlayError):
        Ps5Credentials(regist_key="zz", rp_key=INPUTS["rp_key"])


def test_ddp_messages_match_playactor() -> None:
    assert ddp.build_message("SRCH").decode() == VECTORS["srch"]
    assert ddp.build_wake_message(VECTORS["credential"]).decode() == VECTORS["wake"]


def test_ddp_parse() -> None:
    awake = ddp.parse_response(
        b"HTTP/1.1 200 Ok\nhost-id:A1B2C3D4E5F6\nhost-type:PS5\nhost-name:Salon\n"
        b"system-version:09400001\nrunning-app-name:Astro Bot\nrunning-app-titleid:PPSA01234\n",
        "10.0.0.5",
    )
    assert awake is not None and awake.awake
    assert (awake.host_id, awake.host_name, awake.host_type) == ("A1B2C3D4E5F6", "Salon", "PS5")
    assert (awake.running_app_name, awake.running_app_titleid) == ("Astro Bot", "PPSA01234")
    standby = ddp.parse_response(b"HTTP/1.1 620 Server Standby\nhost-id:X\n", "10.0.0.5")
    assert standby is not None and not standby.awake
    assert ddp.parse_response(ddp.build_message("SRCH"), "10.0.0.5") is None


# --- Simulated console ------------------------------------------------------

# Loopback servers stand in for the console; Home Assistant's test plugin blocks sockets.
network = pytest.mark.usefixtures("socket_enabled")


class FakeDdpConsole(asyncio.DatagramProtocol):
    def __init__(self, status: str) -> None:
        self.status = status
        self.received: list[bytes] = []
        self.transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        self.received.append(data)
        if data.startswith(b"SRCH") and self.status != "silent":
            self.transport.sendto(
                f"HTTP/1.1 {self.status}\nhost-id:A1B2C3D4E5F6\nhost-type:PS5\n".encode(), addr
            )


async def _ddp_console(status: str) -> tuple[FakeDdpConsole, asyncio.DatagramTransport, int]:
    transport, protocol = await asyncio.get_running_loop().create_datagram_endpoint(
        lambda: FakeDdpConsole(status), local_addr=("127.0.0.1", 0)
    )
    return protocol, transport, transport.get_extra_info("sockname")[1]


@network
async def test_ddp_status_awake_standby_and_silent() -> None:
    for status, expected in (("200 Ok", True), ("620 Server Standby", False)):
        _, transport, port = await _ddp_console(status)
        try:
            response = await ddp.async_get_status("127.0.0.1", port=port, timeout=1)
        finally:
            transport.close()
        assert response is not None and response.awake is expected
    _, transport, port = await _ddp_console("silent")
    try:
        assert await ddp.async_get_status("127.0.0.1", port=port, timeout=0.3) is None
    finally:
        transport.close()


@network
async def test_ddp_wake_sends_credential() -> None:
    console, transport, port = await _ddp_console("620 Server Standby")
    try:
        await ddp.async_wake("127.0.0.1", "305441741", port=port, repeat=2)
        await asyncio.sleep(0.05)
    finally:
        transport.close()
    assert console.received == [ddp.build_wake_message("305441741")] * 2


class FakeRemotePlayConsole:
    """Minimal PS5 control channel: init, ctrl, login (+ passcode), standby."""

    def __init__(self, *, passcode: str | None = None, reject: str | None = None) -> None:
        self.passcode = passcode
        self.reject = reject
        self.events: list[str] = []
        self.server: asyncio.Server | None = None

    async def start(self) -> int:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = (await reader.readuntil(b"\r\n\r\n")).decode()
        request_line, *header_lines = head.split("\r\n")
        headers = {
            key.lower(): value.strip()
            for key, _, value in (line.partition(":") for line in header_lines if line)
        }
        path = request_line.split(" ")[1]
        # The client may give up early (e.g. missing passcode).
        with contextlib.suppress(asyncio.IncompleteReadError, ConnectionError):
            await self._route(path, reader, writer, headers)
        writer.close()

    async def _route(self, path: str, reader, writer, headers) -> None:
        if path.endswith("/rgst"):
            await self._register(reader, writer, headers)
        elif path.endswith("/init"):
            self.events.append("init")
            assert headers["rp-registkey"] == CREDS.regist_key
            nonce = base64.b64encode(SERVER_NONCE).decode()
            writer.write(
                f"HTTP/1.1 200 OK\r\nRP-Nonce: {nonce}\r\nContent-Length: 0\r\n\r\n".encode()
            )
        elif path.endswith("/ctrl"):
            await self._control(reader, writer, headers)
        await writer.drain()

    async def _register(self, reader, writer, headers) -> None:
        body = await reader.readexactly(int(headers["content-length"]))
        self.events.append("register")
        if self.reject:
            writer.write(
                f"HTTP/1.1 403 Forbidden\r\nRP-Application-Reason: {self.reject}\r\n"
                "Content-Length: 0\r\n\r\n".encode()
            )
            return
        assert len(body) > 480 and body[:0xC7] == b"A" * 0xC7
        answer = (
            f"PS5-RegistKey: {CREDS.regist_key}\r\nRP-Key: {CREDS.rp_key}\r\n"
            "PS5-Nickname: PS5-123\r\n"
        ).encode()
        # The test pairs with a fixed nonce, see test_register_*.
        key = remoteplay.pin_seed(int(INPUTS["pin"]), 1)
        encrypted = remoteplay._cfb(key, remoteplay._iv(CLIENT_NONCE, 0), answer)
        writer.write(
            f"HTTP/1.1 200 OK\r\nContent-Length: {len(encrypted)}\r\n\r\n".encode() + encrypted
        )

    async def _control(self, reader, writer, headers) -> None:
        codec = AuthCodec(bytes.fromhex(CREDS.rp_key), SERVER_NONCE)
        regist = bytes.fromhex(CREDS.regist_key)
        assert codec.decrypt(base64.b64decode(headers["rp-auth"])) == regist + bytes(
            16 - len(regist)
        )
        assert codec.decrypt(base64.b64decode(headers["rp-did"]))[:10] == remoteplay._DID[:10]
        assert codec.decrypt(base64.b64decode(headers["rp-ostype"])) == b"Win10.0.0"
        codec.decrypt(base64.b64decode(headers["rp-startbitrate"]))
        assert codec.decrypt(base64.b64decode(headers["rp-streamingtype"])) == b"\x01\x00\x00\x00"
        # Server side: its encrypt counter mirrors the client's decrypt counter.
        server = AuthCodec(bytes.fromhex(CREDS.rp_key), SERVER_NONCE)
        server_type = base64.b64encode(server.encrypt(b"\x00\x00\x00\x02")).decode()
        writer.write(f"HTTP/1.1 200 OK\r\nRP-Server-Type: {server_type}\r\n\r\n".encode())
        self.events.append("ctrl")

        async def read_packet() -> tuple[int, bytes]:
            length, packet_type, _ = struct.unpack(">IHH", await reader.readexactly(8))
            payload = await reader.readexactly(length) if length else b""
            return packet_type, codec.decrypt(payload) if payload else b""

        packet_type, _ = await read_packet()
        assert packet_type == remoteplay.PACKET_LOGIN
        writer.write(server.packet(remoteplay.RESPONSE_HEARTBEAT))
        assert (await read_packet())[0] == remoteplay.PACKET_HEARTBEAT
        if self.passcode:
            writer.write(server.packet(remoteplay.RESPONSE_PASSCODE_REQUIRED))
            packet_type, payload = await read_packet()
            assert packet_type == remoteplay.PACKET_PASSCODE
            ok = payload.decode() == self.passcode
            writer.write(server.packet(remoteplay.RESPONSE_LOGIN, b"\x00" if ok else b"\x01"))
            if not ok:
                return
        else:
            writer.write(server.packet(remoteplay.RESPONSE_LOGIN, b"\x00"))
        self.events.append("login")
        packet_type, _ = await read_packet()
        if packet_type == remoteplay.PACKET_STANDBY:
            self.events.append("standby")


@network
async def test_standby_full_sequence() -> None:
    console = FakeRemotePlayConsole()
    port = await console.start()
    try:
        await remoteplay.async_standby("127.0.0.1", CREDS, port=port, timeout=2)
    finally:
        await console.stop()
    assert console.events == ["init", "ctrl", "login", "standby"]


@network
async def test_standby_with_passcode() -> None:
    console = FakeRemotePlayConsole(passcode="1234")
    port = await console.start()
    try:
        with pytest.raises(RemotePlayError) as err:
            await remoteplay.async_standby("127.0.0.1", CREDS, port=port, timeout=2)
        assert err.value.reason == "passcode_required"
        with pytest.raises(RemotePlayError) as err:
            await remoteplay.async_standby("127.0.0.1", CREDS, "9999", port=port, timeout=2)
        assert err.value.reason == "passcode_invalid"
        await remoteplay.async_standby("127.0.0.1", CREDS, "1234", port=port, timeout=2)
    finally:
        await console.stop()
    assert console.events[-1] == "standby"


@network
async def test_standby_unreachable() -> None:
    console = FakeRemotePlayConsole()
    port = await console.start()
    await console.stop()
    with pytest.raises(RemotePlayError) as err:
        await remoteplay.async_standby("127.0.0.1", CREDS, port=port, timeout=1)
    assert err.value.reason == "cannot_connect"


class _Res3(asyncio.DatagramProtocol):
    def connection_made(self, transport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr) -> None:
        if data == b"SRC3":
            self.transport.sendto(b"RES3\n", addr)


async def _pairing_console(reject: str | None = None):
    console = FakeRemotePlayConsole(reject=reject)
    port = await console.start()
    transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
        _Res3, local_addr=("127.0.0.1", port)
    )
    return console, transport, port


@network
async def test_register(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remoteplay.os, "urandom", lambda size: CLIENT_NONCE)
    console, transport, port = await _pairing_console()
    try:
        creds, registration = await remoteplay.async_register(
            "127.0.0.1", INPUTS["user_id"], "1234 5678", port=port, local_port=0, timeout=2
        )
    finally:
        transport.close()
        await console.stop()
    assert creds == CREDS
    assert registration["PS5-Nickname"] == "PS5-123"


@network
async def test_register_rejected_pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(remoteplay.os, "urandom", lambda size: CLIENT_NONCE)
    console, transport, port = await _pairing_console(reject="80108b09")
    try:
        with pytest.raises(RemotePlayError) as err:
            await remoteplay.async_register(
                "127.0.0.1", INPUTS["user_id"], "12345678", port=port, local_port=0, timeout=2
            )
    finally:
        transport.close()
        await console.stop()
    assert err.value.reason == "invalid_pin"


@network
async def test_register_validates_input_and_pairing_mode() -> None:
    with pytest.raises(RemotePlayError) as err:
        await remoteplay.async_register("127.0.0.1", INPUTS["user_id"], "123")
    assert err.value.reason == "invalid_pin"
    console = FakeRemotePlayConsole()
    port = await console.start()  # TCP only: nobody answers SRC3
    try:
        with pytest.raises(RemotePlayError) as err:
            await remoteplay.async_register(
                "127.0.0.1", INPUTS["user_id"], "12345678", port=port, local_port=0, timeout=0.6
            )
    finally:
        await console.stop()
    assert err.value.reason == "not_in_pairing_mode"
