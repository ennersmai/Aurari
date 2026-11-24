"""Skill proposals (G5-02): near-duplicate merge and the owner approval decision.

No model call, and nothing is activated here: a proposal is an unapproved version
until the owner answers the ``skill_activate`` decision. The post-answer hook is
registered at import; ``api/routes/skills.py`` imports this module and main.py
includes that router, so the hook is live in the running app.
"""

import logging
from typing import Any

from aura.config import settings
from aura.engines.learning.skill_store import SkillStore, rid_str
from aura.executor.decisions import DecisionService, get_decision_service, register_answer_hook
from aura.models.learning import SkillDoc, SkillVersion

logger = logging.getLogger(__name__)

ACTION = "skill_activate"


def resource_for(name: str, version: int) -> str:
    return f"skill:{name}:v{version}"


def parse_resource(resource: str) -> tuple[str, int]:
    head, _, num = resource.rpartition(":v")
    if not head.startswith("skill:") or not num.isdigit():
        raise ValueError(f"not a skill resource: {resource}")
    return head[len("skill:"):], int(num)


def _message(name: str, version: SkillVersion, origin_speaker: str) -> str:
    note = ""
    if version.change_note and version.change_note.strip():
        note = version.change_note.strip().splitlines()[0]
    text = f"Skill '{name}' v{version.version}"
    if origin_speaker == "guest":
        text += " (learned from a guest conversation)"
    if note:
        text += f": {note}"
    return f"{text}\n{version.body[:300]}"


async def propose_skill(
    store: SkillStore,
    embeddings: Any,
    draft: dict[str, Any],
    source: str,
    source_task: str | None = None,
    origin_speaker: str = "owner",
    decisions: DecisionService | None = None,
    pre_approved: bool = False,
) -> tuple[SkillDoc, SkillVersion, bool]:
    """Store ``draft`` as an unapproved version and ask the owner. Returns (doc, version, merged).

    ``pre_approved`` (G6-02) is honoured only for ``source="taught"`` with
    ``origin_speaker="owner"``: the version is approved and active at once, a new
    doc is ``trusted``, and no decision is created. Any other call is unapproved.
    """
    owner_taught = pre_approved and source == "taught" and origin_speaker == "owner"
    name = draft["name"]
    when = draft["when_to_use"]
    vec = await embeddings.embed(when)
    doc: SkillDoc | None = None
    if vec:
        near = await store.nearest_doc(vec)
        if near is not None and near[1] >= settings.skill_dup_similarity:
            doc = near[0]
    if doc is None:
        doc = await store.get_doc(name)  # same name, different meaning: still one doc
    merged = doc is not None
    if doc is None:
        doc = await store.create_doc(
            name, when, tags=draft.get("tags"),
            state="trusted" if owner_taught else "candidate",
            origin_speaker=origin_speaker, when_embedding=vec or None,
        )
    version = await store.add_version(
        doc.id, draft.get("body", ""), source, tools=draft.get("tools"),
        pitfalls=draft.get("pitfalls"), source_task=source_task,
        examples=[source_task] if source_task else None,
        change_note=draft.get("change_note") or (f"merged into '{doc.name}'" if merged else None),
        approved=owner_taught, approved_by="owner-taught" if owner_taught else None,
    )
    if owner_taught:
        await store.set_active(doc.id, version.version)
        return doc, version, merged
    await _ask_owner(decisions or get_decision_service(), doc, version, origin_speaker)
    return doc, version, merged


async def _ask_owner(
    service: DecisionService, doc: SkillDoc, version: SkillVersion, origin_speaker: str
) -> None:
    message = _message(doc.name, version, origin_speaker)
    resource = resource_for(doc.name, version.version)
    request_id = f"{doc.name} v{version.version}"
    # One pending item per skill: a newer proposal supersedes the open one.
    for item in await service.find_pending(ACTION):
        try:
            name, _ = parse_resource((item.get("resources") or [""])[0])
        except ValueError:
            continue
        if name == doc.name:
            await service.update_pending(
                rid_str(item["id"]), {"message": message, "resources": [resource], "request_id": request_id}
            )
            return
    await service.create(
        kind="needs_decision", session_id="skill", request_id=request_id, action=ACTION,
        resources=[resource], risk="write", message=message,
    )


async def _on_answer(
    service: DecisionService, decision: dict, allow: bool, decided_by: str, trusted: bool
) -> None:
    if not settings.skills_v2_enabled:
        return
    name, number = parse_resource((decision.get("resources") or [""])[0])
    store = SkillStore(service._db)
    doc = await store.get_doc(name)
    if doc is None:
        logger.warning("skill_activate answered for unknown skill %s", name)
        return
    if allow:
        await store.approve(doc.id, number, decided_by, trusted=trusted)
    else:
        await store.reject(doc.id, number)


register_answer_hook(ACTION, _on_answer)
