"""T14: real per-turn outcome signal (card G5-03). No LLM is ever called."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aura.config import settings
from aura.engines.learning import outcomes
from aura.engines.learning.engine import LearningEngine
from aura.orchestrator.coordinator import Orchestrator

_VECTORS = {
    "what is the capital of france": [1.0, 0.0, 0.0],
    "tell me the french capital city": [0.95, 0.1, 0.0],  # cosine ~0.99, few shared words
    "how do i bake bread": [0.0, 1.0, 0.0],
    "what time is it": [0.0, 0.0, 1.0],
}


class FakeEmbeddings:
    def __init__(self):
        self.calls = 0

    async def embed(self, text):
        self.calls += 1
        return _VECTORS.get(text.lower())


class FailingLLM:
    """Any call fails the test."""

    def __getattr__(self, name):
        async def boom(*a, **k):
            pytest.fail("the outcome classifier must never call an LLM")

        return boom


class FakeLearning:
    def __init__(self):
        self.logged = []
        self.patches = []

    async def log_experience(self, data):
        eid = f"experience:{len(self.logged)}"
        self.logged.append((eid, data))
        return eid

    async def set_experience_outcome(self, eid, outcome):
        self.patches.append((eid, outcome))


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(settings, "outcome_signals_enabled", True)
    outcomes.reset_rings()
    emb = FakeEmbeddings()
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: emb)
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("t14")
    state = SimpleNamespace(
        vector=SimpleNamespace(model_dump=lambda: {}), dominant=("neutral", 0.0)
    )
    orch.emotion_engine = SimpleNamespace(get_current_state=AsyncMock(return_value=state))
    orch.learning_engine = FakeLearning()
    orch.llm_layers = SimpleNamespace(client=FailingLLM())
    orch._apply_l4_emotion_analysis = AsyncMock()
    monkeypatch.setattr(settings, "layer_l4_enabled", False)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    yield orch, emb
    outcomes.reset_rings()


async def _turn(orch, text, speaker="owner", conv="c1"):
    state = await orch.emotion_engine.get_current_state()
    await orch._post_response_chain(
        user_input=text, response="ok", emotional_before=state, user_id="owner",
        conversation_id=conv, goal_context=None, learning_context=None,
        enable_l2=False, speaker=speaker,
    )


def _patches(orch):
    return orch.learning_engine.patches


@pytest.mark.asyncio
async def test_rephrase_within_two_turns_is_negative(rig):
    orch, _ = rig
    await _turn(orch, "What is the capital of France")
    await _turn(orch, "How do I bake bread")
    await _turn(orch, "Tell me the French capital city")  # embedding rephrase of turn 1
    assert _patches(orch) == [
        ("experience:0", {"signal": "negative", "success": False, "source": "rephrase"})
    ]


@pytest.mark.asyncio
async def test_word_overlap_rephrase(rig):
    orch, _ = rig
    await _turn(orch, "what is the capital of france")
    await _turn(orch, "what is the capital of france please")
    assert [p[0] for p in _patches(orch)] == ["experience:0"]


@pytest.mark.asyncio
async def test_different_followup_stays_unknown(rig):
    orch, _ = rig
    await _turn(orch, "What is the capital of France")
    await _turn(orch, "How do I bake bread")
    assert _patches(orch) == []
    assert orch.learning_engine.logged[0][1]["outcome"] == {
        "signal": "unknown", "success": None,
    }


@pytest.mark.asyncio
async def test_rephrase_three_turns_later_does_not_patch(rig):
    orch, _ = rig
    await _turn(orch, "What is the capital of France")
    await _turn(orch, "How do I bake bread")
    await _turn(orch, "What time is it")
    await _turn(orch, "Tell me the French capital city")
    assert _patches(orch) == []


@pytest.mark.asyncio
async def test_correction_marker_marks_previous_negative(rig):
    orch, _ = rig
    await _turn(orch, "How do I bake bread")
    await _turn(orch, "  No, I wanted rye")
    assert _patches(orch) == [
        ("experience:0",
         {"signal": "negative", "success": False, "source": "correction_marker"})
    ]
    await _turn(orch, "I meant sourdough")
    assert [p[0] for p in _patches(orch)] == ["experience:0", "experience:1"]


@pytest.mark.asyncio
async def test_guest_turns_change_nothing(rig):
    orch, _ = rig
    await _turn(orch, "What is the capital of France")
    await _turn(orch, "What is the capital of France", speaker="guest")
    await _turn(orch, "No, wrong", speaker="guest")
    assert _patches(orch) == []
    assert orch.learning_engine.logged[1][1]["outcome"] == {
        "signal": "unknown", "success": None,
    }
    # a later owner rephrase patches the owner turn only, never the guest turns
    await _turn(orch, "What is the capital of France")
    assert [p[0] for p in _patches(orch)] == ["experience:0"]


@pytest.mark.asyncio
async def test_no_conversation_id_keys_by_user(rig):
    orch, _ = rig
    await _turn(orch, "How do I bake bread", conv=None)
    await _turn(orch, "wrong", conv=None)
    assert len(_patches(orch)) == 1


@pytest.mark.asyncio
async def test_flag_off_writes_success_true(rig, monkeypatch):
    orch, emb = rig
    monkeypatch.setattr(settings, "outcome_signals_enabled", False)
    await _turn(orch, "How do I bake bread")
    await _turn(orch, "No, wrong")
    assert all(d["outcome"] == {"success": True} for _, d in orch.learning_engine.logged)
    assert _patches(orch) == [] and emb.calls == 0


@pytest.mark.asyncio
async def test_explicit_feedback_overrides_and_tests_pass_is_positive():
    cur = outcomes.Turn("e2", "no, wrong")
    prev = outcomes.Turn("e1", "hello")
    assert await outcomes.classify_outcome(
        prev, cur, None, explicit_feedback="positive") == ("positive", "explicit")
    assert await outcomes.classify_outcome(
        prev, cur, None, task_tests_passed=True) == ("positive", "task_tests")
    assert (await outcomes.classify_outcome(
        prev, outcomes.Turn("e3", "ok thanks")))[0] == "unknown"


@pytest.mark.asyncio
async def test_failure_never_affects_turn(rig):
    orch, _ = rig
    orch.learning_engine.set_experience_outcome = AsyncMock(side_effect=RuntimeError("db"))
    await _turn(orch, "How do I bake bread")
    await _turn(orch, "wrong")  # must not raise


@pytest.mark.asyncio
async def test_set_experience_outcome_merges_on_real_db():
    from tests.scenarios.test_recall_entity_channel_embedded import _open_db

    db = await _open_db()
    try:
        await db.create("experience", {
            "experience_id": "experience:abc", "user_id": "owner", "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "task_type": "conversation", "domain": "general", "context": {},
            "aura_response": {}, "outcome": {"signal": "unknown", "success": None},
            "emotional_state": {}, "metadata": {},
        })
        engine = LearningEngine.__new__(LearningEngine)
        engine.db = db
        await engine.set_experience_outcome(
            "experience:abc", {"signal": "negative", "success": False, "source": "rephrase"}
        )
        rows = await db.query("SELECT outcome FROM experience")
        assert rows[0]["outcome"] == {
            "signal": "negative", "success": False, "source": "rephrase"}
    finally:
        await db.close()
