"""Skill attribution and outcome statistics (G5-04, agency PRD 7 steps 2 and 3, 6.4).

``record_skill_use`` writes one ``skill_use`` row each time a skill version is
offered to a turn or a delegated task. ``apply_outcome`` turns a later outcome
into one attempt on that version, exactly once. ``unknown`` never counts, guest
requesters never count, and practice rows only move the ``practice_*`` fields.

No model call and no system clock here (``get_clock()`` only).
"""

from __future__ import annotations

import logging
import math
from typing import Any
from uuid import uuid4

import numpy as np
from surrealdb import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import extract_rows, to_record_id
from aura.engines.learning.skill_store import SkillStore, rid_str

logger = logging.getLogger(__name__)

_COUNTED_OUTCOMES = ("positive", "negative")


def attribution_enabled() -> bool:
    """Both flags are needed (G5-04 config)."""
    return bool(settings.skills_v2_enabled and settings.skill_attribution_enabled)


# -- pure helpers -----------------------------------------------------------


def beta_params(attempts: int, successes: int) -> tuple[int, int]:
    """Beta(1, 1) prior updated with the observed counts."""
    return 1 + successes, 1 + attempts - successes


def _beta_quantile(a: float, b: float, q: float) -> float:
    try:  # scipy is present as a transitive dependency; not required.
        from scipy.stats import beta as _beta

        return float(_beta.ppf(q, a, b))
    except ImportError:
        pass
    # Deterministic numeric quantile: midpoint grid, cumulative density, interpolation.
    n = 20000
    x = (np.arange(n) + 0.5) / n
    log_norm = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    logpdf = log_norm + (a - 1) * np.log(x) + (b - 1) * np.log1p(-x)
    cdf = np.cumsum(np.exp(logpdf)) / n
    cdf = cdf / cdf[-1]
    return float(np.interp(q, cdf, x))


def mastery(attempts: int, successes: int) -> tuple[float, float]:
    """``(mean, lower_bound)`` of the Beta posterior.

    The lower bound is the ``skill_mastery_quantile`` quantile, so 2 of 2 ranks
    below 200 of 200 although both rates are 1.0.
    """
    a, b = beta_params(attempts, successes)
    return a / (a + b), _beta_quantile(a, b, settings.skill_mastery_quantile)


# -- attribution ------------------------------------------------------------


async def _resolve_doc_id(store: SkillStore, skill: str) -> str | None:
    if skill.startswith("skill_doc:"):
        return skill
    doc = await store.get_doc(skill)
    return doc.id if doc else None


async def record_skill_use(
    store: SkillStore,
    skill: str,
    version: int,
    turn_id: str | None,
    task_id: str | None,
    requester_role: str,
    tools: list[str] | None = None,
    fact_ids: list[str] | None = None,
    practice: bool = False,
) -> str | None:
    """Write one ``skill_use`` row and return its id; None when attribution is off
    or the skill is unknown. ``skill`` is a doc id or a name."""
    if not attribution_enabled():
        return None
    doc_id = await _resolve_doc_id(store, skill)
    if doc_id is None:
        logger.warning("skill use not recorded, unknown skill: %s", skill)
        return None
    data: dict[str, Any] = {
        "skill": to_record_id(doc_id),
        "version": int(version),
        "requester_role": requester_role,
        "tools": [str(t) for t in (tools or [])],
        "fact_ids": [str(f) for f in (fact_ids or [])],
        "counted": False,
        "practice": bool(practice),
        "created_at": get_clock().now(),
    }
    if turn_id is not None:
        data["turn_id"] = str(turn_id)
    if task_id is not None:
        data["task_id"] = str(task_id)
    rid = RecordID("skill_use", uuid4().hex[:12])
    await store.db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data})
    if not practice:
        await store.touch_used(doc_id)
    return rid_str(rid)


