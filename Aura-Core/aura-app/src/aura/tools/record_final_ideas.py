"""record_final_ideas tool (P2-28 Diverge, steps 5 and 6).

L3 records what it converged on and where each idea came from. The code records the
lineage, computes whether each final idea overlaps L3's own seeds, the run's novelty
contribution, and updates the lens yield.
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
    "name": "record_final_ideas",
    "description": (
        "Last step of the Diverge skill. Record your final ideas and, for each, the ids of the "
        "seed or candidate ideas it came from. Call once per run. Then answer with the final "
        "ideas, never with your seeds."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "ideas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "sources": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "sources"],
                },
            },
        },
        "required": ["run_id", "ideas"],
    },
}


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    if not diverge_enabled():
        return _error("diverge is turned off. Do not call it again; answer without it.")
    if arguments.get("_requester_role") != "owner":
        return _error("diverge is only available to the owner.")
    run_id = arguments.get("run_id")
    store = get_store()
    run_row = await store.get_run(run_id) if isinstance(run_id, str) else None
    if run_row is None:
        return _error("unknown run_id: call record_seed_ideas first.")
    if run_row.get("finalized_at") is not None:
        return _error("this run already has its final ideas recorded.")
    raw = arguments.get("ideas")
    if not isinstance(raw, list) or not raw:
        return _error("ideas must be a non-empty list.")
    if len(raw) > settings.diverge_max_final_ideas:
        return _error(f"too many final ideas (limit {settings.diverge_max_final_ideas}).")
    known = {i["id"] for i in await store.ideas(run_id) if i["role"] in ("seed", "candidate")}
    finals = []
    for item in raw:
        text = item.get("text") if isinstance(item, dict) else None
        sources = item.get("sources") if isinstance(item, dict) else None
        if not isinstance(text, str) or not text.strip():
            return _error("every final idea needs text.")
        if not isinstance(sources, list) or not all(isinstance(s, str) for s in sources):
            return _error("sources must be a list of idea ids.")
        if len(sources) > settings.diverge_max_sources:
            return _error(f"too many sources for one idea (limit {settings.diverge_max_sources}).")
        bad = [s for s in sources if s not in known]
        if bad:
            return _error(f"unknown source ids for this run: {', '.join(b[:40] for b in bad)}.")
        finals.append({"text": text.strip()[: settings.diverge_idea_max_chars], "sources": sources})
    try:
        result = await store.finalize(run_id, finals)
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_final_ideas failed: %s", exc)
        return _error("the final ideas could not be stored.")
    return {
        "status": "OK", "success": True, "run_id": run_id,
        "novelty": result["novelty"],
        "overlaps_seed": [f["overlaps_seed"] for f in result["finals"]],
        "message": (
            f"Recorded {len(result['finals'])} final ideas; {result['novelty']:.0%} do not overlap "
            "your seeds. Answer with the final ideas only. Do not present your seeds."
        ),
    }
