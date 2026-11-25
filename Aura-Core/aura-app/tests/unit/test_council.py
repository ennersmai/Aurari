"""P2-29: the council tool. Offline: a fake plain-call client."""

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.executor.tool_registry import get_tool_registry, load_builtin_tools, reset_tool_registry
from aura.tiers import reset_tier_cache
from aura.tools import consult, council


class FakeLayers:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail: set[str] = set()
        self.gate: asyncio.Event | None = None
        self.in_flight = 0
        self.peak = 0

    async def plain_call(self, model, system, user, max_tokens, temperature):
        self.calls.append({"model": model, "system": system, "user": user})
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            if model in self.fail:
                raise RuntimeError("boom")
            return f"ANSWER-{model}"
        finally:
            self.in_flight -= 1


@pytest.fixture(autouse=True)
def _setup(monkeypatch, tmp_path):
    set_clock(FakeClock(datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)))
    reset_tier_cache()
    reset_tool_registry()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "consult_enabled", True)
    monkeypatch.setattr(settings, "council_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 2)  # Titan: 8 swift, 3 sage
    monkeypatch.setattr(settings, "sage_model2", "anthropic/sage")
    monkeypatch.setattr(settings, "swift_pool2", ["anthropic/haiku", "google/gem", "meta/llama", "qwen/q"])
    consult.begin_turn()
    yield
    set_clock(Clock())
    reset_tier_cache()
    reset_tool_registry()


@pytest.fixture
def layers(monkeypatch):
    fake = FakeLayers()
    monkeypatch.setattr(consult, "_get_layers", lambda: fake)
    return fake


def args(**kw):
    base = {"question": "Audit this design: a single shared cache.", "_requester_role": "owner"}
    base.update(kw)
    return base


def offered():
    registry = get_tool_registry()
    for record in load_builtin_tools():
        registry.register(record)
    return [r.name for r in registry.all()]


async def test_three_independent_parallel_calls(layers):
    out = await council.run(args())
    assert out["success"] is True and out["calls"] == 3
    models = [c["model"] for c in layers.calls]
    # Sage plus two pool models of two other families (the same-family haiku is skipped)
    assert models == ["anthropic/sage", "google/gem", "meta/llama"]
    assert len({m.split("/")[0] for m in models}) == 3
    assert layers.peak == 3  # in flight together
    for call in layers.calls:  # each sees only the question, never an answer
        assert "Audit this design" in call["user"]
        assert "ANSWER-" not in call["user"]
    assert len({c["user"] for c in layers.calls}) == 1


async def test_synthesis_instructions_and_parts(layers):
    out = await council.run(args())
    for part in council.SYNTHESIS_PARTS:
        assert part in out["message"]
    for model in out["models"]:
        assert f"ANSWER-{model}" in out["message"]
    good = "Where they agree: x.\nWhere they disagree and why: y.\nMy conclusion: z."
    assert council.missing_parts(good) == []
    assert council.missing_parts("Where they agree: x. My conclusion: z.") == [
        "Where they disagree and why"
    ]
    assert "—" not in council.MEMBER_SYSTEM + council.SKILL_BODY + council.SKILL_WHEN_TO_USE


async def test_raw_answers_on_trace_and_costs_within_limits(layers):
    await council.run(args())
    records = consult.turn_records()
    assert [r["tool"] for r in records] == ["council"] * 3
    assert {r["answer"] for r in records} == {"ANSWER-anthropic/sage", "ANSWER-google/gem", "ANSWER-meta/llama"}
    state = consult._state()
    assert (state.sage_used, state.swift_used) == (1, 2)
    # a second council in the same Core turn would break the limit; Titan has room for three
    out = await council.run(args())
    assert out["success"] is True and consult._state().sage_used == 2


async def test_core_limits_allow_one_council_only(layers, monkeypatch):
    monkeypatch.setattr(settings, "model_stack_index", 1)  # Core: 3 swift, 1 sage
    monkeypatch.setattr(settings, "sage_model1", "anthropic/sage")
    monkeypatch.setattr(settings, "swift_pool1", ["google/gem", "meta/llama"])
    reset_tier_cache()
    assert (await council.run(args()))["success"] is True
    before = len(layers.calls)
    out = await council.run(args())
    assert out["success"] is False and len(layers.calls) == before


async def test_prior_consult_use_counts(layers):
    consult._state().swift_used = 7  # Titan allows 8
    out = await council.run(args())
    assert out["success"] is False and layers.calls == []
    assert consult._state().swift_used == 7


async def test_one_member_failing_keeps_the_others(layers):
    layers.fail.add("google/gem")
    out = await council.run(args())
    assert out["success"] is True and "the member call failed" in out["message"]
    assert [r["ok"] for r in consult.turn_records()] == [True, False, True]


async def test_pool_without_two_other_families_refused(layers, monkeypatch):
    monkeypatch.setattr(settings, "swift_pool2", ["anthropic/haiku", "google/gem"])
    out = await council.run(args())
    assert out["success"] is False and layers.calls == []
    assert consult._state().sage_used == 0


async def test_guest_and_bad_question_refused(layers):
    assert (await council.run(args(_requester_role="guest")))["success"] is False
    assert (await council.run(args(question="  ")))["success"] is False
    assert (await council.run(args(question="x" * (settings.consult_task_max_chars + 1))))["success"] is False
    assert layers.calls == []


# --- ablation -------------------------------------------------------------


async def test_flag_off_ablation(layers, monkeypatch):
    assert "council" in offered()
    monkeypatch.setattr(settings, "council_enabled", False)
    reset_tool_registry()
    assert "council" not in offered()
    assert "consult" in offered()
    out = await council.run(args())
    assert out["success"] is False and layers.calls == []
    assert consult._state().sage_used == 0 and consult.turn_records() == []


async def test_needs_consult(layers, monkeypatch):
    monkeypatch.setattr(settings, "consult_enabled", False)
    reset_tool_registry()
    assert "council" not in offered()
    assert (await council.run(args()))["success"] is False


async def test_lean_has_no_council(layers, monkeypatch):
    monkeypatch.setattr(settings, "model_stack_index", 0)
    reset_tier_cache()
    reset_tool_registry()
    assert "council" not in offered()
    assert (await council.run(args()))["success"] is False and layers.calls == []


def test_defaults_are_off():
    from aura.config import Settings

    assert Settings.model_fields["council_enabled"].default is False
    assert Settings.model_fields["council_enabled"].validation_alias == "AURA_COUNCIL_ENABLED"
