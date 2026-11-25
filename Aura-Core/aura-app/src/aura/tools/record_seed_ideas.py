"""record_seed_ideas tool (P2-28 Diverge, step 1).

L3 writes its own obvious ideas first. They are stored as the baseline that novelty is
measured against and are never shown to the user as the answer. The result carries a
run id that ``diverge`` and ``record_final_ideas`` need.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from aura.config import settings
from aura.engines.creativity import diverge_enabled
from aura.engines.creativity.lineage import get_store
from aura.tools.consult import _error

logger = logging.getLogger(__name__)

TOOL_DEFINITION = {
    "name": "record_seed_ideas",
    "description": (
        "First step of the Diverge skill for creative requests. Write your own obvious ideas "
        "for the request (the exact number the skill says) and record them here before asking "
        "any helper. They are stored as a baseline, are not shown to the user and are not the "
        "answer. Returns a run_id for the diverge tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "question": {"type": "string", "description": "The creative request, self-contained."},
            "ideas": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Your own obvious ideas, one short sentence each.",
            },
        },
        "required": ["question", "ideas"],
    },
}


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not diverge_enabled():
        return _error("diverge is turned off. Do not call it again; answer without it.")
    if arguments.get("_requester_role") != "owner":
        return _error("diverge is only available to the owner.")
    question = arguments.get("question")
    if not isinstance(question, str) or not question.strip():
        return _error("question is required.")
    if len(question) > settings.consult_task_max_chars:
        return _error(f"question is too long (limit {settings.consult_task_max_chars} characters).")
    ideas = arguments.get("ideas")
    if not isinstance(ideas, list) or not all(isinstance(x, str) for x in ideas):
        return _error("ideas must be a list of strings.")
    ideas = [x.strip()[: settings.diverge_idea_max_chars] for x in ideas if x.strip()]
    if len(ideas) != settings.diverge_seed_count:
        return _error(f"give exactly {settings.diverge_seed_count} obvious ideas of your own.")
    try:
        run_id, seed_ids = await get_store().create_run(question.strip(), ideas)
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_seed_ideas failed: %s", exc)
        return _error("the seed ideas could not be stored.")
    return {
        "status": "OK", "success": True, "run_id": run_id, "seed_ids": seed_ids,
        "message": (
            f"Stored {len(seed_ids)} seed ideas under {run_id}. They are your baseline and are "
            "not shown to the user and are not the answer. Next call diverge with this run_id."
        ),
    }
