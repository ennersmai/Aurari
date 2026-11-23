"""G5-05 (T11): skill index, selection and default context (embedded SurrealDB, real schema)."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.learning.skill_index import (
    SkillCandidate,
    candidates,
    choose_skill,
    load_body,
    render_index,
    select_for_turn,
)
from aura.engines.learning.skill_proposals import propose_skill
from aura.engines.learning.skill_store import SkillStore
from aura.executor.decisions import DecisionService, set_decision_service
from aura.llm.layers import LLMLayers, SynthesisContext
from aura.models.learning import SkillDoc, SkillVersion
from aura.orchestrator.coordinator import Orchestrator, TurnContext
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
# Output of the builder before G5-05 for SynthesisContext("hi", prompt_notes=["a note"]).
_GOLDEN = (2167, "09d5fe885b4326c34fa000b1e9c551fdf40abbec1d80502e39a50b4fb58bcbf7")


def _vec(*pairs: tuple[int, float]) -> list[float]:
    v = [0.0] * 768
    for i, x in pairs:
        v[i] = x
    return v


class FakeEmb:
    def __init__(self, table=None):
        self.table = table or {}
        self.calls = 0

    async def embed(self, text: str):
        self.calls += 1
        return self.table.get(text)


class FailLLM:
    """Any use fails the test: selection must never call a model."""

    def __getattr__(self, name):
        raise AssertionError(f"LLM touched: {name}")


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "skills_v2_enabled", True)
    monkeypatch.setattr(settings, "skill_selection_enabled", True)
    monkeypatch.setattr("aura.engines.learning.skill_store.get_db_client", lambda: d)
    set_decision_service(DecisionService(db=d))
    yield SkillStore(d), d
    set_decision_service(None)  # type: ignore[arg-type]
    set_clock(Clock())
    await d.close()


async def _skill(store, name, when, vec, body="BODY", tools=None, approved=True, activate=True):
    doc = await store.create_doc(name, when, when_embedding=vec)
    await store.add_version(doc.id, body, "taught", tools=tools, approved=approved)
    if approved and activate:
        await store.set_active(doc.id, 1)
    return doc


def _prompt(**kw) -> str:
    layers = LLMLayers.__new__(LLMLayers)
    return layers._build_l3_system_prompt(SynthesisContext(user_input="hi", **kw), "T", None)


async def _select(store, text="q", role="owner", vec=None, **kw):
    return await select_for_turn(
        store, text, role, random.Random(1), request_embedding=vec or _vec((0, 1.0)), **kw
    )


async def test_proposed_candidate_links_task_and_body_stays_out_until_approved(env):
    store, d = env
    emb = FakeEmb({"ship the site": _vec((0, 1.0))})
    doc, v1, _ = await propose_skill(
        store, emb, {"name": "deploy", "when_to_use": "ship the site", "body": "SECRET-STEPS"},
        "distilled", "task:42",
    )
    assert v1.examples == ["task:42"]
    res = await _select(store)
    assert res.stubs == [] and res.chosen is None
    assert "SECRET-STEPS" not in _prompt(skill_index=res.index_text, skill_body=res.body)
    await store.approve(doc.id, 1, "owner")
    res = await _select(store)
    assert res.chosen == (doc.id, 1) and res.chosen_name == "deploy"
    prompt = _prompt(skill_index=res.index_text, skill_body=res.body, skill_name=res.chosen_name)
    assert prompt.count("SECRET-STEPS") == 1


async def test_fifty_skills_index_has_one_liners_and_no_body(env):
    store, _ = env
    for i in range(50):
        await _skill(store, f"skill-{i:02d}", f"when number {i}", _vec((0, 1.0), (1, i / 100)),
                     body=f"PROCEDURE-{i}")
    res = await _select(store)
    assert len(res.stubs) == 50
    text = render_index(res.stubs)
    assert len(text.splitlines()) == 50 and "skill-07: when number 7" in text
    prompt = _prompt(skill_index=text)
    assert "PROCEDURE-" not in prompt and prompt.count("when number") == 50
    # Only the chosen skill's body is added.
    prompt = _prompt(skill_index=text, skill_body=res.body, skill_name=res.chosen_name)
    assert prompt.count("PROCEDURE-") == 1


def _cand(active_stats, prev_stats, sim=0.9):
    doc = SkillDoc(id="skill_doc:x", name="x", when_to_use="w", active_version=2, previous_version=1)
    v1 = SkillVersion(skill=doc.id, version=1, body="old", source="taught",
                      attempts=prev_stats[0], successes=prev_stats[1])
    v2 = SkillVersion(skill=doc.id, version=2, body="new", source="taught",
                      attempts=active_stats[0], successes=active_stats[1])
    return SkillCandidate(doc, sim, {1: v1, 2: v2})


def test_sampler_prefers_proven_but_still_tries_fresh_version():
    rng = random.Random(7)
    cand = _cand((0, 0), (30, 28))
    wins = {1: 0, 2: 0}
    for _ in range(1000):
        _, arm = choose_skill([cand], rng)
        wins[arm.version] += 1
    assert wins[1] > 700 and wins[2] > 20


def test_sampler_trial_ends_after_enough_attempts(monkeypatch):
    monkeypatch.setattr(settings, "skill_trial_attempts", 10)
    cand = _cand((10, 9), (30, 28))
    rng = random.Random(3)
    assert {choose_skill([cand], rng)[1].version for _ in range(200)} == {2}


def test_proven_skill_beats_unproven_across_docs():
    good, fresh = _cand((50, 48), (0, 0)), _cand((0, 0), (0, 0))
    good.doc = good.doc.model_copy(update={"name": "good", "previous_version": None})
    fresh.doc = fresh.doc.model_copy(update={"name": "fresh", "previous_version": None})
    rng = random.Random(11)
    names = [choose_skill([good, fresh], rng)[0].doc.name for _ in range(1000)]
    assert names.count("good") > 800 and names.count("fresh") > 0


async def test_below_floor_returns_none_but_index_still_lists(env):
    store, _ = env
    await _skill(store, "pasta", "cook pasta", _vec((5, 1.0)))
    res = await _select(store, vec=_vec((0, 1.0)))
    assert res.chosen is None and res.body == ""
    assert [s.name for s in res.stubs] == ["pasta"]
    res = await _select(store, vec=_vec((5, 1.0)))
    assert res.chosen is not None


async def test_unapproved_and_rejected_versions_are_never_selected(env):
    store, _ = env
    await _skill(store, "unapproved", "u", _vec((0, 1.0)), approved=False)
    rej = await _skill(store, "rejected", "r", _vec((0, 1.0)))
    await store.reject(rej.id, 1)
    res = await _select(store)
    assert res.chosen is None and res.stubs == []
    assert await load_body("rejected", 1, store) == ""
    assert await load_body("unapproved", 1, store) == ""


async def test_rolled_back_version_is_never_an_arm(env):
    store, _ = env
    doc = await _skill(store, "s", "w", _vec((0, 1.0)), body="V1")
    await store.add_version(doc.id, "V2", "corrected", approved=True)
    await store.set_active(doc.id, 2)
    await store.reject(doc.id, 2)
    await store.set_active(doc.id, 1)  # rollback: V1 active, V2 rejected
    for seed in range(20):
        res = await select_for_turn(store, "q", "owner", random.Random(seed),
                                    request_embedding=_vec((0, 1.0)))
        assert res.body == "V1"
    cands = await candidates(_vec((0, 1.0)), store)
    assert set(cands[0].versions) == {1}


async def test_retired_skill_not_offered(env):
    store, _ = env
    doc = await _skill(store, "old", "w", _vec((0, 1.0)))
    await store.set_state(doc.id, "retired")
    res = await _select(store)
    assert res.stubs == [] and res.chosen is None


async def test_guest_turn_gets_no_skill_text(env):
    store, _ = env
    await _skill(store, "a", "w", _vec((0, 1.0)))
    emb = FakeEmb({"q": _vec((0, 1.0))})
    res = await select_for_turn(store, "q", "guest", random.Random(1), embed=emb.embed)
    assert res.stubs == [] and res.body == "" and res.chosen is None and emb.calls == 0
    res = await select_for_turn(store, "q", "trusted", random.Random(1), embed=emb.embed)
    assert res.stubs == [] and res.body == ""


async def test_guest_origin_skill_selectable_only_after_owner_approval(env):
    store, _ = env
    emb = FakeEmb({"w": _vec((0, 1.0))})
    doc, _, _ = await propose_skill(
        store, emb, {"name": "g", "when_to_use": "w", "body": "GUESTBODY"}, "distilled",
        origin_speaker="guest",
    )
    assert (await _select(store)).chosen is None
    await store.approve(doc.id, 1, "owner")
    assert (await _select(store)).body == "GUESTBODY"


async def test_tool_filter_skips_skill_needing_disallowed_tool(env):
    store, _ = env
    await _skill(store, "needs-bash", "w", _vec((0, 1.0)), tools=["bash"])
    await _skill(store, "plain", "w2", _vec((0, 1.0), (1, 0.05)), tools=["read_file"])
    res = await _select(store, tool_allowed=lambda t: t != "bash")
    assert res.chosen_name == "plain" and [s.name for s in res.stubs] == ["plain"]
    res = await _select(store, tool_allowed=lambda t: False)
    assert res.chosen is None and res.stubs == []


async def test_embedding_timeout_falls_back_to_no_skill(env, monkeypatch):
    store, _ = env
    await _skill(store, "a", "w", _vec((0, 1.0)))
    monkeypatch.setattr(settings, "skill_embed_timeout_ms", 20)

    async def slow(_text):
        await asyncio.sleep(1)
        return _vec((0, 1.0))

    res = await select_for_turn(store, "q", "owner", random.Random(1), embed=slow)
    assert res.chosen is None and res.stubs == []

    async def boom(_text):
        raise RuntimeError("down")

    res = await select_for_turn(store, "q", "owner", random.Random(1), embed=boom)
    assert res.chosen is None


async def test_reachable_embedding_is_reused_without_embed_call(env):
    store, _ = env
    await _skill(store, "a", "w", _vec((0, 1.0)))
    emb = FakeEmb({"q": _vec((0, 1.0))})
    res = await select_for_turn(store, "q", "owner", random.Random(1),
                                request_embedding=_vec((0, 1.0)), embed=emb.embed)
    assert res.chosen is not None and emb.calls == 0


async def test_flag_off_selects_nothing_and_prompt_is_byte_identical(env, monkeypatch):
    store, _ = env
    await _skill(store, "a", "w", _vec((0, 1.0)))
    emb = FakeEmb({"q": _vec((0, 1.0))})
    for flag in ("skill_selection_enabled", "skills_v2_enabled"):
        monkeypatch.setattr(settings, flag, False)
        res = await select_for_turn(store, "q", "owner", random.Random(1), embed=emb.embed)
        assert res.stubs == [] and res.chosen is None
        monkeypatch.setattr(settings, flag, True)
    assert emb.calls == 0
    layers = LLMLayers.__new__(LLMLayers)
    out = layers._build_l3_system_prompt(
        SynthesisContext(user_input="hi", prompt_notes=["a note"], venue="app"), "T", None
    )
    assert (len(out), hashlib.sha256(out.encode()).hexdigest()) == _GOLDEN
    assert "<skills>" not in out


async def test_orchestrator_hook_fills_context_and_applies_session_allowlist(env, monkeypatch):
    store, d = env
    await _skill(store, "needs-bash", "w", _vec((0, 1.0)), tools=["bash"], body="BASHBODY")
    await _skill(store, "safe", "w2", _vec((0, 1.0), (1, 0.05)), tools=["read_file"], body="SAFEBODY")
    emb = FakeEmb({"do it": _vec((0, 1.0))})
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: emb)
    me = SimpleNamespace(db=d, logger=logging.getLogger("t"), llm_layers=FailLLM())

    def ctx(session):
        return SimpleNamespace(
            session=session, chosen_skills=[], skill_index=None, skill_body=None, skill_name=None,
            synthesis_context=SynthesisContext(user_input="do it"),
        )

    sub = SimpleNamespace(is_tool_allowed=lambda n: (n == "read_file", ""))
    c = ctx(sub)
    await Orchestrator._select_skills(me, c, "do it", "owner", None)
    assert c.skill_body == "SAFEBODY" and c.skill_name == "safe"
    assert c.chosen_skills[0][1] == 1 and "needs-bash" not in c.skill_index
    assert c.synthesis_context.skill_body == "SAFEBODY"

    c = ctx(None)  # main session
    await Orchestrator._select_skills(me, c, "do it", "owner", None)
    assert c.skill_body in ("BASHBODY", "SAFEBODY") and "needs-bash" in c.skill_index

    c = ctx(None)
    await Orchestrator._select_skills(me, c, "do it", "guest", None)
    assert c.skill_index is None and c.chosen_skills == []
    assert TurnContext.__dataclass_fields__["skill_body"].default is None
