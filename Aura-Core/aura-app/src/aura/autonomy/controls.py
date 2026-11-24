"""Owner control state and the initiation gate (B1-01).

``may_initiate`` is the single gate for any unprompted work or delivery.
P2-33 extends this same function (autonomy levels 0 to 3, daily budgets);
nothing else may bypass it.
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

LEVELS = ("silent", "important", "open")
IMPORTANT_KINDS = frozenset({"needs_decision", "task_done"})
_RID = RecordID("autonomy_control", "main")


@dataclass
class Controls:
    level: str = "important"
    muted_kinds: list[str] = field(default_factory=list)
    killed: bool = False
    killed_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass
class Decision:
    allowed: bool
    reason: str


_cache: Controls | None = None


def reset_cache() -> None:
    """Forget the cached singleton (tests)."""
    global _cache
    _cache = None


def is_killed() -> bool:
    """Synchronous kill-switch read from the cache; never touches the database."""
    return bool(_cache and _cache.killed)


def _from_row(row: dict[str, Any]) -> Controls:
    return Controls(
        level=row.get("level") or "important",
        muted_kinds=list(row.get("muted_kinds") or []),
        killed=bool(row.get("killed")),
        killed_at=row.get("killed_at"),
        updated_at=row.get("updated_at"),
    )


async def _save(c: Controls, db: Any) -> None:
    c.updated_at = get_clock().now()
    data: dict[str, Any] = {
        "level": c.level,
        "muted_kinds": list(c.muted_kinds),
        "killed": c.killed,
        "updated_at": c.updated_at,
    }
    if c.killed_at is not None:
        data["killed_at"] = c.killed_at
    await db.query("UPSERT $rid CONTENT $data", {"rid": _RID, "data": data})


async def load_controls(db: Any = None) -> Controls:
    """Read the singleton (creating it with the configured default) and cache it."""
    global _cache
    db = db if db is not None else get_db_client()
    rows = extract_rows(await db.query("SELECT * FROM $rid", {"rid": _RID}))
    if rows:
        _cache = _from_row(rows[0])
    else:
        level = settings.autonomy_default_level
        c = Controls(level=level if level in LEVELS else "important")
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


async def set_level(level: str, db: Any = None) -> Controls:
    if level not in LEVELS:
        raise ValueError(f"unknown autonomy level: {level}")
    return await _write(lambda c: setattr(c, "level", level), db)


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


def quiet_hours_active(now: datetime | None = None) -> bool:
    """True inside the quiet window in ``app_timezone``; handles midnight wrap."""
    now = now or get_clock().now()
    try:
        tz = ZoneInfo(settings.app_timezone)
    except Exception:  # noqa: BLE001 - bad timezone name falls back to UTC
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz).time().replace(second=0, microsecond=0)
    start = _parse_hhmm(settings.quiet_hours_start)
    end = _parse_hhmm(settings.quiet_hours_end)
    if start == end:
        return False
    if start < end:
        return start <= local < end
    return local >= start or local < end


async def may_initiate(
    kind: str,
    *,
    now: datetime | None = None,
    owner_created: bool = False,
    source: str = "gate",
    refs: list[Any] | None = None,
    db: Any = None,
) -> Decision:
    """The single gate for unprompted work. P2-33 extends this function.

    Order: killed, master flag, muted kind, level. A ``reminder`` the owner
    created by hand (``owner_created=True``) is allowed at ``important``.
    Every call writes an autonomy_trace row, allowed or refused.
    """
    c = await get_controls(db)
    if c.killed:
        d = Decision(False, "killed")
    elif not settings.autonomy_enabled:
        d = Decision(False, "autonomy_disabled")
    elif kind in c.muted_kinds:
        d = Decision(False, "kind_muted")
    elif await _learning_muted(kind, now, db):
        d = Decision(False, "kind_muted_by_learning")
    elif c.level == "silent":
        d = Decision(False, "level_silent")
    elif c.level == "open":
        d = Decision(True, "level_open")
    elif kind in IMPORTANT_KINDS:
        d = Decision(True, "level_important")
    elif kind == "reminder" and owner_created:
        d = Decision(True, "owner_reminder")
    else:
        d = Decision(False, "level_important_excludes_kind")
    await trace.record(
        source, f"initiate:{kind}", d.reason, allowed=d.allowed, refs=refs, db=db
    )
    return d
