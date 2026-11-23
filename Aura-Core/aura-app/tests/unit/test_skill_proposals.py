"""G5-02 (T12): proposals, near-duplicate merge and owner approval, on the real schema."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aura.api.routes import skills as skills_routes
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.learning.skill_proposals import propose_skill
from aura.engines.learning.skill_store import SkillStore, rid_str
from aura.executor import decisions as decisions_mod
from aura.executor.decisions import DecisionService, register_answer_hook, set_decision_service
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _vec(*pairs: tuple[int, float]) -> list[float]:
    v = [0.0] * 768
    for i, x in pairs:
        v[i] = x
    return v


class FakeEmb:
    def __init__(self, table):
        self.table = table

    async def embed(self, text: str):
        return self.table.get(text)


EMB = FakeEmb({
    "ship the site": _vec((0, 1.0)),
    "deploy the website": _vec((0, 1.0), (1, 0.2)),  # cosine ~0.98
    "cook pasta": _vec((5, 1.0)),
    "no vector": None,
})


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    monkeypatch.setattr(settings, "skills_v2_enabled", True)
    svc = DecisionService(db=d)
    set_decision_service(svc)
    yield SkillStore(d), svc, d, clock
    set_decision_service(None)  # type: ignore[arg-type]
    set_clock(Clock())
    await d.close()


def _draft(name, when, body="do the thing"):
    return {"name": name, "when_to_use": when, "tags": ["t"], "body": body, "tools": ["bash"]}


async def _pending(svc):
    return await svc.find_pending("skill_activate")


async def test_near_duplicate_adds_version_not_doc(env):
    store, svc, _, _ = env
    doc, v1, merged = await propose_skill(store, EMB, _draft("deploy", "ship the site"), "distilled", "task:1")
    assert not merged and v1.version == 1 and doc.state == "candidate"
    assert v1.approved_at is None and doc.active_version is None
    doc2, v2, merged2 = await propose_skill(
        store, EMB, _draft("deploy-web", "deploy the website", "better"), "corrected", "task:2"
    )
    assert merged2 and doc2.id == doc.id and v2.version == 2
    assert len(await store.list_docs(include_unapproved=True)) == 1
    assert (await store.get_doc("deploy")).active_version is None  # nothing live


async def test_dissimilar_creates_new_candidate(env):
    store, _, _, _ = env
    await propose_skill(store, EMB, _draft("deploy", "ship the site"), "distilled")
    doc, v, merged = await propose_skill(store, EMB, _draft("pasta", "cook pasta"), "distilled")
    assert not merged and v.version == 1 and doc.name == "pasta"
    assert len(await store.list_docs(include_unapproved=True)) == 2
    assert await store.list_docs() == []  # neither is live


async def test_missing_embedding_does_not_crash(env):
    store, _, _, _ = env
    doc, v, merged = await propose_skill(store, EMB, _draft("a", "no vector"), "taught")
    assert not merged and doc.when_embedding is None
    _, _, merged2 = await propose_skill(store, EMB, _draft("b", "cook pasta"), "taught")
    assert not merged2


async def test_allow_activates_and_second_proposal_adds_no_second_decision(env):
    store, svc, _, clock = env
    doc, v1, _ = await propose_skill(store, EMB, _draft("deploy", "ship the site"), "distilled")
    pend = await _pending(svc)
    assert len(pend) == 1 and pend[0]["resources"] == ["skill:deploy:v1"]
    assert pend[0]["risk"] == "write" and pend[0]["session_id"] == "skill"
    # a second proposal while pending: still one decision, now about v2
    await propose_skill(store, EMB, _draft("x", "deploy the website"), "corrected")
    pend = await _pending(svc)
    assert len(pend) == 1 and pend[0]["resources"] == ["skill:deploy:v2"]
    await svc.answer(rid_str(pend[0]["id"]), True, "owner")
    d = await store.get_doc("deploy")
    assert d.active_version == 2 and d.state == "candidate"
    got = await store.get_version(doc.id, 2)
    assert got.approved_at == _START and got.approved_by == "owner" and not got.rejected
    assert (await store.get_version(doc.id, 1)).approved_at is None
    assert await _pending(svc) == []


async def test_trusted_approval_and_previous_version(env):
    store, svc, _, _ = env
    await propose_skill(store, EMB, _draft("deploy", "ship the site"), "distilled")
    await svc.answer(rid_str((await _pending(svc))[0]["id"]), True, "owner")
    await propose_skill(store, EMB, _draft("deploy", "ship the site", "v2 body"), "corrected")
    await svc.answer(rid_str((await _pending(svc))[0]["id"]), True, "owner", trusted=True)
    d = await store.get_doc("deploy")
    assert d.active_version == 2 and d.previous_version == 1 and d.state == "trusted"


async def test_deny_keeps_old_active_and_rejects(env):
    store, svc, _, _ = env
    doc, _, _ = await propose_skill(store, EMB, _draft("deploy", "ship the site"), "distilled")
    await svc.answer(rid_str((await _pending(svc))[0]["id"]), True, "owner")
    await propose_skill(store, EMB, _draft("deploy", "ship the site", "bad"), "corrected")
    await svc.answer(rid_str((await _pending(svc))[0]["id"]), False, "owner")
    d = await store.get_doc("deploy")
    v2 = await store.get_version(doc.id, 2)
    assert d.active_version == 1 and v2.rejected and v2.approved_at is None


async def test_guest_message_and_never_approved(env):
    store, svc, _, _ = env
    doc, v, _ = await propose_skill(
        store, EMB, _draft("deploy", "ship the site"), "taught", origin_speaker="guest"
    )
    assert doc.origin_speaker == "guest" and v.approved_at is None
    assert "learned from a guest conversation" in (await _pending(svc))[0]["message"]


async def test_flag_off_hook_does_nothing(env, monkeypatch):
    store, svc, _, _ = env
    doc, _, _ = await propose_skill(store, EMB, _draft("deploy", "ship the site"), "distilled")
    monkeypatch.setattr(settings, "skills_v2_enabled", False)
    out = await svc.answer(rid_str((await _pending(svc))[0]["id"]), True, "owner")
    assert out["status"] == "allowed"
    assert (await store.get_doc("deploy")).active_version is None
    assert (await store.get_version(doc.id, 1)).approved_at is None


async def test_other_needs_decision_unaffected_and_hook_registry(env):
    _, svc, _, _ = env
    seen = []

    async def hook(service, decision, allow, by, trusted):
        seen.append((decision["action"], allow, trusted))

    register_answer_hook("custom_x", hook)
    try:
        for action in ("merge", "custom_x"):
            rec = await svc.create("needs_decision", "s", "r", action, ["a"], "write")
            out = await svc.answer(rid_str(rec["id"]), True, "owner", trusted=True)
            assert out["status"] == "allowed"
        assert seen == [("custom_x", True, True)]
    finally:
        decisions_mod._ANSWER_HOOKS.pop("custom_x", None)


async def test_route_without_pending_decision_is_404(env):
    app = FastAPI()
    app.include_router(skills_routes.router)
    client = TestClient(app)
    assert client.post("/skills/deploy/versions/9/approve", json={"trusted": True}).status_code == 404
