"""W2-22: tests for the Recall Engine's internal tool delegation.

These tests verify that the Recall Engine's ``timeline`` and ``evidence``
methods delegate to the MemoryManager unchanged, and that the orchestrator's
``execute_l2_internal_tool`` routes through the Recall Engine and formats
results identically to the pre-W2-22 behaviour.

The tests drive the real ``Orchestrator.execute_l2_internal_tool`` through the
``turn_orchestrator`` fixture (see ``tests/conftest.py``), with a fake
Recall Engine that returns scripted values. They do not change ``src/``.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.engines.recall.models import ContextPacket, RecallTrace
from tests.conftest import _TURN_FIXED_DATETIME


async def _drain() -> None:
    """Drain background tasks created by process_query's create_task calls."""
    for _ in range(5):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# Helper: build a fake RecallEngine with scripted timeline/evidence returns
# ---------------------------------------------------------------------------
def _make_fake_recall_engine(
    timeline_result: list[dict] | None = None,
    evidence_result: list[dict] | None = None,
):
    """Create a fake RecallEngine whose timeline/evidence return the given values."""
    from aura.engines.recall.engine import RecallEngine

    fake = MagicMock(spec=RecallEngine)
    fake.timeline = AsyncMock(return_value=timeline_result or [])
    fake.evidence = AsyncMock(return_value=evidence_result or [])
    # The orchestrator's _gather_turn_context also calls recall(); give it a
    # no-op default so those paths don't explode.
    fake.recall = AsyncMock(
        return_value=ContextPacket(
            stable_blocks=[],
            dynamic_blocks=[],
            abstain=False,
            trace=RecallTrace(
                turn_id="t",
                user_id="default",
                query="",
                created_at=_TURN_FIXED_DATETIME,
                budget_tokens=0,
                tokens_before=0,
                tokens_after=0,
                items=[],
                channel_errors={},
            ),
        )
    )
    return fake


# ---------------------------------------------------------------------------
# (1) traverse_timeline tool formatting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_traverse_timeline_formats_result_as_before(turn_orchestrator):
    """The traverse_timeline tool returns the same formatted string as before W2-22."""
    orch = turn_orchestrator

    # Script the fake Recall Engine's timeline return.
    fake_recall = _make_fake_recall_engine(
        timeline_result=[
            {
                "experience_id": "experience:abc123",
                "prompt": "What is the capital of France?",
                "response": "The capital of France is Paris.",
                "domain": "geography",
                "timestamp": "2026-01-01T12:00:00",
                "elapsed_ms": 150,
            },
            {
                "experience_id": "experience:def456",
                "prompt": "Tell me more about Paris.",
                "response": "Paris is the capital and most populous city of France.",
                "domain": "geography",
                "timestamp": "2026-01-01T12:05:00",
                "elapsed_ms": 200,
            },
        ]
    )
    orch._fake_recall_engine = fake_recall

    # Monkeypatch get_recall_engine to return our fake.
    import aura.engines.recall.engine as recall_module

    original_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall
    try:
        result = await orch.execute_l2_internal_tool(
            "traverse_timeline",
            {"experience_id": "experience:start", "steps": 2, "direction": "forward"},
        )
    finally:
        recall_module.get_recall_engine = original_get

    # The formatting is unchanged from the pre-W2-22 code.
    expected = (
        "[traverse_timeline] 2 events (forward from experience:start):\n"
        "  1. [2026-01-01T12:00:00] User: What is the capital of France?\n"
        "     Aura: The capital of France is Paris....\n"
        "  2. [2026-01-01T12:05:00] User: Tell me more about Paris.\n"
        "     Aura: Paris is the capital and most populous city of France...."
    )
    assert result == expected
    fake_recall.timeline.assert_awaited_once_with(
        experience_id="experience:start", steps=2, direction="forward"
    )


@pytest.mark.asyncio
async def test_traverse_timeline_empty_result_returns_no_events_string(turn_orchestrator):
    """An empty timeline returns the 'No events found' string."""
    orch = turn_orchestrator

    fake_recall = _make_fake_recall_engine(timeline_result=[])
    import aura.engines.recall.engine as recall_module

    original_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall
    try:
        result = await orch.execute_l2_internal_tool(
            "traverse_timeline",
            {"experience_id": "experience:start", "steps": 3, "direction": "backward"},
        )
    finally:
        recall_module.get_recall_engine = original_get

    assert result == "[traverse_timeline] No backward events found from experience:start."
    fake_recall.timeline.assert_awaited_once_with(
        experience_id="experience:start", steps=3, direction="backward"
    )


