"""Embedded-SurrealDB tests for the memories block on the new channels (W3-05).

Drives the real in-memory embedded SurrealDB through the W2-01 runner's
adapter, with the real schema applied, and the runner's
:class:`HashedBagOfWordsEmbeddings` so every embedding is deterministic and
offline.

Checks, with ``settings.recall_channels_enabled`` on:

* a name that only the lexical channel can find reaches the memories block;
* the trace items for the memories block carry ``channel_ranks`` and
  ``fused_score``;
* the dense channel raising still yields the lexical results and records
  ``channel_errors["memories.dense"]``.

With the flag off, ``retrieve_for_l3_parts`` is called and neither channel is
(the ablation).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import aura.engines.recall.engine as engine_module
from aura.config import settings
from aura.engines.memory.manager import MemoryManager
from aura.engines.recall import RecallEngine, RecallRequest
from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    StubLatentEngine,
)

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


async def _create_memory(
    db: EmbeddedSurrealDB,
    content: str,
    embedding: list[float] | None,
    *,
    user_id: str = "alice",
) -> str:
    """Create one memory through the real schema and return its record id."""
    created = await db.query(
        "CREATE memory CONTENT $data",
        {
            "data": {
                "content": content,
                "timestamp": _START,
                "importance": 0.5,
                "emotional_signature": {},
                "embedding": embedding,
                "user_id": user_id,
                "deprecated": False,
            }
        },
    )
    return str(created[0]["id"])


def _manager(db: EmbeddedSurrealDB) -> MemoryManager:
    """A MemoryManager wired to the embedded DB and the deterministic stub."""
    manager = MemoryManager()
    manager.db = db  # type: ignore[assignment]
    manager.embeddings = HashedBagOfWordsEmbeddings()  # type: ignore[assignment]
    return manager


def _request() -> RecallRequest:
    return RecallRequest(
        user_id="alice",
        user_input="Who is Zephyrine?",
        limit=5,
        include_cold_start=False,
        include_latent=False,
        token_budget=100_000,
    )


async def _seed_lexical_only_name(
    db: EmbeddedSurrealDB,
) -> dict[str, str]:
    """Seed a target only the lexical channel can find.

    The target's stored embedding is unrelated to the query, so the dense
    channel (with ``recall_dense_k = 1``) returns the distractor instead.  The
    target's content still contains the name, so BM25 finds it.
    """
    embeddings = HashedBagOfWordsEmbeddings()
    target = await _create_memory(
        db,
        "My friend Zephyrine lives in Oslo",
        await embeddings.embed("winter garden tomatoes"),
    )
    distractor = await _create_memory(
        db,
        "The weather is cold today",
        await embeddings.embed("Zephyrine"),
    )
    return {"target": target, "distractor": distractor}


@pytest.mark.asyncio
async def test_lexical_only_name_reaches_memories_block(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_dense_k", 1)

    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _seed_lexical_only_name(db)
        manager = _manager(db)
        engine = RecallEngine(
            memory_manager=manager, latent_engine=StubLatentEngine()
        )

        # Prove the name is invisible to the dense channel before asking the
        # engine, so the assertion below is really about the lexical hits.
        query_embedding = await manager.embeddings.embed("Who is Zephyrine?")
        dense_hits = await engine_module.dense_channel(
            db, query_embedding, "alice", None
        )
        assert ids["target"] not in {hit.memory_id for hit in dense_hits}

        packet = await engine.recall(_request())

        memories = packet.block_text("memories")
        assert memories is not None
        assert "Zephyrine" in memories
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_trace_items_carry_channel_ranks_and_fused_score(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_dense_k", 1)

    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        await _seed_lexical_only_name(db)
        manager = _manager(db)
        engine = RecallEngine(
            memory_manager=manager, latent_engine=StubLatentEngine()
        )

        packet = await engine.recall(_request())

        items = [i for i in packet.trace.items if i.source == "recall.channels"]
        assert items, "no memories-block trace items were produced"
        for item in items:
            assert isinstance(item.channel_ranks, dict)
            assert item.channel_ranks
            assert set(item.channel_ranks) <= {"dense", "lexical"}
            assert isinstance(item.fused_score, float)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_dense_failure_still_yields_lexical_results(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("dense down")

    monkeypatch.setattr(engine_module, "dense_channel", _boom)

    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _create_memory(
            db,
            "My friend Zephyrine lives in Oslo",
            await embeddings.embed("My friend Zephyrine lives in Oslo"),
        )
        manager = _manager(db)
        engine = RecallEngine(
            memory_manager=manager, latent_engine=StubLatentEngine()
        )

        packet = await engine.recall(_request())

        memories = packet.block_text("memories")
        assert memories is not None
        assert "Zephyrine" in memories
        assert packet.trace.channel_errors["memories.dense"] == "dense down"
        assert "memories.lexical" not in packet.trace.channel_errors
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_flag_off_uses_retrieve_for_l3_parts_and_no_channels(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", False)

    calls: list[dict[str, Any]] = []

    async def _retrieve_for_l3_parts(**kwargs: Any) -> tuple[list[Any], dict]:
        calls.append(kwargs)
        return [], {}

    def _must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a channel ran with the flag off")

    monkeypatch.setattr(engine_module, "dense_channel", _must_not_run)
    monkeypatch.setattr(engine_module, "lexical_channel", _must_not_run)

    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        manager = _manager(db)
        manager.retrieve_for_l3_parts = _retrieve_for_l3_parts  # type: ignore[method-assign]
        engine = RecallEngine(
            memory_manager=manager, latent_engine=StubLatentEngine()
        )

        packet = await engine.recall(_request())

        assert len(calls) == 1
        assert calls[0]["query"] == "Who is Zephyrine?"
        assert packet.block_text("memories") is None
    finally:
        await db.close()