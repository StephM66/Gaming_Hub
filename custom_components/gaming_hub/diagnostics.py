"""Diagnostics to attach to a bug report, without secrets or account identifiers."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ACCOUNT_ID,
    CONF_API_KEY,
    CONF_BOT_TOKEN,
    CONF_DEVICE_ID,
    CONF_HOST_ID,
    CONF_KIND,
    CONF_NPSSO,
    CONF_PASSCODE,
    CONF_REGIST_KEY,
    CONF_RP_KEY,
    CONF_SESSION_TOKEN,
    CONF_STEAM_ID,
    CONF_USER_ID,
    SUMMARY,
)
from .coordinator import GamingHubConfigEntry
from .summary import loaded_consoles

# Bug reports are public: keys and tokens, and what identifies the person or the console.
# Local addresses stay, they are needed to understand a console that does not answer.
TO_REDACT = {
    CONF_NPSSO,
    CONF_REGIST_KEY,
    CONF_RP_KEY,
    CONF_PASSCODE,
    CONF_ACCOUNT_ID,
    CONF_HOST_ID,
    CONF_SESSION_TOKEN,
    CONF_DEVICE_ID,
    CONF_API_KEY,
    CONF_STEAM_ID,
    CONF_BOT_TOKEN,
    CONF_USER_ID,
    "steam_name",
    "steam_avatar",
    "players",  # nicknames of the console's users
    "online_id",
    "psn_online_id",
    "avatar_url",
    "psn_avatar",
    "mac",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GamingHubConfigEntry
) -> dict[str, Any]:
    if entry.data.get(CONF_KIND) == SUMMARY:
        return {"consoles": [name for name, _ in loaded_consoles(hass)]}
    coordinator = entry.runtime_data
    data = coordinator.data
    return async_redact_data(
        {
            "entry": {"data": dict(entry.data), "options": dict(entry.options)},
            "console": {
                "model": coordinator.model,
                "last_update_success": coordinator.last_update_success,
                "last_error": repr(coordinator.last_exception)
                if coordinator.last_exception
                else None,
            },
            "data": asdict(data) if data else None,
            "parental_settings": coordinator.parental.settings.as_dict(),
            "playstation_network": {
                "linked": coordinator.psn is not None,
                "needs_reauth": coordinator.psn_reauth,
                "status": asdict(coordinator.psn_status) if coordinator.psn_status else None,
            },
        },
        TO_REDACT,
    )
