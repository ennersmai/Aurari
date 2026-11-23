"""P2-41: tool loop ended by budgets and lack of progress, not a round count."""

import itertools
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.config import settings
from aura.orchestrator import tool_loop
from aura.orchestrator.tool_loop import (
    BUDGET_NOTE,
    BUDGET_NOTE_TITAN,
    MAX_ROUNDS_SUFFIX,
    NativeCalls,
    RoundUsage,
    run_tool_loop,
)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeExecutor:
    def __init__(self, results=None):
        self.extract_tool_calls = MagicMock(return_value=[])
        self.results = results  # callable(calls) -> str
        self.execute_and_feedback = AsyncMock(side_effect=self._exec)

    async def _exec(self, calls, requester_role, venue):
        return self.results(calls) if self.results else "ok"


def make_rounds(call_for_round, *, cost=0.0, clock=None, seconds_per_round=0.0, final_text="wrapped up"):
    """Round fn: native calls from call_for_round(idx) (None -> final answer)."""
    log = {"inputs": [], "final_inputs": []}

    async def gen(loop_input, idx):
        log["inputs"].append(loop_input)
        if clock is not None:
            clock.t += seconds_per_round
        call = call_for_round(idx)
        if call is None:
            yield "done"
            return
        yield f"r{idx}"
        yield NativeCalls([call])
        if cost:
            yield RoundUsage(cost)

    async def final(loop_input, idx):
        log["final_inputs"].append(loop_input)
        yield final_text

    return gen, final, log


async def collect(**kw):
    kw.setdefault("user_input", "hi")
    kw.setdefault("requester_role", "owner")
    return [e async for e in run_tool_loop(**kw)]


@pytest.fixture(autouse=True)
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "tool_loop_budgets_enabled", True)
    monkeypatch.setattr(tool_loop, "_cost_unreported_logged", False)


def unique(i):
    return {"tool": "t", "arguments": {"n": i}}


def unique_results(calls):
    return f"result {calls[0]['arguments'].get('n')}"


def fresh_results():
    counter = itertools.count()
    return lambda calls: f"res{next(counter)}"


@pytest.mark.asyncio
async def test_15_rounds_complete_within_budget():
    clock = Clock()
    gen, final, log = make_rounds(lambda i: unique(i) if i <= 15 else None, clock=clock, seconds_per_round=1)
    events = await collect(generate_round=gen, generate_final=final,
                           tool_executor=FakeExecutor(unique_results),
                           turn_budget_seconds=120, turn_budget_usd=0.2, monotonic=clock)
    done = events[-1]
    assert done.kind == "done" and done.text == "done"
    assert done.stats["rounds"] == 16 and done.stats["stop_reason"] is None
    assert log["final_inputs"] == []


@pytest.mark.asyncio
async def test_time_budget_stops_and_writes_final_message():
    clock = Clock()
    gen, final, log = make_rounds(lambda i: unique(i), clock=clock, seconds_per_round=20)
    events = await collect(generate_round=gen, generate_final=final,
                           tool_executor=FakeExecutor(unique_results),
                           turn_budget_seconds=45, turn_budget_usd=1.0, monotonic=clock)
    done = events[-1]
    assert done.stats["stop_reason"] == "time"
    assert done.stats["rounds"] == 3 and done.stats["elapsed_seconds"] == 60.0
    assert done.text == "wrapped up"
    assert "time budget" in log["final_inputs"][0]


@pytest.mark.asyncio
async def test_cost_budget_stops():
    gen, final, log = make_rounds(lambda i: unique(i), cost=0.04)
    events = await collect(generate_round=gen, generate_final=final,
                           tool_executor=FakeExecutor(unique_results),
                           turn_budget_seconds=1000, turn_budget_usd=0.10)
    done = events[-1]
    assert done.stats["stop_reason"] == "cost"
    assert done.stats["rounds"] == 3 and done.stats["cost_usd"] == pytest.approx(0.12)
    assert done.text == "wrapped up"


