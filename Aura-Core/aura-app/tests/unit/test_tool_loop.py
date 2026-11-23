"""
Tests for the single tool loop (W2-31).

These tests run offline with a fake generate_round that pops chunk lists
from a queue and records (loop_input, round_idx).
"""

import asyncio
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.executor.tool_executor import ToolExecutor
from aura.orchestrator.tool_loop import (
    LoopEvent,
    NativeCalls,
    run_tool_loop,
    strip_tool_calls,
    build_loop_input,
    MAX_ROUNDS_SUFFIX,
    ROUND_SEPARATOR,
)


# =========================================================================
# Helpers
# =========================================================================

class _FakeToolExecutor:
    """Fake ToolExecutor for offline tests."""
    
    def __init__(self):
        self.extract_tool_calls = MagicMock(return_value=[])
        self.execute_and_feedback = AsyncMock(return_value="")
        self.called_with_role: str | None = None


async def _run_loop_collect(
    user_input: str,
    generate_round,
    tool_executor: _FakeToolExecutor,
    requester_role: str,
    max_rounds: int | None = None,
    seed_results: str | None = None,
) -> list[LoopEvent]:
    """Run the loop and collect all events."""
    events = []
    async for event in run_tool_loop(
        user_input=user_input,
        generate_round=generate_round,
        tool_executor=tool_executor,
        requester_role=requester_role,
        max_rounds=max_rounds,
        seed_results=seed_results,
    ):
        events.append(event)
    return events


def _make_generate_round(chunks_per_round: list[list[str]]):
    """Create a fake generate_round that pops from chunks_per_round."""
    recorded: list[tuple[str, int]] = []

    async def generate_round(loop_input: str, round_idx: int):
        recorded.append((loop_input, round_idx))
        chunks = chunks_per_round.pop(0) if chunks_per_round else []
        for chunk in chunks:
            yield chunk

    generate_round.recorded = recorded  # type: ignore[attr-defined]
    return generate_round


# =========================================================================
# Tests for strip_tool_calls (copied verbatim from coordinator)
# The regex doesn't handle nested braces, so test with non-nested cases.
# The regex leaves surrounding spaces, so we expect double spaces.
# =========================================================================

def test_strip_tool_calls_removes_json_blocks():
    text = 'Hello ```json {"tool": "x", "arguments": "value"} ``` world'
    assert strip_tool_calls(text) == "Hello  world"

def test_strip_tool_calls_removes_inline():
    text = 'Hello {"tool": "x", "arguments": "value"} world'
    assert strip_tool_calls(text) == "Hello  world"

def test_strip_tool_calls_cleans_whitespace():
    text = 'Hello\n\n\n{"tool": "x", "arguments": "value"}\n\n\nworld'
    assert strip_tool_calls(text) == "Hello\n\nworld"


# =========================================================================
# Tests for build_loop_input
# =========================================================================

def test_build_loop_input_no_blocks():
    assert build_loop_input("hello", []) == "hello"

def test_build_loop_input_with_blocks():
    assert build_loop_input("hello", ["[Round 1]\nR1"]) == "hello\n\n[Tool Execution Results]\n[Round 1]\nR1"

def test_build_loop_input_multiple_blocks():
    assert build_loop_input("hello", ["[Round 1]\nR1", "[Round 2]\nR2"]) == (
        "hello\n\n[Tool Execution Results]\n[Round 1]\nR1\n\n[Round 2]\nR2"
    )


# =========================================================================
# Tests for run_tool_loop
# =========================================================================

@pytest.mark.asyncio
async def test_no_tool_calls_returns_deltas_then_done():
    """No tool calls: events are the deltas then done; done.text is stripped text."""
    executor = _FakeToolExecutor()
    gen = _make_generate_round([["hello", " world"]])

    events = await _run_loop_collect("hello", gen, executor, "owner")

    # Should have deltas and done
    assert [e.kind for e in events] == ["delta", "delta", "done"]
    assert events[-1].text == "hello world"
    assert gen.recorded == [("hello", 1)]  # loop_input, round_idx


