"""One coordinator per console: driver state + linked entities + usage + parental control."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BLOCK_ENTITY,
    CONF_KIND,
    CONF_NPSSO,
    CONF_POWER_ENTITY,
    CONF_PRESET,
    CONF_TURN_OFF_ENTITY,
    CONF_TURN_ON_ENTITY,
    DEVICE_INFO,
    DOMAIN,
    EVENT_PARENTAL,
    MESSAGES,
    STORAGE_VERSION,
    ConsoleKind,
    LinkedPreset,
)
from .drivers import ConsoleDriver
from .drivers.base import unsupported
from .models import ConsoleSnapshot
from .parental import (
    BlockReason,
    Notice,
    ParentalController,
    ParentalDecision,
    ParentalSettings,
)
from .protocols.psn import PsnAuthError, PsnClient, PsnError, PsnStatus
from .usage import UsageTracker

_LOGGER = logging.getLogger(__name__)
# Usage is written at most this often (and when the entry unloads or Home Assistant stops).
SAVE_INTERVAL = timedelta(minutes=5)
# PlayStation Network polling: the game changes often, trophies and status slowly.
PSN_INTERVAL_ON = 60
PSN_INTERVAL_OFF = 15 * 60
PSN_SENSORS = ("psn_status", "trophy_level")

type GamingHubConfigEntry = ConfigEntry[GamingHubCoordinator]


@dataclass(slots=True)
class ConsoleData:
    snapshot: ConsoleSnapshot
    power: float | None  # W, from the linked power sensor
    energy: float  # kWh
    playtime: float  # seconds today
    parental: ParentalDecision


def profile_key(data: dict[str, Any]) -> str:
    """Key of DEVICE_INFO for an entry."""
    kind = ConsoleKind(data[CONF_KIND])
    return data.get(CONF_PRESET, LinkedPreset.OTHER) if kind is ConsoleKind.LINKED else kind


# PlayStation Network platform matching each console.
PSN_PLATFORMS = {ConsoleKind.PS5: "PS5", ConsoleKind.PS3: "PS3", LinkedPreset.PS4: "PS4"}


def _npsso_hash(npsso: str) -> str:
    return hashlib.sha256(npsso.encode()).hexdigest()[:16]


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
        self.usage = UsageTracker()
        self.parental = ParentalController(ParentalSettings())
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._next_save: datetime | None = None
        self.psn: PsnClient | None = None
        self.psn_status: PsnStatus | None = None
        self.psn_platform = PSN_PLATFORMS.get(key)
        self._psn_next = 0.0
        self._psn_was_on = False
        self.psn_reauth = False

    @property
    def sensor_keys(self) -> tuple[str, ...]:
        """Console-specific sensors (driver values, PlayStation Network account)."""
        return self.driver.sensors + (PSN_SENSORS if self.psn else ())

    @property
    def binary_sensor_keys(self) -> tuple[str, ...]:
        return self.driver.binary_sensors + (("ps_plus",) if self.psn else ())

    # --- Lifecycle ----------------------------------------------------------

    async def async_start(self) -> None:
        """Restore stored usage, subscribe to pushes and linked entities."""
        stored = await self._store.async_load() or {}
        self.usage = UsageTracker.from_dict(stored.get("usage"))
        self.parental.settings = ParentalSettings.from_dict(stored.get("parental"))
        if npsso := self.config_entry.data.get(CONF_NPSSO):
            psn = stored.get("psn") or {}
            tokens = psn.get("tokens") if psn.get("npsso") == _npsso_hash(npsso) else None
            self.psn = PsnClient(async_get_clientsession(self.hass), npsso, tokens)

        @callback
        def on_change(*_: Any) -> None:
            self.config_entry.async_create_background_task(
                self.hass, self.async_request_refresh(), f"{DOMAIN} refresh"
            )

        await self.driver.async_start(on_change)
        if power_entity := self.options.get(CONF_POWER_ENTITY):
            self.config_entry.async_on_unload(
                async_track_state_change_event(self.hass, [power_entity], on_change)
            )

    async def async_stop(self) -> None:
        await self.driver.async_stop()
        await self._store.async_save(self._stored())

    def _stored(self) -> dict[str, Any]:
        data = {"usage": self.usage.as_dict(), "parental": self.parental.settings.as_dict()}
        if self.psn:
            npsso = self.config_entry.data[CONF_NPSSO]
            data["psn"] = {"npsso": _npsso_hash(npsso), "tokens": self.psn.tokens}
        return data

    def _schedule_save(self, now: datetime, *, soon: bool = False) -> None:
        # async_delay_save restarts its timer on each call: throttle the calls.
        if soon or self._next_save is None or now >= self._next_save:
            self._store.async_delay_save(self._stored, 1)
            self._next_save = now + SAVE_INTERVAL

    # --- Refresh ------------------------------------------------------------

    @property
    def has_power(self) -> bool:
        # Power and energy only exist with a power sensor (smart plug) linked in the options.
        return bool(self.options.get(CONF_POWER_ENTITY))

    async def _async_update_data(self) -> ConsoleData:
        try:
            snapshot = await self.driver.async_fetch()
        except Exception as err:  # drivers report an unreachable console as off
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        now = dt_util.now()
        await self._async_update_psn(snapshot.is_on, now)
        self._merge_psn(snapshot)
        power = self._power()
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
            energy=self.usage.energy,
            playtime=self.usage.playtime,
            parental=decision,
        )

    async def _async_update_psn(self, console_on: bool, now: datetime) -> None:
        """Poll the PlayStation Network account, more often while the console is on."""
        if self.psn is None or self.psn_reauth:
            return
        just_on = console_on and not self._psn_was_on
        self._psn_was_on = console_on
        if not just_on and time.monotonic() < self._psn_next:
            return
        self._psn_next = time.monotonic() + (PSN_INTERVAL_ON if console_on else PSN_INTERVAL_OFF)
        try:
            self.psn_status = await self.psn.async_get_status()
        except PsnAuthError:
            # Keep the console working; ask for a new NPSSO token.
            self.psn_reauth = True
            self.psn_status = None
            self.config_entry.async_start_reauth(self.hass)
        except PsnError as err:
            _LOGGER.debug("PlayStation Network unavailable: %s", err)
        except Exception:
            # The account is a bonus: an unexpected answer must not take the console down.
            _LOGGER.exception("Unexpected PlayStation Network answer")
        if self.psn.tokens_changed:
            self.psn.tokens_changed = False
            self._schedule_save(now, soon=True)

    def _merge_psn(self, snapshot: ConsoleSnapshot) -> None:
        """Account data, and the current game when the console does not report it."""
        status = self.psn_status
        if status is None:
            return
        snapshot.attributes |= {
            "psn_status": status.online_status,
            "psn_online_id": status.online_id,
            "psn_avatar": status.avatar_url,
            "trophy_level": status.trophy_level,
            "trophy_progress": status.trophy_progress,
            "trophies": status.trophies,
            "ps_plus": status.plus,
        }
        session = status.sessions.get(self.psn_platform or "")
        if snapshot.is_on and not snapshot.title and session and session.online and session.title:
            snapshot.in_game = True
            snapshot.title = session.title
            snapshot.title_id = snapshot.title_id or session.title_id
            snapshot.image_url = snapshot.image_url or session.image

    def _power(self) -> float | None:
        if (entity := self.options.get(CONF_POWER_ENTITY)) and (
            state := self.hass.states.get(entity)
        ):
            try:
                value = float(state.state)
            except ValueError:
                return None
            kilowatts = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT) == UnitOfPower.KILO_WATT
            return value * 1000 if kilowatts else value
        return None

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

    async def async_press(self, button: str) -> None:
        """Restart or quit the game (see ``ConsoleDriver.buttons``)."""
        if button == "restart":
            await self.driver.async_restart()
        else:
            await self.driver.async_quit_game()
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
