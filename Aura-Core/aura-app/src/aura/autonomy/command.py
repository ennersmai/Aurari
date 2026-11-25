"""Changing the autonomy level (P2-33): the Dashboard route and the owner's chat
command "autonomy N" share one path that records the change in the trace,
publishes the new state and wakes the deliverer.
"""

import re
from typing import Any

from aura.autonomy import channel, controls, trace
from aura.config import settings

# The owner's own venues: the app and her Discord DM. Never a guild channel.
OWNER_VENUES = ("app", "dm:owner")
_COMMAND = re.compile(r"^\s*autonomy\s+(\d+)\s*[.!]?\s*$", re.IGNORECASE)


async def state_for(c: controls.Controls, db: Any = None) -> dict[str, Any]:
    """The control state the Dashboard shows (B1-07 fields plus P2-33 level and budget)."""
    try:
        budget = await controls.budget_state(db=db)
    except Exception:  # noqa: BLE001 - the panel must still render without the counters
        budget = None
    return {
        "level": c.level,
        "level_name": controls.LEVEL_NAMES[c.level],
        "effective_level": controls.effective_level(c),
        "tier_cap": controls.tier_cap(),
        "budget": budget,
        "muted_kinds": list(c.muted_kinds),
        "killed": c.killed,
        "killed_at": c.killed_at.isoformat() if c.killed_at else None,
        "quiet_hours": {
            "start": settings.quiet_hours_start,
            "end": settings.quiet_hours_end,
            "active": controls.quiet_hours_active(),
        },
        "autonomy_enabled": settings.autonomy_enabled,
        "workspace_enabled": settings.workspace_enabled,
        "goals_v2_enabled": settings.goals_v2_enabled,
    }


async def announce(c: controls.Controls, action: str, why: str, db: Any = None) -> dict[str, Any]:
    """Trace an owner change, publish the new state and wake the deliverer."""
    from aura.autonomy.delivery import get_deliverer

    state = await state_for(c, db)
    await trace.record("owner", f"controls:{action}", why, db=db)
    await channel.publish("autonomy_state", state)
    await get_deliverer().notify()
    return state


async def change_level(level: int | str, via: str, db: Any = None) -> dict[str, Any]:
    """Set the slider (raises ValueError for anything but 0..3 or a legacy name)."""
    c = await controls.set_level(level, db)
    return await announce(c, "level", f"level set to {c.level} ({controls.LEVEL_NAMES[c.level]}) via {via}", db)


async def handle_chat(text: str, requester_role: str, venue: str, db: Any = None) -> str | None:
    """The reply to "autonomy N" from the owner, or None when the message is not the command.

    Only with ``autonomy_enabled`` (off: the message is an ordinary turn, as before).
    Anyone but the owner gets an ordinary turn; the owner outside her own venues
    gets a refusal.
    """
    m = _COMMAND.match(text or "")
    if m is None or not settings.autonomy_enabled or requester_role != "owner":
        return None
    if venue not in OWNER_VENUES:
        await trace.record("owner", "controls:level", f"chat command refused in venue {venue}",
                           allowed=False, db=db)
        return "I only change my autonomy level in the app or in your DM."
    try:
        state = await change_level(int(m.group(1)), "chat", db)
    except ValueError:
        return "Autonomy levels are 0 (reactive), 1 (attentive), 2 (proactive) and 3 (autonomous)."
    level, effective = state["level"], state["effective_level"]
    reply = f"Autonomy set to {level} ({state['level_name']})."
    if effective < level:
        reply += f" This tier caps it, so I act at {effective} ({controls.LEVEL_NAMES[effective]})."
    return reply
