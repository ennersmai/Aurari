"""W2-35: the selected tools are offered to the model.

Agency PRD 5.2 (selection), T10, 5.3. ``_turn_pipeline`` asks the tool
registry for the tools relevant to this turn and stores them on the
``TurnContext``; the loop contexts it builds carry them in
``SynthesisContext.offered_tools``, and ``_build_l3_system_prompt`` renders
one ``<tool>`` per record inside ``<available_tools>``.

The tests drive the real ``_turn_pipeline`` through the
``turn_orchestrator`` fixture, whose fake registry is exposed as
``orch._fake_tool_registry``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.executor.tool_registry import ToolRecord
from aura.llm.layers import LLMLayers


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def _collect(agen):
    out = []
    async for ev in agen:
        out.append(ev)
    return out


def _records(count: int = 8) -> list[ToolRecord]:
    return [
        ToolRecord(
            name=f"tool_{i}",
            description=f"Does thing {i}.",
            input_schema={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
            },
            transport="builtin",
            risk="read",
        )
        for i in range(count)
    ]


async def _run_turn(orch, requester_role="owner"):
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    events = await _collect(
        orch._turn_pipeline(
            "hello",
            "u1",
            None,
            stream=False,
            context_limit=None,
            enable_l2=True,
            conversation_id="c1",
            reasoning_enabled=False,
            l2_reasoning_enabled=False,
            session_id=None,
            context_mode="deep_work",
            requester_role=requester_role,
        )
    )
    await _drain()
    return events


def _first_loop_context(orch):
    return orch.llm_layers.l3_synthesis.call_args_list[0].args[0]


def _build_prompt(context) -> str:
    return LLMLayers._build_l3_system_prompt(
        MagicMock(), context, "2026-01-01 12:00:00 UTC"
    )


@pytest.mark.asyncio
async def test_t10_selected_tools_reach_the_loop_context_and_prompt(turn_orchestrator):
    orch = turn_orchestrator
    records = _records(8)
    orch._fake_tool_registry.select_tools = AsyncMock(return_value=records)

    events = await _run_turn(orch)

    # The turn completes.
    assert events[-1].kind == "done"
    assert events[-1].text == "resp"

    # The first loop context carries exactly the selected records.
    context = _first_loop_context(orch)
    assert context.offered_tools == records

    # The prompt shows all eight tools and no approval field.
    prompt = _build_prompt(context)
    assert prompt.count("<tool name=") == 8
    assert "force_execute" not in prompt
    # One call per turn.
    orch._fake_tool_registry.select_tools.assert_awaited_once()


@pytest.mark.asyncio
async def test_guest_role_is_passed_to_select_tools(turn_orchestrator):
    orch = turn_orchestrator

    await _run_turn(orch, requester_role="guest")

    orch._fake_tool_registry.select_tools.assert_awaited_once_with(
        "hello", requester_role="guest"
    )


@pytest.mark.asyncio
async def test_select_tools_failure_leaves_no_available_tools(turn_orchestrator):
    orch = turn_orchestrator
    orch._fake_tool_registry.select_tools = AsyncMock(
        side_effect=RuntimeError("registry down")
    )

    events = await _run_turn(orch)

    # The turn still completes.
    assert events[-1].kind == "done"
    assert events[-1].text == "resp"

    context = _first_loop_context(orch)
    assert context.offered_tools == []
    assert "<available_tools>" not in _build_prompt(context)