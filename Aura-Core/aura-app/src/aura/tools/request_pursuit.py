"""request_pursuit tool (B3-05, PRD 9, finding B4): ask the owner to pursue a goal.

Owner only, behind ``goals_v2_enabled``. The tool never creates a grant: for a
scope above ``read`` it raises a ``needs_decision`` and an agenda item, and only
``DecisionService.answer`` (the owner's allow) creates the grant. ``read`` needs
no grant: a read-only pursuit is started under the autonomy gate.
"""

import asyncio
import logging
from typing import Any, Dict
from uuid import uuid4

from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

TOOL_NAME = "request_pursuit"
REQUEST_SCOPES = ("read", "write", "execute", "send")

TOOL_DEFINITION = {
    "name": TOOL_NAME,
    "description": (
        "Ask the owner for permission to work on one of your active goals on your own. "
        "'read' scope starts read-only work at once; 'write', 'execute' and 'send' wait "
        "for the owner's approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Id of an active goal, e.g. 'goal:abc'."},
            "scope": {"type": "string", "enum": list(REQUEST_SCOPES)},
            "budget": {
                "type": "object",
                "description": "Spend limit for the pursuit.",
                "properties": {
                    "minutes": {"type": "integer"},
                    "tokens": {"type": "integer"},
                },
            },
        },
        "required": ["goal_id", "scope"],
    },
}


def request_pursuit_enabled() -> bool:
    """Offered and callable only under goals_v2_enabled and a tier that allows it."""
    if not settings.goals_v2_enabled:
        return False
    if settings.tier_profiles_enabled:
        from aura.tiers import active_profile, tool_allowed

        return tool_allowed(active_profile(), TOOL_NAME)
    return True


def _error(message: str) -> Dict[str, Any]:
    return {"status": "ERROR", "message": message, "success": False}


def _budget(raw: Any) -> tuple[dict[str, int] | None, str | None]:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        return None, "budget must be an object with minutes and tokens."
    caps = {"minutes": settings.pursuit_max_minutes, "tokens": settings.pursuit_max_tokens}
    out: dict[str, int] = {}
    for key, cap in caps.items():
        value = raw.get(key, cap)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
            return None, f"budget.{key} must be a whole number."
        if not 1 <= int(value) <= cap:
            return None, f"budget.{key} must be between 1 and {cap}."
        out[key] = int(value)
    return out, None


async def _active_goal(goal_id: str, db: Any) -> dict[str, Any] | None:
    from aura.engines.goal.evidence import goal_rid

    rows = extract_rows(await db.query("SELECT id, name, status FROM $rid", {"rid": goal_rid(goal_id)}))
    if not rows or rows[0].get("status") != "active":
        return None
    return rows[0]


async def _start_read_pursuit(goal_id: str, budget: dict[str, int]) -> str:
    """Start a read-only pursuit in the background. The engine runs the autonomy gate
    (may_initiate) itself; tool calls inside it carry no grant, so only reads run."""
    from aura.api.routes.goal import get_goal_engine
    from aura.main import orchestrator

    engine = get_goal_engine()
    if engine is None or orchestrator is None:
        raise RuntimeError("goal engine not ready")
    task = asyncio.create_task(
        engine.pursue_goal_autonomously(goal_id, loop_count=1, orchestrator=orchestrator, tool_permissions=[]),
        name=f"request_pursuit:{goal_id}",
    )

    def _log(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception() is not None:
            logger.warning("read pursuit of %s ended: %s", goal_id, t.exception())

    task.add_done_callback(_log)
    return "started"


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not request_pursuit_enabled():
        return _error("request_pursuit is turned off. Do not call it again.")
    # The executor already refuses non-owners; the tool checks too.
    if arguments.get("_requester_role") != "owner":
        return _error("request_pursuit is only available to the owner.")

    goal_id = arguments.get("goal_id")
    scope = arguments.get("scope")
    if not isinstance(goal_id, str) or not goal_id.strip():
        return _error("goal_id is required.")
    goal_id = goal_id.strip()
    if scope not in REQUEST_SCOPES:
        return _error(f"scope must be one of {', '.join(REQUEST_SCOPES)}.")
    budget, err = _budget(arguments.get("budget"))
    if err:
        return _error(err)

    db = get_db_client()
    try:
        goal = await _active_goal(goal_id, db)
    except Exception as e:  # noqa: BLE001 - fail closed
        logger.warning("request_pursuit goal lookup failed: %s", e)
        goal = None
    if goal is None:
        return _error(f"No active goal {goal_id}.")
    name = goal.get("name") or goal_id

    if scope == "read":
        try:
            await _start_read_pursuit(goal_id, budget)
        except Exception as e:  # noqa: BLE001
            return _error(f"Could not start the read-only pursuit: {e}")
        return {"status": "STARTED", "success": True,
                "message": f"Read-only pursuit of '{name}' started."}

    from aura.autonomy.agenda import AgendaService
    from aura.executor.decisions import DecisionService

    hours = settings.pursuit_grant_hours
    message = (f"Aura asks to pursue goal '{name}' ({goal_id}) with scope '{scope}', "
               f"budget {budget['minutes']} minutes and {budget['tokens']} tokens. "
               f"If allowed, the grant expires after {hours} hours.")
    decision = await DecisionService(db=db).create(
        kind="needs_decision",
        session_id="autonomy",
        request_id=f"pursuit:{uuid4().hex[:12]}",
        action="pursuit",
        resources=[goal_id, f"scope:{scope}", f"minutes:{budget['minutes']}", f"tokens:{budget['tokens']}"],
        risk=scope,
        message=message,
    )
    rid = decision.get("id")
    decision_id = f"{rid.table_name}:{rid.id}" if hasattr(rid, "table_name") else str(rid)
    await AgendaService(db).create("needs_decision", message, [goal_id, decision_id], source=TOOL_NAME)
    return {"status": "WAITING", "success": True, "decision_id": decision_id,
            "message": "Waiting for the owner to approve this pursuit."}