# ---------------------------------------------------------------------------
# (2) fetch_supporting_evidence tool formatting
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fetch_supporting_evidence_formats_result_as_before(turn_orchestrator):
    """The fetch_supporting_evidence tool returns the same formatted string as before W2-22."""
    orch = turn_orchestrator

    # Script the fake Recall Engine's evidence return.
    fake_recall = _make_fake_recall_engine(
        evidence_result=[
            {
                "content": "User said: I live in Sofia.",
                "timestamp": "2026-01-01T10:00:00",
                "importance": 0.8,
            },
            {
                "prompt": "Where do I live?",
                "response": "You live in Sofia.",
                "domain": "personal",
                "timestamp": "2026-01-01T10:05:00",
            },
        ]
    )
    import aura.engines.recall.engine as recall_module

    original_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall
    try:
        result = await orch.execute_l2_internal_tool(
            "fetch_supporting_evidence",
            {"insight_id": "insight:abc123"},
        )
    finally:
        recall_module.get_recall_engine = original_get

    # The formatting is unchanged from the pre-W2-22 code.
    expected = (
        "[fetch_supporting_evidence] 2 source(s) for insight:abc123:\n"
        "  1. [2026-01-01T10:00:00] User said: I live in Sofia.\n"
        "  2. [2026-01-01T10:05:00] Where do I live?"
    )
    assert result == expected
    fake_recall.evidence.assert_awaited_once_with(insight_id="insight:abc123")


@pytest.mark.asyncio
async def test_fetch_supporting_evidence_empty_result_returns_no_evidence_string(
    turn_orchestrator,
):
    """An empty evidence result returns the 'No evidence found' string."""
    orch = turn_orchestrator

    fake_recall = _make_fake_recall_engine(evidence_result=[])
    import aura.engines.recall.engine as recall_module

    original_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall
    try:
        result = await orch.execute_l2_internal_tool(
            "fetch_supporting_evidence",
            {"insight_id": "insight:abc123"},
        )
    finally:
        recall_module.get_recall_engine = original_get

    assert result == "[fetch_supporting_evidence] No evidence found for insight:abc123."
    fake_recall.evidence.assert_awaited_once_with(insight_id="insight:abc123")


# ---------------------------------------------------------------------------
# (3) Unknown tool name
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_tool_returns_error_string(turn_orchestrator):
    """An unknown tool name returns an error string."""
    orch = turn_orchestrator

    fake_recall = _make_fake_recall_engine()
    import aura.engines.recall.engine as recall_module

    original_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall
    try:
        result = await orch.execute_l2_internal_tool("unknown_tool", {})
    finally:
        recall_module.get_recall_engine = original_get

    assert result == "[error] Unknown internal tool: unknown_tool"
    # Neither timeline nor evidence should have been called.
    fake_recall.timeline.assert_not_awaited()
    fake_recall.evidence.assert_not_awaited()


# ---------------------------------------------------------------------------
# (4) Exception handling
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_exception_returns_error_string(turn_orchestrator):
    """An exception in the Recall Engine returns an error string."""
    orch = turn_orchestrator

    fake_recall = _make_fake_recall_engine()
    fake_recall.timeline = AsyncMock(side_effect=RuntimeError("boom"))
    import aura.engines.recall.engine as recall_module

    original_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall
    try:
        result = await orch.execute_l2_internal_tool(
            "traverse_timeline", {"experience_id": "experience:start"}
        )
    finally:
        recall_module.get_recall_engine = original_get

    assert result == "[error] Tool execution failed: boom"


# ---------------------------------------------------------------------------
# (5) Verify get_memory_manager is no longer used in execute_l2_internal_tool
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_execute_l2_internal_tool_uses_recall_engine_not_memory_manager(
    turn_orchestrator,
):
    """The execute_l2_internal_tool method uses RecallEngine, not MemoryManager."""
    orch = turn_orchestrator

    fake_recall = _make_fake_recall_engine(timeline_result=[])
    import aura.engines.recall.engine as recall_module
    import aura.engines.memory.manager as memory_module

    original_recall_get = recall_module.get_recall_engine
    recall_module.get_recall_engine = lambda: fake_recall

    # Wrap the real get_memory_manager to detect if it's called.
    original_memory_get = memory_module.get_memory_manager
    memory_manager_called = {"value": False}

    def tracking_memory_get():
        memory_manager_called["value"] = True
        return original_memory_get()

    memory_module.get_memory_manager = tracking_memory_get

    try:
        await orch.execute_l2_internal_tool(
            "traverse_timeline", {"experience_id": "experience:start"}
        )
    finally:
        recall_module.get_recall_engine = original_recall_get
        memory_module.get_memory_manager = original_memory_get

    # get_memory_manager must NOT have been called.
    assert memory_manager_called["value"] is False
    # get_recall_engine must have been called (via the fake).
    fake_recall.timeline.assert_awaited_once()