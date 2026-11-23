"""G5-04: skill attribution and per-version statistics (embedded SurrealDB, real schema)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from surrealdb import RecordID

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.learning import outcomes
from aura.engines.learning.skill_stats import (
    apply_outcome,
    beta_params,
    mastery,
    record_skill_use,
)
from aura.engines.learning.skill_store import SkillStore
from aura.orchestrator.coordinator import Orchestrator
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "skills_v2_enabled", True)
    monkeypatch.setattr(settings, "skill_attribution_enabled", True)
    monkeypatch.setattr("aura.engines.learning.skill_store.get_db_client", lambda: d)
    yield d
    set_clock(Clock())
    await d.close()


async def _skill(db, name="skill-a", versions=2):
    store = SkillStore(db)
    doc = await store.create_doc(name, "use when testing")
    for _ in range(versions):
        await store.add_version(doc.id, "body", "taught", approved=True)
    await store.set_active(doc.id, versions)
    return store, doc


async def _stats(store, doc, v):
    ver = await store.get_version(doc.id, v)
    return ver.attempts, ver.successes, ver.practice_attempts, ver.practice_successes


async def _use(store, doc, role="owner", practice=False, turn="experience:0", task=None, v=2):
    return await record_skill_use(
        store, doc.id, v, turn, task, role, tools=["bash"], fact_ids=[], practice=practice
    )


async def test_negative_then_positive_counts_on_version(db):
    store, doc = await _skill(db)
    u1 = await _use(store, doc)
    assert await apply_outcome(store, u1, "negative") is True
    assert await _stats(store, doc, 2) == (1, 0, 0, 0)
    assert await _stats(store, doc, 1) == (0, 0, 0, 0)
    u2 = await _use(store, doc, turn="experience:1")
    assert await apply_outcome(store, u2, "positive") is True
    assert await _stats(store, doc, 2) == (2, 1, 0, 0)
    q = "SELECT * FROM skill_use WHERE turn_id = 'experience:0'"
    row = extract_rows(await db.query(q))[0]
    assert row["counted"] is True and row["outcome"] == "negative" and row["tools"] == ["bash"]


async def test_unknown_adds_nothing_and_can_still_count_later(db):
    store, doc = await _skill(db)
    u = await _use(store, doc)
    assert await apply_outcome(store, u, "unknown") is False
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)
    assert await apply_outcome(store, u, "negative") is True
    assert await _stats(store, doc, 2) == (1, 0, 0, 0)


async def test_second_patch_does_not_double_count(db):
    store, doc = await _skill(db)
    u = await _use(store, doc)
    assert await apply_outcome(store, u, "positive") is True
    assert await apply_outcome(store, u, "positive") is False
    assert await apply_outcome(store, u, "negative") is False
    assert await _stats(store, doc, 2) == (1, 1, 0, 0)


async def test_concurrent_claims_count_once(db):
    store, doc = await _skill(db)
    u = await _use(store, doc)
    results = await asyncio.gather(*[apply_outcome(store, u, "positive") for _ in range(5)])
    assert sum(results) == 1
    assert await _stats(store, doc, 2) == (1, 1, 0, 0)


async def test_guest_use_recorded_not_counted(db):
    store, doc = await _skill(db)
    u = await _use(store, doc, role="guest")
    assert u is not None
    assert await apply_outcome(store, u, "positive") is False
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)
    row = extract_rows(await db.query("SELECT * FROM skill_use"))[0]
    assert row["requester_role"] == "guest" and row["counted"] is False


async def test_practice_goes_to_practice_fields_only(db):
    store, doc = await _skill(db)
    u = await _use(store, doc, practice=True)
    assert await apply_outcome(store, u, "positive") is True
    assert await _stats(store, doc, 2) == (0, 0, 1, 1)


async def test_flag_off_writes_no_skill_use(db, monkeypatch):
    store, doc = await _skill(db)
    monkeypatch.setattr(settings, "skill_attribution_enabled", False)
    assert await _use(store, doc) is None
    assert extract_rows(await db.query("SELECT * FROM skill_use")) == []
    monkeypatch.setattr(settings, "skill_attribution_enabled", True)
    monkeypatch.setattr(settings, "skills_v2_enabled", False)
    assert await _use(store, doc) is None
    assert extract_rows(await db.query("SELECT * FROM skill_use")) == []


def test_mastery_lower_bound_orders_by_evidence():
    assert beta_params(2, 2) == (3, 1)
    assert beta_params(10, 4) == (5, 7)
    m2, lb2 = mastery(2, 2)
    m200, lb200 = mastery(200, 200)
    assert lb2 < lb200 < 1.0
    assert m2 < m200
    assert lb2 == pytest.approx(0.2 ** (1 / 3), rel=1e-3)  # Beta(3,1) cdf = x^3


def test_mastery_numpy_fallback_matches_closed_form(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_scipy(name, *a, **k):
        if name.startswith("scipy"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_scipy)
    _, lb = mastery(2, 2)
    assert lb == pytest.approx(0.2 ** (1 / 3), abs=1e-3)
    assert mastery(2, 2) == mastery(2, 2)  # deterministic


async def test_inferred_facts_updated_others_untouched(db):
    store, doc = await _skill(db)

    def mk(i, prov):
        return {
            "content": f"c{i}", "kind": "fact", "provenance": prov, "visibility": "private",
            "confidence": 0.5, "recorded_at": _START, "use_count": 2,
        }

    await db.query("CREATE $r CONTENT $d", {"r": RecordID("fact", "inf"), "d": mk(1, "inferred")})
    await db.query("CREATE $r CONTENT $d", {"r": RecordID("fact", "obs"), "d": mk(2, "observed")})
    u = await record_skill_use(
        store, doc.id, 2, "experience:0", None, "owner", fact_ids=["fact:inf", "fact:obs"]
    )
    await apply_outcome(store, u, "negative")
    rows = {r["content"]: r["confidence"] for r in extract_rows(await db.query("SELECT * FROM fact"))}
    assert rows["c1"] == pytest.approx((1.0 + 0 + 1) / (3 + 2))  # smoothed_confidence(1.0, 3)
    assert rows["c2"] == 0.5


# -- turn path ------------------------------------------------------------


class _FakeEmb:
    async def embed(self, text):
        vecs = {"what is the capital of france": [1.0, 0.0], "how do i bake bread": [0.0, 1.0]}
        return vecs.get(text.lower())


class _FakeLearning:
    def __init__(self):
        self.n = 0
        self.patches = []

    async def log_experience(self, data):
        self.n += 1
        return f"experience:{self.n - 1}"

    async def set_experience_outcome(self, eid, outcome):
        self.patches.append((eid, outcome))


class _NoLLM:
    def __getattr__(self, name):
        async def boom(*a, **k):
            pytest.fail("no model call on the reply path")

        return boom


@pytest.fixture
def orch(db, monkeypatch):
    monkeypatch.setattr(settings, "outcome_signals_enabled", True)
    monkeypatch.setattr(settings, "layer_l4_enabled", False)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    outcomes.reset_rings()
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: _FakeEmb())
    o = Orchestrator.__new__(Orchestrator)
    o.logger = logging.getLogger("g504")
    state = SimpleNamespace(vector=SimpleNamespace(model_dump=lambda: {}), dominant=("n", 0.0))
    o.emotion_engine = SimpleNamespace(get_current_state=AsyncMock(return_value=state))
    o.learning_engine = _FakeLearning()
    o.llm_layers = SimpleNamespace(client=_NoLLM())
    o.db = db
    yield o
    outcomes.reset_rings()


async def _turn(o, text, speaker="owner", chosen=None, tools=None):
    state = await o.emotion_engine.get_current_state()
    extra = {"chosen_skills": chosen, "turn_tools": tools} if chosen else {}
    await o._post_response_chain(
        user_input=text, response="ok", emotional_before=state, user_id="owner",
        conversation_id="c1", goal_context=None, learning_context=None, enable_l2=False,
        speaker=speaker, **extra,
    )


async def test_turn_uses_counted_when_next_turn_rephrases(db, orch):
    store, doc = await _skill(db)
    await _turn(orch, "What is the capital of France", chosen=[("skill-a", 2)], tools=["bash"])
    uses = extract_rows(await db.query("SELECT * FROM skill_use"))
    assert len(uses) == 1 and uses[0]["turn_id"] == "experience:0" and uses[0]["tools"] == ["bash"]
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)  # no outcome yet
    await _turn(orch, "What is the capital of France please")  # rephrase -> negative
    assert await _stats(store, doc, 2) == (1, 0, 0, 0)
    await _turn(orch, "No, I meant Paris")  # patches turn 2 (no uses): nothing more
    assert await _stats(store, doc, 2) == (1, 0, 0, 0)


async def test_turn_unknown_follow_up_counts_nothing(db, orch):
    store, doc = await _skill(db)
    await _turn(orch, "What is the capital of France", chosen=[("skill-a", 2)])
    await _turn(orch, "How do I bake bread")
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)


async def test_guest_turn_use_recorded_not_counted(db, orch):
    store, doc = await _skill(db)
    await _turn(orch, "What is the capital of France", speaker="guest", chosen=[("skill-a", 2)])
    row = extract_rows(await db.query("SELECT * FROM skill_use"))[0]
    assert row["requester_role"] == "guest"
    await apply_outcome(store, row, "negative")
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)


async def test_turn_flag_off_writes_no_skill_use(db, orch, monkeypatch):
    await _skill(db)
    monkeypatch.setattr(settings, "skill_attribution_enabled", False)
    await _turn(orch, "What is the capital of France", chosen=[("skill-a", 2)])
    assert extract_rows(await db.query("SELECT * FROM skill_use")) == []


# -- delegation -----------------------------------------------------------


class _FakeOpenCode:
    def __init__(self, files, review_summary):
        self.files, self.review = files, review_summary

    async def result(self, session_id):
        if session_id == "review":
            return MagicMock(summary=self.review, files_changed=[], additions=0, deletions=0)
        return MagicMock(summary="Done", files_changed=self.files, additions=3, deletions=1)

    async def create_session(self, workspace, agent, title):
        return "review"

    async def send(self, session_id, prompt):
        pass

    async def events(self, session_id):
        yield SimpleNamespace(kind="succeeded", data={})


async def _run_delegation(db, monkeypatch, files, review, requester_role="owner"):
    from aura.executor import delegation

    store, doc = await _skill(db)

    def ws(self):
        return Path("/fake/workspace")

    monkeypatch.setattr(delegation.DelegationRunner, "_resolve_workspace_path", ws)
    tq = MagicMock()
    tq.db = MagicMock()
    tq.db.merge = AsyncMock()
    tq.fail_task = AsyncMock()
    runner = delegation.DelegationRunner(delegation.DelegationConfig(
        goal="g", workspace="test", agent="aura-build", success_criteria="c",
        tokens=1000, minutes=1, skill="body", skill_ref=(doc.id, 2),
        requester_role=requester_role,
    ))
    runner._client = _FakeOpenCode(files, review)
    runner._session_id = "main"
    runner._task = SimpleNamespace(task_id="task:t1")
    await runner._record_skill_use("task:t1")
    await runner._handle_session_success(tq, "task:t1")
    return store, doc


async def test_delegation_review_pass_counts_positive(db, monkeypatch):
    store, doc = await _run_delegation(db, monkeypatch, ["a.py"], "VERDICT: PASS")
    assert await _stats(store, doc, 2) == (1, 1, 0, 0)
    row = extract_rows(await db.query("SELECT * FROM skill_use WHERE task_id = 'task:t1'"))[0]
    assert row["counted"] is True and row["requester_role"] == "owner"


async def test_delegation_review_fail_counts_negative(db, monkeypatch):
    store, doc = await _run_delegation(db, monkeypatch, ["a.py"], "VERDICT: FAIL: broken")
    assert await _stats(store, doc, 2) == (1, 0, 0, 0)


async def test_delegation_needs_owner_counts_nothing(db, monkeypatch):
    store, doc = await _run_delegation(db, monkeypatch, ["a.py"], "no verdict here")
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)


async def test_delegation_no_files_no_review_counts_nothing(db, monkeypatch):
    store, doc = await _run_delegation(db, monkeypatch, [], "x")
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)


async def test_delegation_guest_requester_never_counts(db, monkeypatch):
    store, doc = await _run_delegation(db, monkeypatch, ["a.py"], "VERDICT: PASS", "guest")
    assert await _stats(store, doc, 2) == (0, 0, 0, 0)
    assert len(extract_rows(await db.query("SELECT * FROM skill_use"))) == 1


async def test_delegate_tool_resolves_live_version(db, monkeypatch):
    from aura.executor import delegation
    from aura.tools import delegate

    store, doc = await _skill(db)
    await store.add_version(doc.id, "UNAPPROVED BODY", "taught")  # v3, not live
    monkeypatch.setattr(settings, "delegation_enabled", True)
    seen = {}

    async def fake_start(**kw):
        seen.update(kw)
        return "task:x"

    monkeypatch.setattr(delegation, "start_delegation", fake_start)
    args = {"goal": "g", "workspace": "w", "agent": "aura-build", "success_criteria": "c",
            "skill": "skill-a", "_requester_role": "owner"}
    res = await delegate.run(args)
    assert res["success"] is True
    assert seen["skill_ref"] == (doc.id, 2) and seen["skill"] == "body"
    assert seen["requester_role"] == "owner"
    bad = await delegate.run({**args, "skill": "nope"})
    assert bad["success"] is False
