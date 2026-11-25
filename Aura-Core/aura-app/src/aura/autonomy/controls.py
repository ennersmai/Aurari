"""Owner control state and the initiation gate (B1-01, P2-33).

``may_initiate`` is the single gate for any unprompted work or delivery.
Nothing self-started may bypass it.

P2-33 (Phase 2 plan, Part 11) replaced the three named levels with the
autonomy slider 0 to 3 and added daily budgets inside the same function:

- 0 Reactive: only reply. No budget.
- 1 Attentive: follow up on her own agenda items and promised work. 3 messages.
- 2 Proactive: also start conversations, share ideas, propose goals (Mai
  approves each). 6 messages, 5 Sage calls.
- 3 Autonomous: also pursue approved goals, task graphs on Titan.
  10 messages, 10 Sage calls, 1 task graph.

Legacy names map to levels: silent = 0, important = 1, open = 3 (open allowed
every kind, which is level 3; level 1 allows exactly what important allowed).
The effective level is min(slider, tier profile ``autonomy_max_level``) while
tier profiles are on. Budgets count per local day (``app_timezone``) in the
``autonomy_budget`` table.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from surrealdb import RecordID

from aura.autonomy import trace
from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

MAX_LEVEL = 3
LEVEL_NAMES: dict[int, str] = {0: "reactive", 1: "attentive", 2: "proactive", 3: "autonomous"}
# B1-01 names, kept for the stored row, old clients and AURA_AUTONOMY_DEFAULT_LEVEL.
LEGACY_LEVELS: dict[str, int] = {"silent": 0, "important": 1, "open": 3}
LEVELS = tuple(LEVEL_NAMES)  # 0, 1, 2, 3
IMPORTANT_KINDS = frozenset({"needs_decision", "task_done"})

# Kind -> lowest level that allows it. A ``reminder`` the owner created by hand is
# allowed from level 1 (see may_initiate). Kinds not listed need level 3, so the old
# ``open`` (everything) is level 3 and level 2 refuses anything unknown.
KIND_MIN_LEVEL: dict[str, int] = {
    # 1 Attentive: her own open agenda items and promised work (= B1-01 important).
    "needs_decision": 1,
    "task_done": 1,
    # 2 Proactive: start conversations, share ideas, propose goals (Mai approves each).
    "finding": 2,
    "question_for_you": 2,
    "observation": 2,
    "reminder": 2,
    "share": 2,
    "start_conversation": 2,
    "propose_goal": 2,
    "investigate": 2,
    "practice": 2,
    "consolidate": 2,
    "sage_call": 2,
    # 3 Autonomous: pursue approved goals, task graphs and delegations.
    "pursue_goal": 3,
    "task_graph": 3,
    "self_improvement": 3,
    "delegation": 3,
}

# Kinds that spend a message (agenda kinds spend one when the deliverer sends them).
MESSAGE_KINDS = frozenset({
    "finding", "task_done", "needs_decision", "question_for_you", "reminder", "observation",
    "share", "start_conversation",
})
BUDGET_RESOURCES = ("messages", "sage_calls", "task_graphs")
_RID = RecordID("autonomy_control", "main")


def resource_for(kind: str) -> str | None:
    """The daily budget ``kind`` spends, or None (the table gives it no budget)."""
    if kind in MESSAGE_KINDS:
        return "messages"
    if kind == "sage_call":
        return "sage_calls"
    if kind in ("task_graph", "self_improvement"):
        return "task_graphs"
    return None


def budget_limits(level: int) -> dict[str, int]:
    """Daily limits at an effective level (0 means none allowed)."""
    limits = {r: 0 for r in BUDGET_RESOURCES}
    level = min(level, MAX_LEVEL)
    if level >= 1:
        limits["messages"] = int(getattr(settings, f"autonomy_budget_messages_level{level}"))
    if level >= 2:
        limits["sage_calls"] = int(getattr(settings, f"autonomy_budget_sage_calls_level{level}"))
    if level >= 3:
        limits["task_graphs"] = int(settings.autonomy_budget_task_graphs_level3)
    return limits


def parse_level(value: Any) -> int:
    """0..3 from an int, a digit string, a level name or a legacy name. Raises ValueError."""
    if isinstance(value, bool):
        raise ValueError(f"unknown autonomy level: {value!r}")
    if isinstance(value, int):
        if 0 <= value <= MAX_LEVEL:
            return value
        raise ValueError(f"autonomy level must be 0 to {MAX_LEVEL}: {value}")
    text = str(value).strip().lower()
    if text.isdigit():
        return parse_level(int(text))
    if text in LEGACY_LEVELS:
        return LEGACY_LEVELS[text]
    for n, name in LEVEL_NAMES.items():
        if text == name:
            return n
    raise ValueError(f"unknown autonomy level: {value!r}")


def tier_cap() -> int:
    """The tier profile's ``autonomy_max_level`` clamped to 0..3; 3 with tier profiles off."""
    if not settings.tier_profiles_enabled:
        return MAX_LEVEL
    try:
        from aura.tiers import active_profile

        cap = int(active_profile().autonomy_max_level)
    except Exception as e:  # noqa: BLE001 - fail closed to the most reactive level
        logger.warning("tier cap unavailable, using 0: %s", e)
        return 0
    return max(0, min(MAX_LEVEL, cap))


