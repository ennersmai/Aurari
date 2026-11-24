"""Pursuit grants and the risk check (B3-04, PRD 9 rule 7, T11).

Autonomous work on a goal may only do more than read when the owner has
granted that scope. Every failure (no grant, unknown risk, DB error) refuses.
"""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from surrealdb import RecordID

from aura.autonomy import trace
from aura.autonomy.agenda import AgendaService
from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

SCOPES = ("write", "execute", "send")


def required_scope(risk: Any) -> str | None:
    """None for read-only work; an unknown risk needs the widest grant (execute)."""
    if risk == "read":
        return None
    if risk in SCOPES:
        return risk
    return "execute"


async def create(
    goal_id: str,
    scope: str,
    expires_at: datetime,
    *,
    granted_by: str = "owner",
    budget: dict[str, int] | None = None,
    db: Any = None,
) -> str:
    if scope not in SCOPES:
        raise ValueError(f"unknown grant scope: {scope}")
    db = db if db is not None else get_db_client()
    data: dict[str, Any] = {
        "goal_id": str(goal_id),
        "scope": scope,
        "budget": {k: int(v) for k, v in (budget or {}).items() if k in ("tokens", "minutes", "calls") and v is not None},
        "granted_by": granted_by,
        "granted_at": get_clock().now(),
        "expires_at": expires_at,
    }
    rid = RecordID("pursuit_grant", uuid4().hex[:12])
    await db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data})
    return f"pursuit_grant:{rid.id}"


async def check(goal_id: Any, risk: Any, now: datetime | None = None, db: Any = None) -> bool:
    """True only when a live (unrevoked, unexpired) grant covers ``risk``. Fails closed."""
    scope = required_scope(risk)
    if scope is None:
        return True
    if not goal_id:
        return False
    try:
        now = now or get_clock().now()
        db = db if db is not None else get_db_client()
        await revoke_expired(now, db)
        rows = extract_rows(await db.query(
            "SELECT id FROM pursuit_grant WHERE goal_id = $g AND scope = $s "
            "AND revoked_at IS NONE AND expires_at > $now LIMIT 1",
            {"g": str(goal_id), "s": scope, "now": now},
        ))
        return bool(rows)
    except Exception as e:  # noqa: BLE001 - fail closed
        logger.warning("grant check failed, refusing: %s", e)
        return False


async def revoke_expired(now: datetime | None = None, db: Any = None) -> None:
    now = now or get_clock().now()
    db = db if db is not None else get_db_client()
    await db.query(
        "UPDATE pursuit_grant SET revoked_at = $now WHERE revoked_at IS NONE AND expires_at <= $now",
        {"now": now},
    )


async def revoke_all(db: Any = None) -> None:
    """Kill switch (B1-06): revoke every live grant."""
    db = db if db is not None else get_db_client()
    await db.query(
        "UPDATE pursuit_grant SET revoked_at = $now WHERE revoked_at IS NONE",
        {"now": get_clock().now()},
    )


async def refuse(goal_id: Any, tool_name: str, risk: Any, source: str, db: Any = None) -> None:
    """Record a refused autonomous call: one needs_decision per (goal, tool), plus a trace row."""
    refs = [str(goal_id or "unknown_goal"), str(tool_name)]
    try:
        svc = AgendaService(db)
        rows = extract_rows(await svc.db.query(
            "SELECT id FROM agenda_item WHERE kind = 'needs_decision' "
            "AND state IN ['pending', 'delivered'] AND refs = $refs LIMIT 1",
            {"refs": refs},
        ))
        if not rows:
            await svc.create(
                "needs_decision",
                f"Autonomous work on {refs[0]} wants to use '{tool_name}' (risk {risk}) "
                "but has no pursuit grant.",
                refs,
                source=source or "autonomy",
            )
    except Exception as e:  # noqa: BLE001 - the refusal holds regardless
        logger.warning("could not raise needs_decision for %s: %s", refs, e)
    await trace.record(
        source or "autonomy", f"tool:{tool_name}", f"no_grant:{required_scope(risk)}",
        allowed=False, refs=refs, db=db,
    )
