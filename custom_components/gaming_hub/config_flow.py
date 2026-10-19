"""Config flow: one entry per console."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
import voluptuous as vol

from .const import (
    CONF_ACCOUNT_ID,
    CONF_BLOCK_ENTITY,
    CONF_CLIENT_ID,
    CONF_DISCOVERY_PREFIX,
    CONF_ENERGY_SOURCE,
    CONF_HIDE_SOURCES,
    CONF_HOST,
    CONF_HOST_ID,
    CONF_IMAGE_TEMPLATE,
    CONF_KIND,
    CONF_NAME,
    CONF_NPSSO,
    CONF_ON_THRESHOLD,
    CONF_PASSCODE,
    CONF_PIN,
    CONF_PORT,
    CONF_POWER_ENTITY,
    CONF_PRESET,
    CONF_REGIST_KEY,
    CONF_RP_KEY,
    CONF_SOURCE_ENTITY,
    CONF_TURN_OFF_ENTITY,
    CONF_TURN_ON_ENTITY,
    DEFAULT_SWITCH_IMAGE_TEMPLATE,
    DOMAIN,
    PS5_MQTT_CREDENTIALS,
    SUMMARY,
    ConsoleKind,
    LinkedPreset,
)
from .consumption import plug_energy_sensor
from .coordinator import PSN_PLATFORMS, profile_key
from .protocols import ddp, remoteplay
from .protocols import switch_assistant as sa
from .protocols.psn import NPSSO_URL, PsnAuthError, PsnClient, PsnError
from .protocols.webman import DEFAULT_PORT, WebmanClient, WebmanError

# Pairing failures with a dedicated message; anything else is "pairing_failed".
PAIRING_ERRORS = {
    "invalid_pin",
    "invalid_account",
    "not_in_pairing_mode",
    "cannot_connect",
    "in_use",
}
SOURCE_DOMAINS = [
    Platform.MEDIA_PLAYER,
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    "input_boolean",
    "device_tracker",
    Platform.SENSOR,
]
ACTION_DOMAINS = ["script", "scene", "button", "input_button", "switch", "input_boolean"]
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _watts() -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=1000, step=0.5, unit_of_measurement="W", mode=NumberSelectorMode.BOX
        )
    )


def _read_playactor_file(path: Path, host_id: str | None) -> remoteplay.Ps5Credentials | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    try:
        return (
            remoteplay.credentials_from_playactor(data, host_id) if isinstance(data, dict) else None
        )
    except remoteplay.RemotePlayError:
        return None


class GamingHubConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> GamingHubOptionsFlow:
        return GamingHubOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        return config_entry.data.get(CONF_KIND) != SUMMARY

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[*(kind.value for kind in ConsoleKind), SUMMARY]
        )

    async def async_step_summary(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Statistics across all the consoles (once)."""
        await self.async_set_unique_id(SUMMARY)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Gaming Hub", data={CONF_KIND: SUMMARY})

    def _create(self) -> ConfigFlowResult:
        return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

    # --- PlayStation 5 ------------------------------------------------------

    async def async_step_ps5(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                response = await ddp.async_get_status(host, timeout=3)
            except OSError:
                response = None
            if response is None:
                errors["base"] = "cannot_connect"
            elif response.host_type not in (None, "PS5"):
                errors["base"] = "not_ps5"
            else:
                await self.async_set_unique_id(response.host_id or host)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                self._data = {
                    CONF_KIND: ConsoleKind.PS5.value,
                    CONF_HOST: host,
                    CONF_HOST_ID: response.host_id,
                    CONF_NAME: user_input.get(CONF_NAME) or response.host_name or "PlayStation 5",
                }
                return await self.async_step_psn()
        suggested = ""
        if user_input is None:
            try:
                found = await ddp.async_search(None, timeout=2)
            except OSError:
                found = []
            suggested = next((r.address for r in found if r.host_type in (None, "PS5")), "")
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=suggested): str,
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(step_id="ps5", data_schema=schema, errors=errors)

    def _ps5_mqtt_file(self) -> Path:
        return Path(self.hass.config.path(*PS5_MQTT_CREDENTIALS))

    async def async_step_ps5_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        options = ["ps5_register", "ps5_skip"]
        if await self.hass.async_add_executor_job(self._ps5_mqtt_file().is_file):
            options.insert(0, "ps5_import")
        if self.source == SOURCE_RECONFIGURE:
            options.remove("ps5_skip")
        return self.async_show_menu(step_id="ps5_pairing", menu_options=options)

    async def _finish_pairing(
        self, creds: remoteplay.Ps5Credentials, passcode: str | None
    ) -> ConfigFlowResult:
        pairing = {
            CONF_REGIST_KEY: creds.regist_key,
            CONF_RP_KEY: creds.rp_key,
            CONF_PASSCODE: passcode or None,
        }
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_reload_and_abort(
                self._get_reconfigure_entry(), data_updates=pairing
            )
        self._data.update(pairing)
        return self._create()

    async def async_step_ps5_import(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            creds = await self.hass.async_add_executor_job(
                _read_playactor_file, self._ps5_mqtt_file(), self._data.get(CONF_HOST_ID)
            )
            if creds is None:
                errors["base"] = "import_failed"
            else:
                return await self._finish_pairing(creds, user_input.get(CONF_PASSCODE))
        schema = vol.Schema({vol.Optional(CONF_PASSCODE): PASSWORD})
        return self.async_show_form(step_id="ps5_import", data_schema=schema, errors=errors)

    async def async_step_ps5_register(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                creds, _ = await remoteplay.async_register(
                    self._data[CONF_HOST], user_input[CONF_ACCOUNT_ID], user_input[CONF_PIN]
                )
            except remoteplay.RemotePlayError as err:
                errors["base"] = err.reason if err.reason in PAIRING_ERRORS else "pairing_failed"
            else:
                return await self._finish_pairing(creds, user_input.get(CONF_PASSCODE))
        # Known when the PlayStation Network account was linked in the previous step.
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ACCOUNT_ID,
                    description={"suggested_value": self._data.get(CONF_ACCOUNT_ID)},
                ): str,
                vol.Required(CONF_PIN): str,
                vol.Optional(CONF_PASSCODE): PASSWORD,
            }
        )
        return self.async_show_form(
            step_id="ps5_register",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_ps5_skip(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self._create()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        self._data = dict(entry.data)
        if entry.data[CONF_KIND] == SUMMARY:
            return self.async_abort(reason="reconfigure_unsupported")
        if entry.data[CONF_KIND] == ConsoleKind.PS5:
            return self.async_show_menu(step_id="reconfigure", menu_options=["psn", "ps5_pairing"])
        if PSN_PLATFORMS.get(profile_key(self._data)):
            return await self.async_step_psn()
        return self.async_abort(reason="reconfigure_unsupported")

    # --- PlayStation Network (PS5, PS3, PS4) ----------------------------------

    async def _validate_npsso(self, npsso: str) -> tuple[dict[str, str], dict[str, str]]:
        """Data to store for a NPSSO token, and form errors."""
        client = PsnClient(async_get_clientsession(self.hass), npsso)
        try:
            status = await client.async_get_status()
        except PsnAuthError:
            return {}, {"base": "invalid_npsso"}
        except PsnError:
            return {}, {"base": "psn_unavailable"}
        return {CONF_NPSSO: npsso, CONF_ACCOUNT_ID: status.account_id}, {}

    async def async_step_psn(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Optional PlayStation Network account: game, artwork, trophies, PS Plus."""
        errors: dict[str, str] = {}
        if user_input is not None:
            psn: dict[str, Any] = {CONF_NPSSO: None}
            if npsso := (user_input.get(CONF_NPSSO) or "").strip():
                psn, errors = await self._validate_npsso(npsso)
            if not errors:
                self._data.update(psn)
                if self.source == SOURCE_RECONFIGURE:
                    return self.async_update_reload_and_abort(
                        self._get_reconfigure_entry(), data_updates=psn
                    )
                if self._data[CONF_KIND] == ConsoleKind.PS5:
                    return await self.async_step_ps5_pairing()
                return self._create()
        return self.async_show_form(
            step_id="psn",
            data_schema=vol.Schema({vol.Optional(CONF_NPSSO): PASSWORD}),
            description_placeholders={"npsso_url": NPSSO_URL},
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The NPSSO token expired (about every two months)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            psn, errors = await self._validate_npsso(user_input[CONF_NPSSO].strip())
            if not errors:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=psn
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_NPSSO): PASSWORD}),
            description_placeholders={"npsso_url": NPSSO_URL},
            errors=errors,
        )

    # --- PlayStation 3 ------------------------------------------------------

    async def async_step_ps3(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input.get(CONF_PORT, DEFAULT_PORT))
            client = WebmanClient(async_get_clientsession(self.hass), host, port)
            try:
                status = await client.async_get_status()
            except WebmanError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(status.mac or f"{host}:{port}")
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                self._data = {
                    CONF_KIND: ConsoleKind.PS3.value,
                    CONF_HOST: host,
                    CONF_PORT: port,
                    CONF_NAME: user_input.get(CONF_NAME) or "PlayStation 3",
                }
                return await self.async_step_psn()
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=65535)
                ),
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="ps3",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    # --- Nintendo Switch ----------------------------------------------------

    async def async_step_switch(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self.hass.config_entries.async_entries("mqtt"):
            return self.async_abort(reason="mqtt_required")
        if user_input is not None:
            client_id = sa.sanitize_client_id(user_input[CONF_CLIENT_ID])
            await self.async_set_unique_id(client_id)
            self._abort_if_unique_id_configured()
            self._data = {
                CONF_KIND: ConsoleKind.SWITCH.value,
                CONF_CLIENT_ID: client_id,
                CONF_DISCOVERY_PREFIX: user_input[CONF_DISCOVERY_PREFIX].strip("/"),
                CONF_NAME: user_input.get(CONF_NAME) or "Nintendo Switch",
            }
            return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_CLIENT_ID): str,
                vol.Required(CONF_DISCOVERY_PREFIX, default=sa.DEFAULT_DISCOVERY_PREFIX): str,
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(step_id="switch", data_schema=schema)

    async def async_step_mqtt(self, discovery_info: MqttServiceInfo) -> ConfigFlowResult:
        """A Switch Assistant console published its state."""
        client_id = sa.client_id_from_topic(discovery_info.topic)
        if client_id is None:
            return self.async_abort(reason="invalid_discovery")
        await self.async_set_unique_id(client_id)
        self._abort_if_unique_id_configured()
        self._data = {CONF_KIND: ConsoleKind.SWITCH.value, CONF_CLIENT_ID: client_id}
        self.context["title_placeholders"] = {"client_id": client_id}
        return await self.async_step_switch_confirm()

    async def async_step_switch_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._data[CONF_DISCOVERY_PREFIX] = user_input[CONF_DISCOVERY_PREFIX].strip("/")
            self._data[CONF_NAME] = user_input.get(CONF_NAME) or "Nintendo Switch"
            return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_DISCOVERY_PREFIX, default=sa.DEFAULT_DISCOVERY_PREFIX): str,
                vol.Optional(CONF_NAME, default="Nintendo Switch"): str,
            }
        )
        return self.async_show_form(
            step_id="switch_confirm",
            data_schema=schema,
            description_placeholders={"client_id": self._data[CONF_CLIENT_ID]},
        )

    # --- Any other console already in Home Assistant -------------------------

    async def async_step_linked(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            source = user_input[CONF_SOURCE_ENTITY]
            await self.async_set_unique_id(f"linked_{source}")
            self._abort_if_unique_id_configured()
            state = self.hass.states.get(source)
            default_name = state.name if state else source
            self._data = {
                CONF_KIND: ConsoleKind.LINKED.value,
                CONF_PRESET: user_input[CONF_PRESET],
                CONF_SOURCE_ENTITY: source,
                CONF_ON_THRESHOLD: user_input.get(CONF_ON_THRESHOLD, 5),
                CONF_NAME: user_input.get(CONF_NAME) or default_name,
            }
            if PSN_PLATFORMS.get(user_input[CONF_PRESET]):
                return await self.async_step_psn()
            return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_PRESET, default=LinkedPreset.XBOX.value): SelectSelector(
                    SelectSelectorConfig(
                        options=[preset.value for preset in LinkedPreset],
                        translation_key="preset",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(CONF_SOURCE_ENTITY): EntitySelector(
                    EntitySelectorConfig(domain=SOURCE_DOMAINS)
                ),
                vol.Optional(CONF_NAME): str,
                vol.Optional(CONF_ON_THRESHOLD, default=5): _watts(),
            }
        )
        return self.async_show_form(step_id="linked", data_schema=schema)


class GamingHubOptionsFlow(OptionsFlow):
    """Links to other entities: power sensor, commands, parental block."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        if user_input is not None:
            if entry.data[CONF_KIND] == ConsoleKind.SWITCH:
                # An empty template disables artwork instead of restoring the default.
                user_input.setdefault(CONF_IMAGE_TEMPLATE, "")
            self._options = user_input
            if user_input.get(CONF_POWER_ENTITY):
                return await self.async_step_energy()
            return self.async_create_entry(data=user_input)
        fields: dict[Any, Any] = {
            vol.Optional(CONF_POWER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=Platform.SENSOR, device_class="power")
            ),
            vol.Optional(CONF_TURN_ON_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=ACTION_DOMAINS)
            ),
            vol.Optional(CONF_TURN_OFF_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=ACTION_DOMAINS)
            ),
            vol.Optional(CONF_BLOCK_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=ACTION_DOMAINS)
            ),
        }
        if entry.data[CONF_KIND] == ConsoleKind.SWITCH:
            fields[vol.Optional(CONF_IMAGE_TEMPLATE)] = str
        suggested = {CONF_IMAGE_TEMPLATE: DEFAULT_SWITCH_IMAGE_TEMPLATE, **entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), suggested),
        )

    async def async_step_energy(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """With a plug: the energy meter the console replaces, so nothing is counted twice."""
        if user_input is not None:
            return self.async_create_entry(data={**self._options, **user_input})
        options = self.config_entry.options
        power = self._options[CONF_POWER_ENTITY]
        suggested = {
            CONF_ENERGY_SOURCE: options.get(CONF_ENERGY_SOURCE)
            if options.get(CONF_POWER_ENTITY) == power
            else plug_energy_sensor(self.hass, power),
            CONF_HIDE_SOURCES: options.get(CONF_HIDE_SOURCES, True),
        }
        schema = vol.Schema(
            {
                vol.Optional(CONF_ENERGY_SOURCE): EntitySelector(
                    EntitySelectorConfig(domain=Platform.SENSOR, device_class="energy")
                ),
                vol.Required(CONF_HIDE_SOURCES): BooleanSelector(),
            }
        )
        return self.async_show_form(
            step_id="energy", data_schema=self.add_suggested_values_to_schema(schema, suggested)
        )
