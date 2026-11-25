"""Self-started goal proposals, task graphs and delegations (P2-33).

Every entry here passes ``controls.may_initiate`` before it acts:

- ``propose_goal``: level 2. Aura's new goal is paused and becomes a chat
  proposal (a ``needs_decision`` with approve / reject plus an agenda item, which
  the deliverer sends under the message budget and B5 interruptibility).
  Approve makes the goal active; reject cancels it.
- ``start_task_graph``: level 3, Titan only, the daily task graph budget. A
  graph for a ``self_improvement`` goal additionally needs a workspace Mai
  registered for Aura's own repository (D16) and her approval of that graph;
  the budget is spent when she approves. Graphs carry ``origin="autonomous"``.
- ``start_delegation``: level 3, ``origin="autonomous"``.

The kill switch (B1-06) stops autonomous graphs and delegations by origin.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from aura.autonomy import controls, trace
from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.executor.decisions import DecisionService, register_answer_hook

logger = logging.getLogger(__name__)

GOAL_PROPOSAL = "goal_proposal"
GRAPH_APPROVAL = "self_improvement_graph"
ORIGIN = "autonomous"
SELF_IMPROVEMENT = "self_improvement"


def _rid_str(value: Any) -> str:
    if hasattr(value, "table_name"):
        return f"{value.table_name}:{value.id}"
    return str(value)


def aura_repo_workspace() -> str | None:
    """Name of a registered workspace that holds Aura's own repository (D16), or None."""
    from pathlib import Path

    from aura.executor.code_node import is_aura_repo
    from aura.executor.policy import workspace_path

    for name in sorted((settings.workspaces or {}).keys()):
        path = workspace_path(name)
        if path is not None and is_aura_repo(Path(path)):
            return name
    return None


async def _refuse(source: str, action: str, why: str, refs: list[Any], db: Any) -> dict[str, Any]:
    await trace.record(source, action, why, allowed=False, refs=refs, db=db)
    return {"started": False, "reason": why}


async def _ask_owner(db: Any, action: str, resources: list[str], risk: str, message: str,
                     refs: list[str]) -> str:
    """A needs_decision (approve / reject) and its agenda item. Returns the decision id."""
    from aura.autonomy.agenda import AgendaService

    decision = await DecisionService(db=db).create(
        kind="needs_decision", session_id="autonomy", request_id=f"{action}:{uuid4().hex[:12]}",
        action=action, resources=resources, risk=risk, message=message,
    )
    decision_id = _rid_str(decision.get("id"))
    await AgendaService(db).create("needs_decision", message, [*refs, decision_id], source="initiative")
    return decision_id


# -- goal proposals (level 2) ----------------------------------------------------

def _goal_engine() -> Any:
    try:
        from aura.api.routes import goal as goal_routes
    except Exception:  # noqa: BLE001
        return None
    return getattr(goal_routes, "_goal_engine", None)


async def _align_goal_id(goal: Any, db: Any) -> None:
    """Make ``goal.goal_id`` the stored record id. The template path (formulate_goal)
    creates the row under a random id; after a restart the engine reads the record
    id as goal_id anyway, so this only brings that forward."""
    from aura.db.query_utils import extract_rows
    from aura.engines.goal.evidence import goal_rid

    if extract_rows(await db.query("SELECT id FROM $rid", {"rid": goal_rid(goal.goal_id)})):
        return
    rows = extract_rows(await db.query(
        "SELECT id FROM goal WHERE name = $name AND origin = $origin AND created = $created",
        {"name": goal.name, "origin": goal.origin, "created": goal.created},
    ))
    if len(rows) == 1:
        goal.goal_id = _rid_str(rows[0]["id"])


async def propose_goal(engine: Any, goal: Any, *, db: Any = None) -> bool:
    """Turn a goal Aura just created into a proposal Mai approves or rejects.

    The goal is paused until she answers. Refused (level, kill, or a
    self-improvement goal without Aura's workspace): the goal is cancelled.
    """
    db = db if db is not None else engine.db
    await _align_goal_id(goal, db)
    refs = [goal.goal_id]
    d = await controls.may_initiate("propose_goal", source="goal_engine", refs=refs, spend=False, db=db)
    reason = None if d.allowed else d.reason
    if reason is None and goal.goal_type == SELF_IMPROVEMENT and aura_repo_workspace() is None:
        reason = "self_improvement_needs_registered_aura_workspace"
        await trace.record("goal_engine", "propose_goal", reason, allowed=False, refs=refs, db=db)
    if reason is not None:
        await engine.cancel_goal(goal.goal_id, f"proposal refused: {reason}")
        return False
    goal.status = "paused"
    await engine._persist_goal(goal)
    message = (f"I'd like to take on a goal: {goal.name}. {goal.description}".strip()
               + " Approve or reject?")
    decision_id = await _ask_owner(db, GOAL_PROPOSAL, [goal.goal_id], "read", message, refs)
    await trace.record("goal_engine", "propose_goal", "waiting for the owner",
                       refs=[goal.goal_id, decision_id], db=db)
    return True


