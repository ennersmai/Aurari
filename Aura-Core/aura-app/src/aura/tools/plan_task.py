"""plan_task tool (P2-08): create a task graph of research / think / code nodes.

Titan only (D3), owner only (D9, D13), behind ``task_graphs_enabled``. The tool
validates the plan, stores it with status "planned" and returns the graph id at
once. Nothing executes here: the scheduler is P2-09 (research, think) and P2-10
(code).
"""

import logging
from typing import Any, Dict

from aura.config import settings
from aura.models.task_graph import NODE_KINDS, TaskNode
from aura.tiers import active_profile, plan_task_enabled

logger = logging.getLogger(__name__)

_EPSILON = 1e-9

TOOL_DEFINITION = {
    "name": "plan_task",
    "description": (
        "Plan a larger job as a graph of nodes (research, think, code) and return its "
        "graph id at once. Nothing is run by this call. Use it only for work that needs "
        "several steps, e.g. research two things, think over both, then code."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {"type": "string", "description": "What the whole job should achieve."},
            "nodes": {
                "type": "array",
                "description": "The nodes of the graph. At most one node may have kind 'code'.",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "description": "Unique id inside this graph, e.g. 'r1'."},
                        "kind": {"type": "string", "enum": list(NODE_KINDS)},
                        "brief": {"type": "string", "description": "What this node must do."},
                        "success_criteria": {
                            "type": "string",
                            "description": "How to judge that this node succeeded (not empty).",
                        },
                        "depends_on": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Ids of nodes that must finish first.",
                        },
                        "budget_share": {
                            "type": "number",
                            "description": "Share of the graph budget, above 0 and at most 1. "
                                           "Omit to split the rest evenly.",
                        },
                    },
                    "required": ["id", "kind", "brief", "success_criteria"],
                },
            },
            "budget_usd": {"type": "number", "description": "Optional spend limit in USD."},
            "budget_minutes": {"type": "integer", "description": "Optional time limit in minutes."},
        },
        "required": ["goal", "nodes"],
    },
}


def _error(message: str) -> Dict[str, Any]:
    return {"status": "ERROR", "message": message, "success": False}


def _find_cycle(nodes: list[dict[str, Any]]) -> list[str]:
    """Ids left over after Kahn's algorithm: empty when the graph is acyclic."""
    indegree = {n["id"]: len(n["depends_on"]) for n in nodes}
    dependants: dict[str, list[str]] = {n["id"]: [] for n in nodes}
    for n in nodes:
        for dep in n["depends_on"]:
            dependants[dep].append(n["id"])
    ready = [i for i, d in indegree.items() if d == 0]
    seen = 0
    while ready:
        current = ready.pop()
        seen += 1
        for child in dependants[current]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    return sorted(i for i, d in indegree.items() if d > 0) if seen < len(nodes) else []


