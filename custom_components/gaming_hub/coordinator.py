"""One coordinator per console: driver state + PSN account + usage + parental control.

Entities chosen in the "Complete" options fill in what the console cannot do itself (state,
turning on and off, restart). Play time is also counted per identity (the console's account
or the console itself) for the profiles of the "Gaming Hub" entry.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import logging
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_ENTITY_ID, ATTR_UNIT_OF_MEASUREMENT, UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.debounce import Debouncer
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BLOCK_ENTITY,
    CONF_KIND,
    CONF_MODEL,
    CONF_NPSSO,
    CONF_POWER_ENTITY,
    CONF_PRESET,
    CONF_RESTART_ENTITY,
    CONF_STATE_ENTITY,
    CONF_TURN_OFF_ENTITY,
    CONF_TURN_ON_ENTITY,
    DEVICE_INFO,
    DOMAIN,
    EVENT_PARENTAL,
    SIGNAL_PARENTAL_SETTINGS,
    STORAGE_VERSION,
    ConsoleKind,
    texts,
)
from .drivers import ConsoleDriver
from .drivers.base import unsupported
from .models import ACCOUNT, CONSOLE, ConsoleSnapshot, Periods, PowerState
from .parental import (
    BlockReason,
    Notice,
    ParentalController,
    ParentalDecision,
    ParentalSettings,
)
from .presence import is_present
from .protocols.psn import PsnAuthError, PsnClient, PsnError, PsnStatus
from .usage import UsageTracker

_LOGGER = logging.getLogger(__name__)
# Usage is written at most this often (and when the entry unloads or Home Assistant stops).
SAVE_INTERVAL = timedelta(minutes=5)
# PlayStation Network polling: the game changes often, trophies and status slowly.
PSN_INTERVAL_ON = 60
PSN_INTERVAL_OFF = 15 * 60
PSN_SENSORS = ("psn_status", "trophy_level")
# Entities that turn the console on and off when chosen as its state.
SWITCHABLE = ("switch", "input_boolean", "light", "fan")

type GamingHubConfigEntry = ConfigEntry[GamingHubCoordinator]


@dataclass(slots=True)
class ConsoleData:
    snapshot: ConsoleSnapshot
    power: float | None  # W, from the linked power sensor
    energy: float  # kWh
    playtime: float  # seconds today
    playtime_week: float  # seconds this week (Monday to Sunday)
    playtime_month: float  # seconds this month
    parental: ParentalDecision
    # Play time per identity (models.ACCOUNT, models.CONSOLE, Switch players) and who plays.
    playtime_by: dict[str, Periods]
    playing_as: tuple[str, ...]


def profile_key(data: dict[str, Any]) -> str:
    """Key of DEVICE_INFO for an entry."""
    kind = ConsoleKind(data[CONF_KIND])
    return data[CONF_PRESET] if kind is ConsoleKind.PLAYSTATION else kind


# PlayStation Network platform matching each console (profile key).
PSN_PLATFORMS = {"ps5": "PS5", "ps3": "PS3", "ps4": "PS4"}


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
        self.model = entry.data.get(CONF_MODEL) or self.model
        self.usage = UsageTracker()
        # Play time of the console's account and of anyone else, for the profiles.
        self.usage_by: dict[str, UsageTracker] = {}
        self.parental = ParentalController(ParentalSettings())
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._next_save: datetime | None = None
        self.psn: PsnClient | None = None
        self.psn_status: PsnStatus | None = None
        self.psn_platform = PSN_PLATFORMS.get(key)
        self._psn_next = 0.0
        # Energy meter taken over and the plug's sensors hidden by the hub (consumption.py).
        self.energy_taken_over: str | None = None
        self.hidden_entities: list[str] = []
        self._psn_was_on = False
        self.psn_reauth = False

    @property
    def unique_prefix(self) -> str:
        return self.config_entry.entry_id

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config_entry.entry_id)},
            name=self.config_entry.title,
            manufacturer=self.manufacturer,
            model=self.model,
            configuration_url=self.driver.configuration_url,
        )

    @property
    def has_account(self) -> bool:
        """The console's play can be told apart as its account's (Steam, PSN)."""
        return self.driver.account_console or self.psn is not None

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
        self.usage_by = {
            identity: UsageTracker.from_dict(data)
            for identity, data in (stored.get("usage_by") or {}).items()
        }
        self.parental.settings = ParentalSettings.from_dict(stored.get("parental"))
        consumption = stored.get("consumption") or {}
        self.energy_taken_over = consumption.get("taken_over")
        self.hidden_entities = list(consumption.get("hidden") or [])
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
        if watched := [
            entity for entity in (self.options.get(CONF_POWER_ENTITY), self._state_entity) if entity
        ]:
            self.config_entry.async_on_unload(
                async_track_state_change_event(self.hass, watched, on_change)
            )

    async def async_stop(self) -> None:
        await self.driver.async_stop()
        await self._store.async_save(self._stored())

    def _stored(self) -> dict[str, Any]:
        data = {
            "usage": self.usage.as_dict(),
            "usage_by": {identity: usage.as_dict() for identity, usage in self.usage_by.items()},
            "parental": self.parental.settings.as_dict(),
            "consumption": {"taken_over": self.energy_taken_over, "hidden": self.hidden_entities},
        }
        if self.psn:
            npsso = self.config_entry.data[CONF_NPSSO]
            data["psn"] = {"npsso": _npsso_hash(npsso), "tokens": self.psn.tokens}
        return data

    def _schedule_save(self, now: datetime, *, soon: bool = False) -> None:
        # async_delay_save restarts its timer on each call: throttle the calls.
        if soon or self._next_save is None or now >= self._next_save:
            self._store.async_delay_save(self._stored, 1)
            self._next_save = now + SAVE_INTERVAL

    def save_soon(self) -> None:
        self._schedule_save(dt_util.now(), soon=True)

    # --- Refresh ------------------------------------------------------------

    @property
    def has_power(self) -> bool:
        # Power and energy only exist with a power sensor (smart plug) linked in the options.
        return bool(self.options.get(CONF_POWER_ENTITY))

    async def _async_update_data(self) -> ConsoleData:
        try:
            snapshot = await self.driver.async_fetch()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:  # drivers report an unreachable console as off
            raise UpdateFailed(f"{type(err).__name__}: {err}") from err
        now = dt_util.now()
        await self._async_update_psn(snapshot.is_on, now)
        self._merge_psn(snapshot)
        self._complete_state(snapshot)
        power = self._power()
        # Play time: while on, or only while in a game for a computer (Steam).
        counting = snapshot.playing if self.driver.counts_game_time_only else snapshot.is_on
        self.usage.update(now, counting, power)
        identity = self._identity()
        for key in (ACCOUNT, CONSOLE) if self.has_account else (CONSOLE,):
            self.usage_by.setdefault(key, UsageTracker()).update(
                now, counting and identity == key, None
            )
        # The maker's own count when the driver has it (Nintendo account), else the hub's.
        playtime, week, month = snapshot.playtime or _periods(self.usage)
        playtime_by = snapshot.playtime_by or {
            key: _periods(usage) for key, usage in self.usage_by.items()
        }
        playing_as = (snapshot.playing_as or (identity,)) if counting else ()
        decision = self.parental.evaluate(now, counting, playtime)
        self._schedule_save(now)
        if decision.notice or decision.enforce:
            self.config_entry.async_create_background_task(
                self.hass, self._async_apply(decision), f"{DOMAIN} parental control"
            )
        return ConsoleData(
            snapshot=snapshot,
            power=power,
            energy=self.usage.energy,
            playtime=playtime,
            playtime_week=week,
            playtime_month=month,
            parental=decision,
            playtime_by=playtime_by,
            playing_as=tuple(playing_as),
        )

    def _identity(self) -> str:
        """Who plays now: the console's account when it says so, else nobody in particular."""
        if self.driver.account_console:
            return ACCOUNT
        status = self.psn_status
        session = status.sessions.get(self.psn_platform or "") if status else None
        return ACCOUNT if session and session.online else CONSOLE

    @property
    def _state_entity(self) -> str | None:
        """Entity telling the state, for a console that cannot tell it itself."""
        return None if self.driver.native_state else self.options.get(CONF_STATE_ENTITY)

    def _complete_state(self, snapshot: ConsoleSnapshot) -> None:
        """The chosen entity decides on or off; the console or its account gives the game."""
        if not (entity := self._state_entity):
            return
        present = is_present(self.hass.states.get(entity))
        if present is True and not snapshot.is_on:
            snapshot.power = PowerState.ON
        elif present is False:
            snapshot.power = PowerState.OFF

    async def _async_update_psn(self, console_on: bool, now: datetime) -> None:
        """Poll the PlayStation Network account, more often while the console is on."""
        if self.psn is None or self.psn_reauth:
            return
        just_on = console_on and not self._psn_was_on
        self._psn_was_on = console_on
        if not just_on and time.monotonic() < self._psn_next:
            return
        # A console known through the account alone is watched there all the time.
        watch = console_on or self.driver.power_from_psn
        self._psn_next = time.monotonic() + (PSN_INTERVAL_ON if watch else PSN_INTERVAL_OFF)
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
        if self.driver.power_from_psn:
            snapshot.power = PowerState.ON if session and session.online else PowerState.OFF
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
    def _power_switch(self) -> str | None:
        """The state entity when it can also turn the console on and off (a switch)."""
        entity = self._state_entity
        return entity if entity and entity.split(".", 1)[0] in SWITCHABLE else None

    @property
    def can_turn_on(self) -> bool:
        return bool(
            self.options.get(CONF_TURN_ON_ENTITY) or self.driver.can_turn_on or self._power_switch
        )

    @property
    def can_turn_off(self) -> bool:
        return bool(
            self.options.get(CONF_TURN_OFF_ENTITY) or self.driver.can_turn_off or self._power_switch
        )

    @property
    def button_keys(self) -> tuple[str, ...]:
        """The console's buttons, and restart when an entity does it for the console."""
        if "restart" not in self.driver.buttons and self.options.get(CONF_RESTART_ENTITY):
            return (*self.driver.buttons, "restart")
        return self.driver.buttons

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
        elif entity := self._power_switch:
            await self._async_activate(entity)
        else:
            raise unsupported("turn_on")
        await self.async_request_refresh()

    async def async_turn_off(self) -> None:
        if entity := self.options.get(CONF_TURN_OFF_ENTITY):
            await self._async_activate(entity, turn_on=False)
        elif self.driver.can_turn_off:
            await self.driver.async_turn_off()
        elif entity := self._power_switch:
            await self._async_activate(entity, turn_on=False)
        else:
            raise unsupported("turn_off")
        await self.async_request_refresh()

    async def async_press(self, button: str) -> None:
        """Restart or quit the game (see ``ConsoleDriver.buttons``)."""
        if button == "restart" and "restart" not in self.driver.buttons:
            await self._async_activate(self.options[CONF_RESTART_ENTITY])
        elif button == "restart":
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
        async_dispatcher_send(self.hass, SIGNAL_PARENTAL_SETTINGS.format(self.unique_prefix))

    def message(self, decision: ParentalDecision, who: str | None = None) -> str:
        """Text for this console; ``who`` names a profile or the household it applies to."""
        words = texts(self.hass.config.language)
        console = self.config_entry.title
        suffix = "_for" if who else ""
        if decision.notice is Notice.WARNING:
            return words[f"warning{suffix}"].format(
                minutes=round(decision.remaining), console=console, who=who
            )
        key = "blocked_schedule" if decision.reason is BlockReason.SCHEDULE else "blocked_limit"
        text = words[f"{key}{suffix}"].format(console=console, who=who)
        if decision.enforce:
            text = f"{text} {words['turning_off'].format(console=console)}"
        return text

    async def _async_apply(self, decision: ParentalDecision) -> None:
        message = self.message(decision)
        self.hass.bus.async_fire(
            EVENT_PARENTAL,
            {
                "entry_id": self.config_entry.entry_id,
                "console": self.config_entry.title,
                "scope": "console",
                "type": "enforced" if decision.enforce else str(decision.notice),
                "reason": decision.reason and str(decision.reason),
                "remaining": decision.remaining,
                "message": message,
            },
        )
        await self.async_carry_out(decision, message)

    async def async_carry_out(self, decision: ParentalDecision, message: str) -> None:
        """Show the message on the console, and stop play when the decision enforces it."""
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


def _periods(usage: UsageTracker) -> Periods:
    return usage.playtime, usage.week_playtime, usage.month_playtime


def running_consoles(hass: HomeAssistant) -> list[GamingHubCoordinator]:
    """Coordinators of the consoles running (or finishing their setup), with data."""
    consoles = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if (
            isinstance(coordinator, GamingHubCoordinator)
            and entry.state in (ConfigEntryState.LOADED, ConfigEntryState.SETUP_IN_PROGRESS)
            and coordinator.data is not None
        ):
            consoles.append(coordinator)
    return consoles
