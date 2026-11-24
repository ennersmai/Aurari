"""Skill documents API (G5-02).

GET  /skills                              - docs with active version summary and stats
GET  /skills/{name}                       - one doc with all its versions
POST /skills/import                       - body {"name"?, "text"}: inert candidate + decision (G6-02)
POST /skills/{name}/versions/{n}/approve  - body {"trusted": bool}
POST /skills/{name}/versions/{n}/reject

Approve and reject answer the pending ``skill_activate`` decision, so there is one
approval path (``DecisionService.answer``). Unauthenticated like the rest of the API.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException

from aura.config import settings
from aura.engines.learning import skill_proposals, skill_taught
from aura.engines.learning.skill_store import SkillStore, rid_str
from aura.executor.decisions import get_decision_service
from aura.llm.embeddings import get_embeddings_client

router = APIRouter(prefix="/skills", tags=["skills"])


def _doc_json(doc: Any, versions: list[Any]) -> dict[str, Any]:
    active = next((v for v in versions if v.version == doc.active_version), None)
    return {
        **doc.model_dump(mode="json", exclude={"when_embedding"}),
        "active": None if active is None else {
            "version": active.version,
            "source": active.source,
            "attempts": active.attempts,
            "successes": active.successes,
            "approved_at": active.approved_at.isoformat() if active.approved_at else None,
        },
        "version_count": len(versions),
    }


@router.get("")
async def list_skills() -> dict[str, Any]:
    store = SkillStore()
    docs = await store.list_docs(include_unapproved=True)
    return {"skills": [_doc_json(d, await store.list_versions(d.id)) for d in docs]}


@router.post("/import")
async def import_skill(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    if not settings.skills_v2_enabled:
        raise HTTPException(status_code=404, detail="skills are not enabled")
    name = body.get("name")
    if name is not None and not isinstance(name, str):
        raise HTTPException(status_code=422, detail="name must be a string")
    try:
        draft = skill_taught.parse_import(name, body.get("text"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    doc, version, merged = await skill_proposals.propose_skill(
        SkillStore(), get_embeddings_client(), draft, source="imported", origin_speaker="owner"
    )
    return {"skill": doc.name, "version": version.version, "merged": merged, "state": doc.state}


@router.get("/{name}")
async def get_skill(name: str) -> dict[str, Any]:
    store = SkillStore()
    doc = await store.get_doc(name)
    if doc is None:
        raise HTTPException(status_code=404, detail="skill not found")
    versions = await store.list_versions(doc.id)
    return {
        **_doc_json(doc, versions),
        "versions": [v.model_dump(mode="json") for v in versions],
    }


async def _answer(name: str, n: int, allow: bool, trusted: bool) -> dict[str, Any]:
    service = get_decision_service()
    pending = await service.find_pending(skill_proposals.ACTION, f"{name} v{n}")
    if not pending:
        raise HTTPException(status_code=404, detail="no pending decision for that version")
    item = await service.answer(rid_str(pending[0]["id"]), allow, "owner", trusted=trusted)
    return {"decision": item.get("status"), "skill": name, "version": n}


@router.post("/{name}/versions/{n}/approve")
async def approve(
    name: str, n: int, body: dict[str, Any] | None = Body(default=None)
) -> dict[str, Any]:
    return await _answer(name, n, True, bool((body or {}).get("trusted", False)))


@router.post("/{name}/versions/{n}/reject")
async def reject(name: str, n: int) -> dict[str, Any]:
    return await _answer(name, n, False, False)