def validate_plan(arguments: Dict[str, Any], profile: Any) -> tuple[list[TaskNode] | None, float, int, str | None]:
    """Validate the arguments against ``profile``.

    Returns (nodes, budget_usd, budget_minutes, error). On error, nodes is None
    and error says what is wrong and how to fix it.
    """
    goal = arguments.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        return None, 0.0, 0, "goal is required: give a non-empty string describing the whole job."

    raw_nodes = arguments.get("nodes")
    max_nodes = profile.task_graph_max_nodes
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return None, 0.0, 0, f"nodes is required: give a list of 1 to {max_nodes} nodes."
    if len(raw_nodes) > max_nodes:
        return None, 0.0, 0, (
            f"Too many nodes: {len(raw_nodes)} given, the limit is {max_nodes}. "
            f"Merge steps so the plan has at most {max_nodes} nodes."
        )

    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_nodes):
        if not isinstance(raw, dict):
            return None, 0.0, 0, f"Node {index + 1} is not an object. Each node needs id, kind, brief and success_criteria."
        node_id = raw.get("id")
        if not isinstance(node_id, str) or not node_id.strip():
            return None, 0.0, 0, f"Node {index + 1} has no id. Give every node a unique non-empty string id."
        node_id = node_id.strip()
        if node_id in seen_ids:
            return None, 0.0, 0, f"Duplicate node id '{node_id}'. Node ids must be unique; rename one of them."
        seen_ids.add(node_id)
        kind = raw.get("kind")
        if kind not in NODE_KINDS:
            return None, 0.0, 0, (
                f"Node '{node_id}' has unknown kind {kind!r}. Use one of: {', '.join(NODE_KINDS)}."
            )
        brief = raw.get("brief")
        if not isinstance(brief, str) or not brief.strip():
            return None, 0.0, 0, f"Node '{node_id}' has no brief. Say in one or two sentences what it must do."
        criteria = raw.get("success_criteria")
        if not isinstance(criteria, str) or not criteria.strip():
            return None, 0.0, 0, (
                f"Node '{node_id}' has no success_criteria. Add a non-empty string saying how to "
                "judge that the node succeeded."
            )
        depends = raw.get("depends_on") or []
        if not isinstance(depends, list) or not all(isinstance(d, str) for d in depends):
            return None, 0.0, 0, f"Node '{node_id}': depends_on must be a list of node id strings."
        share = raw.get("budget_share")
        if share is not None:
            if isinstance(share, bool) or not isinstance(share, (int, float)) or not (0 < share <= 1):
                return None, 0.0, 0, (
                    f"Node '{node_id}': budget_share must be a number above 0 and at most 1, got {share!r}."
                )
        cleaned.append({
            "id": node_id, "kind": kind, "brief": brief.strip(), "success_criteria": criteria.strip(),
            "depends_on": [d.strip() for d in depends], "budget_share": share,
        })

    for node in cleaned:
        for dep in node["depends_on"]:
            if dep == node["id"]:
                return None, 0.0, 0, f"Node '{node['id']}' depends on itself. Remove it from its own depends_on."
            if dep not in seen_ids:
                return None, 0.0, 0, (
                    f"Node '{node['id']}' depends on unknown node '{dep}'. "
                    f"Known ids: {', '.join(sorted(seen_ids))}. Fix the id or add that node."
                )

    cyclic = _find_cycle(cleaned)
    if cyclic:
        return None, 0.0, 0, (
            f"The dependencies form a cycle through: {', '.join(cyclic)}. "
            "Remove a depends_on link so every node can run after the ones it needs."
        )

    code_nodes = [n["id"] for n in cleaned if n["kind"] == "code"]
    if len(code_nodes) > 1:
        return None, 0.0, 0, (
            f"Only one code node is allowed per graph (one coding session at a time); "
            f"found {len(code_nodes)}: {', '.join(code_nodes)}. Merge them into one code node."
        )

    budget_usd = arguments.get("budget_usd")
    budget_minutes = arguments.get("budget_minutes")
    if budget_usd is None:
        budget_usd = profile.task_budget_usd
    if budget_minutes is None:
        budget_minutes = profile.task_budget_minutes
    if (
        isinstance(budget_usd, bool) or not isinstance(budget_usd, (int, float)) or budget_usd <= 0
        or isinstance(budget_minutes, bool) or not isinstance(budget_minutes, int) or budget_minutes <= 0
    ):
        return None, 0.0, 0, "budget_usd must be a number above 0 and budget_minutes a whole number above 0, or omit them."
    if budget_usd > profile.task_budget_usd + _EPSILON:
        return None, 0.0, 0, (
            f"budget_usd {budget_usd} is over the limit of {profile.task_budget_usd}. Lower it or omit it."
        )
    if budget_minutes > profile.task_budget_minutes:
        return None, 0.0, 0, (
            f"budget_minutes {budget_minutes} is over the limit of {profile.task_budget_minutes}. "
            "Lower it or omit it."
        )

    given = sum(n["budget_share"] for n in cleaned if n["budget_share"] is not None)
    if given > 1.0 + _EPSILON:
        return None, 0.0, 0, (
            f"The budget_share values add up to {given:.2f}, over 1.0. Lower some shares so the total is at most 1.0."
        )
    missing = [n for n in cleaned if n["budget_share"] is None]
    if missing:
        remaining = 1.0 - given
        if remaining <= _EPSILON:
            return None, 0.0, 0, (
                "The given budget_share values use the whole budget, leaving nothing for "
                f"{', '.join(n['id'] for n in missing)}. Lower some shares or give every node a share."
            )
        # Even split of what the given shares leave (everything, when none is given).
        for n in missing:
            n["budget_share"] = remaining / len(missing)

    nodes = [
        TaskNode(
            id=n["id"], kind=n["kind"], brief=n["brief"], success_criteria=n["success_criteria"],
            depends_on=n["depends_on"], budget_share=min(float(n["budget_share"]), 1.0),
        )
        for n in cleaned
    ]
    return nodes, float(budget_usd), int(budget_minutes), None


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and store a task graph; return its id. Executes nothing."""
    if not (settings.task_graphs_enabled and settings.tier_profiles_enabled):
        return _error(
            "Task graphs are turned off (AURA_TASK_GRAPHS_ENABLED and AURA_TIER_PROFILES_ENABLED "
            "must both be on). Do not call plan_task again; answer without a task graph."
        )

    # The executor already refuses non-owners; the tool checks too (D9, D13).
    role = arguments.get("_requester_role")
    if role != "owner":
        return _error("plan_task is only available to the owner.")

    session = arguments.get("_session")
    if session is not None:
        allowed, reason = session.is_tool_allowed("plan_task")
        if not allowed:
            return _error(reason)

    profile = active_profile()
    if profile.name != "titan" or not plan_task_enabled(profile):
        return _error(
            f"plan_task needs the Titan tier; the active tier is '{profile.name}'. "
            "Do not plan a task graph on this tier."
        )

    nodes, budget_usd, budget_minutes, error = validate_plan(arguments, profile)
    if error is not None or nodes is None:
        return _error(error or "Invalid plan.")

    from aura.executor.task_graph import get_task_graph_store

    # TODO(P2-15): the coordinator does not expose the turn id to tools yet; pass it here then.
    created_by_turn = None
    goal = arguments["goal"].strip()
    store = get_task_graph_store()
    graph = await store.create_graph(goal, nodes, budget_usd, budget_minutes, created_by_turn)

    # The "plan" event for chat. There is no conversation id in a tool call, so the
    # event is a blackboard entry of kind "plan" (P2-11 renders it).
    import json

    plan_event = {
        "goal": goal,
        "budget_usd": budget_usd,
        "budget_minutes": budget_minutes,
        "nodes": [
            {"id": n.id, "kind": n.kind, "brief": n.brief, "success_criteria": n.success_criteria,
             "depends_on": n.depends_on, "budget_share": round(n.budget_share, 4)}
            for n in nodes
        ],
    }
    await store.write_blackboard(graph.id, "plan", json.dumps(plan_event))
    logger.info("plan event: graph=%s nodes=%d budget_usd=%s budget_minutes=%s",
                graph.id, len(nodes), budget_usd, budget_minutes)

    return {
        "status": "PLANNED",
        "message": f"Task graph planned. Graph ID: {graph.id}. Nothing has run yet.",
        "graph_id": graph.id,
        "node_count": len(nodes),
        "success": True,
    }
