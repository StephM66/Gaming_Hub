"""Nintendo Switch running Switch Assistant (Atmosphère sysmodule, MQTT).

Topics published by the console (https://github.com/ErSeraph/switch-assistant):

- ``switch_ha/<id>/<sensor>``: retained values, published on change
  (``current_game``, ``current_game_id``, ``game_running``, ``battery``…);
- ``<discovery prefix>/status``: JSON heartbeat every 15 s, ``"online"`` or
  ``"offline"`` (no message when the console goes to sleep);
- ``<discovery prefix>/command``: ``shutdown`` / ``reboot`` (shared by every
  Switch on the broker);
- ``switch_ha/<id>/notify/popup``: ``{"title": …, "message": …}``.

``<id>`` is the client ID set in the Switch app, with every character other
than ``[A-Za-z0-9]`` replaced by ``_``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from urllib.parse import urlsplit

STATE_ROOT = "switch_ha"
DEFAULT_DISCOVERY_PREFIX = "homeassistant"
HEARTBEAT_TIMEOUT = 45.0  # three missed heartbeats
_UNSAFE = re.compile(r"[^A-Za-z0-9]")
_NONE = {"", "none", "unknown"}
_TITLE_ID = re.compile(r"[0-9A-F]{16}")
# Only what the sysmodule publishes is kept, each value at most this long.
SENSORS = frozenset(
    {
        "battery",
        "charging",
        "charger_type",
        "battery_voltage",
        "battery_temperature",
        "battery_health",
        "brightness",
        "backlight",
        "volume",
        "audio_target",
        "game_running",
        "current_game",
        "current_game_id",
        "controller_count",
        "screen_rtsp_url",
        *(f"player_{slot}_controller" for slot in range(1, 9)),
    }
)
MAX_VALUE = 255


def sanitize_client_id(client_id: str) -> str:
    """Topic-safe form of a client ID, as the sysmodule computes it."""
    return _UNSAFE.sub("_", client_id.strip())


def state_topic(client_id: str, sensor: str = "#") -> str:
    return f"{STATE_ROOT}/{sanitize_client_id(client_id)}/{sensor}"


def status_topic(discovery_prefix: str) -> str:
    return f"{discovery_prefix}/status"


def command_topic(discovery_prefix: str) -> str:
    return f"{discovery_prefix}/command"


def popup_topic(client_id: str) -> str:
    return f"{STATE_ROOT}/{sanitize_client_id(client_id)}/notify/popup"


def popup_payload(message: str, title: str | None = None) -> str:
    return json.dumps({"title": title or "Home Assistant", "message": message})


def client_id_from_topic(topic: str) -> str | None:
    """``switch_ha/<id>/<sensor>`` → ``<id>``."""
    parts = topic.split("/")
    if len(parts) >= 3 and parts[0] == STATE_ROOT and parts[1]:
        return parts[1]
    return None


@dataclass(slots=True)
class SwitchAssistantState:
    """Values received from one console, plus liveness."""

    client_id: str
    values: dict[str, str] = field(default_factory=dict)
    last_seen: float | None = None
    offline: bool = False

    def handle_state(self, topic: str, payload: str, *, retained: bool, now: float) -> bool:
        """Store a ``switch_ha/<id>/<sensor>`` message; returns True if it changed."""
        prefix = f"{STATE_ROOT}/{sanitize_client_id(self.client_id)}/"
        if not topic.startswith(prefix):
            return False
        sensor = topic[len(prefix) :]
        if sensor not in SENSORS:
            return False
        payload = payload[:MAX_VALUE]
        changed = self.values.get(sensor) != payload
        self.values[sensor] = payload
        if not retained:
            changed |= self._mark_alive(now)
        return changed

    def handle_status(self, payload: str, *, retained: bool, now: float) -> bool:
        """Store a heartbeat; ignores the broker's own birth messages and other consoles."""
        try:
            data = json.loads(payload)
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        if sanitize_client_id(str(data.get("client_id", ""))) != sanitize_client_id(self.client_id):
            return False
        if data.get("status") == "offline":
            changed = not self.offline
            self.offline = True
            return changed
        return False if retained else self._mark_alive(now)

    def _mark_alive(self, now: float) -> bool:
        changed = self.offline or self.last_seen is None
        self.offline = False
        self.last_seen = now
        return changed

    def is_online(self, now: float) -> bool:
        return (
            not self.offline
            and self.last_seen is not None
            and now - self.last_seen <= HEARTBEAT_TIMEOUT
        )

    def _text(self, key: str) -> str | None:
        value = self.values.get(key)
        return None if value is None or value.strip().lower() in _NONE else value.strip()

    def _number(self, key: str) -> float | None:
        try:
            return float(self.values[key])
        except (KeyError, ValueError):
            return None

    @property
    def game_running(self) -> bool:
        return self.values.get("game_running") == "ON"

    @property
    def title(self) -> str | None:
        return self._text("current_game") if self.game_running else None

    @property
    def title_id(self) -> str | None:
        """Application ID, only when it has the expected 16 hexadecimal digits."""
        value = (self._text("current_game_id") or "").upper() if self.game_running else ""
        return value if _TITLE_ID.fullmatch(value) else None

    @property
    def battery(self) -> float | None:
        return self._number("battery")

    @property
    def battery_temperature(self) -> float | None:
        return self._number("battery_temperature")

    @property
    def charging(self) -> bool | None:
        value = self.values.get("charging")
        return None if value is None else value == "ON"

    @property
    def controllers(self) -> int | None:
        value = self._number("controller_count")
        return None if value is None else int(value)

    @property
    def battery_health(self) -> float | None:
        return self._number("battery_health")

    @property
    def battery_voltage(self) -> float | None:
        return self._number("battery_voltage")

    @property
    def charger(self) -> str | None:
        return self._text("charger_type")

    @property
    def brightness(self) -> float | None:
        return self._number("brightness")

    @property
    def screen_on(self) -> bool | None:
        value = self.values.get("backlight")
        return None if value is None else value == "ON"

    @property
    def volume(self) -> float | None:
        return self._number("volume")

    @property
    def audio_output(self) -> str | None:
        return self._text("audio_target")

    @property
    def players(self) -> dict[str, str]:
        """Controller type per player slot (``player_1`` → ``joycon_pair``…)."""
        return {
            f"player_{slot}": value
            for slot in range(1, 9)
            if (value := self._text(f"player_{slot}_controller"))
        }

    @property
    def stream_url(self) -> str | None:
        """RTSP stream of the screen (available while a game runs)."""
        value = self._text("screen_rtsp_url")
        if not value or any(char.isspace() or ord(char) < 32 for char in value):
            return None
        try:
            url = urlsplit(value)
        except ValueError:
            return None
        # Handed to the stream player: nothing but a plain RTSP address.
        return value if url.scheme == "rtsp" and url.hostname and not url.username else None
