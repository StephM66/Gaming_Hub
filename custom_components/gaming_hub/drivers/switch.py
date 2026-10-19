"""Nintendo Switch running Switch Assistant (CFW), over the MQTT integration."""

from __future__ import annotations

from collections.abc import Callable
import time

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from ..const import (
    CONF_CLIENT_ID,
    CONF_DISCOVERY_PREFIX,
    CONF_IMAGE_TEMPLATE,
    DEFAULT_SWITCH_IMAGE_TEMPLATE,
)
from ..models import ConsoleSnapshot, PowerState
from ..protocols import switch_assistant as sa
from .base import ConsoleDriver


class SwitchDriver(ConsoleDriver):
    sensors = ("battery", "battery_temperature", "controllers")
    binary_sensors = ("charging",)
    can_restart = True
    can_notify = True

    def __init__(self, hass: HomeAssistant, entry) -> None:
        super().__init__(hass, entry)
        self._client_id: str = entry.data[CONF_CLIENT_ID]
        self._prefix: str = entry.data.get(CONF_DISCOVERY_PREFIX, sa.DEFAULT_DISCOVERY_PREFIX)
        self._template: str = entry.options.get(CONF_IMAGE_TEMPLATE, DEFAULT_SWITCH_IMAGE_TEMPLATE)
        self.state = sa.SwitchAssistantState(self._client_id)
        self._unsubscribe: list[Callable[[], None]] = []

    @property
    def can_turn_off(self) -> bool:
        return True

    async def async_start(self, on_change: Callable[[], None]) -> None:
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            raise ConfigEntryNotReady("MQTT is not available")

        @callback
        def on_state(message: mqtt.ReceiveMessage) -> None:
            if self.state.handle_state(
                message.topic, str(message.payload), retained=message.retain, now=time.monotonic()
            ):
                on_change()

        @callback
        def on_status(message: mqtt.ReceiveMessage) -> None:
            if self.state.handle_status(
                str(message.payload), retained=message.retain, now=time.monotonic()
            ):
                on_change()

        self._unsubscribe = [
            await mqtt.async_subscribe(self.hass, sa.state_topic(self._client_id), on_state),
            await mqtt.async_subscribe(self.hass, sa.status_topic(self._prefix), on_status),
        ]

    async def async_stop(self) -> None:
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe = []

    async def async_fetch(self) -> ConsoleSnapshot:
        state = self.state
        attributes = {
            "battery": state.battery,
            "battery_temperature": state.battery_temperature,
            "controllers": state.controllers,
            "charging": state.charging,
        }
        if not state.is_online(time.monotonic()):
            return ConsoleSnapshot(PowerState.OFF, attributes=attributes)
        title_id = state.title_id
        image = None
        if title_id and self._template:
            image = self._template.format(title_id=title_id, title_id_lower=title_id.lower())
        return ConsoleSnapshot(
            PowerState.ON,
            in_game=state.game_running,
            title=state.title,
            title_id=title_id,
            image_url=image,
            attributes=attributes,
        )

    async def async_turn_off(self) -> None:
        await mqtt.async_publish(self.hass, sa.command_topic(self._prefix), "shutdown")

    async def async_restart(self) -> None:
        await mqtt.async_publish(self.hass, sa.command_topic(self._prefix), "reboot")

    async def async_notify(self, message: str, title: str | None = None) -> None:
        await mqtt.async_publish(
            self.hass, sa.popup_topic(self._client_id), sa.popup_payload(message, title)
        )
