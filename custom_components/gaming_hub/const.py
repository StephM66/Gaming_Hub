"""Constants for Gaming Hub."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "gaming_hub"
EVENT_PARENTAL: Final = f"{DOMAIN}_parental"
STORAGE_VERSION: Final = 1
# Config entry of the cross-console statistics (kind of entry, not a console).
SUMMARY: Final = "summary"
SIGNAL_CONSOLES_UPDATED: Final = f"{DOMAIN}_consoles_updated"


class ConsoleKind(StrEnum):
    """One driver per kind."""

    PS5 = "ps5"
    PS3 = "ps3"
    SWITCH = "switch"
    LINKED = "linked"  # any console already in Home Assistant (Xbox, PS4, Steam…)


class LinkedPreset(StrEnum):
    """Presets of the linked driver (manufacturer and model shown)."""

    XBOX = "xbox"
    PS4 = "ps4"
    PS3 = "ps3"  # unmodified PS3: state from any entity, game from the PSN account
    PC = "pc"
    RETRO = "retro"
    OTHER = "other"


# Entry data
CONF_KIND: Final = "kind"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_NAME: Final = "name"
CONF_HOST_ID: Final = "host_id"
CONF_REGIST_KEY: Final = "regist_key"
CONF_RP_KEY: Final = "rp_key"
CONF_PASSCODE: Final = "passcode"
CONF_ACCOUNT_ID: Final = "account_id"
CONF_PIN: Final = "pin"
CONF_CLIENT_ID: Final = "client_id"
CONF_DISCOVERY_PREFIX: Final = "discovery_prefix"
CONF_SOURCE_ENTITY: Final = "source_entity"
CONF_PRESET: Final = "preset"
CONF_ON_THRESHOLD: Final = "on_threshold"
CONF_NPSSO: Final = "npsso"

# Options (every kind)
CONF_POWER_ENTITY: Final = "power_entity"
CONF_TURN_ON_ENTITY: Final = "turn_on_entity"
CONF_TURN_OFF_ENTITY: Final = "turn_off_entity"
CONF_BLOCK_ENTITY: Final = "block_entity"
CONF_ENERGY_SOURCE: Final = "energy_source"
CONF_HIDE_SOURCES: Final = "hide_sources"
CONF_IMAGE_TEMPLATE: Final = "image_template"

# ps5-mqtt keeps playactor credentials in the Home Assistant configuration folder.
PS5_MQTT_CREDENTIALS: Final = ("ps5-mqtt", "credentials.json")

# Third-party icon service keyed by Switch title ID; can be cleared in the options.
DEFAULT_SWITCH_IMAGE_TEMPLATE: Final = "https://tinfoil.media/ti/{title_id}/256/256/"


DEVICE_INFO: Final[dict[str, tuple[str, str]]] = {
    ConsoleKind.PS5: ("Sony", "PlayStation 5"),
    ConsoleKind.PS3: ("Sony", "PlayStation 3"),  # also LinkedPreset.PS3 (same key)
    ConsoleKind.SWITCH: ("Nintendo", "Switch"),
    LinkedPreset.XBOX: ("Microsoft", "Xbox"),
    LinkedPreset.PS4: ("Sony", "PlayStation 4"),
    LinkedPreset.PC: ("PC", "PC / Steam Deck"),
    LinkedPreset.RETRO: ("Retro", "Console rétro"),
    LinkedPreset.OTHER: ("Gaming Hub", "Console"),
}

# Messages shown on the console and carried by events (fr, else en).
MESSAGES: Final[dict[str, dict[str, str]]] = {
    "fr": {
        "warning": "Plus que {minutes} min de jeu sur {console}.",
        "blocked_limit": "Temps de jeu du jour écoulé sur {console}.",
        "blocked_schedule": "Hors des heures de jeu autorisées sur {console}.",
        "turning_off": "{console} va s'éteindre.",
    },
    "en": {
        "warning": "{minutes} min of play left on {console}.",
        "blocked_limit": "Daily play time is over on {console}.",
        "blocked_schedule": "Outside of the allowed play hours on {console}.",
        "turning_off": "{console} is turning off.",
    },
}
