"""Discord account: the game being played, whatever launched it, through the player's own bot.

Discord recognises most PC games by itself (Steam, Battle.net, GOG, Epic, emulators…) and shows
"Playing …" to the servers the player is in. A bot of the player's own, in one of those servers,
receives it with the presence intent. Gaming Hub speaks Discord's Gateway itself (WebSocket,
JSON, API v10), so nothing else is needed: create a bot, enable its Presence Intent, invite it to
a server the player is in, then give Gaming Hub its token and the player's user ID.

The player must share their activity (Discord settings, Activity Privacy). Invisible looks
offline. Read only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
import logging
import random
import re
from typing import Any

import aiohttp

API_BASE = "https://discord.com/api/v10"
GATEWAY_URL = "wss://gateway.discord.gg/?v=10&encoding=json"
PORTAL_URL = "https://discord.com/developers/applications"
INTENTS = 1 << 0 | 1 << 8  # GUILDS, GUILD_PRESENCES
# Application flags: presence intent enabled (100 servers or more, under 100).
PRESENCE_FLAGS = 1 << 12 | 1 << 13
STATUSES = ("online", "idle", "dnd", "offline")
PLAYING = 0  # activity type
_TIMEOUT = aiohttp.ClientTimeout(total=20)
_MAX_TEXT = 255
_MAX_MESSAGE = 16 * 1024 * 1024  # a server's first event lists every member online
_USER_ID = re.compile(r"\d{17,20}")
_ASSET = re.compile(r"\d{17,20}")
# Gateway close codes: the token, the intents, the version are wrong; reconnecting won't help.
_AUTH_FAILED = 4004
_INTENTS_REFUSED = {4013, 4014}
_NEW_SESSION = {4007, 4009}  # reconnect, but identify again
_BACKOFF = (0, 1, 5, 15, 60, 300)  # seconds before attempt n
_HELD = 30  # seconds: a connection that lasted is no failure, reconnect at once
_KEEP_SESSION = 4900  # closing with 1000 or 1001 would end the session: no resuming

_LOGGER = logging.getLogger(__name__)


class DiscordError(Exception):
    """Discord unreachable or unexpected answer (temporary)."""


class DiscordAuthError(DiscordError):
    """The bot token is refused."""


class DiscordIntentError(DiscordError):
    """The bot's Presence Intent is off in the Developer Portal."""


class DiscordUserError(DiscordError):
    """No such user, or the bot shares no server with them."""


def _text(value: Any) -> str | None:
    return value[:_MAX_TEXT] if isinstance(value, str) and value else None


def user_id(text: str) -> str | None:
    text = text.strip()
    return text if _USER_ID.fullmatch(text) else None


@dataclass(frozen=True, slots=True)
class DiscordStatus:
    status: str = "offline"  # one of STATUSES
    desktop: bool = False  # Discord open on a computer
    game: str | None = None
    game_id: str | None = None  # Discord application of the game
    started: datetime | None = None
    image: str | None = None


def _image(activity: dict[str, Any], application: str | None) -> str | None:
    assets = activity.get("assets")
    large = assets.get("large_image") if isinstance(assets, dict) else None
    if not isinstance(large, str):
        return None
    if large.startswith("mp:") and "/" in large and ".." not in large:
        return f"https://media.discordapp.net/{large[3:]}"
    if application and _ASSET.fullmatch(large):
        return f"https://cdn.discordapp.com/app-assets/{application}/{large}.png"
    return None


def parse_presence(raw: Any) -> DiscordStatus:
    """What a presence says (fields are optional and unvalidated, says Discord)."""
    if not isinstance(raw, dict):
        return DiscordStatus()
    status = raw.get("status") if raw.get("status") in STATUSES else "offline"
    client = raw.get("client_status")
    desktop = isinstance(client, dict) and client.get("desktop") in STATUSES[:3]
    activities = raw.get("activities")
    playing = next(
        (
            activity
            for activity in (activities if isinstance(activities, list) else ())
            if isinstance(activity, dict)
            and activity.get("type") == PLAYING
            and _text(activity.get("name"))
        ),
        None,
    )
    if status == "offline" or playing is None:
        return DiscordStatus(status, desktop)
    application = playing.get("application_id")
    application = str(application) if _ASSET.fullmatch(str(application)) else None
    timestamps = playing.get("timestamps")
    start = timestamps.get("start") if isinstance(timestamps, dict) else None
    return DiscordStatus(
        status,
        desktop,
        game=_text(playing.get("name")),
        game_id=application,
        started=(
            datetime.fromtimestamp(start / 1000, UTC)
            if isinstance(start, int) and 0 < start < 10**14
            else None
        ),
        image=_image(playing, application),
    )


