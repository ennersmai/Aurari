"""Skill correction (G6-03): a new, unapproved version from failures or an owner correction.

Runs only inside the dreaming phase, never on the reply path. The skill body is
never edited: only the pitfalls list grows (capped, oldest dropped). The result
goes through ``propose_skill(source="corrected")``, so the active version keeps
serving until the owner approves.

Watermark: ``skill_correction_log`` holds one row per handled group with the exact
``skill_use`` ids it consumed. A use whose id is in any log row is never selected
again, so the same negatives cannot feed a second correction.

Scoping (agency PRD 7.5): a lesson from a delegated task in workspace W (the
basename of ``task.workspace_path``) is stored as ``workspace:<W>: lesson``. A
turn-based use has no workspace, so its lesson is unscoped. A scoped line becomes
unscoped only when a similar lesson (embedding cosine >= ``skill_dup_similarity``,
no model) arrives from a different workspace, or from an unscoped source.
"""

import logging
import math
import re
from datetime import timedelta
from typing import Any

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import extract_rows, to_record_id
from aura.engines.learning.skill_proposals import propose_skill
from aura.engines.learning.skill_store import SkillStore, rid_str
from aura.logging_config import sanitize_log_payload

logger = logging.getLogger(__name__)

_SCOPE_RE = re.compile(r"^workspace:([^:]+): (.*)$", re.S)
_TEXT_CHARS = 500
_LESSON_CHARS = 300
_MAX_EVIDENCE = 5
_MAX_STEPS_IN_PROMPT = 40
_SCAN_LIMIT = 200

_PROMPT = (
    "A reusable skill was followed and the result was a failure or was corrected by the "
    "owner. Write ONE sentence for the skill's pitfalls list: what to avoid or do "
    "differently next time. Do not rewrite the procedure. Reply with the sentence only.\n\n"
    "SKILL:\n{body}\n\nEVIDENCE:\n{evidence}"
)


