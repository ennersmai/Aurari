"""G6-03: skill correction in dreaming, on the real schema with a fake LLM and embeddings."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from surrealdb import RecordID

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.dreaming.engine import DreamingEngine
from aura.engines.learning.skill_stats import apply_outcome, record_skill_use
from aura.engines.learning.skill_store import SkillStore
from aura.executor.decisions import DecisionService, set_decision_service
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
BODY = "1. build\n2. upload\n3. verify"


def _vec(i):
    v = [0.0] * 768
    v[i] = 1.0
    return v


class FakeEmb:
    """Texts starting with 'same' share a vector; every other text is distinct."""

    async def embed(self, text):
        if text.startswith("same"):
            return _vec(3)
        if text.startswith("when-"):
            return _vec(10 + int(text.split("-")[1]))
        return _vec(100 + (sum(map(ord, text)) % 500))


class FakeLLM:
    def __init__(self, replies=(), forbid=False):
        self.replies = list(replies)
        self.calls = []
        self.forbid = forbid

    async def complete(self, messages, **kw):
        if self.forbid:
            pytest.fail("model called when it must not be")
        self.calls.append(messages[0]["content"])
        return self.replies.pop(0)


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    for flag in ("skills_v2_enabled", "skill_attribution_enabled", "skill_correction_enabled"):
        monkeypatch.setattr(settings, flag, True)
    svc = DecisionService(db=d)
    set_decision_service(svc)
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: FakeEmb())
    yield d, svc
    set_decision_service(None)  # type: ignore[arg-type]
    set_clock(Clock())
    await d.close()


async def _skill(d, name="deploy-site", n=0, pitfalls=None):
    store = SkillStore(d)
    doc = await store.create_doc(name, f"when-{n}")
    v = await store.add_version(doc.id, BODY, "distilled", tools=["bash"],
                                pitfalls=pitfalls or ["stale cache"], approved=True)
    await store.set_active(doc.id, v.version)
    return store, doc


async def _task(d, tid, ws):
    await d.query("CREATE $rid CONTENT $d", {"rid": RecordID("task", tid), "d": {
        "goal_id": RecordID("goal", "g"), "description": "x", "created": _START,
        "task_id": f"task:{tid}", "goal": "Deploy", "status": "failed", "delegated": True,
        "workspace_path": ws, "steps": [{"step_number": 0, "step_type": "tool",
                                         "title": f"step of {tid}", "result": "RAW-OUTPUT"}],
    }})


async def _count_negative(store, field, value):
    for r in extract_rows(await store.db.query(
        f"SELECT * FROM skill_use WHERE {field} = $v", {"v": value}
    )):
        await apply_outcome(store, r, "negative")


async def _neg_task(store, doc, tid, ws="C:/work/alpha"):
    await _task(store.db, tid, ws)
    await record_skill_use(store, doc.id, 1, None, f"task:{tid}", "owner")
    await _count_negative(store, "task_id", f"task:{tid}")


async def _neg_turn(store, doc, eid, text, nxt=None, source="correction_marker"):
    rows = [(eid, text, {"signal": "negative", "source": source})]
    if nxt:
        rows.append((eid + "n", nxt, {}))
    for i, (e, t, outcome) in enumerate(rows):
        await store.db.query("CREATE experience CONTENT $d", {"d": {
            "timestamp": _START + timedelta(seconds=i), "user_id": "u1",
            "task_type": "conversation", "domain": "general",
            "context": {"user_query": t}, "aura_response": {"response": "r"},
            "outcome": outcome, "emotional_state": {}, "experience_id": e,
        }})
    await record_skill_use(store, doc.id, 1, eid, None, "owner")
    await _count_negative(store, "turn_id", eid)


def _engine(db, llm):
    eng = DreamingEngine.__new__(DreamingEngine)
    eng.db = db
    eng._llm_layers = SimpleNamespace(client=llm)
    eng._learning_engine = None
    eng.last_dream_cycle = None
    eng.logger = logging.getLogger("t")
    return eng


async def _correct(d, llm):
    await _engine(d, llm)._correct_skills()


async def test_two_negatives_one_corrected_version_and_no_second_feed(env):
    d, svc = env
    store, doc = await _skill(d)
    await _neg_task(store, doc, "t1")
    await _neg_task(store, doc, "t2")
    llm = FakeLLM(["Always purge the CDN cache after upload."])
    await _correct(d, llm)
    vs = await store.list_versions(doc.id)
    assert [v.version for v in vs] == [1, 2]
    v2 = vs[1]
    assert v2.source == "corrected" and v2.body == BODY and v2.approved_at is None
    assert v2.pitfalls == ["stale cache", "workspace:alpha: Always purge the CDN cache after upload."]
    assert "skill_use:" in v2.change_note
    assert "RAW-OUTPUT" not in llm.calls[0] and "step of t1" in llm.calls[0]
    assert (await store.get_doc("deploy-site")).active_version == 1  # v1 keeps serving
    assert len(await svc.find_pending("skill_activate")) == 1
    log = extract_rows(await d.query("SELECT * FROM skill_correction_log"))
    assert len(log) == 1 and len(log[0]["use_ids"]) == 2 and log[0]["new_version"] == 2
    await _correct(d, FakeLLM(forbid=True))  # the same negatives never feed a second correction
    assert len(await store.list_versions(doc.id)) == 2
    await _neg_task(store, doc, "t3")  # one fresh negative is below the threshold
    await _correct(d, FakeLLM(forbid=True))


async def test_single_negative_without_explicit_correction_does_nothing(env):
    d, _ = env
    store, doc = await _skill(d)
    await _neg_turn(store, doc, "experience:a", "deploy it", nxt="deploy it again", source="rephrase")
    await _correct(d, FakeLLM(forbid=True))
    assert len(await store.list_versions(doc.id)) == 1


async def test_one_explicit_owner_correction_is_enough_and_unscoped(env):
    d, _ = env
    store, doc = await _skill(d)
    await _neg_turn(store, doc, "experience:a", "deploy it", nxt="no, use the staging bucket first")
    llm = FakeLLM(["Upload to the staging bucket before production."])
    await _correct(d, llm)
    assert "no, use the staging bucket first" in llm.calls[0]
    v2 = (await store.list_versions(doc.id))[1]
    assert v2.pitfalls[-1] == "Upload to the staging bucket before production."  # no workspace


async def test_workspace_lesson_stays_scoped_until_a_second_workspace_repeats_it(env):
    d, _ = env
    store, doc = await _skill(d)
    await _neg_task(store, doc, "a1", "C:/w/alpha")
    await _neg_task(store, doc, "a2", "C:/w/alpha")
    await _correct(d, FakeLLM(["same lesson about caches"]))
    v2 = (await store.list_versions(doc.id))[1]
    assert v2.pitfalls[-1] == "workspace:alpha: same lesson about caches"
    # alpha repeating it changes nothing
    await _neg_task(store, doc, "a3", "C:/w/alpha")
    await _neg_task(store, doc, "a4", "C:/w/alpha")
    await _correct(d, FakeLLM(["same lesson about caches, again"]))
    assert len(await store.list_versions(doc.id)) == 2
    await _neg_task(store, doc, "b1", "C:/w/beta")
    await _neg_task(store, doc, "b2", "C:/w/beta")
    await _correct(d, FakeLLM(["same lesson about caches (beta)"]))
    v3 = (await store.list_versions(doc.id))[2]
    assert "same lesson about caches" in v3.pitfalls
    assert not any(p.startswith("workspace:") for p in v3.pitfalls)
    assert len(v3.pitfalls) == len(v2.pitfalls)


async def test_pitfalls_never_exceed_the_cap_and_oldest_drop(env, monkeypatch):
    d, _ = env
    monkeypatch.setattr(settings, "skill_pitfalls_max", 3)
    store, doc = await _skill(d, pitfalls=["p1", "p2", "p3"])
    await _neg_task(store, doc, "c1")
    await _neg_task(store, doc, "c2")
    await _correct(d, FakeLLM(["new lesson"]))
    v2 = (await store.list_versions(doc.id))[1]
    assert v2.pitfalls == ["p2", "p3", "workspace:alpha: new lesson"]


async def test_per_cycle_cap(env, monkeypatch):
    d, _ = env
    monkeypatch.setattr(settings, "skill_correct_max_per_cycle", 2)
    skills = [await _skill(d, name=f"s{i}", n=i) for i in range(3)]
    for i, (store, doc) in enumerate(skills):
        await _neg_task(store, doc, f"x{i}a")
        await _neg_task(store, doc, f"x{i}b")
    llm = FakeLLM([f"lesson {i}" for i in range(3)])
    await _correct(d, llm)
    assert len(llm.calls) == 2
    await _correct(d, llm)
    assert len(llm.calls) == 3


async def test_flag_off_makes_no_model_call(env, monkeypatch):
    d, _ = env
    store, doc = await _skill(d)
    await _neg_task(store, doc, "f1")
    await _neg_task(store, doc, "f2")
    eng = _engine(d, FakeLLM(forbid=True))

    async def noop(*a, **k):
        return 0

    for name in ("_tiered_pruning", "_weave_causality", "_store_dream_report"):
        monkeypatch.setattr(eng, name, noop)
    monkeypatch.setattr(settings, "skill_correction_enabled", False)
    await eng.enter_rem_sleep()
    monkeypatch.setattr(settings, "skill_correction_enabled", True)
    monkeypatch.setattr(settings, "skills_v2_enabled", False)
    await eng.enter_rem_sleep()
    assert len(extract_rows(await d.query("SELECT * FROM skill_version"))) == 1


async def test_guest_negatives_are_never_candidates(env):
    d, _ = env
    store, doc = await _skill(d)
    for i in range(3):
        await record_skill_use(store, doc.id, 1, None, f"task:g{i}", "guest")
        await _count_negative(store, "task_id", f"task:g{i}")
    await _correct(d, FakeLLM(forbid=True))
