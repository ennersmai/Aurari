"""P2-05: L4 appraisal starts at turn start, in parallel, with a deadline.

Drives the real ``_turn_pipeline`` through the ``turn_orchestrator`` fixture with
``_appraise_message`` replaced by a gated fake, and the real post-response chain.
"""

import asyncio
import types
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.config import settings
from aura.models.emotion import EmotionState, EmotionVector


def _state(label: str) -> EmotionState:
    return EmotionState(
        timestamp=datetime(2026, 1, 1, 12, 0, 0),
        vector=EmotionVector(),
        dominant=(label, 0.5),
        description=label,
    )


@pytest.fixture
def orch(turn_orchestrator, monkeypatch):
    from aura.orchestrator.coordinator import Orchestrator

    o = turn_orchestrator
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    monkeypatch.setattr(settings, "layer_l4_enabled", True)
    monkeypatch.setattr(settings, "appraisal_parallel_enabled", True)
    monkeypatch.setattr(settings, "appraisal_turn_deadline_ms", 50)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)

    o.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    o.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    o.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    o._log_interaction_experience = AsyncMock()
    o._post_response_chain = types.MethodType(Orchestrator._post_response_chain, o)

    o.state = {"current": _state("old")}
    o.emotion_engine.get_current_state = AsyncMock(side_effect=lambda: o.state["current"])
    o.appraise_calls = []
    o.gate = asyncio.Event()
    o.mode = "fast"  # "fast": apply at once, "slow": wait for the gate

    async def fake_appraise(user_input, conversation_history, venue, speaker):
        o.appraise_calls.append((user_input, conversation_history, venue, speaker))
        if o.mode == "slow":
            await o.gate.wait()
        o.state["current"] = _state("new")

    o._appraise_message = fake_appraise
    yield o


async def _settle():
    """Await every task the turn left behind (post-response chain, appraisal)."""
    for _ in range(3):
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        if not pending:
            return
        await asyncio.wait(pending, timeout=2)


def _prompt_states(o):
    return [c.args[0].emotional_state.description for c in o.llm_layers.l3_synthesis.await_args_list]


def _timing(o):
    return [
        c.args[2]["appraisal"]
        for c in o._publish_trace.call_args_list
        if c.args[:2] == ("L4", "appraisal_timing")
    ]


async def _turn(o, text="hello", **kw):
    return await o.process_query(text, "u1", [{"role": "user", "content": "x"}],
                                 deep_analysis_enabled=False, **kw)


@pytest.mark.asyncio
async def test_done_in_time_gives_this_turn_the_new_state(orch):
    await _turn(orch)
    await _settle()
    assert _prompt_states(orch) == ["new"]
    assert _timing(orch) == ["this_turn"]
    assert len(orch.appraise_calls) == 1
    assert orch.appraise_calls[0] == ("hello", [{"role": "user", "content": "x"}], "app", "owner")


@pytest.mark.asyncio
async def test_slow_appraisal_does_not_delay_turn_and_applies_after(orch):
    orch.mode = "slow"
    # The gate is never opened inside the deadline: the turn must still finish.
    reply = await asyncio.wait_for(_turn(orch), timeout=1.0)
    assert reply == "resp"
    assert _prompt_states(orch) == ["old"]
    assert _timing(orch) == ["next_turn"]
    assert orch.state["current"].description == "old"  # not applied yet, not cancelled
    assert len(orch.appraise_calls) == 1
    orch.gate.set()
    await _settle()
    assert orch.state["current"].description == "new"
    assert len(orch.appraise_calls) == 1  # applied once, chain did not repeat it
    # next turn sees it
    orch.mode = "fast"
    await _turn(orch)
    await _settle()
    assert _prompt_states(orch)[-1] == "new"


@pytest.mark.asyncio
async def test_exactly_one_call_per_message_flag_on_and_off(orch, monkeypatch):
    await _turn(orch)
    await _settle()
    assert len(orch.appraise_calls) == 1
    orch.mode = "slow"
    orch.gate.set()
    await _turn(orch, "again")
    await _settle()
    assert len(orch.appraise_calls) == 2
    monkeypatch.setattr(settings, "appraisal_parallel_enabled", False)
    await _turn(orch, "third")
    await _settle()
    assert len(orch.appraise_calls) == 3


@pytest.mark.asyncio
async def test_flag_off_ablation_appraises_in_chain_only(orch, monkeypatch):
    monkeypatch.setattr(settings, "appraisal_parallel_enabled", False)
    seen_before_gen = []
    orig = orch.llm_layers.l3_synthesis

    async def synth(ctx, **kw):
        seen_before_gen.append(len(orch.appraise_calls))
        return "resp"

    orch.llm_layers.l3_synthesis = synth
    await _turn(orch)
    await _settle()
    assert seen_before_gen == [0]  # not started before generation
    assert len(orch.appraise_calls) == 1
    assert _timing(orch) == []
    assert not getattr(orch, "_appraisal_tasks", None)


@pytest.mark.asyncio
async def test_other_gates_off_means_no_parallel_task(orch, monkeypatch):
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", False)
    orch._apply_l4_emotion_analysis = AsyncMock()
    await _turn(orch)
    await _settle()
    assert orch.appraise_calls == []
    assert _timing(orch) == []
    orch._apply_l4_emotion_analysis.assert_awaited_once()  # legacy path unchanged


@pytest.mark.asyncio
async def test_teaching_early_return_leaves_no_appraisal(orch):
    orch.mode = "slow"
    orch._classify_intent = AsyncMock(return_value=({}, "CHAT", "taught"))
    reply = await _turn(orch)
    await _settle()
    assert reply == "taught"
    assert len(orch.appraise_calls) <= 1  # cancelled, possibly before its first step
    assert orch.state["current"].description == "old"
    assert not orch._appraisal_tasks


@pytest.mark.asyncio
async def test_pre_intent_return_never_starts_appraisal(orch):
    orch._pre_intent_reply = AsyncMock(return_value="sleeping")
    assert await _turn(orch) == "sleeping"
    await _settle()
    assert orch.appraise_calls == []


@pytest.mark.asyncio
async def test_exception_in_task_is_logged_not_raised_and_ref_released(orch):
    async def boom(**kw):
        raise RuntimeError("x")

    orch._appraise_message = lambda **kw: boom(**kw)
    assert await _turn(orch) == "resp"
    await _settle()
    assert not orch._appraisal_tasks


@pytest.mark.asyncio
async def test_engine_lock_serialises_appraise():
    from aura.engines.emotion.engine import EmotionEngine
    from aura.models.emotion import EmotionPhysicsConfig

    eng = EmotionEngine(config=EmotionPhysicsConfig())
    active = 0
    peak = 0

    async def fake(event):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1

    eng._appraise_unlocked = fake
    await asyncio.gather(eng.appraise(None), eng.appraise(None), eng.appraise(None))
    assert peak == 1
