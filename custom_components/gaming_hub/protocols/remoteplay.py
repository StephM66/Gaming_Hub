"""PS5 Remote Play control channel: PIN pairing and standby.

Only the control channel is implemented (TCP 9295, no video stream). It is
enough to pair with a PIN and to put the console in rest mode, which is all a
home automation hub needs. Ported from playactor (ISC licence,
https://github.com/dhleong/playactor); see NOTICE.md.

Sequence for standby:

1. ``GET /sie/ps5/rp/sess/init`` with the registration key; the console answers
   with a 16-byte nonce (``RP-Nonce``).
2. ``GET /sie/ps5/rp/sess/ctrl`` with headers encrypted with AES-128-CFB. The
   key is derived from ``RP-Key`` and the nonce, the IV from a per-message
   counter. The TCP connection then carries length-prefixed packets.
3. Login packet (with the PSN login passcode if the console asks for it), then
   the standby packet; the console closes the connection when it goes to sleep.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .ddp import local_address, resolve_ipv4
from .rp_keys import (
    PS5_AERO_KEYS,
    PS5_AUTH_NONCE_KEYS,
    PS5_AUTH_SEED_KEYS,
    PS5_INIT_KEYS,
)

RP_PORT = 9295
RP_VERSION = "1.0"
USER_AGENT = "remoteplay Windows"
CLIENT_TYPE = "dabfa2ec873de5839bee8d3f4c0239c4282c07c25c6077a2931afcf0adc0d34f"
_HMAC_KEY = bytes.fromhex("464687b349ca8ce859c5270f5d7a69d6")
_NONCE_LENGTH = 16
_PADDING_LENGTH = 480
# Answers and packets of the control channel are tiny; refuse anything big.
_MAX_BODY = 64 * 1024
_DID = bytes([0x00, 0x18, 0x00, 0x00, 0x00, 0x07, 0x00, 0x40, 0x00, 0x80]) + bytes(22)
_OS_TYPE = b"Win10.0.0"

# Control channel packet types.
PACKET_LOGIN = 0x05
PACKET_STANDBY = 0x50
PACKET_HEARTBEAT = 0x1FE
PACKET_PASSCODE = 0x8004
RESPONSE_PASSCODE_REQUIRED = 0x04
RESPONSE_LOGIN = 0x05
RESPONSE_HEARTBEAT = 0xFE

_REASONS = {
    "80108b09": "invalid_pin",
    "80108b02": "invalid_account",
    "80108b10": "in_use",
    "80108b15": "crashed",
    "80108b11": "version_mismatch",
}


class RemotePlayError(Exception):
    """Remote Play failure; ``reason`` is a stable key for translations."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class Ps5Credentials:
    """What pairing returns and what wake/standby need."""

    regist_key: str
    rp_key: str

    def __post_init__(self) -> None:
        try:
            if len(bytes.fromhex(self.rp_key)) != _NONCE_LENGTH:
                raise ValueError
            bytes.fromhex(self.regist_key).decode("ascii")
        except (ValueError, UnicodeDecodeError) as err:
            raise RemotePlayError("invalid_credentials") from err

    @property
    def user_credential(self) -> str:
        """DDP wake-up credential."""
        return str(int(bytes.fromhex(self.regist_key).decode("ascii"), 16))

    @classmethod
    def from_registration(cls, registration: dict[str, str]) -> Ps5Credentials:
        """Build from a pairing answer (or a playactor ``registration`` map)."""
        regist_key = registration.get("PS5-RegistKey") or registration.get("PS4-RegistKey")
        rp_key = registration.get("RP-Key")
        if not regist_key or not rp_key:
            raise RemotePlayError("invalid_credentials", "missing RegistKey or RP-Key")
        return cls(regist_key=regist_key, rp_key=rp_key)


def parse_account_id(value: str) -> str:
    """Normalise a PSN account ID to the base64 form pairing expects.

    Accepts the decimal ID (as shown by the PlayStation Network integration)
    or the 8-byte little-endian base64 form used by Remote Play tools.
    """
    value = value.strip()
    if value.isdigit():
        number = int(value)
        if number >= 1 << 64:
            raise RemotePlayError("invalid_account")
        return base64.b64encode(number.to_bytes(8, "little")).decode()
    try:
        raw = base64.b64decode(value, validate=True)
    except ValueError as err:
        raise RemotePlayError("invalid_account") from err
    if len(raw) != 8:
        raise RemotePlayError("invalid_account")
    return value


# --- Crypto -----------------------------------------------------------------


def _iv(nonce: bytes, counter: int) -> bytes:
    digest = hmac.new(_HMAC_KEY, nonce + counter.to_bytes(8, "big"), hashlib.sha256)
    return digest.digest()[:_NONCE_LENGTH]


