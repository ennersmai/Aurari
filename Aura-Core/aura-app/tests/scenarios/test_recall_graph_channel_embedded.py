"""Embedded-SurrealDB test for the graph channel (card W4-03).

"where does my sister live?" matches "My sister is called Ana" by words; the
fact "Ana resides in Porto" shares only the entity Ana with it, so only the graph
channel (PPR over the ``about`` edges) reaches it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from tests.scenarios.runner import HashedBagOfWordsEmbeddings
from tests.scenarios.test_recall_entity_channel_embedded import (
    _fact,
    _learn,
    _open_db,
    _recall,
)

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_QUESTION = "where does my sister live?"

@pytest.mark.asyncio
async def test_graph_channel_reaches_fact_through_shared_entity(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    # Keep dense small so it cannot return the whole tiny database.
    monkeypatch.setattr(settings, "recall_dense_k", 1)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        ana = {"name": "Ana", "type": "person", "surface": "Ana"}
        await _learn(
            db, embeddings, "My sister is called Ana.", conversation_id="c1",
            entities=[ana],
            fact=_fact(content="My sister is called Ana.", subject="sister",
                       predicate="is called", object="Ana", about=["Ana"]),
        )
        target_ids = await _learn(
            db, embeddings, "Ana resides in Porto.", conversation_id="c2",
            entities=[ana],
            fact=_fact(content="Ana resides in Porto.", subject="Ana",
                       predicate="resides in", object="Porto", about=["Ana"]),
        )
        for i, thing in enumerate(["tea", "chess", "rain", "trains", "violins"]):
            await _learn(
                db, embeddings, f"I like {thing} a lot number {i}.",
                conversation_id=f"f{i}",
                fact=_fact(content=f"I like {thing} a lot number {i}.",
                           subject="I", predicate="like", object=thing,
                           about=[]),
            )
        target = str(target_ids[0])

        
        monkeypatch.setattr(settings, "recall_graph_channel_enabled", True)
        on = await _recall(db, "app", _QUESTION)
        by_key = {item.key: item.channel_ranks or {} for item in on.trace.items}
        assert "graph" in by_key[target]
        assert set(by_key[target]) == {"graph"}

        monkeypatch.setattr(settings, "recall_graph_channel_enabled", False)
        off = await _recall(db, "app", _QUESTION)
        assert not any(
            item.channel_ranks and "graph" in item.channel_ranks
            for item in off.trace.items
        )
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_graph_channel_never_bridges_through_unreadable_memory(monkeypatch):
    """An owner-only fact (and its app episode) linking Bob and Ana must not
    carry a guild recall from Bob's guild fact to Ana's guild fact."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(settings, "recall_dense_k", 1)
    monkeypatch.setattr(settings, "recall_graph_channel_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        bob = {"name": "Bob", "type": "person", "surface": "Bob"}
        ana = {"name": "Ana", "type": "person", "surface": "Ana"}
        guild = "guild:99/channel:7"
        await _learn(
            db, embeddings, "Bob plays the bass.", venue=guild,
            conversation_id="g1", entities=[bob],
            fact=_fact(content="Bob plays the bass.", subject="Bob",
                       predicate="plays", object="bass", about=["Bob"]),
        )
        await _learn(
            db, embeddings, "Bob is secretly dating Ana.", venue="app",
            conversation_id="a1", entities=[bob, ana],
            fact=_fact(content="Bob is secretly dating Ana.", subject="Bob",
                       predicate="dating", object="Ana", about=["Bob", "Ana"]),
        )
        target_ids = await _learn(
            db, embeddings, "Ana resides in Porto.", venue=guild,
            conversation_id="g2", entities=[ana],
            fact=_fact(content="Ana resides in Porto.", subject="Ana",
                       predicate="resides in", object="Porto", about=["Ana"]),
        )
        target = str(target_ids[0])

        packet = await _recall(db, guild, "what does Bob play?")
        graph_keys = {
            item.key
            for item in packet.trace.items
            if item.channel_ranks and "graph" in item.channel_ranks
        }
        assert target not in graph_keys

    finally:
        await db.close()
        set_clock(Clock())
