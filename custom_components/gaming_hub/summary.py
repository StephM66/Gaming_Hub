"""Statistics across all the consoles, on one "Gaming Hub" device.

Added once from the menu. Its sensors add up the consoles' play time (today, this week,
this month, with the share of each console) and tell which consoles are on and what is
played. Console coordinators signal each refresh; the summary only reads their data.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_CONSOLES_UPDATED, texts
from .coordinator import ConsoleData, running_consoles

type Consoles = list[tuple[str, ConsoleData]]


def loaded_consoles(hass: HomeAssistant) -> Consoles:
    """Name and latest data of each console currently running."""
    return [(c.config_entry.title, c.data) for c in running_consoles(hass)]


def _total(seconds: Callable[[ConsoleData], float], per: float, digits: int):
    def value(consoles: Consoles) -> float:
        return round(sum(seconds(data) for _, data in consoles) / per, digits)

    def shares(consoles: Consoles) -> dict[str, Any]:
        return {name: round(seconds(data) / per, digits) for name, data in consoles}

    return value, shares


def _games(consoles: Consoles) -> dict[str, str]:
    return {
        name: data.snapshot.title
        for name, data in consoles
        if data.snapshot.playing and data.snapshot.title
    }


def start_of_day() -> datetime:
    return dt_util.start_of_local_day()


def start_of_week() -> datetime:
    today = dt_util.start_of_local_day()
    return today - timedelta(days=today.weekday())


def start_of_month() -> datetime:
    return dt_util.start_of_local_day().replace(day=1)


@dataclass(frozen=True, kw_only=True)
class SummarySensorDescription(SensorEntityDescription):
    value_fn: Callable[[Consoles], Any]
    attributes_fn: Callable[[Consoles], dict[str, Any]]
    last_reset_fn: Callable[[], datetime] | None = None
    none_text: bool = False  # no value reads "None" instead of "unknown"


def _playtime(
    key: str,
    seconds: Callable[[ConsoleData], float],
    unit: str,
    period_start: Callable[[], datetime],
) -> SummarySensorDescription:
    per, digits = (60, 1) if unit == UnitOfTime.MINUTES else (3600, 2)
    value, shares = _total(seconds, per, digits)
    return SummarySensorDescription(
        key=key,
        device_class=SensorDeviceClass.DURATION,
        # Not "total increasing": while consoles load after a restart the sum goes up from
        # zero, which would read as resets and count the same play time again. With
        # last_reset, a temporary drop is only a negative change.
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=unit,
        suggested_display_precision=0 if unit == UnitOfTime.MINUTES else 1,
        value_fn=value,
        attributes_fn=shares,
        last_reset_fn=period_start,
    )


SUMMARY_SENSORS: tuple[SummarySensorDescription, ...] = (
    _playtime("playtime_today", lambda data: data.playtime, UnitOfTime.MINUTES, start_of_day),
    _playtime("playtime_week", lambda data: data.playtime_week, UnitOfTime.HOURS, start_of_week),
    _playtime("playtime_month", lambda data: data.playtime_month, UnitOfTime.HOURS, start_of_month),
    SummarySensorDescription(
        key="consoles_on",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda consoles: sum(data.snapshot.is_on for _, data in consoles),
        attributes_fn=lambda consoles: {
            "consoles": [name for name, data in consoles if data.snapshot.is_on]
        },
    ),
    SummarySensorDescription(
        key="games",
        value_fn=lambda consoles: ", ".join(_games(consoles).values())[:255] or None,
        attributes_fn=_games,
        none_text=True,
    ),
)


class SummarySensor(SensorEntity):
    entity_description: SummarySensorDescription
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry, description: SummarySensorDescription) -> None:
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_translation_key = description.key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Gaming Hub",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(self.hass, SIGNAL_CONSOLES_UPDATED, self._async_update)
        )
        self._compute()

    @callback
    def _async_update(self) -> None:
        self._compute()
        self.async_write_ha_state()

    def _compute(self) -> None:
        consoles = loaded_consoles(self.hass)
        value = self.entity_description.value_fn(consoles)
        if value is None and self.entity_description.none_text:
            value = texts(self.hass.config.language)["none"]
        self._attr_native_value = value
        self._attr_extra_state_attributes = self.entity_description.attributes_fn(consoles)
        if self.entity_description.last_reset_fn:
            self._attr_last_reset = self.entity_description.last_reset_fn()
