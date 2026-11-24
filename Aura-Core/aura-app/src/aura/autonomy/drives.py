"""Drives as persisted scalars (B2-01).

Five floats in 0..1 on the singleton ``drive_state:main``. Pure arithmetic:
no model call, no wall clock (callers pass ``now`` or the injected clock is
used). Decay toward baseline is computed from ``now - updated_at`` when an
event arrives, not from a timer. Drives update at every autonomy level,
including ``silent``; the gate only governs initiation, not inner state.
Everything is behind ``drives_enabled``.
"""

import logging
import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from surrealdb import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

DRIVES = ("curiosity", "competence", "connection", "coherence", "rest")
EVENTS = (
    "question_opened",
    "question_resolved",
    "prediction_failed",
    "goal_unfinished_tick",
    "task_done",
    "finding_pending",
    "finding_delivered",
    "exchange_happened",
    "contradiction_open",
    "contradiction_settled",
    "dream_completed",
    "consolidation_debt",
)
FACTOR_MIN, FACTOR_MAX = 0.8, 1.2
_RID = RecordID("drive_state", "main")


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class DriveModel:
    levels: dict[str, float]
    updated_at: datetime | None = None

    @classmethod
    def fresh(cls) -> "DriveModel":
        return cls({d: _clamp(settings.drive_baseline) for d in DRIVES})

    def decay(self, now: datetime) -> None:
        """Drift every level toward baseline for the time since ``updated_at``."""
        if self.updated_at is None:
            return
        hours = max(0.0, (now - self.updated_at).total_seconds() / 3600.0)
        if hours <= 0.0:
            return
        keep = math.exp(-settings.drive_decay_per_hour * hours)
        base = settings.drive_baseline
        for d in DRIVES:
            self.levels[d] = _clamp(base + (self.levels[d] - base) * keep)

    def apply(self, event: str, count: int = 1) -> None:
        """Add the configured deltas of ``event``; only the listed drives move."""
        for d in DRIVES:
            delta = getattr(settings, f"drive_delta_{event}_{d}", None)
            if delta is not None:
                self.levels[d] = _clamp(self.levels[d] + delta * count)

    def on_event(self, name: str, payload: dict[str, Any] | None, now: datetime) -> bool:
        """Decay to ``now`` then apply the event. Returns False for an unknown event."""
        if name not in EVENTS:
            return False
        self.decay(now)
        count = 1
        if name == "consolidation_debt":
            count = max(0, min(int((payload or {}).get("count", 0)), settings.drive_consolidation_debt_cap))
        self.apply(name, count)
        self.updated_at = now
        return True

    def as_dict(self) -> dict[str, float]:
        return {d: float(self.levels[d]) for d in DRIVES}


_EMOTION_SIGNAL = {
    "curiosity": ("curiosity", "fascination"),
    "competence": ("boredom",),
}


def emotion_factor(drive: str, emotion_vector: dict[str, float] | None) -> float:
    """Factor in [0.8, 1.2]; exactly 1.0 when modulation is off or no dimension matches."""
    if not settings.drive_emotion_modulation_enabled:
        return 1.0
    dims = _EMOTION_SIGNAL.get(drive)
    if not dims or not emotion_vector:
        return 1.0
    signal = max(float(emotion_vector.get(k, 0.0) or 0.0) for k in dims)
    # Centered on 0.5: a calm vector lowers the gain, an intense one raises it.
    factor = 1.0 + settings.drive_emotion_span * (signal - 0.5)
    return _clamp(factor, FACTOR_MIN, FACTOR_MAX)


def gain(drive: str, emotion_vector: dict[str, float] | None = None, model: DriveModel | None = None) -> float:
    """The drive level times its emotion factor. 0.0 when drives are off."""
    if not settings.drives_enabled or drive not in DRIVES:
        return 0.0
    m = model or _model
    level = m.levels[drive] if m is not None else _clamp(settings.drive_baseline)
    return level * emotion_factor(drive, emotion_vector)


_model: DriveModel | None = None


def reset_cache() -> None:
    """Forget the cached model (tests)."""
    global _model
    _model = None


def current() -> DriveModel | None:
    return _model


async def load(db: Any = None) -> DriveModel:
    """Read ``drive_state:main`` into the cache (in memory only when absent)."""
    global _model
    db = db if db is not None else get_db_client()
    rows = extract_rows(await db.query("SELECT * FROM $rid", {"rid": _RID}))
    if rows:
        row = rows[0]
        _model = DriveModel(
            {d: _clamp(float(row.get(d, settings.drive_baseline))) for d in DRIVES},
            row.get("updated_at"),
        )
    else:
        _model = DriveModel.fresh()
    return _model


async def _persist(m: DriveModel, db: Any) -> None:
    data: dict[str, Any] = m.as_dict()
    data["updated_at"] = m.updated_at
    await db.query("UPSERT $rid CONTENT $data", {"rid": _RID, "data": data})


async def _pending_episodes(db: Any) -> int:
    rows = extract_rows(
        await db.query(
            "SELECT count() AS n FROM episode WHERE extraction_status = $s GROUP ALL",
            {"s": "pending"},
        )
    )
    return int(rows[0]["n"]) if rows else 0


async def on_event(
    name: str,
    payload: dict[str, Any] | None = None,
    now: datetime | None = None,
    db: Any = None,
) -> dict[str, float] | None:
    """Apply an event, persist, publish ``drive_state``. None when disabled or unknown."""
    if not settings.drives_enabled or name not in EVENTS:
        return None
    db = db if db is not None else get_db_client()
    now = now or get_clock().now()
    if _model is None:
        await load(db)
    assert _model is not None
    payload = dict(payload or {})
    if name == "consolidation_debt" and "count" not in payload:
        payload["count"] = await _pending_episodes(db)
    _model.on_event(name, payload, now)
    await _persist(_model, db)
    values = _model.as_dict()
    try:
        from aura.autonomy import channel

        await channel.publish("drive_state", {**values, "event": name})
    except Exception:
        logger.warning("drive_state publish failed", exc_info=True)
    return values
