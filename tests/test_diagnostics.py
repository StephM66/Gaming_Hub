"""Diagnostics: useful for a bug report, nothing secret or personal in it."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.helpers.json import json_dumps

from custom_components.gaming_hub.diagnostics import async_get_config_entry_diagnostics
from custom_components.gaming_hub.protocols.psn import PsnSession, PsnStatus

from .conftest import REGIST_KEY, RP_KEY
from .test_entities import PSN_STATUS, _setup


async def test_diagnostics_hide_keys_and_account(hass: HomeAssistant, mock_ddp, ps5_entry) -> None:
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps5_entry, data={**ps5_entry.data, "npsso": "secret-npsso", "account_id": "4242"}
    )
    status = PsnStatus(
        account_id="4242",
        online_id="Steph66",
        online_status="online",
        avatar_url="https://psn/avatar.png",
        sessions={"PS5": PsnSession("PS5", True, "Astro Bot", "PPSA01234_00", None)},
    )
    with patch(PSN_STATUS, AsyncMock(return_value=status)):
        await _setup(hass, ps5_entry)
        diagnostics = await async_get_config_entry_diagnostics(hass, ps5_entry)

    text = json_dumps(diagnostics)  # what the user downloads
    for secret in ("secret-npsso", "4242", "Steph66", "avatar.png", REGIST_KEY, RP_KEY):
        assert secret not in text
    assert "A1B2C3D4E5F6" not in text  # console identifier
    assert diagnostics["console"]["last_update_success"] is True
    assert diagnostics["data"]["snapshot"]["title"] == "Astro Bot"
    assert diagnostics["playstation_network"]["status"]["online_status"] == "online"
