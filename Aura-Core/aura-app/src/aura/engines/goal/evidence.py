"""Criteria checker (B3-02): code-only evidence that a goal criterion is met.

No model call and no LLM statement counts as evidence. ``check`` returns the open
criteria that are now provably met; ``owner_confirms`` is never decided here (the
owner route sets it).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aura.db.client import get_db_client
from aura.db.query_utils import to_record_id

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Met:
    """A criterion found met, with the reference that proves it."""

    criterion_id: str
    name: str
    kind: str
    ref: str
    at: datetime


def _bare(goal_id: str) -> str:
    return goal_id.partition(":")[2] or goal_id


def _goal_forms(goal_id: str) -> list[str]:
    return [goal_id, _bare(goal_id)]


def goal_rid(goal_id: str) -> Any:
    """Record id of a goal whether ``goal_id`` is ``goal:x`` or the bare ``x``."""
    return to_record_id(goal_id if ":" in goal_id else f"goal:{goal_id}")


def _file_exists(spec: dict[str, Any]) -> str | None:
    from aura.executor.policy import inside_workspace, workspace_path

    name, rel = spec.get("workspace"), spec.get("path")
    if not name or not rel:
        return None
    root = workspace_path(name)
    if root is None:
        return None
    target = Path(rel) if Path(rel).is_absolute() else root / rel
    if not inside_workspace(target, name):
        return None
    return str(target.resolve()) if target.is_file() else None


async def _test_pass(db: Any, goal_id: str, spec: dict[str, Any]) -> str | None:
    rows = await db.query(
        "SELECT id FROM task WHERE goal_id = $rid AND status = 'complete' "
        "AND tests_passed = true LIMIT 1",
        {"rid": goal_rid(goal_id)},
    )
    return str(rows[0]["id"]) if rows else None


async def _task_node_done(db: Any, goal_id: str, spec: dict[str, Any]) -> str | None:
    graphs = await db.query(
        "SELECT VALUE id FROM task_graph WHERE goal IN $forms", {"forms": _goal_forms(goal_id)}
    )
    if not graphs:
        return None
    nodes = await db.query(
        "SELECT id, node_id, status FROM task_node WHERE graph IN $graphs", {"graphs": graphs}
    )
    wanted = spec.get("node_id")
    if wanted:
        nodes = [n for n in nodes if n.get("node_id") == wanted]
    if not nodes or any(n.get("status") != "done" for n in nodes):
        return None
    return str(nodes[0]["id"])


async def _question_resolved(db: Any, goal_id: str, spec: dict[str, Any]) -> str | None:
    qid = spec.get("question_id")
    if not qid:
        return None
    rows = await db.query(
        "SELECT status FROM $rid", {"rid": to_record_id(str(qid) if ":" in str(qid) else f"question:{qid}")}
    )
    return str(qid) if rows and rows[0].get("status") == "resolved" else None


async def check(goal: Any, now: datetime, db: Any = None) -> list[Met]:
    """Open criteria of ``goal`` that are now met by evidence found in code."""
    db = db or get_db_client()
    met: list[Met] = []
    for crit in goal.criteria or []:
        if crit.get("status") == "met":
            continue
        kind, spec = crit.get("kind"), crit.get("spec") or {}
        try:
            if kind == "file_exists":
                ref = _file_exists(spec)
            elif kind == "test_pass":
                ref = await _test_pass(db, goal.goal_id, spec)
            elif kind == "task_node_done":
                ref = await _task_node_done(db, goal.goal_id, spec)
            elif kind == "question_resolved":
                ref = await _question_resolved(db, goal.goal_id, spec)
            else:  # owner_confirms is set by the route, never by the checker
                ref = None
        except Exception as e:
            logger.warning(f"Criterion {crit.get('id')} ({kind}) not checked: {e}")
            ref = None
        if ref:
            met.append(Met(crit["id"], crit.get("name", ""), kind, ref, now))
    return met