async def _on_goal_proposal(service: DecisionService, decision: dict, allow: bool,
                            decided_by: str, trusted: bool) -> None:
    goal_id = str((decision.get("resources") or [""])[0])
    approved = allow and decided_by == "owner"
    from aura.engines.goal.evidence import goal_rid

    # The goal may have left the engine's in-memory list (it keeps active goals),
    # so the row is updated directly and the engine reloads.
    if approved:
        # Mai approved it, so the goal links to her approval (not an orphan, P2-32).
        from aura.db.query_utils import extract_rows

        rows = extract_rows(await service._db.query("SELECT origin_link FROM $rid", {"rid": goal_rid(goal_id)}))
        link = dict((rows[0].get("origin_link") if rows else None) or {})
        link = {"kind": link.get("kind") or "aura_drive", "ref": _rid_str(decision.get("id")) or None,
                "approved": True}
        await service._db.query(
            "UPDATE $rid SET status = 'active', origin_link = $link, updated = $now WHERE status = 'paused'",
            {"rid": goal_rid(goal_id), "link": link, "now": get_clock().now()},
        )
    else:
        await service._db.query(
            "UPDATE $rid SET status = 'cancelled', stage = 'closed', stage_changed = $now, "
            "close_reason = $why, updated = $now WHERE status = 'paused'",
            {"rid": goal_rid(goal_id), "now": get_clock().now(), "why": "proposal rejected by Mai"},
        )
    engine = _goal_engine()
    if engine is not None:
        try:
            await engine._load_active_goals()
        except Exception as e:  # noqa: BLE001
            logger.warning("goal engine reload after proposal answer failed: %s", e)
    await trace.record("owner", "goal_proposal", "approved" if approved else "rejected",
                       refs=[goal_id], db=service._db)


# -- task graphs and delegations (level 3) ---------------------------------------

