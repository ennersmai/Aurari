"""G6-02: taught and imported skills, on the real schema with fake embeddings and a fake LLM."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aura.api.routes import skills as skills_routes
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.learning.engine import LearningEngine
from aura.engines.learning.skill_store import SkillStore
from aura.engines.learning.skill_taught import (
    build_taught_draft,
    describes_procedure,
    parse_import,
)
from aura.executor.decisions import DecisionService, set_decision_service
from aura.models.learning import Experience
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
STEPS = "To release the app:\n1. Run the tests.\n2. Build the bundle.\n3. Push the tag."
SENTENCES = "Open the dashboard. Click the export button."


def _vec(*pairs):
    v = [0.0] * 768
    for i, x in pairs:
        v[i] = x
    return v


class FakeEmb:
    """Same vector for every text: any two skills are near matches."""

    async def embed(self, text):
        return _vec((0, 1.0))


class DistinctEmb:
    def __init__(self):
        self.seen = {}

    async def embed(self, text):
        if text not in self.seen:
            self.seen[text] = _vec((len(self.seen), 1.0))
        return self.seen[text]


class ForbiddenLLM:
    def __getattr__(self, name):
        raise AssertionError("no model call is allowed in G6-02")


# --- pure heuristic -------------------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    (STEPS, True),
    ("- stash changes\n- pull main\n- reapply", True),
    (SENTENCES, True),
    ("First, open the file. Then run the linter.", True),
    ("I prefer short answers.", False),
    ("Please always call me Sam, and keep replies brief.", False),
    ("1. only one item", False),
    ("Open the door.", False),
    ("", False),
])
def test_describes_procedure(text, expected):
    assert describes_procedure(text) is expected


def test_draft_uses_owner_words():
    d = build_taught_draft(STEPS)
    assert d["body"] == STEPS and d["when_to_use"] == "To release the app:"
    assert d["name"] == "to-release-the-app"
    assert build_taught_draft("x" * (settings.skill_body_max_chars + 1)) is None


def test_parse_import_front_matter_and_refusals():
    d = parse_import(
        None, "---\nname: Deploy Site\nwhen_to_use: ship the site\ntags: [ops, web]\n---\nRun deploy."
    )
    assert d == {
        "name": "deploy-site", "when_to_use": "ship the site", "tags": ["ops", "web"], "body": "Run deploy.",
    }
    assert parse_import("My Name", "Just a body line.")["name"] == "my-name"
    for bad in ("", "   ", "---\nname: x\nno colon here\n---\nbody", "---\nname: x\nbody never closed",
                "---\nname: x\n---\n", "x" * (settings.skill_body_max_chars + 1), None):
        with pytest.raises(ValueError):
            parse_import(None, bad)


# --- integration ----------------------------------------------------------------------


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "skills_v2_enabled", True)
    monkeypatch.setattr(settings, "skill_taught_enabled", True)
    svc = DecisionService(db=d)
    set_decision_service(svc)
    eng = LearningEngine.__new__(LearningEngine)
    eng.logger = logging.getLogger("t")
    eng.db = d
    eng.embeddings = FakeEmb()
    eng.llm_layers = ForbiddenLLM()

    async def no_compile(exp):
        return None

    eng._compile_new_skill = no_compile  # existing path, not under test
    yield eng, SkillStore(d), svc, d
    set_decision_service(None)  # type: ignore[arg-type]
    set_clock(Clock())
    await d.close()


def _exp(text, speaker="owner"):
    return Experience(
        experience_id="experience:t1", user_id="u1" if speaker == "owner" else speaker,
        task_type="instruction", domain="coding", context={"user_query": text}, aura_response={}, outcome={}, emotional_state={},
        metadata={"intent": "teaching", "speaker": speaker},
    )


async def _pending(svc):
    return await svc.find_pending("skill_activate")


async def test_owner_teaching_creates_trusted_live_v1_without_decision(env):
    eng, store, svc, _ = env
    await eng._process_pattern_extraction(_exp(STEPS))
    docs = await store.list_docs()
    assert len(docs) == 1
    doc = docs[0]
    assert doc.state == "trusted" and doc.active_version == 1 and doc.origin_speaker == "owner"
    v = await store.get_version(doc.id, 1)
    assert v.approved_at == _START and v.approved_by == "owner-taught" and v.source == "taught"
    assert await _pending(svc) == []


async def test_same_teaching_again_is_v2_pre_approved_no_decision(env):
    eng, store, svc, _ = env
    await eng._process_pattern_extraction(_exp(STEPS))
    await eng._process_pattern_extraction(_exp(STEPS + "\n4. Announce it."))
    docs = await store.list_docs(include_unapproved=True)
    assert len(docs) == 1
    doc = docs[0]
    assert doc.active_version == 2 and doc.previous_version == 1 and doc.state == "trusted"
    v2 = await store.get_version(doc.id, 2)
    assert v2.approved_by == "owner-taught"
    assert await _pending(svc) == []  # the G5-02 decision path is not triggered


async def test_guest_teaching_is_inert_candidate_with_decision(env):
    eng, store, svc, _ = env
    await eng._process_pattern_extraction(_exp(STEPS, speaker="discord_42"))
    assert await store.list_docs() == []
    doc = (await store.list_docs(include_unapproved=True))[0]
    assert doc.state == "candidate" and doc.origin_speaker == "guest" and doc.active_version is None
    assert (await store.get_version(doc.id, 1)).approved_at is None
    pend = await _pending(svc)
    assert len(pend) == 1 and "learned from a guest conversation" in pend[0]["message"]


async def test_missing_speaker_is_never_trusted(env):
    eng, store, svc, _ = env
    exp = _exp(STEPS)
    exp.metadata = {"intent": "teaching"}
    await eng._process_pattern_extraction(exp)
    doc = (await store.list_docs(include_unapproved=True))[0]
    assert doc.state == "candidate" and len(await _pending(svc)) == 1


async def test_guest_near_match_on_trusted_skill_stays_unapproved(env):
    eng, store, svc, _ = env
    await eng._process_pattern_extraction(_exp(STEPS))
    await eng._process_pattern_extraction(_exp(STEPS + "\n4. Evil.", speaker="discord_42"))
    doc = (await store.list_docs(include_unapproved=True))[0]
    assert doc.active_version == 1
    assert (await store.get_version(doc.id, 2)).approved_at is None
    assert len(await _pending(svc)) == 1


async def test_plain_preference_makes_no_skill(env):
    eng, store, svc, _ = env
    await eng._process_pattern_extraction(_exp("I prefer short answers."))
    assert await store.list_docs(include_unapproved=True) == [] and await _pending(svc) == []


@pytest.mark.parametrize("flag", ["skills_v2_enabled", "skill_taught_enabled"])
async def test_flag_off_leaves_fast_lane_unchanged(env, monkeypatch, flag):
    eng, store, svc, _ = env
    compiled = []

    async def compile_(exp):
        compiled.append(exp)

    eng._compile_new_skill = compile_
    monkeypatch.setattr(settings, flag, False)
    await eng._process_pattern_extraction(_exp(STEPS))
    assert len(compiled) == 1  # the existing route still runs
    assert await store.list_docs(include_unapproved=True) == [] and await _pending(svc) == []


def _client():
    app = FastAPI()
    app.include_router(skills_routes.router)
    return TestClient(app)


async def test_import_creates_inert_candidate_and_one_decision(env, monkeypatch):
    _, store, svc, d = env
    monkeypatch.setattr(skills_routes, "SkillStore", lambda: SkillStore(d))
    monkeypatch.setattr(skills_routes, "get_embeddings_client", lambda: DistinctEmb())
    r = _client().post("/skills/import", json={
        "text": "---\nname: pr-review\nwhen_to_use: review a pull request\ntags: a, b\n---\n1. Read the diff.\n2. Comment.",
    })
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "candidate" and r.json()["version"] == 1
    assert await store.list_docs() == []
    doc = await store.get_doc("pr-review")
    assert doc.tags == ["a", "b"] and doc.active_version is None
    v = await store.get_version(doc.id, 1)
    assert v.source == "imported" and v.approved_at is None
    assert len(await _pending(svc)) == 1


async def test_import_oversize_and_malformed_refused(env, monkeypatch):
    _, store, svc, d = env
    monkeypatch.setattr(skills_routes, "SkillStore", lambda: SkillStore(d))
    monkeypatch.setattr(skills_routes, "get_embeddings_client", lambda: DistinctEmb())
    c = _client()
    big = "x" * (settings.skill_body_max_chars + 1)
    assert c.post("/skills/import", json={"text": big}).status_code == 422
    assert c.post("/skills/import", json={"text": "---\nname x\n---\nbody"}).status_code == 422
    assert c.post("/skills/import", json={"text": "---\nname: x\nbody"}).status_code == 422
    assert c.post("/skills/import", json={}).status_code == 422
    assert await store.list_docs(include_unapproved=True) == [] and await _pending(svc) == []