@pytest.mark.asyncio
async def test_one_tool_round_then_none():
    """One tool round then none: events delta..., separator, delta..., done."""
    executor = _FakeToolExecutor()
    executor.extract_tool_calls.side_effect = [
        [{"tool": "t", "arguments": {}}],  # round 1: has calls
        [],  # round 2: no calls
    ]
    executor.execute_and_feedback.return_value = "R1"

    gen = _make_generate_round([
        ['ok {"tool": "t", "arguments": {}}'],  # round 1
        ["final"],  # round 2
    ])

    events = await _run_loop_collect("hello", gen, executor, "owner")

    # Events: delta(round1), separator, delta(round2), done
    kinds = [e.kind for e in events]
    assert kinds == ["delta", "separator", "delta", "done"]

    # Second loop input includes tool results
    assert gen.recorded[0] == ("hello", 1)
    assert gen.recorded[1] == ("hello\n\n[Tool Execution Results]\n[Round 1]\nR1", 2)

    # Done text is stripped
    assert events[-1].text == "final"

    # execute_and_feedback awaited once with requester_role
    assert executor.execute_and_feedback.await_count == 1
    assert executor.execute_and_feedback.await_args.kwargs["requester_role"] == "owner"


@pytest.mark.asyncio
async def test_tool_calls_every_round_max_rounds():
    """Tool calls every round with max_rounds=5: 5 rounds, 4 separators, suffix."""
    executor = _FakeToolExecutor()
    executor.extract_tool_calls.return_value = [{"tool": "t", "arguments": {}}]
    executor.execute_and_feedback.return_value = "R"

    gen = _make_generate_round([
        [f'round{i} {{"tool": "t", "arguments": {{}}}}'] for i in range(1, 6)
    ])

    events = await _run_loop_collect("hello", gen, executor, "owner", max_rounds=5)

    # 5 rounds * 1 delta each + 4 separators + 1 suffix delta + 1 done = 11 events
    deltas = [e for e in events if e.kind == "delta"]
    separators = [e for e in events if e.kind == "separator"]
    done = [e for e in events if e.kind == "done"]

    assert len(deltas) == 6  # 5 rounds + suffix
    assert len(separators) == 4
    assert len(done) == 1

    # Last delta is the suffix
    assert deltas[-1].text == MAX_ROUNDS_SUFFIX
    # Done text ends with suffix
    assert events[-1].text.endswith(MAX_ROUNDS_SUFFIX)


@pytest.mark.asyncio
async def test_seed_results_first_loop_input():
    """seed_results='SEED': first loop input includes [Seed] block."""
    executor = _FakeToolExecutor()
    executor.extract_tool_calls.return_value = []
    gen = _make_generate_round([["ok"]])

    await _run_loop_collect("hello", gen, executor, "owner", seed_results="SEED")

    # First loop input should contain [Seed]
    assert gen.recorded[0][0] == "hello\n\n[Tool Execution Results]\n[Seed]\nSEED"


@pytest.mark.asyncio
async def test_execute_and_feedback_returns_empty_stops_after_round_1():
    """execute_and_feedback returns '': loop stops after round 1, no separator."""
    executor = _FakeToolExecutor()
    executor.extract_tool_calls.return_value = [{"tool": "t", "arguments": {}}]
    executor.execute_and_feedback.return_value = ""

    gen = _make_generate_round([
        ['ok {"tool": "t", "arguments": "value"}'],
    ])

    events = await _run_loop_collect("hello", gen, executor, "owner")

    # Should stop after round 1 - no separator, no second round
    kinds = [e.kind for e in events]
    assert kinds == ["delta", "done"]
    assert events[-1].text == "ok"


@pytest.mark.asyncio
async def test_round_text_with_tool_call_stripped_in_done():
    """Round text 'ok {"tool": "x", "arguments": "value"}' with no further calls: done.text == 'ok'."""
    executor = _FakeToolExecutor()
    executor.extract_tool_calls.return_value = []  # No calls in the response
    gen = _make_generate_round([['ok {"tool": "x", "arguments": "value"}']])

    events = await _run_loop_collect("hello", gen, executor, "owner")

    assert events[-1].text == "ok"


# =========================================================================
# T1/T2 through the real executor (W2-31 test requirement)
# =========================================================================

def _make_real_executor_with_fake_db():
    """Build a ToolExecutor with __new__ and fake db from test_requester_role.py."""
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.logger = __import__("logging").getLogger("aura.executor.test")
    executor._llm_layers = None

    class _FakeDB:
        async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
            return [{
                "id": "skill:test_tool",
                "name": "test_tool",
                "skill_type": "local_function",
                "execution_config": {
                    "module": "aura.tools._test_stub",
                    "function": "run",
                },
                "definition": {},
            }]

        async def merge(self, thing: str, data: dict) -> Any:
            return []

    executor.db = _FakeDB()
    return executor


def _make_test_tool_module(invoked: list[dict]) -> types.ModuleType:
    """Create a tool module that records calls and returns a string."""
    mod = types.ModuleType("aura.tools._test_stub")

    async def run(arguments: dict) -> str:
        invoked.append(dict(arguments))
        return "ok:" + str(arguments.get("x"))

    mod.run = run
    return mod