async def start_task_graph(goal: Any, plan: dict[str, Any], *, db: Any = None) -> dict[str, Any]:
    """Plan a task graph for an approved goal. ``plan`` has plan_task's arguments
    (goal, nodes, optional budget_usd / budget_minutes).

    Returns {"started": bool, "graph_id"?, "decision_id"?, "reason"?}.
    """
    from aura.executor.task_graph import TaskGraphStore
    from aura.tiers import active_profile, plan_task_enabled
    from aura.tools.plan_task import validate_plan

    db = db if db is not None else get_db_client()
    goal_id = goal.goal_id
    self_improvement = goal.goal_type == SELF_IMPROVEMENT
    kind = SELF_IMPROVEMENT if self_improvement else "task_graph"
    # Checked first without spending; a plain graph spends when it is created,
    # a self-improvement graph when Mai approves it.
    d = await controls.may_initiate(kind, source="initiative", refs=[goal_id], spend=False, db=db)
    if not d.allowed:
        return {"started": False, "reason": d.reason}
    if getattr(goal, "status", "active") != "active":
        return await _refuse("initiative", f"graph:{kind}", "goal is not approved and active", [goal_id], db)
    profile = active_profile()
    if not plan_task_enabled(profile) or profile.name != "titan":
        return await _refuse("initiative", f"graph:{kind}", "task graphs need the Titan tier", [goal_id], db)

    ws = None
    graph_goal = str(plan.get("goal") or goal.name).strip()
    if self_improvement:
        ws = aura_repo_workspace()
        if ws is None:
            return await _refuse("initiative", "graph:self_improvement",
                                 "self_improvement_needs_registered_aura_workspace", [goal_id], db)
        graph_goal = f"{graph_goal}\nworkspace: {ws}"
    nodes, budget_usd, budget_minutes, error = validate_plan({**plan, "goal": graph_goal}, profile)
    if error is not None or nodes is None:
        return await _refuse("initiative", f"graph:{kind}", f"invalid plan: {error}", [goal_id], db)
    if self_improvement:
        from aura.executor.code_node import _WORKSPACE_RE

        # Every workspace the plan names must be Aura's (code nodes resolve the brief, then the goal).
        for text in [graph_goal, *(n.brief or "" for n in nodes)]:
            other = next((m.group(1) for m in _WORKSPACE_RE.finditer(text) if m.group(1) != ws), None)
            if other is not None:
                return await _refuse("initiative", "graph:self_improvement",
                                     f"the plan names workspace {other}, not {ws}", [goal_id], db)

    if not self_improvement:
        d = await controls.may_initiate(kind, source="initiative", refs=[goal_id], db=db)
        if not d.allowed:
            return {"started": False, "reason": d.reason}
    store = TaskGraphStore(db)
    graph = await store.create_graph(graph_goal, nodes, budget_usd, budget_minutes, origin=ORIGIN)
    await store.write_blackboard(graph.id, "plan", json.dumps({
        "goal": graph_goal, "origin": ORIGIN, "for_goal": goal_id,
        "nodes": [{"id": n.id, "kind": n.kind, "brief": n.brief} for n in nodes],
    }))
    if self_improvement:
        message = (f"Self-improvement on my own code (workspace '{ws}'), for goal '{goal.name}': "
                   f"{len(nodes)} step(s), up to ${budget_usd:.2f} and {budget_minutes} minutes. "
                   f"Graph {graph.id}. Approve or reject this graph?")
        decision_id = await _ask_owner(db, GRAPH_APPROVAL, [graph.id, goal_id, f"workspace:{ws}"],
                                       "execute", message, [graph.id, goal_id])
        await trace.record("initiative", "graph:self_improvement", "waiting for the owner",
                           refs=[graph.id, decision_id], db=db)
        return {"started": False, "graph_id": graph.id, "decision_id": decision_id,
                "reason": "waiting_for_owner"}
    _start(graph.id)
    await trace.record("initiative", "graph:start", "autonomous task graph started",
                       refs=[graph.id, goal_id], db=db)
    return {"started": True, "graph_id": graph.id}


def _start(graph_id: str) -> None:
    from aura.executor.task_scheduler import get_task_scheduler

    get_task_scheduler().start(graph_id)


async def _on_graph_approval(service: DecisionService, decision: dict, allow: bool,
                             decided_by: str, trusted: bool) -> None:
    from aura.executor.task_graph import TaskGraphStore
    from aura.models.task_graph import GraphStatus

    db = service._db
    resources = [str(r) for r in (decision.get("resources") or [])]
    graph_id = resources[0] if resources else ""
    refs = resources[:2]
    store = TaskGraphStore(db)
    graph = await store.get_graph(graph_id) if graph_id else None
    if graph is None or graph.origin != ORIGIN or graph.status != GraphStatus.PLANNED:
        logger.warning("self-improvement approval for unknown or started graph %s", graph_id)
        return
    why = None
    if not (allow and decided_by == "owner"):
        why = "rejected by the owner"
    else:
        ws = next((r.partition(":")[2] for r in resources if r.startswith("workspace:")), None)
        if ws is None or ws != aura_repo_workspace():
            why = "self_improvement_needs_registered_aura_workspace"
        else:
            d = await controls.may_initiate(SELF_IMPROVEMENT, source="owner_approval", refs=refs, db=db)
            if not d.allowed:
                why = d.reason
    if why is not None:
        await store.update_graph(graph_id, status=GraphStatus.CANCELLED)
        await trace.record("initiative", "graph:self_improvement", why, allowed=False, refs=refs, db=db)
        return
    _start(graph_id)
    await trace.record("initiative", "graph:start", "self-improvement graph approved and started",
                       refs=refs, db=db)


async def start_delegation(*, db: Any = None, refs: list[Any] | None = None, **kwargs: Any) -> str | None:
    """A self-started delegation: level 3, recorded with ``origin="autonomous"``.
    Returns the task id, or None when the gate refuses."""
    from aura.executor import delegation

    d = await controls.may_initiate("delegation", source="initiative", refs=refs, db=db)
    if not d.allowed:
        return None
    kwargs.pop("origin", None)
    return await delegation.start_delegation(**kwargs, origin=ORIGIN)


register_answer_hook(GOAL_PROPOSAL, _on_goal_proposal)
register_answer_hook(GRAPH_APPROVAL, _on_graph_approval)