def _s(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def split_scope(line: str) -> tuple[str | None, str]:
    m = _SCOPE_RE.match(line)
    return (m.group(1), m.group(2)) if m else (None, line)


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(x * x for x in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


async def _consumed(db: Any) -> set[str]:
    out: set[str] = set()
    for r in extract_rows(await db.query("SELECT use_ids FROM skill_correction_log")):
        out.update(r.get("use_ids") or [])
    return out


async def _turn_info(db: Any, experience_id: str) -> tuple[bool, str]:
    """``(explicit correction, correcting message)`` for a failed turn.

    Explicit means the turn's outcome source is ``correction_marker`` (G5-03). The
    message is the next owner turn of the same user; the turn's own query if none.
    """
    rows = extract_rows(await db.query(
        "SELECT timestamp, user_id, outcome, context FROM experience WHERE experience_id = $e",
        {"e": experience_id},
    ))
    if not rows:
        return False, ""
    row = rows[0]
    explicit = (row.get("outcome") or {}).get("source") == "correction_marker"
    own = _s((row.get("context") or {}).get("user_query"))
    nxt = extract_rows(await db.query(
        "SELECT context FROM experience WHERE user_id = $u AND timestamp > $t "
        "ORDER BY timestamp ASC LIMIT 1",
        {"u": row.get("user_id"), "t": row.get("timestamp")},
    ))
    msg = _s(((nxt[0].get("context") or {}) if nxt else {}).get("user_query")) or own
    return explicit, msg


async def find_correction_candidates(db: Any, since: Any) -> list[dict[str, Any]]:
    """Groups of counted owner negatives not yet corrected, oldest first.

    Each is ``{skill, version, uses, explicit}``; kept when it has at least
    ``skill_correct_min_negatives`` uses or one explicit owner correction message.
    """
    rows = extract_rows(await db.query(
        "SELECT * FROM skill_use WHERE counted = true AND outcome = 'negative' "
        "AND requester_role = 'owner' AND practice = false AND created_at >= $since "
        "ORDER BY created_at ASC LIMIT $limit",
        {"since": since, "limit": _SCAN_LIMIT},
    ))
    done = await _consumed(db)
    groups: dict[tuple[str, int], dict[str, Any]] = {}
    for r in rows:
        rid = rid_str(r.get("id"))
        if rid in done:
            continue
        key = (rid_str(r["skill"]) or "", int(r["version"]))
        g = groups.setdefault(key, {"skill": key[0], "version": key[1], "uses": [], "explicit": False})
        g["uses"].append({"id": rid, "turn_id": r.get("turn_id"), "task_id": r.get("task_id")})
    out = []
    for g in groups.values():
        for u in g["uses"]:
            if u["turn_id"] and not u["task_id"]:
                u["explicit"], u["message"] = await _turn_info(db, str(u["turn_id"]))
                g["explicit"] = g["explicit"] or u["explicit"]
        if g["explicit"] or len(g["uses"]) >= int(settings.skill_correct_min_negatives):
            out.append(g)
    return out


async def _task_evidence(db: Any, task_id: str) -> tuple[str, str | None]:
    """``(step titles text, workspace name or None)`` of a failed task."""
    rows = extract_rows(await db.query("SELECT * FROM task WHERE task_id = $t", {"t": task_id}))
    if not rows:
        return "", None
    task = rows[0]
    titles = [
        _s(s.get("title"))[:200] for s in (task.get("steps") or [])
        if isinstance(s, dict) and _s(s.get("title"))
    ][:_MAX_STEPS_IN_PROMPT]
    titles = sanitize_log_payload(titles, max_list_preview=_MAX_STEPS_IN_PROMPT)
    path = _s(task.get("workspace_path")).replace("\\", "/").rstrip("/")
    ws = path.rsplit("/", 1)[-1] if path else None
    return "Failed task steps: " + "; ".join(str(t) for t in titles), ws or None


async def gather_evidence(db: Any, group: dict[str, Any]) -> tuple[str, str | None]:
    """Prompt evidence text and the workspace the lesson is scoped to (None = unscoped).

    Scoped to a workspace only when every use is a task in that one workspace.
    """
    parts: list[str] = []
    workspaces: set[str | None] = set()
    for u in group["uses"][:_MAX_EVIDENCE]:
        if u.get("task_id"):
            text, ws = await _task_evidence(db, str(u["task_id"]))
            workspaces.add(ws)
        else:
            msg = _s(u.get("message"))[:_TEXT_CHARS]
            text = f"Owner message: {sanitize_log_payload(msg)}" if msg else ""
            workspaces.add(None)
        if text.strip():
            parts.append(text)
    ws = next(iter(workspaces)) if len(workspaces) == 1 else None
    return "\n".join(f"- {p}" for p in parts), ws


async def draft_lesson(llm: Any, body: str, evidence: str) -> str | None:
    """One background model call; one lesson sentence or None for an unusable reply."""
    reply = await llm.complete(
        [{"role": "user", "content": _PROMPT.format(body=body[:3000], evidence=evidence)}],
        model=settings.memory_extraction_model or settings.active_l2_model,
        temperature=0,
    )
    text = " ".join(_s(reply).split())
    return text[:_LESSON_CHARS] if text else None


async def merge_lesson(
    embeddings: Any, pitfalls: list[str], lesson: str, workspace: str | None
) -> list[str] | None:
    """Pitfalls with ``lesson`` added or unscoped; None when nothing changes. Capped."""
    vec = await embeddings.embed(lesson)
    out = list(pitfalls)
    cap = int(settings.skill_pitfalls_max)
    if vec:
        for i, line in enumerate(out):
            scope, text = split_scope(line)
            other = await embeddings.embed(text)
            if _cos(vec, other or []) < settings.skill_dup_similarity:
                continue
            if scope is None or scope == workspace:
                return None  # already known: unscoped, or same workspace
            out[i] = text  # a second workspace (or an unscoped source) repeats it
            return out[-cap:]
    out.append(f"workspace:{workspace}: {lesson}" if workspace else lesson)
    return out[-cap:]


async def _log(db: Any, group: dict[str, Any], outcome: str, new_version: int | None) -> None:
    data: dict[str, Any] = {
        "skill": to_record_id(group["skill"]), "version": group["version"],
        "use_ids": [u["id"] for u in group["uses"]], "outcome": outcome,
        "corrected_at": get_clock().now(),
    }
    if new_version is not None:
        data["new_version"] = new_version
    await db.query("CREATE skill_correction_log CONTENT $data", {"data": data})


async def correct_cycle(db: Any, llm: Any, embeddings: Any) -> int:
    """Correct up to ``skill_correct_max_per_cycle`` skill versions. Returns proposals made."""
    since = get_clock().now() - timedelta(hours=float(settings.skill_correct_lookback_hours))
    groups = await find_correction_candidates(db, since)
    store = SkillStore(db)
    proposed = 0
    for group in groups[: int(settings.skill_correct_max_per_cycle)]:
        try:
            doc_rows = extract_rows(
                await db.query("SELECT name FROM $r", {"r": to_record_id(group["skill"])})
            )
            doc = await store.get_doc(doc_rows[0]["name"]) if doc_rows else None
            versions = await store.list_versions(group["skill"]) if doc else []
            if doc is None or doc.state == "retired" or not versions:
                await _log(db, group, "dropped", None)
                continue
            base = versions[-1]
            evidence, workspace = await gather_evidence(db, group)
            lesson = await draft_lesson(llm, base.body, evidence)
            merged = await merge_lesson(embeddings, base.pitfalls, lesson, workspace) if lesson else None
            if merged is None:
                await _log(db, group, "dropped" if not lesson else "no_change", None)
                continue
            ids = ", ".join(
                f"{u['id']} ({u.get('task_id') or u.get('turn_id')})"
                for u in group["uses"][:_MAX_EVIDENCE]
            )
            _, new, _ = await propose_skill(
                store, embeddings,
                {"name": doc.name, "when_to_use": doc.when_to_use, "body": base.body,
                 "tools": base.tools, "pitfalls": merged,
                 "change_note": f"corrected from v{group['version']} failures; evidence: {ids}"},
                source="corrected", origin_speaker="owner",
            )
            await _log(db, group, "proposed", new.version)
            proposed += 1
        except Exception as e:
            logger.warning(
                "[CORRECT] %s v%s failed, will retry next cycle: %s", group["skill"], group["version"], e
            )
    return proposed