async def apply_outcome(store: SkillStore, use: Any, outcome: str) -> bool:
    """Count ``outcome`` for one use. ``use`` is a ``skill_use`` id or a row with ``id``.

    Returns True when this call counted it. The claim (``counted = false`` ->
    true) is one conditional UPDATE, and the version is incremented in the
    query only when the claim changed a row, so concurrent calls count once.
    """
    if not attribution_enabled():
        return False
    use_id = use.get("id") if isinstance(use, dict) else use
    rid = to_record_id(rid_str(use_id))
    if outcome not in _COUNTED_OUTCOMES:
        # `unknown` is evidence of nothing: remember it, count nothing.
        await store.db.query(
            "UPDATE $rid SET outcome = $o WHERE outcome = NONE", {"rid": rid, "o": "unknown"}
        )
        return False
    claimed = extract_rows(
        await store.db.query(
            "UPDATE $rid SET counted = true, outcome = $o "
            "WHERE counted = false AND requester_role = 'owner' RETURN AFTER",
            {"rid": rid, "o": outcome},
        )
    )
    if not claimed:
        return False
    row = claimed[0]
    success = 1 if outcome == "positive" else 0
    if row.get("practice"):
        sql = (
            "UPDATE skill_version SET practice_attempts += 1, practice_successes += $s "
            "WHERE skill = $skill AND version = $v"
        )
    else:
        sql = (
            "UPDATE skill_version SET attempts += 1, successes += $s "
            "WHERE skill = $skill AND version = $v"
        )
    await store.db.query(
        sql, {"s": success, "skill": to_record_id(rid_str(row["skill"])), "v": int(row["version"])}
    )
    if not row.get("practice"):
        await _update_fact_confidence(store.db, row.get("fact_ids") or [], success == 1)
    return True


async def _update_fact_confidence(db: Any, fact_ids: list[str], success: bool) -> None:
    """Smoothed update for the ``inferred`` facts a skill use relied on (other
    provenances are never touched). Reuses the insight confidence formula."""
    if not fact_ids:
        return
    from aura.engines.learning.engine import smoothed_confidence

    try:
        rows = extract_rows(
            await db.query(
                "SELECT id, confidence, use_count FROM fact "
                "WHERE id IN $ids AND provenance = 'inferred'",
                {"ids": [to_record_id(f) for f in fact_ids]},
            )
        )
        for row in rows:
            n = max(int(row.get("use_count") or 0), 1)
            prior_successes = float(row.get("confidence") or 0.0) * n
            new = smoothed_confidence(prior_successes + (1 if success else 0), n + 1)
            await db.query(
                "UPDATE $rid SET confidence = $c", {"rid": row["id"], "c": min(1.0, max(0.0, new))}
            )
    except Exception as exc:
        logger.warning("Fact confidence update failed (non-critical): %s", exc)


async def _uses_where(store: SkillStore, field: str, value: str) -> list[dict[str, Any]]:
    return extract_rows(
        await store.db.query(f"SELECT * FROM skill_use WHERE {field} = $v", {"v": value})
    )


async def apply_outcome_for_turn(store: SkillStore, turn_id: str, outcome: str) -> int:
    """Apply ``outcome`` to every use recorded for ``turn_id``; returns how many counted."""
    if not attribution_enabled():
        return 0
    n = 0
    for row in await _uses_where(store, "turn_id", turn_id):
        n += bool(await apply_outcome(store, row, outcome))
    return n


async def apply_outcome_for_task(store: SkillStore, task_id: str, outcome: str) -> int:
    """Apply ``outcome`` to every use recorded for ``task_id``."""
    if not attribution_enabled():
        return 0
    n = 0
    for row in await _uses_where(store, "task_id", task_id):
        n += bool(await apply_outcome(store, row, outcome))
    return n


async def resolve_live_skill(name: str, store: SkillStore | None = None) -> tuple[str, int, str] | None:
    """``(doc id, version, body)`` of the skill's active version, or None when the skill
    is unknown, retired, has no active version, or that version is rejected/unapproved."""
    store = store or SkillStore()
    doc = await store.get_doc(name)
    if doc is None or doc.state == "retired" or doc.active_version is None:
        return None
    version = await store.get_version(doc.id, doc.active_version)
    if version is None or version.rejected or version.approved_at is None:
        return None
    return doc.id, version.version, version.body
