"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.gaming_hub.const import (
    CONF_HOST,
    CONF_HOST_ID,
    CONF_KIND,
    CONF_NAME,
    CONF_PORT,
    CONF_REGIST_KEY,
    CONF_RP_KEY,
    DOMAIN,
)
from custom_components.gaming_hub.protocols.ddp import DdpResponse

REGIST_KEY = "3132333461626364"
RP_KEY = "00112233445566778899aabbccddeeff"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/gaming_hub in every test."""


def ddp_response(code: int = 200, **fields: str) -> DdpResponse:
    return DdpResponse(
        "192.168.1.20",
        code,
        {"host-id": "A1B2C3D4E5F6", "host-name": "PS5-Salon", "host-type": "PS5", **fields},
    )


@pytest.fixture
def mock_ddp() -> Generator[dict[str, AsyncMock]]:
    """PS5 discovery, status and wake-up, answering as an awake console."""
    base = "custom_components.gaming_hub.protocols.ddp"
    with (
        patch(f"{base}.async_get_status", AsyncMock(return_value=ddp_response())) as status,
        patch(f"{base}.async_search", AsyncMock(return_value=[ddp_response()])) as search,
        patch(f"{base}.async_wake", AsyncMock()) as wake,
    ):
        yield {"status": status, "search": search, "wake": wake}


@pytest.fixture
def ps5_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="PS5 Salon",
        unique_id="A1B2C3D4E5F6",
        data={
            CONF_KIND: "ps5",
            CONF_HOST: "192.168.1.20",
            CONF_HOST_ID: "A1B2C3D4E5F6",
            CONF_NAME: "PS5 Salon",
            CONF_REGIST_KEY: REGIST_KEY,
            CONF_RP_KEY: RP_KEY,
        },
    )


@pytest.fixture
def ps3_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="PS3",
        unique_id="00:1F:A7:12:34:56",
        data={CONF_KIND: "ps3", CONF_HOST: "192.168.1.30", CONF_PORT: 80, CONF_NAME: "PS3"},
    )
