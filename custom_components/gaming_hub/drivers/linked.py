"""Any console already known to Home Assistant (Xbox, PS4, Steam, smart plug…).

The state comes from one source entity:

- a media player (Xbox, PlayStation 4, PlayStation Network, Android TV…):
  power, current game and artwork, power commands;
- a game account sensor (Steam): in game with the game and its artwork, standby while the
  account is only online;
- any other entity: on/off only, read by ``presence.is_present`` (switch, binary sensor,
  device tracker or ping, HDMI switch input "linked", power sensor above a threshold…).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta

from homeassistant.components.media_player import MediaPlayerEntityFeature
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_ENTITY_PICTURE,
    ATTR_SUPPORTED_FEATURES,
    STATE_IDLE,
    STATE_ON,
    STATE_PAUSED,
    STATE_PLAYING,
    STATE_STANDBY,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_state_change_event

from ..const import CONF_ON_THRESHOLD, CONF_SOURCE_ENTITY
from ..models import ConsoleSnapshot, PowerState
from ..presence import is_present
from .base import ConsoleDriver, unsupported

_PLAYING = {STATE_PLAYING, STATE_PAUSED, "buffering"}
_AWAKE = {STATE_ON, STATE_IDLE, *_PLAYING}
_SWITCHABLE = {"switch", "input_boolean", "fan", "light"}
# Integrations whose sensor is a game account's status, with the game being played as
# attributes (Home Assistant's Steam integration: "game", "game_id", "game_image_*").
ACCOUNT_PLATFORMS = {"steam_online"}
_ACCOUNT_OFF = {"offline", STATE_UNAVAILABLE, STATE_UNKNOWN}


def media_from_state(state: State) -> tuple[str | None, str | None, str | None, str | None]:
    """Title, title ID, absolute image URL and frontend picture path of a media player."""
    title = state.attributes.get("media_title")
    content_id = state.attributes.get("media_content_id")
    picture = state.attributes.get(ATTR_ENTITY_PICTURE)
    if isinstance(picture, str) and picture.startswith(("http://", "https://")):
        return title, content_id, picture, None
    return title, content_id, None, picture


def account_snapshot(state: State) -> ConsoleSnapshot:
    """A game account: in game when it reports a game, else standby (or off when offline)."""
    if state.state in _ACCOUNT_OFF:
        return ConsoleSnapshot(PowerState.OFF)
    attributes = state.attributes
    if not (title := attributes.get("game")):
        return ConsoleSnapshot(PowerState.STANDBY)
    image = attributes.get("game_image_main") or attributes.get("game_image_header")
    return ConsoleSnapshot(
        PowerState.ON,
        in_game=True,
        title=str(title),
        title_id=str(attributes["game_id"]) if attributes.get("game_id") else None,
        image_url=image if isinstance(image, str) and image.startswith("https://") else None,
    )


class LinkedDriver(ConsoleDriver):
    update_interval = timedelta(seconds=30)  # state changes are pushed

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        self.source: str = entry.data[CONF_SOURCE_ENTITY]
        self._domain = self.source.split(".", 1)[0]
        self._threshold = float(entry.data.get(CONF_ON_THRESHOLD, 5.0))
        self._unsubscribe: Callable[[], None] | None = None
        registered = er.async_get(hass).async_get(self.source)
        self._account = registered is not None and registered.platform in ACCOUNT_PLATFORMS

    def _features(self) -> int:
        state = self.hass.states.get(self.source)
        return int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)) if state else 0

    @property
    def can_turn_on(self) -> bool:
        if self._domain == "media_player":
            return bool(self._features() & MediaPlayerEntityFeature.TURN_ON)
        return self._domain in _SWITCHABLE

    @property
    def can_turn_off(self) -> bool:
        if self._domain == "media_player":
            return bool(self._features() & MediaPlayerEntityFeature.TURN_OFF)
        return self._domain in _SWITCHABLE

    async def async_start(self, on_change: Callable[[], None]) -> None:
        @callback
        def changed(event: Event[EventStateChangedData]) -> None:
            on_change()

        self._unsubscribe = async_track_state_change_event(self.hass, [self.source], changed)

    async def async_stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()
            self._unsubscribe = None

    async def async_fetch(self) -> ConsoleSnapshot:
        state = self.hass.states.get(self.source)
        if state is None:
            return ConsoleSnapshot(PowerState.OFF)
        value = state.state
        if self._domain == "media_player":
            if value == STATE_STANDBY:
                return ConsoleSnapshot(PowerState.STANDBY)
            if value not in _AWAKE:
                return ConsoleSnapshot(PowerState.OFF)
            title, title_id, image, picture = media_from_state(state)
            return ConsoleSnapshot(
                PowerState.ON,
                in_game=value in _PLAYING,
                title=title,
                title_id=title_id,
                image_url=image,
                entity_picture=picture,
            )
        if self._account:
            return account_snapshot(state)
        threshold = self._threshold if self._domain == "sensor" else None
        on = is_present(state, threshold)
        return ConsoleSnapshot(PowerState.ON if on else PowerState.OFF)

    async def _call(self, service: str) -> None:
        domain = "media_player" if self._domain == "media_player" else "homeassistant"
        await self.hass.services.async_call(
            domain, service, {ATTR_ENTITY_ID: self.source}, blocking=True
        )

    async def async_turn_on(self) -> None:
        if not self.can_turn_on:
            raise unsupported("turn_on")
        await self._call("turn_on")

    async def async_turn_off(self) -> None:
        if not self.can_turn_off:
            raise unsupported("turn_off")
        await self._call("turn_off")
