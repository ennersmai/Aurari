"""Dismissal learning (B5-03, PRD 8.2). No model call.

Per-kind state in ``agenda_kind_stats``: a threshold delta that eases on
acknowledgement and rises on dismissal or ignore, a streak counter, and a
learned mute after ``dismissal_mute_after`` dismissals in a row. Everything is
behind ``dismissal_learning_enabled``; off, thresholds stay at config values.

The synchronous readers (``threshold_delta``, ``dismissal_ages``) use an
in-memory mirror that every write updates and ``refresh`` reloads, so
``delivery.threshold`` and ``collect_signals`` stay synchronous.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from surrealdb import RecordID

from aura.autonomy import trace
from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

_DISMISSAL_LOG_LIMIT = 20


@dataclass
class KindStats:
    kind: str
    threshold_delta: float = 0.0
    consecutive_dismissals: int = 0
    muted_until: datetime | None = None
    delivered: int = 0
    acknowledged: int = 0
    dismissed: int = 0
    ignored: int = 0


_stats: dict[str, KindStats] = {}
_dismissal_times: list[datetime] = []


def reset_cache() -> None:
    _stats.clear()
    _dismissal_times.clear()


def enabled() -> bool:
    return bool(settings.dismissal_learning_enabled)


def _from_row(row: dict[str, Any]) -> KindStats:
    return KindStats(
        kind=row["kind"],
        threshold_delta=float(row.get("threshold_delta") or 0.0),
        consecutive_dismissals=int(row.get("consecutive_dismissals") or 0),
        muted_until=row.get("muted_until"),
        delivered=int(row.get("delivered") or 0),
        acknowledged=int(row.get("acknowledged") or 0),
        dismissed=int(row.get("dismissed") or 0),
        ignored=int(row.get("ignored") or 0),
    )


def _rid(kind: str) -> RecordID:
    return RecordID("agenda_kind_stats", kind)


async def _save(s: KindStats, db: Any) -> None:
    data = {
        "kind": s.kind,
        "threshold_delta": s.threshold_delta,
        "consecutive_dismissals": s.consecutive_dismissals,
        "delivered": s.delivered,
        "acknowledged": s.acknowledged,
        "dismissed": s.dismissed,
        "ignored": s.ignored,
        "updated_at": get_clock().now(),
    }
    if s.muted_until is not None:
        data["muted_until"] = s.muted_until
    await db.query("UPSERT $rid CONTENT $data", {"rid": _rid(s.kind), "data": data})
    _stats[s.kind] = s


async def get_stats(kind: str, db: Any = None) -> KindStats:
    db = db if db is not None else get_db_client()
    rows = extract_rows(await db.query("SELECT * FROM $rid", {"rid": _rid(kind)}))
    return _from_row(rows[0]) if rows else KindStats(kind=kind)


async def refresh(db: Any = None) -> None:
    """Reload the sync mirror: kind stats and the recent dismissal log."""
    db = db if db is not None else get_db_client()
    _stats.clear()
    for row in extract_rows(await db.query("SELECT * FROM agenda_kind_stats")):
        _stats[row["kind"]] = _from_row(row)
    rows = extract_rows(
        await db.query(
            "SELECT resolved_at FROM agenda_item WHERE resolved_at != NONE "
            "AND (state = 'dismissed' OR ignored = true) ORDER BY resolved_at DESC LIMIT $n",
            {"n": _DISMISSAL_LOG_LIMIT},
        )
    )
    _dismissal_times[:] = [r["resolved_at"] for r in rows]


def threshold_delta(kind: str) -> float:
    """Learned delta added to the config threshold; 0 when learning is off."""
    if not enabled():
        return 0.0
    s = _stats.get(kind)
    return s.threshold_delta if s else 0.0


def dismissal_ages(now: datetime) -> tuple[float, ...]:
    """Ages in seconds of the recent dismissals (feeds B5-01's penalty)."""
    if not enabled():
        return ()
    return tuple(max(0.0, (now - t).total_seconds()) for t in _dismissal_times)


def _clamp(v: float) -> float:
    return min(settings.dismissal_threshold_ceiling, max(settings.dismissal_threshold_floor, v))


async def is_muted(kind: str, now: datetime | None = None, db: Any = None) -> bool:
    """True while a learned mute for ``kind`` is running. Read by ``may_initiate``."""
    if not enabled():
        return False
    now = now or get_clock().now()
    s = await get_stats(kind, db)
    return s.muted_until is not None and s.muted_until > now


async def record_delivered(kind: str, db: Any = None) -> None:
    if not enabled():
        return
    db = db if db is not None else get_db_client()
    s = await get_stats(kind, db)
    s.delivered += 1
    await _save(s, db)


async def record_outcome(
    kind: str, outcome: str, *, item_id: str | None = None, db: Any = None
) -> KindStats | None:
    """Apply ``acknowledged``, ``dismissed`` or ``ignored`` to the kind's state."""
    if not enabled():
        return None
    if outcome not in ("acknowledged", "dismissed", "ignored"):
        raise ValueError(f"unknown outcome: {outcome}")
    db = db if db is not None else get_db_client()
    now = get_clock().now()
    s = await get_stats(kind, db)
    refs = [item_id] if item_id else None
    if outcome == "acknowledged":
        s.acknowledged += 1
        s.consecutive_dismissals = 0
        s.threshold_delta = _clamp(s.threshold_delta - settings.dismissal_ease_step)
    else:
        if outcome == "dismissed":
            s.dismissed += 1
        else:
            s.ignored += 1
        s.consecutive_dismissals += 1
        s.threshold_delta = _clamp(s.threshold_delta + settings.dismissal_raise_step)
        _dismissal_times.insert(0, now)
        del _dismissal_times[_DISMISSAL_LOG_LIMIT:]
        if s.consecutive_dismissals >= settings.dismissal_mute_after:
            s.muted_until = now + timedelta(seconds=settings.dismissal_mute_seconds)
            s.consecutive_dismissals = 0
            await trace.record(
                "dismissal_learning",
                f"mute:{kind}",
                f"{settings.dismissal_mute_after} dismissals in a row; muted until {s.muted_until.isoformat()}",
                refs=refs,
                db=db,
            )
    await _save(s, db)
    return s


async def lift_mute(kind: str, db: Any = None) -> None:
    """The owner lifts a learned mute (called by ``unmute_kind``)."""
    db = db if db is not None else get_db_client()
    s = await get_stats(kind, db)
    if s.muted_until is None:
        return
    await db.query("UPDATE $rid SET muted_until = NONE", {"rid": _rid(kind)})
    s.muted_until = None
    _stats[kind] = s


async def sweep_ignored(now: datetime | None = None, db: Any = None) -> int:
    """Expire delivered items unanswered for ``agenda_ignore_hours``; count them as ignored."""
    if not enabled():
        return 0
    db = db if db is not None else get_db_client()
    now = now or get_clock().now()
    cutoff = now - timedelta(hours=settings.agenda_ignore_hours)
    rows = extract_rows(
        await db.query(
            "UPDATE agenda_item SET state = 'expired', ignored = true, resolved_at = $now "
            "WHERE state = 'delivered' AND delivered_at != NONE AND delivered_at <= $cutoff RETURN AFTER",
            {"now": now, "cutoff": cutoff},
        )
    )
    for row in rows:
        rid = row["id"]
        item_id = f"{rid.table_name}:{rid.id}" if isinstance(rid, RecordID) else str(rid)
        await record_outcome(row["kind"], "ignored", item_id=item_id, db=db)
    return len(rows)


async def stats_report(db: Any = None) -> dict[str, Any]:
    """Per-kind counters and reply rate (acknowledged over delivered)."""
    db = db if db is not None else get_db_client()
    out: dict[str, Any] = {}
    for row in extract_rows(await db.query("SELECT * FROM agenda_kind_stats")):
        s = _from_row(row)
        out[s.kind] = {
            "delivered": s.delivered,
            "acknowledged": s.acknowledged,
            "dismissed": s.dismissed,
            "ignored": s.ignored,
            "reply_rate": (s.acknowledged / s.delivered) if s.delivered else None,
            "threshold_delta": s.threshold_delta,
            "consecutive_dismissals": s.consecutive_dismissals,
            "muted_until": s.muted_until.isoformat() if s.muted_until else None,
        }
    return out