def _cfb(key: bytes, iv: bytes, data: bytes, *, decrypt: bool = False) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CFB(iv))
    context = cipher.decryptor() if decrypt else cipher.encryptor()
    return context.update(data) + context.finalize()


def pin_seed(pin: int, key_offset: int) -> bytes:
    """AES key of the pairing exchange."""
    seed = bytearray(PS5_INIT_KEYS[(i * 0x20 + key_offset) % len(PS5_INIT_KEYS)] for i in range(16))
    seed[12:16] = bytes(a ^ b for a, b in zip(seed[12:16], pin.to_bytes(4, "big"), strict=True))
    return bytes(seed)


def _aeropause(nonce: bytes, padding: bytes) -> bytes:
    offset = padding[0] >> 3
    return bytes(
        ((nonce[i] ^ PS5_AERO_KEYS[i * 0x20 + offset]) + 0xD3 + i) & 0xFF for i in range(16)
    )


def auth_nonce(server_nonce: bytes) -> bytes:
    """Transform the console nonce into the IV nonce of the control channel."""
    offset = (server_nonce[0] >> 3) * 0x70
    return bytes(
        ((server_nonce[i] - 0x2D - i) ^ PS5_AUTH_NONCE_KEYS[offset + i]) & 0xFF for i in range(16)
    )


def auth_seed(rp_key: bytes, server_nonce: bytes) -> bytes:
    """AES key of the control channel."""
    offset = (server_nonce[7] >> 3) * 0x70
    return bytes(
        (((rp_key[i] + 0x18 + i) & 0xFF) ^ server_nonce[i] ^ PS5_AUTH_SEED_KEYS[offset + i])
        for i in range(16)
    )


class AuthCodec:
    """Control channel cipher: one AES-CFB stream per message, counter-based IV."""

    def __init__(self, rp_key: bytes, server_nonce: bytes) -> None:
        self._key = auth_seed(rp_key, server_nonce)
        self._nonce = auth_nonce(server_nonce)
        self._encrypt_counter = 0
        self._decrypt_counter = 0

    def encrypt(self, data: bytes) -> bytes:
        iv = _iv(self._nonce, self._encrypt_counter)
        self._encrypt_counter += 1
        return _cfb(self._key, iv, data)

    def decrypt(self, data: bytes) -> bytes:
        iv = _iv(self._nonce, self._decrypt_counter)
        self._decrypt_counter += 1
        return _cfb(self._key, iv, data, decrypt=True)

    def packet(self, packet_type: int, payload: bytes = b"") -> bytes:
        """Encode an outgoing packet; empty payloads are sent in clear."""
        header = struct.pack(">IHH", len(payload), packet_type, 0)
        return header + (self.encrypt(payload) if payload else b"")


def build_registration_body(account_id: str, pin: str, nonce: bytes) -> tuple[bytes, bytes, bytes]:
    """Pairing request body, plus the key and IV to decrypt the answer."""
    padding = bytearray(b"A" * _PADDING_LENGTH)
    key = pin_seed(int(pin), padding[0x18D] & 0x1F)
    aero = _aeropause(nonce, padding)
    padding[0xC7:0xCF] = aero[8:16]
    padding[0x191:0x199] = aero[0:8]
    iv = _iv(nonce, 0)
    record = f"Client-Type: {CLIENT_TYPE}\r\nNp-AccountId: {account_id}\r\n".encode()
    return bytes(padding) + _cfb(key, iv, record), key, iv


def parse_body(body: bytes) -> dict[str, str]:
    """Parse ``Key: value`` lines."""
    result: dict[str, str] = {}
    for line in body.decode("utf-8", "replace").split("\r\n"):
        key, sep, value = line.partition(":")
        if sep and value.strip():
            result[key.strip()] = value.strip()
    return result


# --- Transport --------------------------------------------------------------


@dataclass(slots=True)
class _Response:
    status: int
    headers: dict[str, str]
    body: bytes


async def _read_response(reader: asyncio.StreamReader, *, read_body: bool) -> _Response:
    try:
        head = await reader.readuntil(b"\r\n\r\n")
    except asyncio.LimitOverrunError as err:
        raise RemotePlayError("protocol", "headers too large") from err
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        raise RemotePlayError("protocol", f"unexpected status line {lines[0][:80]!r}")
    headers: dict[str, str] = {}
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep:
            headers[key.strip().lower()] = value.strip()
    length = headers.get("content-length", "0").strip() or "0"
    if not length.isdigit() or int(length) > _MAX_BODY:
        raise RemotePlayError("protocol", f"unexpected content length {length[:20]!r}")
    body = b""
    if read_body and int(length):
        body = await reader.readexactly(int(length))
    return _Response(int(parts[1]), headers, body)


