"""G6-01 (T11): skill distillation in dreaming, end to end on the real schema."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from surrealdb import RecordID

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.dreaming.engine import DreamingEngine
from aura.engines.learning import skill_distill
from aura.engines.learning.skill_index import candidates
from aura.engines.learning.skill_store import SkillStore
from aura.executor.decisions import DecisionService, set_decision_service
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _vec(*pairs):
    v = [0.0] * 768
    for i, x in pairs:
        v[i] = x
    return v


class FakeEmb:
    async def embed(self, text):
        return {
            "ship the site": _vec((0, 1.0)),
            "deploy the website": _vec((0, 1.0), (1, 0.2)),
        }.get(text, _vec((9, 1.0)))


class FakeLLM:
    def __init__(self, replies, forbid=False):
        self.replies = list(replies)
        self.calls = []
        self.forbid = forbid

    async def complete(self, messages, **kw):
        if self.forbid:
            pytest.fail("model called when it must not be")
        self.calls.append(messages[0]["content"])
        return self.replies.pop(0)


def _draft(name="deploy-site", when="ship the site", body="1. build\n2. upload\n3. verify"):
    return json.dumps({"name": name, "when_to_use": when, "tags": ["deploy"], "body": body,
                       "tools": ["bash"], "pitfalls": ["stale cache"]})


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    monkeypatch.setattr(settings, "skills_v2_enabled", True)
    monkeypatch.setattr(settings, "skill_distill_enabled", True)
    svc = DecisionService(db=d)
    set_decision_service(svc)
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: FakeEmb())
    yield d, svc, clock
    set_decision_service(None)  # type: ignore[arg-type]
    set_clock(Clock())
    await d.close()


async def _plant(db, tid, role="owner", reviewed=True, status="complete", steps=4, goal="Deploy the site"):
    # The legacy init_schema still requires goal_id, description and created on task.
    await db.query("CREATE $rid CONTENT $d", {"rid": RecordID("task", tid), "d": {
        "goal_id": RecordID("goal", "g"), "description": goal, "created": _START,
        "task_id": f"task:{tid}", "goal": goal, "status": status,
        "delegated": True, "requested_by_role": role, "reviewed": reviewed,
        "updated_at": _START + timedelta(minutes=1),
        "steps": [{"step_number": i, "step_type": "tool", "title": f"step {i}",
                   "result": "RAW-TOOL-OUTPUT"} for i in range(steps)],
    }})


def _engine(db, llm):
    eng = DreamingEngine.__new__(DreamingEngine)
    eng.db = db
    eng._llm_layers = SimpleNamespace(client=llm)
    eng._learning_engine = None
    eng.last_dream_cycle = None
    eng.logger = logging.getLogger("t")
    return eng


async def _distill(env, llm):
    await _engine(env[0], llm)._distill_skills()


async def test_t11_one_candidate_one_decision_and_no_repeat(env):
    d, svc, _ = env
    await _plant(d, "a1")
    llm = FakeLLM([_draft()])
    await _distill(env, llm)
    store = SkillStore(d)
    docs = await store.list_docs(include_unapproved=True)
    assert [x.name for x in docs] == ["deploy-site"]
    v = (await store.list_versions(docs[0].id))[0]
    assert v.source == "distilled" and v.source_task == "task:a1"
    assert "task:a1" in v.examples and v.approved_at is None
    assert "step 0" in llm.calls[0] and "RAW-TOOL-OUTPUT" not in llm.calls[0]
    # inert: never offered, so the body is absent from the default prompt
    assert await candidates(_vec((0, 1.0)), store) == []
    assert len(await svc.find_pending("skill_activate")) == 1
    await _distill(env, FakeLLM([], forbid=True))  # second cycle: nothing left
    assert len(await store.list_docs(include_unapproved=True)) == 1


async def test_guest_unreviewed_short_and_failed_are_skipped(env):
    d, _, _ = env
    await _plant(d, "g1", role="guest")
    await _plant(d, "g2", reviewed=False)
    await _plant(d, "g3", steps=2)
    await _plant(d, "g4", status="failed")
    await _distill(env, FakeLLM([], forbid=True))
    assert await SkillStore(d).list_docs(include_unapproved=True) == []


async def test_near_duplicate_becomes_version_two(env):
    d, _, _ = env
    await _plant(d, "n1")
    await _plant(d, "n2")
    await _distill(env, FakeLLM([_draft(), _draft(name="publish-website", when="deploy the website")]))
    store = SkillStore(d)
    docs = await store.list_docs(include_unapproved=True)
    assert len(docs) == 1
    assert len(await store.list_versions(docs[0].id)) == 2


async def test_invalid_output_creates_nothing_and_is_not_retried(env):
    d, svc, _ = env
    await _plant(d, "i1")
    await _plant(d, "i2")
    await _plant(d, "i3")
    big = _draft(body="x" * (settings.skill_body_max_chars + 1))
    await _distill(env, FakeLLM(["not json", big]))
    await _distill(env, FakeLLM([_draft(body="  ")]))  # empty body
    assert await SkillStore(d).list_docs(include_unapproved=True) == []
    assert await svc.find_pending("skill_activate") == []
    await _distill(env, FakeLLM([], forbid=True))  # all three are logged


async def test_flag_off_makes_no_model_call(env, monkeypatch):
    d, _, _ = env
    await _plant(d, "f1")
    monkeypatch.setattr(settings, "skill_distill_enabled", False)
    eng = _engine(d, FakeLLM([], forbid=True))

    async def noop(*a, **k):
        return 0

    for name in ("_tiered_pruning", "_weave_causality", "_store_dream_report"):
        monkeypatch.setattr(eng, name, noop)
    await eng.enter_rem_sleep()
    monkeypatch.setattr(settings, "skill_distill_enabled", True)
    monkeypatch.setattr(settings, "skills_v2_enabled", False)
    await eng.enter_rem_sleep()


async def test_per_cycle_cap(env, monkeypatch):
    d, _, _ = env
    monkeypatch.setattr(settings, "skill_distill_max_per_cycle", 2)
    for i in range(3):
        await _plant(d, f"c{i}")
    llm = FakeLLM([_draft(name=f"s{i}", when=f"w{i}") for i in range(3)])
    await _distill(env, llm)
    assert len(llm.calls) == 2
    await _distill(env, llm)  # the third waits for the next cycle
    assert len(llm.calls) == 3


async def test_failing_phase_does_not_stop_later_phases(env, monkeypatch):
    d, _, _ = env
    eng = _engine(d, FakeLLM([]))
    ran = []

    async def boom():
        raise RuntimeError("boom")

    async def pruning():
        ran.append(1)
        return 0

    async def noop(*a, **k):
        return 0

    monkeypatch.setattr(eng, "_distill_skills", boom)
    monkeypatch.setattr(eng, "_tiered_pruning", pruning)
    monkeypatch.setattr(eng, "_weave_causality", noop)
    monkeypatch.setattr(eng, "_store_dream_report", noop)
    await eng.enter_rem_sleep()
    assert ran


async def test_lookback_window_uses_fake_clock(env):
    d, _, clock = env
    await _plant(d, "w1")
    clock.advance((settings.skill_distill_lookback_hours + 5) * 3600)
    await _distill(env, FakeLLM([], forbid=True))  # task is now older than the window
