"""Current game, consumption, play time, parental status and console sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    Platform,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import CONF_KIND, DOMAIN, SIGNAL_PARENTAL_SETTINGS, SUMMARY, texts
from .coordinator import ConsoleData, GamingHubConfigEntry, GamingHubCoordinator
from .entity import GamingHubEntity
from .household import GamingHub, OwnerData, ParentalOwner
from .parental import ParentalStatus
from .protocols.discord import STATUSES as DISCORD_STATUSES
from .protocols.steam import STATUSES as STEAM_STATUSES
from .summary import (
    SUMMARY_SENSORS,
    SummarySensor,
    start_of_day,
    start_of_month,
    start_of_week,
)

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class HubSensorDescription(SensorEntityDescription):
    value_fn: Callable[[ConsoleData], Any]
    exists_fn: Callable[[GamingHubCoordinator], bool] = lambda _: True
    attributes_fn: Callable[[ConsoleData], dict[str, Any]] | None = None
    # No value reads "None" in Home Assistant's language instead of "unknown".
    none_text: bool = False


def _attribute(key: str) -> Callable[[ConsoleData], Any]:
    return lambda data: data.snapshot.attributes.get(key)


HUB_SENSORS: tuple[HubSensorDescription, ...] = (
    HubSensorDescription(
        key="game",
        value_fn=lambda data: data.snapshot.title if data.snapshot.playing else None,
        attributes_fn=lambda data: {"title_id": data.snapshot.title_id},
        none_text=True,
    ),
    HubSensorDescription(
        key="power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        value_fn=lambda data: data.power,
        exists_fn=lambda coordinator: coordinator.has_power,
    ),
    HubSensorDescription(
        key="energy",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=2,
        value_fn=lambda data: round(data.energy, 4),
        exists_fn=lambda coordinator: coordinator.has_power,
    ),
    HubSensorDescription(
        key="playtime_today",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: round(data.playtime / 60, 1),
        # Games and players of the day, when the console's maker gives them (Nintendo).
        attributes_fn=lambda data: data.snapshot.attributes.get("playtime_today"),
    ),
    HubSensorDescription(
        key="playtime_week",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda data: round(data.playtime_week / 3600, 2),
    ),
    HubSensorDescription(
        key="playtime_month",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        suggested_display_precision=1,
        value_fn=lambda data: round(data.playtime_month / 3600, 2),
    ),
    HubSensorDescription(
        key="parental_status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in ParentalStatus],
        value_fn=lambda data: data.parental.status.value,
        attributes_fn=lambda data: {"reason": data.parental.reason and data.parental.reason.value},
    ),
    HubSensorDescription(
        key="parental_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: round(max(data.parental.remaining, 0), 1),
    ),
)

# Console-specific values, created when the driver lists them.
DRIVER_SENSORS: dict[str, HubSensorDescription] = {
    description.key: description
    for description in (
        HubSensorDescription(
            key="cpu_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            value_fn=_attribute("cpu_temperature"),
        ),
        HubSensorDescription(
            key="rsx_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            value_fn=_attribute("rsx_temperature"),
        ),
        HubSensorDescription(
            key="fan_speed",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("fan_speed"),
        ),
        HubSensorDescription(
            key="firmware",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("firmware"),
        ),
        HubSensorDescription(
            key="system_version",
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("system_version"),
        ),
        HubSensorDescription(
            key="battery",
            device_class=SensorDeviceClass.BATTERY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("battery"),
        ),
        HubSensorDescription(
            key="battery_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("battery_temperature"),
        ),
        HubSensorDescription(
            key="controllers",
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_attribute("controllers"),
            attributes_fn=lambda data: data.snapshot.attributes.get("players") or {},
        ),
        # PlayStation 3 (webMAN MOD)
        HubSensorDescription(
            key="fan_mode",
            device_class=SensorDeviceClass.ENUM,
            options=["syscon", "auto", "dynamic", "manual", "ps2"],
            value_fn=_attribute("fan_mode"),
        ),
        HubSensorDescription(
            key="fan_target",
            device_class=SensorDeviceClass.TEMPERATURE,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("fan_target"),
        ),
        HubSensorDescription(
            key="session_time",
            device_class=SensorDeviceClass.DURATION,
            native_unit_of_measurement=UnitOfTime.MINUTES,
            suggested_display_precision=0,
            value_fn=_attribute("session_time"),
        ),
        HubSensorDescription(
            key="memory_free",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfInformation.MEGABYTES,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("memory_free"),
        ),
        HubSensorDescription(
            key="hdd_free",
            device_class=SensorDeviceClass.DATA_SIZE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfInformation.GIGABYTES,
            suggested_display_precision=1,
            value_fn=_attribute("hdd_free"),
        ),
        HubSensorDescription(
            key="started_at",
            device_class=SensorDeviceClass.TIMESTAMP,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("started_at"),
        ),
        HubSensorDescription(
            key="network",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("network"),
        ),
        HubSensorDescription(
            key="ip_address",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("ip_address"),
        ),
        HubSensorDescription(
            key="runtime",
            device_class=SensorDeviceClass.DURATION,
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfTime.HOURS,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("runtime"),
        ),
        HubSensorDescription(
            key="power_on_count",
            state_class=SensorStateClass.TOTAL_INCREASING,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("power_on_count"),
        ),
        # Nintendo Switch (Switch Assistant)
        HubSensorDescription(
            key="battery_health",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("battery_health"),
        ),
        HubSensorDescription(
            key="battery_voltage",
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.MILLIVOLT,
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            value_fn=_attribute("battery_voltage"),
        ),
        HubSensorDescription(
            key="charger",
            device_class=SensorDeviceClass.ENUM,
            options=["unconnected", "enough_power", "low_power", "not_supported", "unknown"],
            entity_category=EntityCategory.DIAGNOSTIC,
            value_fn=_attribute("charger"),
        ),
        HubSensorDescription(
            key="brightness",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("brightness"),
        ),
        HubSensorDescription(
            key="volume",
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
            value_fn=_attribute("volume"),
        ),
        HubSensorDescription(
            key="audio_output",
            device_class=SensorDeviceClass.ENUM,
            options=["speaker", "headphone", "tv", "usb", "bluetooth", "unknown"],
            value_fn=_attribute("audio_output"),
        ),
        # Steam account
        HubSensorDescription(
            key="steam_status",
            device_class=SensorDeviceClass.ENUM,
            options=list(STEAM_STATUSES),
            value_fn=_attribute("steam_status"),
            attributes_fn=lambda data: {
                "name": data.snapshot.attributes.get("steam_name"),
                "avatar": data.snapshot.attributes.get("steam_avatar"),
            },
        ),
        # Discord account
        HubSensorDescription(
            key="discord_status",
            device_class=SensorDeviceClass.ENUM,
            options=list(DISCORD_STATUSES),
            value_fn=_attribute("discord_status"),
            attributes_fn=lambda data: {"since": data.snapshot.attributes.get("discord_since")},
        ),
        # PlayStation Network account
        HubSensorDescription(
            key="psn_status",
            value_fn=_attribute("psn_status"),
            attributes_fn=lambda data: {
                "online_id": data.snapshot.attributes.get("psn_online_id"),
                "avatar": data.snapshot.attributes.get("psn_avatar"),
            },
        ),
        HubSensorDescription(
            key="trophy_level",
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_attribute("trophy_level"),
            attributes_fn=lambda data: {
                "progress": data.snapshot.attributes.get("trophy_progress"),
                **(data.snapshot.attributes.get("trophies") or {}),
            },
        ),
    )
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    if entry.data.get(CONF_KIND) == SUMMARY:
        hub: GamingHub = entry.runtime_data
        assert hub.household is not None
        owners = [(hub.household, None), *((o, sid) for sid, o in hub.profiles.items())]
        async_add_entities(SummarySensor(entry, description) for description in SUMMARY_SENSORS)
        for owner, subentry_id in owners:
            async_add_entities(
                [
                    OwnerSensor(owner, description)
                    for description in OWNER_SENSORS
                    if description.key != REMAINING
                    and (subentry_id is not None or not description.profile_only)
                ],
                config_subentry_id=subentry_id,
            )
            _remaining_while_limited(
                hass,
                entry,
                owner,
                lambda owner=owner: OwnerSensor(owner, OWNER_REMAINING),
                async_add_entities,
                subentry_id,
            )
        return
    coordinator = entry.runtime_data
    descriptions = [d for d in HUB_SENSORS if d.exists_fn(coordinator) and d.key != REMAINING]
    descriptions += [DRIVER_SENSORS[key] for key in coordinator.sensor_keys]
    entities = [HubSensor(coordinator, description) for description in descriptions]
    # Sensors no longer provided (power and energy once the plug is unlinked) are removed.
    registry = er.async_get(hass)
    wanted = {entity.unique_id for entity in entities}
    if coordinator.parental.settings.has_limit:
        wanted.add(f"{coordinator.unique_prefix}_{REMAINING}")
    for stale in er.async_entries_for_config_entry(registry, entry.entry_id):
        if stale.domain == Platform.SENSOR and stale.unique_id not in wanted:
            registry.async_remove(stale.entity_id)
    async_add_entities(entities)
    _remaining_while_limited(
        hass,
        entry,
        coordinator,
        lambda: HubSensor(coordinator, CONSOLE_REMAINING),
        async_add_entities,
    )


REMAINING = "parental_remaining"


def _remaining_while_limited(
    hass: HomeAssistant,
    entry: GamingHubConfigEntry,
    owner: Any,
    make: Callable[[], Entity],
    async_add_entities: AddConfigEntryEntitiesCallback,
    subentry_id: str | None = None,
) -> None:
    """The play time left only exists while a daily limit or allowed hours are set.

    Added and removed as the parental settings of ``owner`` (console, profile or household)
    change, so it never counts down to midnight for nothing.
    """
    registry = er.async_get(hass)
    unique_id = f"{owner.unique_prefix}_{REMAINING}"
    added = False

    @callback
    def follow() -> None:
        nonlocal added
        if owner.parental.settings.has_limit:
            if not added:
                added = True
                async_add_entities([make()], config_subentry_id=subentry_id)
            return
        added = False
        if entity_id := registry.async_get_entity_id(Platform.SENSOR, DOMAIN, unique_id):
            registry.async_remove(entity_id)

    follow()
    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_PARENTAL_SETTINGS.format(owner.unique_prefix), follow)
    )


class HubSensor(GamingHubEntity, SensorEntity):
    entity_description: HubSensorDescription

    def __init__(
        self, coordinator: GamingHubCoordinator, description: HubSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator.data)
        if value is None and self.entity_description.none_text:
            return texts(self.hass.config.language)["none"]
        # States are limited to 255 characters; text comes from the consoles.
        return value[:255] if isinstance(value, str) else value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)


# --- Household ("Gaming Hub" device) and profiles --------------------------------------


@dataclass(frozen=True, kw_only=True)
class OwnerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[OwnerData], Any]
    attributes_fn: Callable[[OwnerData], dict[str, Any]] | None = None
    last_reset_fn: Callable[[], datetime] | None = None
    none_text: bool = False
    # The household's play time is on the "Gaming Hub" statistics sensors already.
    profile_only: bool = False


def _owner_playtime(
    key: str, index: int, unit: str, period_start: Callable[[], datetime]
) -> OwnerSensorDescription:
    per, digits = (60, 1) if unit == UnitOfTime.MINUTES else (3600, 2)
    attribute = ("playtime", "playtime_week", "playtime_month")[index]
    return OwnerSensorDescription(
        key=key,
        device_class=SensorDeviceClass.DURATION,
        # A sum over consoles: after a restart it grows back from zero (see summary.py).
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=unit,
        suggested_display_precision=0 if unit == UnitOfTime.MINUTES else 1,
        value_fn=lambda data: round(getattr(data, attribute) / per, digits),
        attributes_fn=lambda data: {
            console: round(periods[index] / per, digits)
            for console, periods in data.consoles.items()
        },
        last_reset_fn=period_start,
        profile_only=True,
    )


OWNER_SENSORS: tuple[OwnerSensorDescription, ...] = (
    _owner_playtime("playtime_today", 0, UnitOfTime.MINUTES, start_of_day),
    _owner_playtime("playtime_week", 1, UnitOfTime.HOURS, start_of_week),
    _owner_playtime("playtime_month", 2, UnitOfTime.HOURS, start_of_month),
    OwnerSensorDescription(
        key="playing_on",
        value_fn=lambda data: (
            ", ".join(game or console for console, game in data.playing.items())[:255] or None
        ),
        attributes_fn=lambda data: dict(data.playing),
        none_text=True,
        profile_only=True,
    ),
    OwnerSensorDescription(
        key="parental_status",
        device_class=SensorDeviceClass.ENUM,
        options=[status.value for status in ParentalStatus],
        value_fn=lambda data: data.parental.status.value,
        attributes_fn=lambda data: {"reason": data.parental.reason and data.parental.reason.value},
    ),
    OwnerSensorDescription(
        key="parental_remaining",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        suggested_display_precision=0,
        value_fn=lambda data: round(max(data.parental.remaining, 0), 1),
    ),
)


class OwnerSensor(GamingHubEntity[ParentalOwner], SensorEntity):
    entity_description: OwnerSensorDescription

    def __init__(self, owner: ParentalOwner, description: OwnerSensorDescription) -> None:
        super().__init__(owner, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        value = self.entity_description.value_fn(self.coordinator.data)
        if value is None and self.entity_description.none_text:
            return texts(self.hass.config.language)["none"]
        return value

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.entity_description.attributes_fn is None:
            return None
        return self.entity_description.attributes_fn(self.coordinator.data)

    @property
    def last_reset(self) -> datetime | None:
        reset = self.entity_description.last_reset_fn
        return reset() if reset else None


CONSOLE_REMAINING = next(d for d in HUB_SENSORS if d.key == REMAINING)
OWNER_REMAINING = next(d for d in OWNER_SENSORS if d.key == REMAINING)