def _raise_for_status(response: _Response) -> None:
    if response.status < 300:
        return
    code = response.headers.get("rp-application-reason", "").lower()
    raise RemotePlayError(_REASONS.get(code, "rejected"), f"HTTP {response.status} {code}")


def _request(
    method: str,
    path: str,
    host: str,
    headers: dict[str, str],
    *,
    length: int = 0,
    keep_alive: bool = False,
) -> bytes:
    lines = [
        f"{method} {path} HTTP/1.1",
        f"Host: {host}:{RP_PORT}",
        f"User-Agent: {USER_AGENT}",
        f"Connection: {'keep-alive' if keep_alive else 'close'}",
        f"Content-Length: {length}",
        *(f"{key}: {value}" for key, value in headers.items()),
    ]
    return ("\r\n".join(lines) + "\r\n\r\n").encode()


async def _open_connection(host: str, port: int, timeout: float):
    try:
        return await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, TimeoutError) as err:
        raise RemotePlayError("cannot_connect", str(err)) from err


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()


class _SearchProtocol(asyncio.DatagramProtocol):
    def __init__(self, console: str) -> None:
        self.answered = asyncio.Event()
        self._console = console

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        if addr[0] == self._console and data.startswith(b"RES3"):
            self.answered.set()


async def _announce_registration(host: str, port: int, local_port: int, timeout: float) -> None:
    """Send ``SRC3`` and wait for ``RES3``; the console rejects pairing otherwise."""
    loop = asyncio.get_running_loop()
    try:
        console = await resolve_ipv4(host)
        local = local_address(console)
    except OSError as err:
        raise RemotePlayError("cannot_connect", str(err)) from err
    try:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _SearchProtocol(console), local_addr=(local, local_port)
        )
    except OSError:
        transport, protocol = await loop.create_datagram_endpoint(
            lambda: _SearchProtocol(console), local_addr=(local, 0)
        )
    try:
        for _ in range(3):
            transport.sendto(b"SRC3", (console, port))
            try:
                await asyncio.wait_for(protocol.answered.wait(), timeout / 3)
            except TimeoutError:
                continue
            return
    finally:
        transport.close()
    raise RemotePlayError("not_in_pairing_mode")


async def async_register(
    host: str,
    account_id: str,
    pin: str,
    *,
    port: int = RP_PORT,
    local_port: int = RP_PORT,
    timeout: float = 10.0,
) -> tuple[Ps5Credentials, dict[str, str]]:
    """Pair with a console showing a PIN (Settings > System > Remote Play > Link Device).

    Returns the credentials and the full pairing answer (nickname, MAC…).
    """
    pin = pin.strip().replace(" ", "")
    if not pin.isdigit() or len(pin) != 8:
        raise RemotePlayError("invalid_pin")
    account = parse_account_id(account_id)
    await _announce_registration(host, port, local_port, timeout)
    await asyncio.sleep(0.1)
    body, key, iv = build_registration_body(account, pin, os.urandom(_NONCE_LENGTH))
    reader, writer = await _open_connection(host, port, timeout)
    try:
        writer.write(
            _request(
                "POST", "/sie/ps5/rp/sess/rgst", host, {"RP-Version": RP_VERSION}, length=len(body)
            )
            + body
        )
        await writer.drain()
        response = await asyncio.wait_for(_read_response(reader, read_body=True), timeout)
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
        raise RemotePlayError("cannot_connect", str(err)) from err
    finally:
        await _close(writer)
    _raise_for_status(response)
    registration = parse_body(_cfb(key, iv, response.body, decrypt=True))
    return Ps5Credentials.from_registration(registration), registration


async def _session_nonce(host: str, port: int, creds: Ps5Credentials, timeout: float) -> bytes:
    reader, writer = await _open_connection(host, port, timeout)
    try:
        writer.write(
            _request(
                "GET",
                "/sie/ps5/rp/sess/init",
                host,
                {"RP-RegistKey": creds.regist_key, "RP-Version": RP_VERSION},
            )
        )
        await writer.drain()
        response = await asyncio.wait_for(_read_response(reader, read_body=True), timeout)
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
        raise RemotePlayError("cannot_connect", str(err)) from err
    finally:
        await _close(writer)
    _raise_for_status(response)
    try:
        nonce = base64.b64decode(response.headers["rp-nonce"])
    except (KeyError, ValueError) as err:
        raise RemotePlayError("protocol", "missing RP-Nonce") from err
    if len(nonce) != _NONCE_LENGTH:
        raise RemotePlayError("protocol", "bad RP-Nonce length")
    return nonce