class DiscordClient:
    """REST calls checking a bot and a player when they are added."""

    def __init__(
        self, session: aiohttp.ClientSession, token: str, *, api_base: str = API_BASE
    ) -> None:
        self._session = session
        self._token = token
        self._api_base = api_base

    async def _get(self, path: str) -> Any:
        try:
            async with self._session.get(
                f"{self._api_base}{path}",
                headers={"Authorization": f"Bot {self._token}"},
                timeout=_TIMEOUT,
            ) as response:
                if response.status == 401:
                    raise DiscordAuthError("token refused")
                if response.status == 404:
                    raise DiscordUserError("not found")
                if response.status != 200:
                    raise DiscordError(f"Discord answered {response.status}")
                return await response.json(content_type=None)
        except aiohttp.ClientError as err:
            raise DiscordError(type(err).__name__) from err
        except ValueError as err:
            raise DiscordError("unexpected answer") from err

    async def async_check(self, player: str) -> str:
        """The player's name, once the bot is known to see their games."""
        application = await self._get("/applications/@me")
        flags = application.get("flags") if isinstance(application, dict) else None
        if not isinstance(flags, int) or not flags & PRESENCE_FLAGS:
            raise DiscordIntentError("presence intent off")
        user = await self._get(f"/users/{player}")
        if not isinstance(user, dict):
            raise DiscordError("unexpected answer")
        guilds = await self._get("/users/@me/guilds")
        for guild in guilds if isinstance(guilds, list) else ():
            if not isinstance(guild, dict) or not _ASSET.fullmatch(str(guild.get("id"))):
                continue
            try:
                await self._get(f"/guilds/{guild['id']}/members/{player}")
            except DiscordUserError:
                continue
            return _text(user.get("global_name")) or _text(user.get("username")) or player
        raise DiscordUserError("no server in common")


