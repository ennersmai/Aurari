"""Tests for the Recall Engine trace API routes (W2-23)."""

import dataclasses
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from aura.api.routes.recall import get_recall_trace, list_recall_traces
from aura.engines.recall.models import ContextPacket, RecallTrace, TraceItem, Block, BlockKind


def make_trace(turn_id: str, created_at: datetime | None = None) -> RecallTrace:
    """Create a sample RecallTrace for testing."""
    if created_at is None:
        created_at = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    return RecallTrace(
        turn_id=turn_id,
        user_id="test_user",
        query="test query",
        created_at=created_at,
        budget_tokens=3000,
        tokens_before=2500,
        tokens_after=2000,
        items=[
            TraceItem(
                block="memories",
                key="memory:abc",
                source="memory.retrieve_for_l3",
                rank=0,
                tokens=500,
                fate="kept",
            ),
            TraceItem(
                block="insights",
                key="insight:1",
                source="learning.get_learning_context",
                rank=0,
                tokens=300,
                fate="duplicate",
                duplicate_of="cold_start:cold_insight:0",
            ),
        ],
        channel_errors={},
    )


@pytest.mark.asyncio
async def test_get_recall_trace_found():
    """Test getting a trace that exists."""
    trace = make_trace("turn_123")

    fake_engine = MagicMock()
    fake_engine.get_trace = MagicMock(return_value=trace)

    with patch("aura.api.routes.recall.get_recall_engine", return_value=fake_engine):
        result = await get_recall_trace("turn_123")

    assert result["turn_id"] == "turn_123"
    assert result["user_id"] == "test_user"
    assert result["query"] == "test query"
    assert result["created_at"] == "2026-01-01T12:00:00+00:00"
    assert result["budget_tokens"] == 3000
    assert result["tokens_before"] == 2500
    assert result["tokens_after"] == 2000
    assert len(result["items"]) == 2
    assert result["items"][0]["block"] == "memories"
    assert result["items"][0]["fate"] == "kept"
    assert result["items"][1]["fate"] == "duplicate"
    assert result["items"][1]["duplicate_of"] == "cold_start:cold_insight:0"
    assert result["channel_errors"] == {}


@pytest.mark.asyncio
async def test_get_recall_trace_not_found():
    """Test getting a trace that doesn't exist (returns 404)."""
    fake_engine = MagicMock()
    fake_engine.get_trace = MagicMock(return_value=None)

    with patch("aura.api.routes.recall.get_recall_engine", return_value=fake_engine):
        with pytest.raises(HTTPException) as exc_info:
            await get_recall_trace("nonexistent")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "trace not found"


@pytest.mark.asyncio
async def test_list_recall_traces_order():
    """Test that traces are listed newest first."""
    trace1 = make_trace("turn_1", datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    trace2 = make_trace("turn_2", datetime(2026, 1, 1, 12, 1, 0, tzinfo=timezone.utc))
    trace3 = make_trace("turn_3", datetime(2026, 1, 1, 12, 2, 0, tzinfo=timezone.utc))

    fake_engine = MagicMock()
    # _traces is an OrderedDict with oldest first
    fake_engine._traces = {
        "turn_1": trace1,
        "turn_2": trace2,
        "turn_3": trace3,
    }

    with patch("aura.api.routes.recall.get_recall_engine", return_value=fake_engine):
        result = await list_recall_traces()

    # Should be newest first (reverse of insertion order)
    assert result == {"turn_ids": ["turn_3", "turn_2", "turn_1"]}


@pytest.mark.asyncio
async def test_list_recall_traces_empty():
    """Test listing traces when none exist."""
    fake_engine = MagicMock()
    fake_engine._traces = {}

    with patch("aura.api.routes.recall.get_recall_engine", return_value=fake_engine):
        result = await list_recall_traces()

    assert result == {"turn_ids": []}