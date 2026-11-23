"""Embedded-SurrealDB tests for recall feedback (card W4-06)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.recall import engine as engine_module
from aura.engines.recall.feedback import record_feedback
from aura.engines.recall.models import ContextPacket, RecallTrace, TraceItem
from aura.orchestrator.coordinator import Orchestrator
from tests.scenarios.runner import HashedBagOfWordsEmbeddings
from tests.scenarios.test_recall_entity_channel_embedded import (
    _fact,
    _learn,
    _open_db,
    _recall,
)

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_TEXTS = [
    "My sister Ana lives in Porto.",
    "I enjoy playing chess on weekends.",
    "The violin needs new strings soon.",
]


def _packet(ids) -> ContextPacket:
    items = [
        TraceItem(block="memories", key=str(i), source="fact", rank=n, tokens=5,
                  fate="kept")
        for n, i in enumerate(ids)
    ]
    trace = RecallTrace(turn_id="t", user_id="owner", query="q",
                        created_at=_START, budget_tokens=100, tokens_before=15,
                        tokens_after=15, items=items, channel_errors={})
    return ContextPacket(stable_blocks=[], dynamic_blocks=[], abstain=False,
                         trace=trace)


async def _seed(db, embeddings) -> list:
    ids = []
    for n, text in enumerate(_TEXTS):
        ids += await _learn(
            db, embeddings, text, conversation_id=f"c{n}",
            fact=_fact(content=text, subject="s", predicate="p", object="o",
                       about=[]),
        )
    return ids


async def _facts(db) -> dict[str, dict]:
    rows = await db.query("SELECT * FROM fact")
    return {r["content"]: r for r in rows}


async def _edges(db) -> list[dict]:
    return await db.query("SELECT * FROM co_used")


@pytest.fixture
def feedback_on(monkeypatch):
    monkeypatch.setattr(settings, "recall_feedback_enabled", True)


@pytest.mark.asyncio
async def test_only_the_quoted_fact_is_used(feedback_on):
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        emb = HashedBagOfWordsEmbeddings()
        ids = await _seed(db, emb)
        await record_feedback(db, emb, _packet(ids), "Your sister Ana lives in Porto.")

        facts = await _facts(db)
        used = facts[_TEXTS[0]]
        assert used["use_count"] == 1
        assert used["last_used_at"] == _START
        assert used["unused_streak"] == 0
        for text in _TEXTS[1:]:
            assert facts[text]["unused_streak"] == 1
            assert facts[text]["use_count"] == 0
            assert facts[text].get("last_used_at") is None
        assert await _edges(db) == []
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_two_used_facts_share_one_co_used_edge(feedback_on):
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        emb = HashedBagOfWordsEmbeddings()
        ids = await _seed(db, emb)
        reply = "Ana lives in Porto and you enjoy playing chess on weekends."
        await record_feedback(db, emb, _packet(ids), reply)
        edges = await _edges(db)
        assert len(edges) == 1 and edges[0]["weight"] == 1

        await record_feedback(db, emb, _packet(ids), reply)
        edges = await _edges(db)
        assert len(edges) == 1 and edges[0]["weight"] == 2
        assert (await _facts(db))[_TEXTS[2]]["unused_streak"] == 2
    finally:
        await db.close()
        set_clock(Clock())


def _orchestrator(db) -> Orchestrator:
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("aura.orchestrator.feedback-test")
    orch.emotion_engine = SimpleNamespace(
        get_current_state=AsyncMock(return_value=SimpleNamespace())
    )
    orch._log_interaction_experience = AsyncMock()
    orch.db = db
    return orch


async def _run_chain(orch, packet, response):
    await orch._post_response_chain(
        user_input="hi", response=response, emotional_before=SimpleNamespace(),
        user_id="owner", conversation_id="c1", goal_context=None,
        learning_context=None, enable_l2=False, packet=packet,
    )


@pytest.mark.asyncio
async def test_flag_off_orchestrator_changes_nothing(monkeypatch):
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "layer_l4_enabled", False)
    db = await _open_db()
    try:
        emb = HashedBagOfWordsEmbeddings()
        ids = await _seed(db, emb)
        before = await _facts(db)
        await _run_chain(_orchestrator(db), _packet(ids), _TEXTS[0])
        assert await _facts(db) == before
        assert await _edges(db) == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_chain_calls_feedback_only_when_flag_on(monkeypatch):
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "layer_l4_enabled", False)
    calls = AsyncMock()
    monkeypatch.setattr("aura.engines.recall.feedback.record_feedback", calls)
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: "emb")
    orch = _orchestrator("db")
    packet = _packet([])

    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    await _run_chain(orch, packet, "reply")
    calls.assert_not_awaited()

    monkeypatch.setattr(settings, "recall_feedback_enabled", True)
    await _run_chain(orch, packet, "reply")
    calls.assert_awaited_once_with("db", "emb", packet, "reply")


@pytest.mark.asyncio
async def test_feedback_failure_is_only_logged(caplog):
    emb = SimpleNamespace(embed=AsyncMock(side_effect=RuntimeError("boom")))
    db = SimpleNamespace(
        query=AsyncMock(
            return_value=[{"id": "fact:a", "content": "x y", "embedding": None}]
        )
    )
    with caplog.at_level(logging.WARNING):
        await record_feedback(db, emb, _packet(["fact:a"]), "reply")
    assert "Recall feedback failed" in caplog.text


@pytest.mark.asyncio
async def test_engine_reads_unused_streak_into_rerank(monkeypatch):
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_rerank_enabled", True)
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        emb = HashedBagOfWordsEmbeddings()
        ids = await _seed(db, emb)
        for _ in range(5):
            await record_feedback(db, emb, _packet(ids[:1]), "Something else entirely")
        assert (await _facts(db))[_TEXTS[0]]["unused_streak"] == 5

        seen = []
        real = engine_module.rerank

        def spy(candidates, **kw):
            seen.extend(candidates)
            return real(candidates, **kw)

        monkeypatch.setattr(engine_module, "rerank", spy)
        await _recall(db, "app", "sister Ana Porto")
        assert {c.id: c.unused_streak for c in seen}.get(str(ids[0])) == 5
    finally:
        await db.close()
        set_clock(Clock())
