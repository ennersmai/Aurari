"""Embedded-SurrealDB tests for the temporal channel (card W4-02).

The real schema through the scenario runner's adapter, the runner's
deterministic embeddings, and a ``FakeClock`` that is moved between turns so
each fact is recorded on a known day. A hit only counts when it carries the
``temporal`` channel rank: in a small database the dense channel returns every
fact, so "the fact is in the memories block" alone proves nothing.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.manager import MemoryManager
from aura.engines.memory.v2.episodes import store_episode
from aura.engines.memory.v2.extraction import Extraction
from aura.engines.memory.v2.facts import write_facts
from aura.engines.recall import RecallEngine, RecallRequest
from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    StubLatentEngine,
)

# A Sunday afternoon.
_NOW = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(settings, "recall_temporal_channel_enabled", True)
    set_clock(FakeClock(_NOW))
    database = EmbeddedSurrealDB()
    await database.connect()
    try:
        yield database
    finally:
        await database.close()
        set_clock(Clock())


def _manager(db: EmbeddedSurrealDB) -> MemoryManager:
    manager = MemoryManager()
    manager.db = db  # type: ignore[assignment]
    manager.embeddings = HashedBagOfWordsEmbeddings()  # type: ignore[assignment]
    return manager


async def _learn_at(
    db: EmbeddedSurrealDB,
    when: datetime,
    content: str,
    *,
    subject: str,
    predicate: str,
    obj: str,
    venue: str = "app",
) -> None:
    """Record one turn and its fact with the clock set to ``when``."""
    set_clock(FakeClock(when))
    embeddings = HashedBagOfWordsEmbeddings()
    episode_id = await store_episode(
        db,
        embeddings,
        user_text=content,
        aura_text="Noted.",
        speaker="owner",
        venue=venue,
        conversation_id=f"c-{when.isoformat()}",
        emotional_signature={"joy": 0.1},
        salience=0.3,
    )
    rows = await db.query("SELECT * FROM $rid", {"rid": episode_id})
    extraction = Extraction.model_validate(
        {
            "entities": [],
            "facts": [
                {
                    "content": content,
                    "kind": "fact",
                    "subject": subject,
                    "predicate": predicate,
                    "object": obj,
                    "about": [],
                    "asserted_by": "user",
                    "implied": False,
                    "negates": False,
                }
            ],
            "questions": [],
            "predictions": [],
        }
    )
    await write_facts(db, embeddings, rows[0], extraction)
    set_clock(FakeClock(_NOW))


async def _temporal_contents(
    db: EmbeddedSurrealDB, question: str, venue: str = "app"
) -> set[str]:
    """The contents of the facts that carry a ``temporal`` channel rank."""
    engine = RecallEngine(
        memory_manager=_manager(db), latent_engine=StubLatentEngine()
    )
    packet = await engine.recall(
        RecallRequest(
            user_id="owner",
            user_input=question,
            limit=20,
            include_cold_start=False,
            include_latent=False,
            token_budget=100_000,
            venue=venue,
        )
    )
    ids = [
        item.key
        for item in packet.trace.items
        if item.channel_ranks and "temporal" in item.channel_ranks
    ]
    if not ids:
        return set()
    rows = await db.query("SELECT id, content FROM fact")
    by_id = {str(row["id"]): row["content"] for row in rows}
    return {by_id[i] for i in ids if i in by_id}


async def _seed_days(db: EmbeddedSurrealDB) -> None:
    await _learn_at(db, _NOW - timedelta(days=2), "The plumber came round.",
                    subject="plumber", predicate="came", obj="round")
    await _learn_at(db, _NOW - timedelta(days=1), "I bought a red bicycle.",
                    subject="I", predicate="bought", obj="bicycle")
    await _learn_at(db, _NOW - timedelta(hours=2), "Lunch was soup.",
                    subject="lunch", predicate="was", obj="soup")


@pytest.mark.asyncio
async def test_yesterday_returns_only_yesterdays_facts(db):
    await _seed_days(db)
    found = await _temporal_contents(db, "what did I say yesterday?")
    assert found == {"I bought a red bicycle."}


@pytest.mark.asyncio
async def test_iso_date_and_days_ago(db):
    await _seed_days(db)
    assert await _temporal_contents(db, "what happened on 2026-11-13?") == {
        "The plumber came round."
    }
    assert await _temporal_contents(db, "what happened 2 days ago?") == {
        "The plumber came round."
    }


@pytest.mark.asyncio
async def test_superseded_fact_is_found_for_its_time(db):
    """A question about a time is about the past: the superseded fact counts."""
    await _learn_at(db, _NOW - timedelta(days=1), "I live in Lisbon.",
                    subject="I", predicate="live in", obj="Lisbon")
    await _learn_at(db, _NOW - timedelta(hours=1), "I live in Porto.",
                    subject="I", predicate="live in", obj="Porto")
    superseded = await db.query(
        "SELECT content FROM fact WHERE valid_to IS NOT NONE"
    )
    assert [row["content"] for row in superseded] == ["I live in Lisbon."]
    assert await _temporal_contents(db, "where did I live yesterday?") == {
        "I live in Lisbon."
    }


@pytest.mark.asyncio
async def test_other_venue_fact_is_not_returned(db):
    await _learn_at(db, _NOW - timedelta(days=1), "The raid starts at nine.",
                    subject="raid", predicate="starts at", obj="nine",
                    venue="guild:99/channel:7")
    await _learn_at(db, _NOW - timedelta(days=1), "I bought a red bicycle.",
                    subject="I", predicate="bought", obj="bicycle")
    assert await _temporal_contents(db, "what did I say yesterday?") == {
        "I bought a red bicycle."
    }


@pytest.mark.asyncio
async def test_no_time_expression_and_ablation(db, monkeypatch):
    await _seed_days(db)
    assert await _temporal_contents(db, "tell me about bicycles") == set()
    monkeypatch.setattr(settings, "recall_temporal_channel_enabled", False)
    assert await _temporal_contents(db, "what did I say yesterday?") == set()
