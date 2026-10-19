"""Config, discovery, reconfigure and options flows."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import SOURCE_MQTT, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.mqtt import MqttServiceInfo
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_hub.const import DOMAIN
from custom_components.gaming_hub.protocols.remoteplay import Ps5Credentials, RemotePlayError
from custom_components.gaming_hub.protocols.webman import WebmanError, WebmanStatus

from .conftest import REGIST_KEY, RP_KEY

CREDS = Ps5Credentials(REGIST_KEY, RP_KEY)
SETUP = "custom_components.gaming_hub.async_setup_entry"


@pytest.fixture(autouse=True)
def no_setup():
    with patch(SETUP, AsyncMock(return_value=True)):
        yield


async def _menu(hass: HomeAssistant, choice: str):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["ps5", "ps3", "switch", "linked"]
    return await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": choice}
    )


async def _ps5_to_pairing(hass: HomeAssistant):
    result = await _menu(hass, "ps5")
    assert result["type"] is FlowResultType.FORM
    # The discovered console is suggested.
    assert result["data_schema"]({})["host"] == "192.168.1.20"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.20"}
    )
    assert result["type"] is FlowResultType.MENU
    return result


async def test_ps5_pair_with_pin(hass: HomeAssistant, mock_ddp) -> None:
    result = await _ps5_to_pairing(hass)
    assert result["menu_options"] == ["ps5_register", "ps5_skip"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ps5_register"}
    )
    register = "custom_components.gaming_hub.protocols.remoteplay.async_register"
    with patch(register, AsyncMock(side_effect=RemotePlayError("invalid_pin"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"account_id": "1234567890123456789", "pin": "12345678"}
        )
    assert result["errors"] == {"base": "invalid_pin"}
    with patch(register, AsyncMock(return_value=(CREDS, {}))) as mocked:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"account_id": "1234567890123456789", "pin": "87654321", "passcode": "1234"},
        )
    mocked.assert_awaited_once_with("192.168.1.20", "1234567890123456789", "87654321")
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "PS5-Salon"
    assert result["result"].unique_id == "A1B2C3D4E5F6"
    assert result["data"] == {
        "kind": "ps5",
        "host": "192.168.1.20",
        "host_id": "A1B2C3D4E5F6",
        "name": "PS5-Salon",
        "regist_key": REGIST_KEY,
        "rp_key": RP_KEY,
        "passcode": "1234",
    }


async def test_ps5_import_from_ps5_mqtt(hass: HomeAssistant, mock_ddp, tmp_path: Path) -> None:
    credentials = tmp_path / "credentials.json"
    credentials.write_text(
        json.dumps(
            {
                "A1B2C3D4E5F6": {
                    "user-credential": "305441741",
                    "registration": {"PS5-RegistKey": REGIST_KEY, "RP-Key": RP_KEY},
                }
            }
        )
    )
    with patch(
        "custom_components.gaming_hub.config_flow.GamingHubConfigFlow._ps5_mqtt_file",
        return_value=credentials,
    ):
        result = await _ps5_to_pairing(hass)
        assert result["menu_options"] == ["ps5_import", "ps5_register", "ps5_skip"]
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "ps5_import"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert (result["data"]["regist_key"], result["data"]["rp_key"]) == (REGIST_KEY, RP_KEY)


async def test_ps5_import_failure(hass: HomeAssistant, mock_ddp, tmp_path: Path) -> None:
    credentials = tmp_path / "credentials.json"
    credentials.write_text("{}")
    with patch(
        "custom_components.gaming_hub.config_flow.GamingHubConfigFlow._ps5_mqtt_file",
        return_value=credentials,
    ):
        result = await _ps5_to_pairing(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"next_step_id": "ps5_import"}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["errors"] == {"base": "import_failed"}


async def test_ps5_skip_and_duplicates(hass: HomeAssistant, mock_ddp) -> None:
    result = await _ps5_to_pairing(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ps5_skip"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "regist_key" not in result["data"]
    result = await _menu(hass, "ps5")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "192.168.1.20"}
    )
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "already_configured")


async def test_ps5_unreachable(hass: HomeAssistant, mock_ddp) -> None:
    mock_ddp["status"].return_value = None
    result = await _menu(hass, "ps5")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "10.0.0.9"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_ps5_reconfigure_pairs_later(hass: HomeAssistant, mock_ddp, ps5_entry) -> None:
    ps5_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        ps5_entry,
        data={k: v for k, v in ps5_entry.data.items() if k not in ("regist_key", "rp_key")},
    )
    result = await ps5_entry.start_reconfigure_flow(hass)
    assert result["menu_options"] == ["ps5_register"]
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "ps5_register"}
    )
    with patch(
        "custom_components.gaming_hub.protocols.remoteplay.async_register",
        AsyncMock(return_value=(CREDS, {})),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"account_id": "1234567890123456789", "pin": "12345678"}
        )
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "reconfigure_successful")
    assert ps5_entry.data["regist_key"] == REGIST_KEY


async def test_ps3(hass: HomeAssistant) -> None:
    result = await _menu(hass, "ps3")
    target = "custom_components.gaming_hub.protocols.webman.WebmanClient.async_get_status"
    with patch(target, AsyncMock(side_effect=WebmanError("off"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.30"}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    with patch(target, AsyncMock(return_value=WebmanStatus(mac="00:1F:A7:12:34:56"))):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.1.30", "port": 80, "name": "PS3 Chambre"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "00:1F:A7:12:34:56"
    assert result["data"] == {
        "kind": "ps3",
        "host": "192.168.1.30",
        "port": 80,
        "name": "PS3 Chambre",
    }


async def test_switch_requires_mqtt(hass: HomeAssistant) -> None:
    result = await _menu(hass, "switch")
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "mqtt_required")


async def test_switch_manual(hass: HomeAssistant) -> None:
    MockConfigEntry(domain="mqtt").add_to_hass(hass)
    result = await _menu(hass, "switch")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"client_id": "switch-ha-1a2b", "discovery_prefix": "homeassistant"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "switch_ha_1a2b"
    assert result["data"]["client_id"] == "switch_ha_1a2b"


async def test_switch_mqtt_discovery(hass: HomeAssistant) -> None:
    info = MqttServiceInfo(
        topic="switch_ha/switch_ha_1a2b/current_game_id",
        payload="0100152000022000",
        qos=0,
        retain=True,
        subscribed_topic="switch_ha/+/current_game_id",
        timestamp=0,
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=info
    )
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "switch_confirm")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"discovery_prefix": "homeassistant", "name": "Switch Léo"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Switch Léo"
    # Already configured: further discoveries abort.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_MQTT}, data=info
    )
    assert result["reason"] == "already_configured"


async def test_linked_xbox(hass: HomeAssistant) -> None:
    hass.states.async_set("media_player.xbox_series_x", "on", {"friendly_name": "Xbox Series X"})
    result = await _menu(hass, "linked")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"preset": "xbox", "source_entity": "media_player.xbox_series_x"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Xbox Series X"
    assert result["data"]["preset"] == "xbox"


async def test_options(hass: HomeAssistant, ps5_entry) -> None:
    ps5_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(ps5_entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            "power_entity": "sensor.prise_ps5_power",
            "watts_playing": 180,
            "watts_idle": 60,
            "watts_standby": 3.5,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert ps5_entry.options["power_entity"] == "sensor.prise_ps5_power"
    assert ps5_entry.options["watts_standby"] == 3.5
