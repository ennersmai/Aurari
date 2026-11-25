"""Criteria checker (B3-02): code-only evidence that a goal criterion is met.

No model call and no LLM statement counts as evidence. ``check`` returns the open
criteria that are now provably met; ``owner_confirms`` is never decided here (the
owner route sets it).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aura.config import settings
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


# P2-32 kinds. ``mai_confirms`` is B3's ``owner_confirms`` under the plan's name.
OWNER_KINDS = ("owner_confirms", "mai_confirms")
COMPARATORS = {
    ">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b, "<": lambda a, b: a < b,
}


async def _metric_tasks_complete(db: Any, goal_id: str) -> float:
    rows = await db.query(
        "SELECT id FROM task WHERE goal_id = $rid AND status = 'complete'", {"rid": goal_rid(goal_id)}
    )
    return float(len(rows))


async def _metric_tests_passed(db: Any, goal_id: str) -> float:
    rows = await db.query(
        "SELECT id FROM task WHERE goal_id = $rid AND status = 'complete' AND tests_passed = true",
        {"rid": goal_rid(goal_id)},
    )
    return float(len(rows))


# Metrics code can read. A metric_threshold spec naming any other metric is an uncheckable spec.
METRICS = {"tasks_complete": _metric_tasks_complete, "tests_passed_tasks": _metric_tests_passed}


async def _metric_threshold(db: Any, goal_id: str, spec: dict[str, Any]) -> str | None:
    fn = METRICS.get(str(spec.get("metric")))
    cmp = COMPARATORS.get(str(spec.get("op")))
    value = spec.get("value")
    if fn is None or cmp is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    current = await fn(db, goal_id)
    return f"{spec['metric']}={current:g}" if cmp(current, float(value)) else None


async def _commit(db: Any, goal: Any, spec: dict[str, Any]) -> str | None:
    """A commit made since the goal was created whose subject contains ``spec['contains']``,
    in a registered workspace. Read-only git; the sha is the reference."""
    from aura.executor.policy import workspace_path

    name, needle = spec.get("workspace"), str(spec.get("contains") or "").strip().lower()
    root = workspace_path(name) if name else None
    if root is None or not needle:
        return None
    since = goal.created.isoformat()
    proc = await asyncio.create_subprocess_exec(
        "git", "-C", str(root), "log", "--format=%H%x09%s", f"--since={since}",
        "-n", str(settings.goals_v3_commit_scan_max),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return None
    for line in out.decode("utf-8", "replace").splitlines():
        sha, _, subject = line.partition("	")
        if needle in subject.lower():
            return sha
    return None


def classify(spec: dict[str, Any]) -> str:
    """How a spec is decided: ``owner`` (waits for Mai), ``code`` (code can check it) or
    ``model`` (valid kind, but code has no way to check it; Swift may only flag it)."""
    kind = spec.get("kind") if isinstance(spec, dict) else None
    if kind in OWNER_KINDS:
        return "owner"
    if kind == "metric_threshold":
        ok = (spec.get("metric") in METRICS and spec.get("op") in COMPARATORS
              and isinstance(spec.get("value"), (int, float)) and not isinstance(spec.get("value"), bool))
        return "code" if ok else "model"
    if kind in ("file_exists",):
        return "code" if spec.get("workspace") and spec.get("path") else "model"
    if kind == "commit":
        return "code" if spec.get("workspace") and spec.get("contains") else "model"
    if kind in ("test_pass", "task_node_done"):
        return "code"
    if kind == "question_resolved":
        return "code" if spec.get("question_id") else "model"
    return "model"


async def _resolve(db: Any, goal: Any, kind: Any, spec: dict[str, Any]) -> str | None:
    if kind == "file_exists":
        return _file_exists(spec)
    if kind == "test_pass":
        return await _test_pass(db, goal.goal_id, spec)
    if kind == "task_node_done":
        return await _task_node_done(db, goal.goal_id, spec)
    if kind == "question_resolved":
        return await _question_resolved(db, goal.goal_id, spec)
    if kind == "commit":
        return await _commit(db, goal, spec)
    if kind == "metric_threshold":
        return await _metric_threshold(db, goal.goal_id, spec)
    return None  # owner kinds are set by the owner route, never by the checker


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
            ref = await _resolve(db, goal, kind, spec)
        except Exception as e:
            logger.warning(f"Criterion {crit.get('id')} ({kind}) not checked: {e}")
            ref = None
        if ref:
            met.append(Met(crit["id"], crit.get("name", ""), kind, ref, now))
    return met


@dataclass(frozen=True)
class MilestoneMet:
    """An open milestone found done by code, with the reference that proves it."""

    index: int
    name: str
    kind: str
    ref: str
    at: datetime


async def check_milestones(goal: Any, now: datetime, db: Any = None) -> list[MilestoneMet]:
    """Open milestones of ``goal`` whose spec code can check and that are now met.

    Only specs classified ``code`` are tried. ``mai_confirms`` and model-only specs are
    never decided here: no model call, no LLM statement is evidence.
    """
    db = db or get_db_client()
    met: list[MilestoneMet] = []
    for i, m in enumerate(goal.milestones or []):
        spec = m.get("evidence_spec") or {}
        if m.get("status") == "done" or classify(spec) != "code":
            continue
        try:
            ref = await _resolve(db, goal, spec.get("kind"), spec)
        except Exception as e:
            logger.warning(f"Milestone {m.get('name')} ({spec.get('kind')}) not checked: {e}")
            ref = None
        if ref:
            met.append(MilestoneMet(i, m.get("name", ""), spec["kind"], ref, now))
    return met
