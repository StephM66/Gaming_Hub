"""Constants for Gaming Hub."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from .models import PowerProfile

DOMAIN: Final = "gaming_hub"
EVENT_PARENTAL: Final = f"{DOMAIN}_parental"
STORAGE_VERSION: Final = 1


class ConsoleKind(StrEnum):
    """One driver per kind."""

    PS5 = "ps5"
    PS3 = "ps3"
    SWITCH = "switch"
    LINKED = "linked"  # any console already in Home Assistant (Xbox, PS4, Steam…)


class LinkedPreset(StrEnum):
    """Presets of the linked driver: device info and power profile."""

    XBOX = "xbox"
    PS4 = "ps4"
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
CONF_WATTS_PLAYING: Final = "watts_playing"
CONF_WATTS_IDLE: Final = "watts_idle"
CONF_WATTS_STANDBY: Final = "watts_standby"
CONF_IMAGE_TEMPLATE: Final = "image_template"

# ps5-mqtt keeps playactor credentials in the Home Assistant configuration folder.
PS5_MQTT_CREDENTIALS: Final = ("ps5-mqtt", "credentials.json")

# Third-party icon service keyed by Switch title ID; can be cleared in the options.
DEFAULT_SWITCH_IMAGE_TEMPLATE: Final = "https://tinfoil.media/ti/{title_id}/256/256/"

# Rough consumption figures (W): playing, on without game, standby/off.
# Adjustable per console in the options; a linked power sensor always wins.
POWER_PROFILES: Final[dict[str, PowerProfile]] = {
    ConsoleKind.PS5: PowerProfile(playing=200, idle=70, standby=1.5),
    ConsoleKind.PS3: PowerProfile(playing=90, idle=75, standby=0.5),
    ConsoleKind.SWITCH: PowerProfile(playing=12, idle=7, standby=0.5),
    LinkedPreset.XBOX: PowerProfile(playing=150, idle=50, standby=10),
    LinkedPreset.PS4: PowerProfile(playing=140, idle=60, standby=5),
    LinkedPreset.PC: PowerProfile(),
    LinkedPreset.RETRO: PowerProfile(playing=10, idle=10, standby=0),
    LinkedPreset.OTHER: PowerProfile(),
}

DEVICE_INFO: Final[dict[str, tuple[str, str]]] = {
    ConsoleKind.PS5: ("Sony", "PlayStation 5"),
    ConsoleKind.PS3: ("Sony", "PlayStation 3"),
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
