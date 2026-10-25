"""Config flow: one entry per console."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import Platform
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    SelectOptionDict,
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
    CONF_ACCOUNTS,
    CONF_API_KEY,
    CONF_BLOCK_ENTITY,
    CONF_BOT_TOKEN,
    CONF_CLIENT_ID,
    CONF_CONSOLES,
    CONF_DEVICE_ID,
    CONF_DISCOVERY_PREFIX,
    CONF_ENERGY_SOURCE,
    CONF_HIDE_SOURCES,
    CONF_HOST,
    CONF_HOST_ID,
    CONF_IMAGE_TEMPLATE,
    CONF_KIND,
    CONF_MODEL,
    CONF_NAME,
    CONF_NPSSO,
    CONF_PASSCODE,
    CONF_PIN,
    CONF_PLAYERS,
    CONF_PORT,
    CONF_POWER_ENTITY,
    CONF_PRESET,
    CONF_REGIST_KEY,
    CONF_RESTART_ENTITY,
    CONF_RP_KEY,
    CONF_SESSION_TOKEN,
    CONF_STATE_ENTITY,
    CONF_STEAM_ID,
    CONF_TURN_OFF_ENTITY,
    CONF_TURN_ON_ENTITY,
    CONF_USER_ID,
    DEFAULT_SWITCH_IMAGE_TEMPLATE,
    DEVICE_INFO,
    DOMAIN,
    PS5_MQTT_CREDENTIALS,
    REMOVED_KINDS,
    SUBENTRY_PROFILE,
    SUMMARY,
    ConsoleKind,
    PsnConsole,
)
from .consumption import plug_energy_sensor
from .protocols import ddp, discord, nintendo, remoteplay, steam
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
ACTION_DOMAINS = ["script", "scene", "button", "input_button", "switch", "input_boolean"]
# Entities that can tell whether a console is on ("Complete" options).
STATE_DOMAINS = [
    Platform.SWITCH,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.MEDIA_PLAYER,
    "input_boolean",
    "device_tracker",
]
PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
CONF_LINK = "link"  # Nintendo account link pasted during sign-in
CONF_ACCOUNT = "account"  # Steam account as typed: SteamID64, profile link or custom name


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
        self._nintendo_login: nintendo.NintendoLogin | None = None
        self._nintendo_devices: dict[str, nintendo.NintendoDevice] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> GamingHubOptionsFlow:
        return GamingHubOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        return config_entry.data.get(CONF_KIND) not in {SUMMARY, *REMOVED_KINDS}

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Profiles belong to the "Gaming Hub" entry."""
        if config_entry.data.get(CONF_KIND) == SUMMARY:
            return {SUBENTRY_PROFILE: ProfileSubentryFlow}
        return {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(
            step_id="user", menu_options=[*(kind.value for kind in ConsoleKind), SUMMARY]
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Created with the first console (see __init__._ensure_hub)."""
        return await self.async_step_summary()

    async def async_step_summary(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Statistics, household and profiles across all the consoles (once)."""
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
        if entry.data[CONF_KIND] not in (ConsoleKind.PS5, ConsoleKind.PS3):
            # Account consoles renew their sign-in when the account asks (reauthentication).
            return self.async_abort(reason="reconfigure_unsupported")
        if entry.data[CONF_KIND] == ConsoleKind.PS5:
            return self.async_show_menu(step_id="reconfigure", menu_options=["psn", "ps5_pairing"])
        return await self.async_step_psn()  # modified PS3: link or unlink the account

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
        if entry_data.get(CONF_KIND) == ConsoleKind.NINTENDO:
            return await self.async_step_nintendo_reauth()
        if entry_data.get(CONF_KIND) == ConsoleKind.STEAM:
            return await self.async_step_steam_reauth()
        if entry_data.get(CONF_KIND) == ConsoleKind.DISCORD:
            return await self.async_step_discord_reauth()
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

    # --- Nintendo account (Switch, Switch 2) --------------------------------

    def _nintendo_form(self, step_id: str, errors: dict[str, str]) -> ConfigFlowResult:
        if self._nintendo_login is None:
            self._nintendo_login = nintendo.login()
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({vol.Required(CONF_LINK): str}),
            description_placeholders={"login_url": self._nintendo_login.url},
            errors=errors,
        )

    async def _nintendo_sign_in(self, link: str) -> tuple[str, dict[str, str]]:
        """Session token for the pasted link (and the account's consoles), or form errors."""
        session = async_get_clientsession(self.hass)
        login = self._nintendo_login or nintendo.login()
        try:
            token = await nintendo.async_session_token(session, link, login.verifier)
            devices = await nintendo.NintendoClient(session, token).async_devices()
        except nintendo.NintendoAuthError:
            return "", {"base": "invalid_link"}
        except nintendo.NintendoError:
            return "", {"base": "nintendo_unavailable"}
        self._nintendo_devices = {device.device_id: device for device in devices}
        return token, {}

    async def async_step_nintendo(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Sign in to the Nintendo account that manages the console (Parental Controls)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token, errors = await self._nintendo_sign_in(user_input[CONF_LINK])
            if not errors:
                if not self._nintendo_devices:
                    return self.async_abort(reason="no_nintendo_console")
                self._data = {CONF_KIND: ConsoleKind.NINTENDO.value, CONF_SESSION_TOKEN: token}
                return await self.async_step_nintendo_console()
        return self._nintendo_form("nintendo", errors)

    async def async_step_nintendo_console(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Which console of the account, when it has several."""
        devices = self._nintendo_devices
        if user_input is None and len(devices) == 1:
            user_input = {}
        if user_input is not None:
            device = devices[user_input.get(CONF_DEVICE_ID) or next(iter(devices))]
            await self.async_set_unique_id(f"nintendo_{device.device_id}")
            self._abort_if_unique_id_configured(
                updates={CONF_SESSION_TOKEN: self._data[CONF_SESSION_TOKEN]}
            )
            self._data |= {
                CONF_DEVICE_ID: device.device_id,
                CONF_MODEL: device.model,
                CONF_NAME: user_input.get(CONF_NAME) or device.name,
            }
            return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(
                                value=device_id, label=f"{device.name} ({device.model})"
                            )
                            for device_id, device in devices.items()
                        ]
                    )
                ),
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(step_id="nintendo_console", data_schema=schema)

    async def async_step_nintendo_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The Nintendo session ended (signed out, password changed): sign in again."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            token, errors = await self._nintendo_sign_in(user_input[CONF_LINK])
            if not errors and entry.data[CONF_DEVICE_ID] not in self._nintendo_devices:
                errors["base"] = "nintendo_console_missing"
            if not errors:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_SESSION_TOKEN: token}
                )
        return self._nintendo_form("nintendo_reauth", errors)

    # --- PS4 or PS3 through the PlayStation Network account -------------------

    async def async_step_playstation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """On or off, game and artwork, as the PlayStation Network account sees the console."""
        errors: dict[str, str] = {}
        if user_input is not None:
            model = PsnConsole(user_input[CONF_PRESET])
            psn, errors = await self._validate_npsso(user_input[CONF_NPSSO].strip())
            if not errors:
                await self.async_set_unique_id(f"psn_{psn[CONF_ACCOUNT_ID]}_{model}")
                self._abort_if_unique_id_configured(updates=psn)
                self._data = {
                    CONF_KIND: ConsoleKind.PLAYSTATION.value,
                    CONF_PRESET: model.value,
                    CONF_NAME: user_input.get(CONF_NAME) or DEVICE_INFO[model][1],
                    **psn,
                }
                return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_PRESET, default=PsnConsole.PS4.value): SelectSelector(
                    SelectSelectorConfig(
                        options=[console.value for console in PsnConsole],
                        translation_key="psn_console",
                        mode=SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(CONF_NPSSO): PASSWORD,
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="playstation",
            data_schema=schema,
            description_placeholders={"npsso_url": NPSSO_URL},
            errors=errors,
        )

    # --- Steam account (PC, Steam Deck) ---------------------------------------

    async def _steam_status(
        self, api_key: str, account: str
    ) -> tuple[steam.SteamStatus | None, dict[str, str]]:
        client = steam.SteamClient(async_get_clientsession(self.hass), api_key)
        try:
            return await client.async_status(await client.async_resolve(account)), {}
        except steam.SteamAuthError:
            return None, {"base": "invalid_api_key"}
        except steam.SteamAccountError:
            return None, {"base": "steam_account_not_found"}
        except steam.SteamError:
            return None, {"base": "steam_unavailable"}

    async def async_step_steam(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Status and game of a Steam account, with the owner's Web API key."""
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            status, errors = await self._steam_status(api_key, user_input[CONF_ACCOUNT])
            if status is not None:
                await self.async_set_unique_id(f"steam_{status.steam_id}")
                self._abort_if_unique_id_configured(updates={CONF_API_KEY: api_key})
                self._data = {
                    CONF_KIND: ConsoleKind.STEAM.value,
                    CONF_API_KEY: api_key,
                    CONF_STEAM_ID: status.steam_id,
                    CONF_NAME: user_input.get(CONF_NAME) or status.name or "Steam",
                }
                return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): PASSWORD,
                vol.Required(CONF_ACCOUNT): str,
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="steam",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in (user_input or {}).items() if k != CONF_API_KEY}
            ),
            description_placeholders={"key_url": steam.KEY_URL},
            errors=errors,
        )

    async def async_step_steam_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The Web API key was revoked or replaced."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            api_key = user_input[CONF_API_KEY].strip()
            status, errors = await self._steam_status(api_key, entry.data[CONF_STEAM_ID])
            if status is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="steam_reauth",
            data_schema=vol.Schema({vol.Required(CONF_API_KEY): PASSWORD}),
            description_placeholders={"key_url": steam.KEY_URL},
            errors=errors,
        )

    # --- Discord account (PC games of any launcher) ---------------------------

    async def _discord_name(self, token: str, player: str) -> tuple[str | None, dict[str, str]]:
        if (user_id := discord.user_id(player)) is None:
            return None, {"base": "discord_user_not_found"}
        client = discord.DiscordClient(async_get_clientsession(self.hass), token)
        try:
            return await client.async_check(user_id), {}
        except discord.DiscordAuthError:
            return None, {"base": "invalid_bot_token"}
        except discord.DiscordIntentError:
            return None, {"base": "discord_presence_intent"}
        except discord.DiscordUserError:
            return None, {"base": "discord_user_not_found"}
        except discord.DiscordError:
            return None, {"base": "discord_unavailable"}

    async def async_step_discord(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Games of a Discord account, seen by the player's own bot."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = user_input[CONF_BOT_TOKEN].strip()
            name, errors = await self._discord_name(token, user_input[CONF_USER_ID])
            if name is not None:
                user_id = user_input[CONF_USER_ID].strip()
                await self.async_set_unique_id(f"discord_{user_id}")
                self._abort_if_unique_id_configured(updates={CONF_BOT_TOKEN: token})
                self._data = {
                    CONF_KIND: ConsoleKind.DISCORD.value,
                    CONF_BOT_TOKEN: token,
                    CONF_USER_ID: user_id,
                    CONF_NAME: user_input.get(CONF_NAME) or name,
                }
                return self._create()
        schema = vol.Schema(
            {
                vol.Required(CONF_BOT_TOKEN): PASSWORD,
                vol.Required(CONF_USER_ID): str,
                vol.Optional(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="discord",
            data_schema=self.add_suggested_values_to_schema(
                schema, {k: v for k, v in (user_input or {}).items() if k != CONF_BOT_TOKEN}
            ),
            description_placeholders={"portal_url": discord.PORTAL_URL},
            errors=errors,
        )

    async def async_step_discord_reauth(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The bot's token was reset."""
        errors: dict[str, str] = {}
        if user_input is not None:
            entry = self._get_reauth_entry()
            token = user_input[CONF_BOT_TOKEN].strip()
            name, errors = await self._discord_name(token, entry.data[CONF_USER_ID])
            if name is not None:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_BOT_TOKEN: token}
                )
        return self.async_show_form(
            step_id="discord_reauth",
            data_schema=vol.Schema({vol.Required(CONF_BOT_TOKEN): PASSWORD}),
            description_placeholders={"portal_url": discord.PORTAL_URL},
            errors=errors,
        )

    # --- Nintendo Switch modified with Switch Assistant ----------------------

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


class GamingHubOptionsFlow(OptionsFlow):
    """Power sensor, and entities that complete what the console cannot do itself."""

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
        actions = EntitySelector(EntitySelectorConfig(domain=ACTION_DOMAINS))
        fields: dict[Any, Any] = {
            vol.Optional(CONF_POWER_ENTITY): EntitySelector(
                EntitySelectorConfig(domain=Platform.SENSOR, device_class="power")
            ),
        }
        # Only what the console cannot do itself (all of it when it is not running now);
        # a choice made earlier stays shown so it can be cleared.
        driver = (
            entry.runtime_data.driver
            if entry.state is ConfigEntryState.LOADED and hasattr(entry.runtime_data, "driver")
            else None
        )
        missing = {
            CONF_STATE_ENTITY: driver is None or not driver.native_state,
            CONF_TURN_ON_ENTITY: driver is None or not driver.can_turn_on,
            CONF_TURN_OFF_ENTITY: driver is None or not driver.can_turn_off,
            CONF_RESTART_ENTITY: driver is None or "restart" not in driver.buttons,
        }
        for key, shown in missing.items():
            if shown or entry.options.get(key):
                selector = (
                    EntitySelector(EntitySelectorConfig(domain=STATE_DOMAINS))
                    if key == CONF_STATE_ENTITY
                    else actions
                )
                fields[vol.Optional(key)] = selector
        fields[vol.Optional(CONF_BLOCK_ENTITY)] = actions
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


class ProfileSubentryFlow(ConfigSubentryFlow):
    """A child: what is theirs among the consoles, accounts and Switch players."""

    def _schema(self) -> vol.Schema:
        consoles = [
            entry
            for entry in self.hass.config_entries.async_entries(DOMAIN)
            if entry.data.get(CONF_KIND) in {kind.value for kind in ConsoleKind}
        ]

        def choice(options: list[SelectOptionDict]) -> SelectSelector:
            return SelectSelector(
                SelectSelectorConfig(options=options, multiple=True, mode=SelectSelectorMode.LIST)
            )

        def account(entry: ConfigEntry) -> str:
            service = {ConsoleKind.STEAM: "Steam", ConsoleKind.DISCORD: "Discord"}
            return f"{entry.title} ({service.get(entry.data[CONF_KIND], 'PlayStation Network')})"

        accounts = [
            SelectOptionDict(value=entry.entry_id, label=account(entry))
            for entry in consoles
            if entry.data[CONF_KIND] in (ConsoleKind.STEAM, ConsoleKind.DISCORD)
            or entry.data.get(CONF_NPSSO)
        ]
        players = [
            SelectOptionDict(value=f"{entry.entry_id}|{name}", label=f"{name} ({entry.title})")
            for entry in consoles
            if entry.state is ConfigEntryState.LOADED
            for name in getattr(entry.runtime_data.driver, "players", [])
        ]
        fields: dict[Any, Any] = {vol.Required(CONF_NAME): str}
        if accounts:
            fields[vol.Optional(CONF_ACCOUNTS)] = choice(accounts)
        if players:
            fields[vol.Optional(CONF_PLAYERS)] = choice(players)
        if consoles:
            fields[vol.Optional(CONF_CONSOLES)] = choice(
                [SelectOptionDict(value=entry.entry_id, label=entry.title) for entry in consoles]
            )
        return vol.Schema(fields)

    @staticmethod
    def _data(user_input: dict[str, Any]) -> dict[str, Any]:
        return {
            key: user_input.get(key, []) for key in (CONF_ACCOUNTS, CONF_PLAYERS, CONF_CONSOLES)
        }

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME].strip(), data=self._data(user_input)
            )
        return self.async_show_form(step_id="user", data_schema=self._schema())

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            return self.async_update_and_abort(
                self._get_entry(),
                subentry,
                title=user_input[CONF_NAME].strip(),
                data=self._data(user_input),
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                self._schema(), {CONF_NAME: subentry.title, **subentry.data}
            ),
        )