@pytest.mark.asyncio
async def test_no_progress_same_call_three_times():
    gen, final, _ = make_rounds(lambda i: {"tool": "t", "arguments": {"b": 1}})
    events = await collect(generate_round=gen, generate_final=final, tool_executor=FakeExecutor(fresh_results()))
    assert events[-1].stats["stop_reason"] == "no_progress:repeat_call"
    assert events[-1].stats["rounds"] == 3


@pytest.mark.asyncio
async def test_no_progress_arguments_normalised_by_key_order():
    calls = [{"tool": "t", "arguments": {"a": 1, "b": 2}}, {"tool": "t", "arguments": {"b": 2, "a": 1}},
             {"tool": "t", "arguments": {"a": 1, "b": 2}}]
    gen, final, _ = make_rounds(lambda i: calls[(i - 1) % 3])
    events = await collect(generate_round=gen, generate_final=final, tool_executor=FakeExecutor(fresh_results()))
    assert events[-1].stats["stop_reason"] == "no_progress:repeat_call"


@pytest.mark.asyncio
async def test_no_progress_three_failures_in_a_row():
    gen, final, _ = make_rounds(lambda i: unique(i))
    ex = FakeExecutor(lambda calls: f"❌ Tool t failed: boom {calls[0]['arguments']['n']}")
    events = await collect(generate_round=gen, generate_final=final, tool_executor=ex)
    assert events[-1].stats["stop_reason"] == "no_progress:consecutive_failures"
    assert events[-1].stats["rounds"] == 3


@pytest.mark.asyncio
async def test_failure_streak_resets_on_success():
    def results(calls):
        n = calls[0]["arguments"]["n"]
        return f"ok {n}" if n % 3 == 0 else f"❌ Tool t failed: {n}"
    gen, final, _ = make_rounds(lambda i: unique(i) if i <= 8 else None)
    events = await collect(generate_round=gen, generate_final=final, tool_executor=FakeExecutor(results))
    assert events[-1].stats["stop_reason"] is None


@pytest.mark.asyncio
async def test_no_progress_three_rounds_of_repeated_results():
    # round 1 result is new, rounds 2-4 repeat it (three in a row equal to earlier ones)
    gen, final, _ = make_rounds(lambda i: unique(i))
    events = await collect(generate_round=gen, generate_final=final, tool_executor=FakeExecutor(lambda c: "same"))
    assert events[-1].stats["stop_reason"] == "no_progress:repeated_results"
    assert events[-1].stats["rounds"] == 4


@pytest.mark.asyncio
async def test_safety_breaker_logs_incident(caplog):
    gen, final, _ = make_rounds(lambda i: unique(i))
    with caplog.at_level(logging.ERROR, logger="aura.orchestrator.tool_loop"):
        events = await collect(generate_round=gen, generate_final=final,
                               tool_executor=FakeExecutor(unique_results), max_rounds=6,
                               turn_budget_seconds=10**6, turn_budget_usd=0.0)
    assert events[-1].stats["stop_reason"] == "safety_breaker"
    assert events[-1].stats["rounds"] == 6
    assert any(r.levelno == logging.ERROR and "INCIDENT" in r.getMessage() for r in caplog.records)
    assert events[-1].text == "wrapped up"


@pytest.mark.asyncio
async def test_default_breaker_is_safety_setting(monkeypatch):
    monkeypatch.setattr(settings, "tool_loop_safety_rounds", 4)
    gen, final, _ = make_rounds(lambda i: unique(i))
    events = await collect(generate_round=gen, generate_final=final,
                           tool_executor=FakeExecutor(unique_results),
                           turn_budget_seconds=10**6, turn_budget_usd=0.0)
    assert events[-1].stats["stop_reason"] == "safety_breaker" and events[-1].stats["rounds"] == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("titan", [False, True])