@pytest.mark.asyncio
async def test_real_executor_guest_role_refused():
    """With requester_role='guest', the fake tool is never called and results contain refusal."""
    invoked: list[dict] = []
    sys.modules["aura.tools._test_stub"] = _make_test_tool_module(invoked)
    executor = _make_real_executor_with_fake_db()

    # Call execute_and_feedback with guest role
    calls = [{"tool": "test_tool", "arguments": {"_runtime_approved": True, "force_execute": True, "x": 1}}]
    feedback = await executor.execute_and_feedback(calls, requester_role="guest")

    # Tool should never be invoked
    assert invoked == []
    # Feedback should contain refusal message
    assert "Tool use is not available to this user." in feedback
    assert "failed" in feedback.lower()


@pytest.mark.asyncio
async def test_real_executor_owner_role_executes():
    """With requester_role='owner', the tool receives exactly {'x': 1}."""
    invoked: list[dict] = []
    sys.modules["aura.tools._test_stub"] = _make_test_tool_module(invoked)
    executor = _make_real_executor_with_fake_db()

    # Call execute_and_feedback with owner role
    calls = [{"tool": "test_tool", "arguments": {"_runtime_approved": True, "force_execute": True, "x": 1}}]
    feedback = await executor.execute_and_feedback(calls, requester_role="owner")

    # Tool should be invoked with x=1 (force_execute and _runtime_approved stripped)
    assert len(invoked) == 1
    assert invoked[0] == {"x": 1, "_venue": "app", "_requester_role": "owner"}
    assert "succeeded" in feedback.lower()


# =========================================================================
# Parametrised test for owner/guest roles (from card requirement)
# =========================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "guest"])
async def test_requester_role_parametrised(role):
    """Parametrised test: execute_and_feedback awaited with requester_role."""
    executor = _FakeToolExecutor()
    executor.extract_tool_calls.side_effect = [
        [{"tool": "t", "arguments": {}}],
        [],
    ]
    executor.execute_and_feedback.return_value = "R1"

    gen = _make_generate_round([
        ['ok {"tool": "t", "arguments": {}}'],
        ["final"],
    ])

    await _run_loop_collect("hello", gen, executor, role)

    assert executor.execute_and_feedback.await_count == 1
    assert executor.execute_and_feedback.await_args.kwargs["requester_role"] == role


# =========================================================================
# Native calls (W2-37)
# =========================================================================

@pytest.mark.asyncio
async def test_native_calls_execute_without_text_extraction():
    """A round yielding NativeCalls executes them; extract_tool_calls is not called."""
    executor = _FakeToolExecutor()
    executor.execute_and_feedback.return_value = "R1"
    calls = [{"tool": "t", "arguments": {"x": 1}, "id": "c1"}]

    async def generate_round(loop_input, round_idx):
        if round_idx == 1:
            yield "thinking"
            yield NativeCalls(calls)
        else:
            yield "final"

    events = await _run_loop_collect("hello", generate_round, executor, "owner")

    # Native calls execute; extraction only ran for the final text round.
    assert [c.args[0] for c in executor.extract_tool_calls.call_args_list] == ["final"]
    executor.execute_and_feedback.assert_awaited_once()
    assert executor.execute_and_feedback.await_args.args[0] == calls
    assert [e.kind for e in events] == ["delta", "separator", "delta", "done"]
    assert events[-1].text == "final"


@pytest.mark.asyncio
async def test_native_calls_guest_role_refused_by_real_executor():
    """Native calls still reach the real executor's gate with requester_role='guest'."""
    invoked: list[dict] = []
    sys.modules["aura.tools._test_stub"] = _make_test_tool_module(invoked)
    executor = _make_real_executor_with_fake_db()
    calls = [{
        "tool": "test_tool",
        "arguments": {"_runtime_approved": True, "force_execute": True, "x": 1},
        "id": "c1",
    }]
    seen_inputs: list[str] = []

    async def generate_round(loop_input, round_idx):
        seen_inputs.append(loop_input)
        if round_idx == 1:
            yield "calling"
            yield NativeCalls(calls)
        else:
            yield "final"

    with patch.object(
        executor, "execute_and_feedback", wraps=executor.execute_and_feedback
    ) as spy:
        events = await _run_loop_collect("hello", generate_round, executor, "guest")

    # The real executor refused the guest before invoking the tool.
    assert invoked == []
    spy.assert_awaited_once()
    assert spy.await_args.kwargs["requester_role"] == "guest"
    # The refusal reached the loop as the round's feedback.
    assert "Tool use is not available to this user." in seen_inputs[1]
    assert events[-1].text == "final"