@dataclass
class Controls:
    level: int = 1
    muted_kinds: list[str] = field(default_factory=list)
    killed: bool = False
    killed_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Decision:
    allowed: bool
    reason: str


def effective_level(c: Controls) -> int:
    """min(slider, tier cap)."""
    return max(0, min(int(c.level), tier_cap()))


_cache: Controls | None = None


def reset_cache() -> None:
    """Forget the cached singleton (tests)."""
    global _cache
    _cache = None


def is_killed() -> bool:
    """Synchronous kill-switch read from the cache; never touches the database."""
    return bool(_cache and _cache.killed)


def _level_from_row(row: dict[str, Any]) -> int:
    """The stored number; a B1-01 row only has the legacy name (migrated on load)."""
    stored = row.get("autonomy_level")
    if stored is not None:
        try:
            return parse_level(int(stored))
        except (TypeError, ValueError):
            pass
    try:
        return parse_level(row.get("level") or "important")
    except ValueError:
        return 1


def _from_row(row: dict[str, Any]) -> Controls:
    return Controls(
        level=_level_from_row(row),
        muted_kinds=list(row.get("muted_kinds") or []),
        killed=bool(row.get("killed")),
        killed_at=row.get("killed_at"),
        updated_at=row.get("updated_at"),
    )


async def _save(c: Controls, db: Any) -> None:
    c.updated_at = get_clock().now()
    data: dict[str, Any] = {
        "level": LEVEL_NAMES[c.level],
        "autonomy_level": c.level,
        "muted_kinds": list(c.muted_kinds),
        "killed": c.killed,
        "updated_at": c.updated_at,
    }
    if c.killed_at is not None:
        data["killed_at"] = c.killed_at
    await db.query("UPSERT $rid CONTENT $data", {"rid": _RID, "data": data})


async def load_controls(db: Any = None) -> Controls:
    """Read the singleton (creating it with the configured default) and cache it.

    A B1-01 row (only the name silent / important / open) is migrated here:
    silent -> 0, important -> 1, open -> 3.
    """
    global _cache
    db = db if db is not None else get_db_client()
    rows = extract_rows(await db.query("SELECT * FROM $rid", {"rid": _RID}))
    if rows:
        c = _from_row(rows[0])
        if rows[0].get("autonomy_level") is None:
            await _save(c, db)
            logger.info("autonomy_control migrated: level %r -> %d", rows[0].get("level"), c.level)
        _cache = c
    else:
        try:
            level = parse_level(settings.autonomy_default_level)
        except ValueError:
            level = 1
        c = Controls(level=level)
        await _save(c, db)
        _cache = c
    return _cache


async def get_controls(db: Any = None) -> Controls:
    """The cached controls (loaded on first use)."""
    if _cache is None:
        await load_controls(db)
    assert _cache is not None
    return _cache


async def _write(mutate, db: Any) -> Controls:
    global _cache
    db = db if db is not None else get_db_client()
    current = await get_controls(db)
    new = Controls(**vars(current))
    new.muted_kinds = list(current.muted_kinds)
    mutate(new)
    await _save(new, db)
    _cache = new
    return new


async def set_level(level: int | str, db: Any = None) -> Controls:
    """Set the slider (0..3; legacy names accepted). Raises ValueError."""
    n = parse_level(level)
    return await _write(lambda c: setattr(c, "level", n), db)


async def _learning_muted(kind: str, now: datetime | None, db: Any) -> bool:
    from aura.autonomy import learning

    try:
        return await learning.is_muted(kind, now, db)
    except Exception as e:  # noqa: BLE001 - the learning table must not break the gate
        logger.warning("learned mute check failed: %s", e)
        return False


async def mute_kind(kind: str, db: Any = None) -> Controls:
    def m(c: Controls) -> None:
        if kind not in c.muted_kinds:
            c.muted_kinds.append(kind)

    return await _write(m, db)


async def unmute_kind(kind: str, db: Any = None) -> Controls:
    def m(c: Controls) -> None:
        c.muted_kinds = [k for k in c.muted_kinds if k != kind]

    from aura.autonomy import learning

    try:
        await learning.lift_mute(kind, db)  # the owner can lift a learned mute too
    except Exception as e:  # noqa: BLE001
        logger.warning("lifting learned mute failed: %s", e)
    return await _write(m, db)


async def set_killed(killed: bool, db: Any = None) -> Controls:
    now = get_clock().now()

    def m(c: Controls) -> None:
        c.killed = killed
        c.killed_at = now if killed else None

    return await _write(m, db)


def _parse_hhmm(value: str) -> time:
    h, _, m = value.strip().partition(":")
    return time(int(h), int(m or 0))


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.app_timezone)
    except Exception:  # noqa: BLE001 - bad timezone name falls back to UTC
        return ZoneInfo("UTC")