class DiscordGateway:
    """One connection per bot, shared by every player watched with it.

    Keeps the presence of each member of the bot's servers who is online; a member missing
    is offline. ``ready`` is set once every server has been received.
    """

    def __init__(
        self, session: aiohttp.ClientSession, token: str, *, url: str = GATEWAY_URL
    ) -> None:
        self._session = session
        self._token = token
        self._url = url
        self.presences: dict[str, dict[str, Any]] = {}
        self.ready = asyncio.Event()
        self.error: DiscordError | None = None  # gave up: token or intents to fix
        self._listeners: dict[str, list[Callable[[], None]]] = {}
        self._seq: int | None = None
        self._session_id: str | None = None
        self._resume_url: str | None = None
        self._pending: set[str] = set()  # servers announced, not received yet
        self._seen: set[str] = set()  # members online in the servers received
        self._acked = True

    def status(self, player: str) -> DiscordStatus:
        return parse_presence(self.presences.get(player))

    def subscribe(self, player: str, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.setdefault(player, []).append(listener)

        def unsubscribe() -> None:
            self._listeners[player].remove(listener)

        return unsubscribe

    def _notify(self, players: Any) -> None:
        for player in players:
            for listener in list(self._listeners.get(player, ())):
                listener()

    async def async_run(self) -> None:
        """Stay connected until cancelled, or until Discord refuses the token.

        Intents refused: keep trying, slowly, so turning the Presence Intent on is enough.
        """
        failures = 0
        loop = asyncio.get_running_loop()
        while True:
            started = loop.time()
            try:
                await self._connect()
                failures = 0 if loop.time() - started > _HELD else failures + 1
            except (DiscordAuthError, DiscordIntentError) as err:
                self.error = err
                self.ready.set()  # waiting is over: the error tells why
                self._notify(list(self._listeners))
                if isinstance(err, DiscordAuthError):
                    return
                failures = len(_BACKOFF)
            except (
                aiohttp.ClientError,
                TimeoutError,
                ValueError,
                LookupError,
                TypeError,
                DiscordError,
            ) as err:
                _LOGGER.debug("Discord gateway: %s", err)
                failures += 1
            await asyncio.sleep(_BACKOFF[min(failures, len(_BACKOFF) - 1)] * random.uniform(1, 1.5))

    async def _connect(self) -> None:
        resume = self._session_id is not None and self._resume_url is not None
        url = f"{self._resume_url}/?v=10&encoding=json" if resume else self._url
        async with self._session.ws_connect(url, max_msg_size=_MAX_MESSAGE) as ws:
            hello = await ws.receive_json(timeout=30)
            if not isinstance(hello, dict) or hello.get("op") != 10:
                raise DiscordError("no hello")
            interval = float(hello["d"]["heartbeat_interval"]) / 1000
            if resume:
                await ws.send_json(
                    {
                        "op": 6,
                        "d": {
                            "token": self._token,
                            "session_id": self._session_id,
                            "seq": self._seq,
                        },
                    }
                )
            else:
                await ws.send_json(
                    {
                        "op": 2,
                        "d": {
                            "token": self._token,
                            "intents": INTENTS,
                            "large_threshold": 250,
                            "properties": {
                                "os": "linux",
                                "browser": "gaming_hub",
                                "device": "gaming_hub",
                            },
                        },
                    }
                )
            beating = asyncio.create_task(self._heartbeat(ws, interval))
            try:
                await self._receive(ws)
            finally:
                beating.cancel()
            code = ws.close_code
        if code == _AUTH_FAILED:
            raise DiscordAuthError("token refused")
        if code in _INTENTS_REFUSED:
            raise DiscordIntentError(f"closed with {code}")
        if code in _NEW_SESSION:
            self._session_id = None

    async def _heartbeat(self, ws: aiohttp.ClientWebSocketResponse, interval: float) -> None:
        await asyncio.sleep(interval * random.random())
        try:
            while True:
                self._acked = False
                await ws.send_json({"op": 1, "d": self._seq})
                await asyncio.sleep(interval)
                if not self._acked:  # no answer: the connection is dead, resume on a new one
                    await ws.close(code=_KEEP_SESSION)
                    return
        except (aiohttp.ClientError, ConnectionError):
            return  # the connection is already closing: the receiving side handles it

    async def _receive(self, ws: aiohttp.ClientWebSocketResponse) -> None:
        async for message in ws:
            if message.type is not aiohttp.WSMsgType.TEXT:
                break
            payload = message.json()
            if not isinstance(payload, dict):
                continue
            op = payload.get("op")
            if op == 0:
                if isinstance(payload.get("s"), int):
                    self._seq = payload["s"]
                self._dispatch(payload.get("t"), payload.get("d"))
            elif op == 1:
                await ws.send_json({"op": 1, "d": self._seq})
            elif op == 11:
                self._acked = True
            elif op == 7:  # asked to reconnect: resume
                await ws.close(code=_KEEP_SESSION)
            elif op == 9:  # session invalid
                if not payload.get("d"):
                    self._session_id = None
                await asyncio.sleep(random.uniform(1, 5))
                await ws.close(code=_KEEP_SESSION)

    def _dispatch(self, event: Any, data: Any) -> None:
        if not isinstance(data, dict):
            return
        if event == "READY":
            self.error = None
            self._session_id = _text(data.get("session_id"))
            self._resume_url = _text(data.get("resume_gateway_url"))
            guilds = data.get("guilds") if isinstance(data.get("guilds"), list) else []
            self._pending = {str(g.get("id")) for g in guilds if isinstance(g, dict)}
            self._seen = set()
            if not self._pending:
                self._received_all()
        elif event == "GUILD_CREATE":
            presences = data.get("presences") if isinstance(data.get("presences"), list) else []
            for presence in presences:
                self._store(presence)
            self._pending.discard(str(data.get("id")))
            if not self._pending:
                self._received_all()
        elif event == "PRESENCE_UPDATE":
            if (player := self._store(data)) is not None:
                self._notify((player,))

    def _store(self, presence: Any) -> str | None:
        user = presence.get("user") if isinstance(presence, dict) else None
        player = str(user.get("id")) if isinstance(user, dict) else ""
        if not _USER_ID.fullmatch(player):
            return None
        self.presences[player] = presence
        self._seen.add(player)
        return player

    def _received_all(self) -> None:
        # Members known before a new session and absent from it went offline meanwhile.
        for player in set(self.presences) - self._seen:
            del self.presences[player]
        self.ready.set()
        self._notify(list(self._listeners))