async def test_budget_note_once(titan):
    clock = Clock()
    gen, final, log = make_rounds(lambda i: unique(i) if i <= 11 else None, clock=clock, seconds_per_round=10)
    await collect(generate_round=gen, generate_final=final, tool_executor=FakeExecutor(unique_results),
                  turn_budget_seconds=100, turn_budget_usd=1.0, monotonic=clock, allow_task_graph=titan)
    expected = BUDGET_NOTE_TITAN if titan else BUDGET_NOTE
    with_note = [i for i in log["inputs"] if expected in i]
    assert len(with_note) == 1
    assert log["inputs"].index(with_note[0]) == 8  # first input after 80s elapsed
    assert ("plan_task" in with_note[0]) is titan
    assert sum(BUDGET_NOTE[:30] in i for i in log["inputs"]) == 1


@pytest.mark.asyncio
async def test_budget_note_on_cost():
    gen, final, log = make_rounds(lambda i: unique(i) if i <= 4 else None, cost=0.09)
    await collect(generate_round=gen, generate_final=final, tool_executor=FakeExecutor(unique_results),
                  turn_budget_seconds=1000, turn_budget_usd=0.10)
    assert sum(BUDGET_NOTE in i for i in log["inputs"]) == 1


@pytest.mark.asyncio
async def test_no_max_rounds_suffix_anywhere_when_flag_on():
    gen, final, _ = make_rounds(lambda i: unique(i))
    events = await collect(generate_round=gen, generate_final=final,
                           tool_executor=FakeExecutor(lambda c: "same"), max_rounds=3)
    assert events[-1].stats["stop_reason"] is not None
    assert all(MAX_ROUNDS_SUFFIX not in e.text for e in events)
    assert "Stopped after max tool rounds" not in "".join(e.text for e in events)


@pytest.mark.asyncio
async def test_final_call_counts_toward_neither_budget():
    clock = Clock()
    gen, _final, log = make_rounds(lambda i: unique(i), clock=clock, seconds_per_round=50)

    async def slow_final(loop_input, idx):
        clock.t += 500
        yield RoundUsage(5.0)
        yield "bye"

    events = await collect(generate_round=gen, generate_final=slow_final,
                           tool_executor=FakeExecutor(unique_results),
                           turn_budget_seconds=60, turn_budget_usd=0.2, monotonic=clock)
    assert events[-1].stats["elapsed_seconds"] == 100.0 and events[-1].stats["cost_usd"] == 0.0
    assert events[-1].text == "bye"


@pytest.mark.asyncio
async def test_flag_off_ablation_keeps_max_rounds_behaviour(monkeypatch):
    monkeypatch.setattr(settings, "tool_loop_budgets_enabled", False)
    gen, final, log = make_rounds(lambda i: unique(i))
    events = await collect(generate_round=gen, generate_final=final,
                           tool_executor=FakeExecutor(unique_results), max_rounds=5,
                           turn_budget_seconds=1, turn_budget_usd=0.0)
    deltas = [e for e in events if e.kind == "delta"]
    assert len(deltas) == 6  # 5 round texts + suffix
    assert deltas[-1].text == MAX_ROUNDS_SUFFIX
    assert events[-1].text.endswith(MAX_ROUNDS_SUFFIX)
    assert events[-1].stats is None and log["final_inputs"] == []


def test_max_rounds_alias_feeds_breaker(monkeypatch):
    from aura.config import Settings
    monkeypatch.setenv("AURA_TOOL_LOOP_MAX_ROUNDS", "7")
    monkeypatch.delenv("AURA_TOOL_LOOP_SAFETY_ROUNDS", raising=False)
    assert Settings().tool_loop_safety_rounds == 7
    monkeypatch.setenv("AURA_TOOL_LOOP_SAFETY_ROUNDS", "12")
    assert Settings().tool_loop_safety_rounds == 12
    monkeypatch.delenv("AURA_TOOL_LOOP_MAX_ROUNDS")
    monkeypatch.delenv("AURA_TOOL_LOOP_SAFETY_ROUNDS")
    assert Settings().tool_loop_safety_rounds == 40


def test_openrouter_usage_cost_parsing():
    from aura.llm.provider import _usage_cost
    assert _usage_cost({"usage": {"cost": 0.0123}}) == 0.0123
    assert _usage_cost({"usage": {}}) == 0.0
    assert _usage_cost({}) == 0.0
    assert _usage_cost({"usage": {"cost": "x"}}) == 0.0
