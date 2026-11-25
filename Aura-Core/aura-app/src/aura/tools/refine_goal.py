"""refine_goal tool (P2-32): fill the crystal checklist of a goal from the conversation.

Owner only (``_requester_role`` is set by the executor), behind ``goals_v3_enabled``.
On Mai's goals the outcome and done criteria need Mai's words (``mai_said``) or her
confirmation of a recorded proposal (``confirm``); otherwise they are recorded as proposed.
The tool never calls a model and never marks a milestone done.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from aura.config import settings
from aura.models.goal import CHECKLIST_FIELDS

logger = logging.getLogger(__name__)

TOOL_NAME = "refine_goal"

TOOL_DEFINITION = {
    "name": TOOL_NAME,
    "description": (
        "Fill checklist fields of a goal when the conversation gives them: outcome, done_criteria "
        "(list of checkable statements), owner (mai, aura or shared), horizon, first_action. Pass "
        "only what the conversation gave. On Mai's goals the outcome and done criteria need Mai's "
        "words: set mai_said true only if Mai said them; otherwise they are recorded as proposed. "
        "When Mai agrees to a proposal, call again with confirm true and no fields."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal_id": {"type": "string", "description": "Id of an active goal, e.g. 'goal:abc'."},
            "fields": {
                "type": "object",
                "description": "Checklist fields to set.",
                "properties": {
                    "outcome": {"type": "string"},
                    "done_criteria": {"type": "array", "items": {"type": "string"}},
                    "owner": {"type": "string", "enum": ["mai", "aura", "shared"]},
                    "horizon": {"type": "string"},
                    "first_action": {"type": "string"},
                },
            },
            "mai_said": {"type": "boolean", "description": "Mai herself said the outcome or done criteria."},
            "confirm": {"type": "boolean", "description": "Mai confirmed the pending proposal."},
        },
        "required": ["goal_id"],
    },
}


def refine_goal_enabled() -> bool:
    return bool(settings.goals_v3_enabled)


def _error(message: str) -> Dict[str, Any]:
    return {"status": "ERROR", "message": message, "success": False}


def _engine() -> Any:
    from aura.api.routes.goal import get_goal_engine

    return get_goal_engine()


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not refine_goal_enabled():
        return _error("refine_goal is turned off. Do not call it again.")
    if arguments.get("_requester_role") != "owner":
        return _error("refine_goal is only available to the owner.")
    goal_id = arguments.get("goal_id")
    if not isinstance(goal_id, str) or not goal_id.strip():
        return _error("goal_id is required.")
    fields = arguments.get("fields") or {}
    if not isinstance(fields, dict):
        return _error(f"fields must be an object with: {', '.join(CHECKLIST_FIELDS)}.")
    try:
        engine = _engine()
    except Exception:  # noqa: BLE001 - no engine, no goals
        return _error("The goal engine is not ready.")
    ok, message = await engine.refine_checklist(
        goal_id.strip(), fields,
        mai_said=arguments.get("mai_said") is True, confirm=arguments.get("confirm") is True,
    )
    if not ok:
        return _error(message)
    return {"status": "OK", "message": message, "success": True}