def control_headers(codec: AuthCodec, creds: Ps5Credentials) -> dict[str, str]:
    """Headers of the control request; encryption order matters (IV counter)."""

    def encrypt(data: bytes) -> str:
        return base64.b64encode(codec.encrypt(data)).decode()

    regist = bytes.fromhex(creds.regist_key)
    headers = {"RP-Auth": encrypt(regist + bytes(_NONCE_LENGTH - len(regist)))}
    headers["RP-Version"] = RP_VERSION
    headers["RP-Did"] = encrypt(_DID)
    headers["RP-ControllerType"] = "3"
    headers["RP-ClientType"] = "11"
    headers["RP-OSType"] = encrypt(_OS_TYPE)
    headers["RP-ConPath"] = "1"
    headers["RP-StartBitrate"] = encrypt(bytes(4))
    headers["RP-StreamingType"] = encrypt(struct.pack("<i", 1))
    return headers


class _ControlChannel:
    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, codec: AuthCodec
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._codec = codec

    async def send(self, packet_type: int, payload: bytes = b"") -> None:
        self._writer.write(self._codec.packet(packet_type, payload))
        await self._writer.drain()

    async def receive(self) -> tuple[int, bytes]:
        length, packet_type, _ = struct.unpack(">IHH", await self._reader.readexactly(8))
        if length > _MAX_BODY:
            raise RemotePlayError("protocol", f"packet of {length} bytes")
        payload = await self._reader.readexactly(length) if length else b""
        return packet_type, self._codec.decrypt(payload) if payload else b""

    async def receive_answer(self, *expected: int) -> tuple[int, bytes]:
        """Wait for one of ``expected``, answering heartbeats meanwhile."""
        while True:
            packet_type, payload = await self.receive()
            if packet_type == RESPONSE_HEARTBEAT:
                await self.send(PACKET_HEARTBEAT)
            elif packet_type in expected:
                return packet_type, payload

    async def login(self, passcode: str | None) -> None:
        await self.send(PACKET_LOGIN)
        packet_type, payload = await self.receive_answer(RESPONSE_LOGIN, RESPONSE_PASSCODE_REQUIRED)
        if packet_type == RESPONSE_PASSCODE_REQUIRED:
            if not passcode:
                raise RemotePlayError("passcode_required")
            await self.send(PACKET_PASSCODE, passcode.encode())
            packet_type, payload = await self.receive_answer(RESPONSE_LOGIN)
        if payload and payload[0] != 0:
            raise RemotePlayError("passcode_invalid" if payload[0] == 1 else "login_failed")


async def async_standby(
    host: str,
    creds: Ps5Credentials,
    passcode: str | None = None,
    *,
    port: int = RP_PORT,
    timeout: float = 10.0,
) -> None:
    """Put an awake console in rest mode."""
    nonce = await _session_nonce(host, port, creds, timeout)
    codec = AuthCodec(bytes.fromhex(creds.rp_key), nonce)
    reader, writer = await _open_connection(host, port, timeout)
    try:
        writer.write(
            _request(
                "GET",
                "/sie/ps5/rp/sess/ctrl",
                host,
                control_headers(codec, creds),
                keep_alive=True,
            )
        )
        await writer.drain()
        response = await asyncio.wait_for(_read_response(reader, read_body=False), timeout)
        _raise_for_status(response)
        if server_type := response.headers.get("rp-server-type"):
            codec.decrypt(base64.b64decode(server_type))  # keeps the IV counters aligned
        channel = _ControlChannel(reader, writer, codec)
        await asyncio.wait_for(channel.login(passcode), timeout)
        await channel.send(PACKET_STANDBY)
        # The console closes the connection when it goes to sleep.
        with contextlib.suppress(asyncio.IncompleteReadError, ConnectionError, TimeoutError):
            await asyncio.wait_for(channel.receive_answer(), timeout)
    except (OSError, TimeoutError, asyncio.IncompleteReadError) as err:
        raise RemotePlayError("cannot_connect", str(err)) from err
    finally:
        await _close(writer)


def credentials_from_playactor(data: dict, host_id: str | None) -> Ps5Credentials | None:
    """Credentials of one console from a playactor ``credentials.json`` (used by ps5-mqtt).

    The file maps console IDs (DDP ``host-id``) to their pairing; with a single
    console in the file, its ID does not need to match.
    """
    entries = {str(key).upper(): value for key, value in data.items() if isinstance(value, dict)}
    entry = entries.get((host_id or "").upper())
    if entry is None and len(entries) == 1:
        entry = next(iter(entries.values()))
    if entry is None or not isinstance(entry.get("registration"), dict):
        return None
    return Ps5Credentials.from_registration(entry["registration"])
