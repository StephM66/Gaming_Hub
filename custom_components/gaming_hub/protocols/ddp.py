"""PlayStation Device Discovery Protocol (DDP).

A PS5 answers an ``SRCH`` datagram on UDP 9302 with an HTTP-like status line:
``200 Ok`` when awake, ``620 Server Standby`` in rest mode. No answer means the
console is fully off or unreachable. Waking it from rest mode needs the
``user-credential`` derived from the Remote Play registration key.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import socket

PS5_DDP_PORT = 9302
PS5_DDP_VERSION = "00030010"
BROADCAST = "255.255.255.255"
STATUS_STANDBY = 620

# Fields sent with WAKEUP, identical to the official Remote Play client.
_WAKE_FIELDS = {"app-type": "r", "auth-type": "R", "client-type": "vr", "model": "w"}


@dataclass(frozen=True, slots=True)
class DdpResponse:
    """Answer of a console to SRCH."""

    address: str
    status_code: int
    fields: dict[str, str] = field(default_factory=dict)

    @property
    def awake(self) -> bool:
        """Whether the console is on (not in rest mode)."""
        return self.status_code != STATUS_STANDBY

    @property
    def host_id(self) -> str | None:
        """Console identifier (its MAC address, without separators)."""
        return self.fields.get("host-id")

    @property
    def host_name(self) -> str | None:
        """Name set on the console."""
        return self.fields.get("host-name")

    @property
    def host_type(self) -> str | None:
        """``PS5`` (or ``PS4`` for consoles answering the PS4 protocol)."""
        return self.fields.get("host-type")

    @property
    def system_version(self) -> str | None:
        """Firmware version as an integer string, e.g. ``"09400001"``."""
        return self.fields.get("system-version")

    @property
    def running_app_name(self) -> str | None:
        """Running application, when the console reports it (PS4 does, PS5 rarely)."""
        return self.fields.get("running-app-name")

    @property
    def running_app_titleid(self) -> str | None:
        """Title ID of the running application, when reported."""
        return self.fields.get("running-app-titleid")


def build_message(kind: str, data: dict[str, str] | None = None) -> bytes:
    """Build a DDP datagram (``SRCH`` or ``WAKEUP``)."""
    body = "".join(f"{key}:{value}\n" for key, value in (data or {}).items())
    return (
        f"{kind} * HTTP/1.1\n{body}device-discovery-protocol-version:{PS5_DDP_VERSION}\n"
    ).encode()


def build_wake_message(credential: str) -> bytes:
    """Build the WAKEUP datagram for a user credential."""
    return build_message("WAKEUP", {**_WAKE_FIELDS, "user-credential": credential})


def parse_response(data: bytes, address: str) -> DdpResponse | None:
    """Parse a console answer; ``None`` for anything else (e.g. our own SRCH)."""
    lines = data.decode("utf-8", "replace").splitlines()
    if not lines or not lines[0].startswith("HTTP/"):
        return None
    parts = lines[0].split(" ", 2)
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    fields: dict[str, str] = {}
    for line in lines[1:33]:  # a real answer has about ten fields
        key, sep, value = line.partition(":")
        if sep and value.strip():
            fields[key.strip().lower()[:64]] = value.strip()[:255]
    return DdpResponse(address=address, status_code=int(parts[1]), fields=fields)


def regist_key_to_credential(regist_key: str) -> str:
    """Derive the DDP ``user-credential`` from a ``PS5-RegistKey``.

    The registration key is the hex encoding of an ASCII hex string; the
    credential is that inner hex number written in decimal.
    """
    inner = bytes.fromhex(regist_key).decode("ascii")
    return str(int(inner, 16))


async def resolve_ipv4(host: str) -> str:
    """IPv4 address of a host name (or the address itself)."""
    infos = await asyncio.get_running_loop().getaddrinfo(
        host, None, family=socket.AF_INET, type=socket.SOCK_DGRAM
    )
    return infos[0][4][0]


class _Collector(asyncio.DatagramProtocol):
    def __init__(self, console: str | None) -> None:
        self.responses: dict[str, DdpResponse] = {}
        self.done = asyncio.Event()
        self._console = console

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        # A query to one console only trusts that console's address.
        if self._console is not None and addr[0] != self._console:
            return
        if (response := parse_response(data, addr[0])) is None:
            return
        if len(self.responses) < 64:
            self.responses[response.host_id or addr[0]] = response
        if self._console is not None:
            self.done.set()


def local_address(target: str) -> str:
    """Address of the interface that reaches ``target`` (connecting a UDP socket sends nothing)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        probe.connect((target, PS5_DDP_PORT))
        return probe.getsockname()[0]


async def _open(console: str | None) -> tuple[asyncio.DatagramTransport, _Collector]:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        # Listen for the answer on the interface that reaches the console only.
        sock.bind((local_address(console or BROADCAST), 0))
        sock.setblocking(False)
    except OSError:
        sock.close()
        raise
    transport, protocol = await loop.create_datagram_endpoint(
        lambda: _Collector(console), sock=sock
    )
    return transport, protocol


async def async_search(
    host: str | None = None,
    *,
    port: int = PS5_DDP_PORT,
    timeout: float = 2.0,
    attempts: int = 2,
) -> list[DdpResponse]:
    """Send SRCH to one console, or broadcast it when ``host`` is ``None``.

    With a host, returns as soon as it answers; a broadcast collects every
    answer received before the timeout.
    """
    console = await resolve_ipv4(host) if host is not None else None
    transport, protocol = await _open(console)
    message = build_message("SRCH")
    try:
        for _ in range(max(attempts, 1)):
            transport.sendto(message, (console or BROADCAST, port))
            try:
                await asyncio.wait_for(protocol.done.wait(), timeout / max(attempts, 1))
            except TimeoutError:
                continue
            break
    finally:
        transport.close()
    return list(protocol.responses.values())


async def async_get_status(
    host: str, *, port: int = PS5_DDP_PORT, timeout: float = 2.0
) -> DdpResponse | None:
    """Status of one console, or ``None`` when it does not answer."""
    responses = await async_search(host, port=port, timeout=timeout)
    return responses[0] if responses else None


async def async_wake(
    host: str, credential: str, *, port: int = PS5_DDP_PORT, repeat: int = 3
) -> None:
    """Send WAKEUP a few times (UDP gives no acknowledgement)."""
    console = await resolve_ipv4(host)
    transport, _ = await _open(console)
    message = build_wake_message(credential)
    try:
        for index in range(max(repeat, 1)):
            if index:
                await asyncio.sleep(0.2)
            transport.sendto(message, (console, port))
    finally:
        transport.close()