def quiet_hours_active(now: datetime | None = None) -> bool:
    """True inside the quiet window in ``app_timezone``; handles midnight wrap."""
    now = now or get_clock().now()
    local = now.astimezone(_tz()).time().replace(second=0, microsecond=0)
    start = _parse_hhmm(settings.quiet_hours_start)
    end = _parse_hhmm(settings.quiet_hours_end)
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


# -- P2-33 daily budgets ---------------------------------------------------------

def day_key(now: datetime) -> str:
    """The local day YYYY-MM-DD in ``app_timezone``; budgets reset when it changes."""
    return now.astimezone(_tz()).date().isoformat()


def _budget_rid(day: str) -> RecordID:
    return RecordID("autonomy_budget", day)


async def _budget_row(day: str, db: Any) -> dict[str, Any]:
    rows = extract_rows(await db.query("SELECT * FROM $rid", {"rid": _budget_rid(day)}))
    return rows[0] if rows else {}


async def _spend(resource: str, limit: int, now: datetime, db: Any) -> tuple[bool, int]:
    """Take one unit of today's ``resource`` if below ``limit``. Returns (taken, used)."""
    if resource not in BUDGET_RESOURCES:  # the field name below is never caller text
        raise ValueError(f"unknown budget resource: {resource}")
    day = day_key(now)
    rid = _budget_rid(day)
    if not await _budget_row(day, db):
        await db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": {
            "day": day, "messages": 0, "sage_calls": 0, "task_graphs": 0, "updated_at": now,
        }})
    # One conditional UPDATE, so the check and the increment are not split.
    rows = extract_rows(await db.query(
        f"UPDATE $rid SET {resource} += 1, updated_at = $now WHERE {resource} < $limit RETURN AFTER",
        {"rid": rid, "now": now, "limit": int(limit)},
    ))
    if rows:
        return True, int(rows[0].get(resource) or 0)
    return False, int((await _budget_row(day, db)).get(resource) or 0)


async def budget_state(now: datetime | None = None, db: Any = None) -> dict[str, Any]:
    """Today's use and limits at the current effective level (Dashboard)."""
    db = db if db is not None else get_db_client()
    now = now or get_clock().now()
    level = effective_level(await get_controls(db))
    day = day_key(now)
    row = await _budget_row(day, db)
    limits = budget_limits(level)
    return {
        "day": day,
        "resources": {r: {"used": int(row.get(r) or 0), "limit": limits[r]} for r in BUDGET_RESOURCES},
    }


async def may_initiate(
    kind: str,
    *,
    now: datetime | None = None,
    owner_created: bool = False,
    source: str = "gate",
    refs: list[Any] | None = None,
    spend: bool = True,
    db: Any = None,
) -> Decision:
    """The single gate for unprompted work (B1-01, extended by P2-33).

    Order: killed, master flag, muted kind, learned mute, effective level
    (min of slider and tier cap; see ``KIND_MIN_LEVEL``), daily budget.

    A ``reminder`` the owner created by hand (``owner_created=True``) is allowed
    from level 1 and spends no budget. ``spend=False`` checks the budget without
    taking from it; it is for callers that only prepare work whose real action
    passes this gate again (an agenda item is checked when created and charged
    when the deliverer sends it). Every call writes an autonomy_trace row,
    allowed or refused, with the level, the cap and the budget in ``cost``.
    """
    c = await get_controls(db)
    cost: dict[str, Any] = {}
    if c.killed:
        d = Decision(False, "killed")
    elif not settings.autonomy_enabled:
        d = Decision(False, "autonomy_disabled")
    elif kind in c.muted_kinds:
        d = Decision(False, "kind_muted")
    elif await _learning_muted(kind, now, db):
        d = Decision(False, "kind_muted_by_learning")
    else:
        cap = tier_cap()
        level = max(0, min(int(c.level), cap))
        owner_reminder = kind == "reminder" and owner_created
        need = 1 if owner_reminder else KIND_MIN_LEVEL.get(kind, MAX_LEVEL)
        cost = {"level": level, "slider": int(c.level), "tier_cap": cap, "needs_level": need}
        if level < need:
            d = Decision(False, "level_0_reactive" if level == 0 else f"level_{level}_excludes_kind")
        else:
            d = Decision(True, "owner_reminder" if owner_reminder else f"level_{level}")
            resource = None if owner_reminder else resource_for(kind)
            if resource is not None:
                limit = budget_limits(level)[resource]
                when = now or get_clock().now()
                bdb = db if db is not None else get_db_client()
                if spend:
                    taken, used = await _spend(resource, limit, when, bdb)
                else:
                    used = int((await _budget_row(day_key(when), bdb)).get(resource) or 0)
                    taken = used < limit
                cost["budget"] = {"resource": resource, "day": day_key(when), "used": used,
                                  "limit": limit, "spent": bool(spend and taken)}
                if not taken:
                    d = Decision(False, f"budget_exhausted:{resource}")
    await trace.record(
        source, f"initiate:{kind}", d.reason, allowed=d.allowed, cost=cost, refs=refs, db=db
    )
    return d
