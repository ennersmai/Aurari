"""Skill distillation (G6-01): draft a skill from a finished owner task, while dreaming.

The only model call here runs inside the dreaming phase, never on the chat path.
A draft goes through ``propose_skill`` as an unapproved candidate (or a new
version of a near match); nothing is activated. Only the task goal and step
titles reach the prompt, never tool output or file contents.
"""

import json
import logging
from datetime import timedelta
from typing import Any

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.learning.skill_proposals import propose_skill
from aura.engines.learning.skill_store import SkillStore
from aura.logging_config import sanitize_log_payload

logger = logging.getLogger(__name__)

_TITLE_CHARS = 200
_GOAL_CHARS = 1000
_MAX_STEPS_IN_PROMPT = 40
_SCAN_LIMIT = 50

_PROMPT = (
    "A task finished successfully and passed review. Write a reusable skill for doing "
    "this kind of task again. Reply with JSON only, no prose, with keys: name (short, "
    "lowercase, hyphenated), when_to_use (one or two sentences), tags (list of short "
    "words), body (the procedure in plain steps), tools (tool names used), pitfalls "
    "(list of things to avoid).\n\nTASK BRIEF:\n{goal}\n\nSTEP TITLES:\n{steps}"
)


def _s(value: Any) -> str:
    return str(value).strip() if value is not None else ""


async def find_distillable_tasks(db: Any, since: Any, limit: int | None = None) -> list[dict[str, Any]]:
    """Complete, reviewed, owner-requested delegated tasks not yet looked at, oldest first."""
    rows = extract_rows(await db.query(
        "SELECT * FROM task WHERE delegated = true AND status = 'complete' "
        "AND reviewed = true AND requested_by_role = 'owner' AND updated_at >= $since "
        "AND array::len(steps) >= $min_steps ORDER BY updated_at ASC LIMIT $limit",
        {"since": since, "min_steps": int(settings.skill_distill_min_steps), "limit": _SCAN_LIMIT},
    ))
    done = {
        r.get("task_id") for r in extract_rows(await db.query("SELECT task_id FROM skill_distill_log"))
    }
    fresh = [r for r in rows if _s(r.get("task_id")) not in done]
    return fresh[:limit] if limit else fresh


def build_prompt(task: dict[str, Any]) -> str:
    titles = [
        _s(s.get("title"))[:_TITLE_CHARS]
        for s in (task.get("steps") or [])
        if isinstance(s, dict) and _s(s.get("title"))
    ]
    titles = sanitize_log_payload(titles[:_MAX_STEPS_IN_PROMPT], max_list_preview=_MAX_STEPS_IN_PROMPT)
    lines = "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1))
    return _PROMPT.format(goal=_s(task.get("goal"))[:_GOAL_CHARS], steps=lines)


def parse_draft(raw: Any) -> dict[str, Any] | None:
    """Validate the model reply. None (and a log line) for anything unusable."""
    text = _s(raw)
    if text.startswith("```"):
        text = text.strip("`")
        text = text[4:] if text.lower().startswith("json") else text
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        logger.warning("[DISTILL] draft dropped: invalid JSON")
        return None
    if not isinstance(data, dict):
        logger.warning("[DISTILL] draft dropped: not an object")
        return None
    name, when, body = _s(data.get("name")), _s(data.get("when_to_use")), _s(data.get("body"))
    if not name or not when or not body:
        logger.warning("[DISTILL] draft dropped: missing name, when_to_use or body")
        return None
    if len(body) > int(settings.skill_body_max_chars):
        logger.warning("[DISTILL] draft dropped: body is %d chars", len(body))
        return None

    def _list(key: str) -> list[str]:
        v = data.get(key)
        return [_s(x) for x in v if _s(x)] if isinstance(v, list) else []

    return {
        "name": name, "when_to_use": when, "body": body,
        "tags": _list("tags"), "tools": _list("tools"), "pitfalls": _list("pitfalls"),
    }


async def draft_skill(llm: Any, task: dict[str, Any]) -> dict[str, Any] | None:
    """One model call from the brief and step titles. Raises if the call itself fails."""
    reply = await llm.complete(
        [{"role": "user", "content": build_prompt(task)}],
        model=settings.memory_extraction_model or settings.active_l2_model,
        temperature=0,
    )
    return parse_draft(reply)


async def _mark(db: Any, task_id: str, outcome: str) -> None:
    await db.query("CREATE skill_distill_log CONTENT $data", {"data": {
        "task_id": task_id, "outcome": outcome, "distilled_at": get_clock().now(),
    }})


async def distill_cycle(db: Any, llm: Any, embeddings: Any) -> int:
    """Draft and propose up to ``skill_distill_max_per_cycle`` tasks. Returns proposals made."""
    since = get_clock().now() - timedelta(hours=float(settings.skill_distill_lookback_hours))
    tasks = await find_distillable_tasks(db, since, int(settings.skill_distill_max_per_cycle))
    store = SkillStore(db)
    proposed = 0
    for task in tasks:
        task_id = _s(task.get("task_id"))
        try:
            draft = await draft_skill(llm, task)
            if draft is None:
                await _mark(db, task_id, "dropped")
                continue
            await propose_skill(
                store, embeddings, draft, source="distilled", source_task=task_id,
                origin_speaker="owner",
            )
            await _mark(db, task_id, "proposed")
            proposed += 1
        except Exception as e:
            logger.warning("[DISTILL] task %s failed, will retry next cycle: %s", task_id, e)
    return proposed
