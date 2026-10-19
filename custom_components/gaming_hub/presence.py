"""Is a console on? Read from any Home Assistant entity.

Whatever tells it in a given home: an HDMI switch or sync box input ("linked"), a ping or
router tracker, a TV input, an HDMI-CEC device, a smart plug's power (above a threshold),
a media player. Nothing here knows about a particular product.
"""

from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State

# Lower-case states meaning "on / awake", across domains and common integrations.
ON_STATES = frozenset(
    {
        "on",
        "home",  # device trackers, ping
        "linked",  # HDMI input with an active signal (Hue Play HDMI Sync Box, …)
        "connected",
        "active",
        "playing",
        "paused",
        "buffering",
        "idle",  # media player on, nothing playing
    }
)


def is_present(state: State | None, threshold: float | None = None) -> bool | None:
    """True or False from the entity's state; None when it does not know.

    A numeric state (power in W) counts as on at or above ``threshold``.
    """
    if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
        return None
    if threshold is not None:
        try:
            return float(state.state) >= threshold
        except ValueError:
            pass
    return state.state.lower() in ON_STATES
