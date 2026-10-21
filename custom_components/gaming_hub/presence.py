"""Is a console on? Read from an entity the user chose to fill in a missing state.

Only for consoles that cannot say it themselves ("Complete" options): a switch powering a
PC, an HDMI input, a ping, a smart plug's power above a threshold…
"""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State

# Lower-case states meaning "on / awake", across domains and common integrations.
ON_STATES = frozenset(
    {"on", "home", "linked", "connected", "active", "playing", "paused", "buffering", "idle"}
)
ON_THRESHOLD = 5.0  # W, for a power sensor


def is_present(state: State | None) -> bool | None:
    """True or False from the entity's state; None when it does not know.

    A numeric state (power in W) counts as on at or above ``ON_THRESHOLD``.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    try:
        return float(state.state) >= ON_THRESHOLD
    except ValueError:
        return state.state.lower() in ON_STATES
