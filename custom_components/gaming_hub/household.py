"""The household and its profiles: play time per child, parental rules across consoles.

Lives in the "Gaming Hub" entry; profiles are its subentries. Each console publishes who
played and for how long (``ConsoleData.playtime_by``: its account, a Switch player, or the
console itself) and who plays now (``playing_as``). The hub adds it up for the household
(every console) and for each profile:

- a console's account time goes to the profile owning that account (Steam, PSN);
- a Switch player's time goes to the profile owning that player;
- anything else goes to the console's main player, or stays unattributed (household only).

Each level has its own parental rules. When one blocks, the consoles concerned (all the
consoles on for the household, the ones where the child plays for a profile) show the
message and stop when they can. Rules of each console still apply: the strictest wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ACCOUNTS,
    CONF_CONSOLES,
    CONF_KIND,
    CONF_PLAYERS,
    DOMAIN,
    EVENT_PARENTAL,
    SIGNAL_CONSOLES_UPDATED,
    SIGNAL_PARENTAL_SETTINGS,
    STORAGE_VERSION,
    SUBENTRY_PROFILE,
    SUMMARY,
    texts,
)
from .coordinator import GamingHubCoordinator, running_consoles
from .models import ACCOUNT, PLAYER
from .parental import (
    BlockReason,
    Notice,
    ParentalController,
    ParentalDecision,
    ParentalSettings,
    ParentalStatus,
)

_LOGGER = logging.getLogger(__name__)
SAVE_DELAY = 10  # seconds; settings change rarely


@dataclass(slots=True)
class OwnerData:
    """Play time and parental state of the household or of a profile."""

    playtime: float = 0.0  # seconds today
    playtime_week: float = 0.0
    playtime_month: float = 0.0
    consoles: dict[str, list[float]] = field(default_factory=dict)  # name: [today, week, month]
    playing: dict[str, str | None] = field(default_factory=dict)  # console played now: game
    playing_on: list[GamingHubCoordinator] = field(default_factory=list)
    parental: ParentalDecision = field(
        default_factory=lambda: ParentalDecision(ParentalStatus.DISABLED)
    )

    def play(self, coordinator: GamingHubCoordinator) -> None:
        if coordinator not in self.playing_on:
            self.playing_on.append(coordinator)
            self.playing[coordinator.config_entry.title] = coordinator.data.snapshot.title

    def add(self, console: str, periods: tuple[float, float, float]) -> None:
        today, week, month = periods
        self.playtime += today
        self.playtime_week += week
        self.playtime_month += month
        share = self.consoles.setdefault(console, [0.0, 0.0, 0.0])
        for index, seconds in enumerate(periods):
            share[index] += seconds


@dataclass(frozen=True, slots=True)
class ProfileRules:
    """What belongs to a child (profile subentry data)."""

    accounts: frozenset[str] = frozenset()  # console entry IDs whose account is the child's
    players: frozenset[str] = frozenset()  # "<console entry ID>|<Switch player>"
    consoles: frozenset[str] = frozenset()  # console entry IDs where the child plays most

    @classmethod
    def from_data(cls, data: Any) -> ProfileRules:
        return cls(
            frozenset(data.get(CONF_ACCOUNTS) or ()),
            frozenset(data.get(CONF_PLAYERS) or ()),
            frozenset(data.get(CONF_CONSOLES) or ()),
        )


def owner_of(rules: dict[str, ProfileRules], entry_id: str, identity: str) -> str | None:
    """Profile the play of ``identity`` on a console counts for; None when unattributed."""
    for profile_id, profile in rules.items():
        if identity == ACCOUNT and entry_id in profile.accounts:
            return profile_id
        if (
            identity.startswith(PLAYER)
            and f"{entry_id}|{identity.removeprefix(PLAYER)}" in profile.players
        ):
            return profile_id
    # The rest (the console itself, an account or player nobody claimed): its main player.
    return next((pid for pid, profile in rules.items() if entry_id in profile.consoles), None)


def attribute(
    consoles: list[GamingHubCoordinator], rules: dict[str, ProfileRules]
) -> tuple[OwnerData, dict[str | None, OwnerData]]:
    """Household totals, and play per profile (None: unattributed)."""
    household = OwnerData()
    owners: dict[str | None, OwnerData] = {profile_id: OwnerData() for profile_id in rules}
    for coordinator in consoles:
        entry_id, name, data = (
            coordinator.config_entry.entry_id,
            coordinator.config_entry.title,
            coordinator.data,
        )
        household.add(name, (data.playtime, data.playtime_week, data.playtime_month))
        if data.playing_as:
            household.play(coordinator)
        for identity, periods in data.playtime_by.items():
            owners.setdefault(owner_of(rules, entry_id, identity), OwnerData()).add(name, periods)
        for identity in data.playing_as:
            owners.setdefault(owner_of(rules, entry_id, identity), OwnerData()).play(coordinator)
    return household, owners


class ParentalOwner(DataUpdateCoordinator[OwnerData]):
    """The household or a profile: its rules, decisions and entities (one device)."""

    def __init__(
        self,
        hub: GamingHub,
        name: str,
        unique_prefix: str,
        device_info: DeviceInfo,
        settings: ParentalSettings,
        who: str,
    ) -> None:
        super().__init__(hub.hass, _LOGGER, config_entry=hub.entry, name=name)
        self.hub = hub
        self.unique_prefix = unique_prefix
        self.device_info = device_info
        self.parental = ParentalController(settings)
        self.who = who  # name used in messages
        self.data = OwnerData()

    async def _async_update_data(self) -> OwnerData:
        return self.data

    async def async_update_parental(self, **changes: Any) -> None:
        """Change parental settings (from the config entities) and re-evaluate."""
        for key, value in changes.items():
            setattr(self.parental.settings, key, value)
        self.hub.save()
        self.hub.refresh()
        async_dispatcher_send(self.hass, SIGNAL_PARENTAL_SETTINGS.format(self.unique_prefix))


class GamingHub:
    """Runtime of the "Gaming Hub" entry: household, profiles, their decisions."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self.household: ParentalOwner | None = None
        self.profiles: dict[str, ParentalOwner] = {}
        self.rules: dict[str, ProfileRules] = {}

    async def async_start(self) -> None:
        stored = await self._store.async_load() or {}
        entry = self.entry
        hub_device = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Gaming Hub",
            entry_type=DeviceEntryType.SERVICE,
        )
        words = texts(self.hass.config.language)
        self.household = ParentalOwner(
            self,
            entry.title,
            entry.entry_id,
            hub_device,
            ParentalSettings.from_dict(stored.get("household")),
            words["household"],
        )
        saved = stored.get("profiles") or {}
        for subentry_id, subentry in entry.subentries.items():
            if subentry.subentry_type != SUBENTRY_PROFILE:
                continue
            self.rules[subentry_id] = ProfileRules.from_data(subentry.data)
            self.profiles[subentry_id] = ParentalOwner(
                self,
                subentry.title,
                f"{entry.entry_id}_{subentry_id}",
                DeviceInfo(
                    identifiers={(DOMAIN, f"{entry.entry_id}_{subentry_id}")},
                    name=subentry.title,
                    manufacturer="Gaming Hub",
                    entry_type=DeviceEntryType.SERVICE,
                    via_device=(DOMAIN, entry.entry_id),
                ),
                ParentalSettings.from_dict(saved.get(subentry_id)),
                subentry.title,
            )
        entry.async_on_unload(
            async_dispatcher_connect(self.hass, SIGNAL_CONSOLES_UPDATED, self.refresh)
        )
        self.refresh()

    def save(self) -> None:
        self._store.async_delay_save(self._stored, SAVE_DELAY)

    def _stored(self) -> dict[str, Any]:
        assert self.household is not None
        return {
            "household": self.household.parental.settings.as_dict(),
            "profiles": {
                subentry_id: owner.parental.settings.as_dict()
                for subentry_id, owner in self.profiles.items()
            },
        }

    async def async_stop(self) -> None:
        await self._store.async_save(self._stored())

    @callback
    def refresh(self) -> None:
        """Add up the consoles, decide for the household and each profile, act."""
        if self.household is None:
            return
        now = dt_util.now()
        household, owners = attribute(running_consoles(self.hass), self.rules)
        targets = [(self.household, household)]
        targets += [(owner, owners[profile_id]) for profile_id, owner in self.profiles.items()]
        for owner, data in targets:
            data.parental = owner.parental.evaluate(now, bool(data.playing_on), data.playtime)
            owner.async_set_updated_data(data)
            if data.parental.notice or data.parental.enforce:
                self._apply(owner, data.parental, data.playing_on)

    def _apply(
        self,
        owner: ParentalOwner,
        decision: ParentalDecision,
        consoles: list[GamingHubCoordinator],
    ) -> None:
        """Event for the parents, then a message and a stop on each console concerned."""
        household = owner is self.household
        messages = {c.config_entry.title: c.message(decision, owner.who) for c in consoles}
        self.hass.bus.async_fire(
            EVENT_PARENTAL,
            {
                "scope": "household" if household else "profile",
                "profile": None if household else owner.name,
                "consoles": list(messages),
                "type": "enforced" if decision.enforce else str(decision.notice),
                "reason": decision.reason and str(decision.reason),
                "remaining": decision.remaining,
                "message": next(iter(messages.values()), None)
                or _message_without_console(self.hass, decision, owner.who),
            },
        )
        for coordinator in consoles:
            self.entry.async_create_background_task(
                self.hass,
                coordinator.async_carry_out(decision, messages[coordinator.config_entry.title]),
                f"{DOMAIN} parental control",
            )


def _message_without_console(hass: HomeAssistant, decision: ParentalDecision, who: str) -> str:
    """For the parents' event when the child plays on no known console."""
    words = texts(hass.config.language)
    if decision.notice is Notice.WARNING:
        return words["warning_for"].format(minutes=round(decision.remaining), who=who)
    key = "blocked_schedule_for" if decision.reason is BlockReason.SCHEDULE else "blocked_limit_for"
    return words[key].format(who=who)


def parental_owners(entry: ConfigEntry) -> list[tuple[Any, str | None]]:
    """Who has parental settings in an entry, with the profile subentry they belong to."""
    if entry.data.get(CONF_KIND) != SUMMARY:
        return [(entry.runtime_data, None)]
    hub: GamingHub = entry.runtime_data
    return [(hub.household, None), *((o, sid) for sid, o in hub.profiles.items())]
