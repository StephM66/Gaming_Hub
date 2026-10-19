"""One coordinator per console: driver state + linked entities + usage + parental control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_PLAYING,
    UnitOfPower,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BLOCK_ENTITY,
    CONF_KIND,
    CONF_NOW_PLAYING_ENTITY,
    CONF_POWER_ENTITY,
    CONF_PRESET,
    CONF_TURN_OFF_ENTITY,
    CONF_TURN_ON_ENTITY,
    CONF_WATTS_IDLE,
    CONF_WATTS_PLAYING,
    CONF_WATTS_STANDBY,
    DEVICE_INFO,
    DOMAIN,
    EVENT_PARENTAL,
    MESSAGES,
    POWER_PROFILES,
    STORAGE_VERSION,
    ConsoleKind,
    LinkedPreset,
)
from .drivers import ConsoleDriver
from .drivers.base import unsupported
from .drivers.linked import media_from_state
from .models import ConsoleSnapshot, PowerProfile
from .parental import (
    BlockReason,
    Notice,
    ParentalController,
    ParentalDecision,
    ParentalSettings,
)
from .usage import UsageTracker

_LOGGER = logging.getLogger(__name__)
# Usage is written at most this often (and when the entry unloads or Home Assistant stops).
SAVE_INTERVAL = timedelta(minutes=5)

type GamingHubConfigEntry = ConfigEntry[GamingHubCoordinator]


@dataclass(slots=True)
class ConsoleData:
    snapshot: ConsoleSnapshot
    power: float | None  # W
    power_measured: bool
    energy: float  # kWh
    playtime: float  # seconds today
    parental: ParentalDecision


def profile_key(data: dict[str, Any]) -> str:
    """Key of POWER_PROFILES / DEVICE_INFO for an entry."""
    kind = ConsoleKind(data[CONF_KIND])
    return data.get(CONF_PRESET, LinkedPreset.OTHER) if kind is ConsoleKind.LINKED else kind


class GamingHubCoordinator(DataUpdateCoordinator[ConsoleData]):
    config_entry: GamingHubConfigEntry

    def __init__(
        self, hass: HomeAssistant, entry: GamingHubConfigEntry, driver: ConsoleDriver
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=entry.title,
            update_interval=driver.update_interval,
            request_refresh_debouncer=Debouncer(hass, _LOGGER, cooldown=1.0, immediate=True),
        )
        self.driver = driver
        self.options = dict(entry.options)
        key = profile_key(dict(entry.data))
        self.manufacturer, self.model = DEVICE_INFO[key]
        default = POWER_PROFILES[key]
        self.profile = PowerProfile(
            playing=float(self.options.get(CONF_WATTS_PLAYING, default.playing)),
            idle=float(self.options.get(CONF_WATTS_IDLE, default.idle)),
            standby=float(self.options.get(CONF_WATTS_STANDBY, default.standby)),
        )
        self.usage = UsageTracker()
        self.parental = ParentalController(ParentalSettings())
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._next_save: datetime | None = None

    # --- Lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        """Restore stored usage, subscribe to pushes and linked entities."""
        stored = await self._store.async_load() or {}
        self.usage = UsageTracker.from_dict(stored.get("usage"))
        self.parental.settings = ParentalSettings.from_dict(stored.get("parental"))

        @callback
        def on_change(*_: Any) -> None:
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), f"{DOMAIN} refresh"
            )

        await self.driver.async_start(on_change)
        linked = [
            entity
            for key in (CONF_POWER_ENTITY, CONF_NOW_PLAYING_ENTITY)
            if (entity := self.options.get(key))
        ]
        if linked:
            self.config_entry.async_on_unload(
                async_track_state_change_event(self.hass, linked, on_change)
            )

    async def async_stop(self) -> None:
        await self.driver.async_stop()
        await self._store.async_save(self._stored())

    def _stored(self) -> dict[str, Any]:
        return {"usage": self.usage.as_dict(), "parental": self.parental.settings.as_dict()}

    def _schedule_save(self, now: datetime, *, soon: bool = False) -> None:
        # async_delay_save restarts its timer on each call: throttle the calls.
        if soon or self._next_save is None or now >= self._next_save:
            self._store.async_delay_save(self._stored, 1)
            self._next_save = now + SAVE_INTERVAL

    # --- Refresh ------------------------------------------------------------

    @property
    def has_power(self) -> bool:
        return bool(self.options.get(CONF_POWER_ENTITY)) or self.profile.known

    async def _async_update_data(self) -> ConsoleData:
        try:
            snapshot = await self.driver.async_fetch()
        except Exception as err:  # drivers report an unreachable console as off
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        self._merge_now_playing(snapshot)
        power, measured = self._power(snapshot)
        now = dt_util.now()
        self.usage.update(now, snapshot.is_on, power)
        decision = self.parental.evaluate(now, snapshot.is_on, self.usage.playtime)
        self._schedule_save(now)
        if decision.notice or decision.enforce:
            self.config_entry.async_create_background_task(
                self.hass, self._async_apply(decision), f"{DOMAIN} parental control"
            )
        return ConsoleData(
            snapshot=snapshot,
            power=power,
            power_measured=measured,
            energy=self.usage.energy,
            playtime=self.usage.playtime,
            parental=decision,
        )

    def _merge_now_playing(self, snapshot: ConsoleSnapshot) -> None:
        """Take the game from a linked media player (e.g. PlayStation Network)."""
        entity = self.options.get(CONF_NOW_PLAYING_ENTITY)
        if not entity or not snapshot.is_on or snapshot.title:
            return
        state = self.hass.states.get(entity)
        if state is None or state.state != STATE_PLAYING:
            return
        title, title_id, image, picture = media_from_state(state)
        if title:
            snapshot.in_game = True
            snapshot.title = title
            snapshot.title_id = snapshot.title_id or title_id
            snapshot.image_url = snapshot.image_url or image
            snapshot.entity_picture = None if snapshot.image_url else picture

    def _power(self, snapshot: ConsoleSnapshot) -> tuple[float | None, bool]:
        if (entity := self.options.get(CONF_POWER_ENTITY)) and (
            state := self.hass.states.get(entity)
        ):
            try:
                value = float(state.state)
            except ValueError:
                pass
            else:
                kilowatts = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfPower.KILO_WATT
                return value * 1000 if kilowatts else value, True
        return self.profile.estimate(snapshot), False

    # --- Commands -----------------------------------------------------------

    @property
    def can_turn_on(self) -> bool:
        return bool(self.options.get(CONF_TURN_ON_ENTITY)) or self.driver.can_turn_on

    @property
    def can_turn_off(self) -> bool:
        return bool(self.options.get(CONF_TURN_OFF_ENTITY)) or self.driver.can_turn_off

    async def _async_activate(self, entity_id: str, *, turn_on: bool = True) -> None:
        """Run a script/scene, press a button or switch an entity."""
        domain = entity_id.split(".", 1)[0]
        if domain in ("script", "scene"):
            service_domain, service = domain, "turn_on"
        elif domain in ("button", "input_button"):
            service_domain, service = domain, "press"
        else:
            service_domain, service = "homeassistant", "turn_on" if turn_on else "turn_off"
        await self.hass.services.async_call(
            service_domain, service, {ATTR_ENTITY_ID: entity_id}, blocking=True
        )

    async def async_turn_on(self) -> None:
        if entity := self.options.get(CONF_TURN_ON_ENTITY):
            await self._async_activate(entity)
        elif self.driver.can_turn_on:
            await self.driver.async_turn_on()
        else:
            raise unsupported("turn_on")
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        if entity := self.options.get(CONF_TURN_OFF_ENTITY):
            await self._async_activate(entity, turn_on=False)
        elif self.driver.can_turn_off:
            await self.driver.async_turn_off()
        else:
            raise unsupported("turn_off")
        await self.async_request_refresh()

    async def async_restart(self) -> None:
        await self.driver.async_restart()
        await self.async_request_refresh()

    async def async_notify(self, message: str, title: str | None = None) -> None:
        await self.driver.async_notify(message, title)

    # --- Parental control ---------------------------------------------------

    async def async_update_parental(self, **changes: Any) -> None:
        """Change parental settings (from the config entities) and re-evaluate."""
        for key, value in changes.items():
            setattr(self.parental.settings, key, value)
        self._schedule_save(dt_util.now(), soon=True)
        await self.async_refresh()

    def message(self, decision: ParentalDecision) -> str:
        texts = MESSAGES["fr" if self.hass.config.language.startswith("fr") else "en"]
        console = self.config_entry.title
        if decision.notice is Notice.WARNING:
            return texts["warning"].format(minutes=round(decision.remaining or 0), console=console)
        key = "blocked_schedule" if decision.reason is BlockReason.SCHEDULE else "blocked_limit"
        text = texts[key].format(console=console)
        if decision.enforce:
            text = f"{text} {texts['turning_off'].format(console=console)}"
        return text

    async def _async_apply(self, decision: ParentalDecision) -> None:
        message = self.message(decision)
        self.hass.bus.async_fire(
            EVENT_PARENTAL,
            {
                "entry_id": self.config_entry.entry_id,
                "console": self.config_entry.title,
                "type": "enforced" if decision.enforce else str(decision.notice),
                "reason": decision.reason and str(decision.reason),
                "remaining": decision.remaining,
                "message": message,
            },
        )
        if decision.notice and self.driver.can_notify:
            try:
                await self.driver.async_notify(message, "Gaming Hub")
            except HomeAssistantError as err:
                _LOGGER.warning("Could not notify %s: %s", self.config_entry.title, err)
        if not decision.enforce:
            return
        try:
            if entity := self.options.get(CONF_BLOCK_ENTITY):
                await self._async_activate(entity)
            else:
                await self.async_turn_off()
        except HomeAssistantError as err:
            _LOGGER.warning("Parental control could not stop %s: %s", self.config_entry.title, err)
