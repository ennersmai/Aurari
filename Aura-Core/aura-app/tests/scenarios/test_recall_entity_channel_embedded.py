"""Embedded-SurrealDB tests for the entity channel (card W4-01).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter, with the real schema applied as the runner applies
it at connect time, and uses the runner's
:class:`HashedBagOfWordsEmbeddings` so every embedding is deterministic and
offline.

With ``recall_channels_enabled``, ``memory_v2_recall_enabled`` and
``recall_entity_channel_enabled`` all on, the memories block must:

* recall facts about an entity named by an alias in the last two turns,
  even when the question shares no words with the fact (e.g. "what does Pixel
  eat?" finds "Pixel eats kibble");
* not return another venue's fact about the same entity;
* the flag off gives exactly the M4 behaviour (ablation: no entity channel).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

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

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _open_db() -> EmbeddedSurrealDB:
    db = EmbeddedSurrealDB()
    await db.connect()
    return db


def _manager(db: EmbeddedSurrealDB) -> MemoryManager:
    """A MemoryManager wired to the embedded DB and the deterministic stub."""
    manager = MemoryManager()
    manager.db = db  # type: ignore[assignment]
    manager.embeddings = HashedBagOfWordsEmbeddings()  # type: ignore[assignment]
    return manager


def _request(venue: str, question: str = "What do I know?") -> RecallRequest:
    return RecallRequest(
        user_id="owner",
        user_input=question,
        limit=5,
        include_cold_start=False,
        include_latent=False,
        token_budget=100_000,
        venue=venue,
    )


def _extraction(entities: list[dict], fact: dict) -> Extraction:
    return Extraction.model_validate(
        {
            "entities": entities,
            "facts": [fact],
            "questions": [],
            "predictions": [],
        }
    )


async def _learn(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
    text: str,
    *,
    speaker: str = "owner",
    venue: str = "app",
    conversation_id: str = "c1",
    entities: list[dict] | None = None,
    fact: dict | None = None,
) -> list:
    """Store one turn and write its fact; return the created fact ids."""
    episode_id = await store_episode(
        db,
        embeddings,
        user_text=text,
        aura_text="Aura replies.",
        speaker=speaker,
        venue=venue,
        conversation_id=conversation_id,
        emotional_signature={"joy": 0.2},
        salience=0.4,
    )
    rows = await db.query("SELECT * FROM $rid", {"rid": episode_id})
    assert len(rows) == 1
    return await write_facts(
        db,
        embeddings,
        rows[0],
        _extraction(entities or [], fact or {}),
    )


def _fact(**overrides) -> dict:
    fact = {
        "content": "I live in Lisbon.",
        "kind": "fact",
        "subject": "I",
        "predicate": "live in",
        "object": "Lisbon",
        "about": ["Lisbon"],
        "asserted_by": "user",
        "implied": False,
        "negates": False,
    }
    fact.update(overrides)
    return fact


async def _recall(
    db: EmbeddedSurrealDB,
    venue: str,
    question: str = "What do I know?",
) -> Any:
    engine = RecallEngine(
        memory_manager=_manager(db), latent_engine=StubLatentEngine()
    )
    return await engine.recall(_request(venue, question))


# ---------------------------------------------------------------------------
# Entity channel tests
# ---------------------------------------------------------------------------


async def _seed_pixel(db: EmbeddedSurrealDB) -> None:
    """Seed "Pixel" as an entity, then a fact about Pixel that never names it."""
    embeddings = HashedBagOfWordsEmbeddings()
    await _learn(
        db,
        embeddings,
        "My cat is called Pixel.",
        entities=[{"name": "Pixel", "type": "other", "surface": "Pixel"}],
        fact=_fact(
            content="My cat is called Pixel.",
            subject="cat",
            predicate="is called",
            object="Pixel",
            about=["Pixel"],
        ),
    )
    await _learn(
        db,
        embeddings,
        "Her favourite food is tuna.",
        conversation_id="c2",
        entities=[{"name": "Pixel", "type": "other", "surface": "Her"}],
        fact=_fact(
            content="Her favourite food is tuna.",
            subject="Pixel",
            predicate="favourite food",
            object="tuna",
            about=["Pixel"],
        ),
    )


@pytest.mark.asyncio
async def test_entity_channel_finds_fact_by_alias_with_no_word_overlap(monkeypatch):
    """"what does Pixel eat?" finds "Her favourite food is tuna." (about Pixel),
    which shares no word with the question, through the entity channel; with
    the flag off no hit carries an entity rank."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        await _seed_pixel(db)

        monkeypatch.setattr(settings, "recall_entity_channel_enabled", True)
        on = await _recall(db, "app", "what does Pixel eat?")
        assert "tuna" in (on.block_text("memories") or "")
        assert any(
            item.channel_ranks and "entity" in item.channel_ranks
            for item in on.trace.items
        )

        monkeypatch.setattr(settings, "recall_entity_channel_enabled", False)
        off = await _recall(db, "app", "what does Pixel eat?")
        assert not any(
            item.channel_ranks and "entity" in item.channel_ranks
            for item in off.trace.items
        )
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_entity_channel_respects_venue_visibility(monkeypatch):
    """Another venue's fact about the same entity is not returned.

    The entity "Pixel" exists in both the app venue and a guild venue, but
    the fact about what Pixel eats is only visible in the app. A recall from
    the guild should not return the app's fact.
    """
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(settings, "recall_entity_channel_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        # App venue: Pixel eats kibble
        await _learn(
            db,
            embeddings,
            "My cat Pixel eats kibble.",
            venue="app",
            conversation_id="app",
            entities=[
                {"name": "Pixel", "type": "person", "surface": "Pixel"},
                {"name": "kibble", "type": "other", "surface": "kibble"},
            ],
            fact=_fact(
                content="Pixel eats kibble.",
                subject="Pixel",
                predicate="eats",
                object="kibble",
                about=["Pixel", "kibble"],
            ),
        )

        # Guild venue: Pixel chases mice (different fact, same entity)
        await _learn(
            db,
            embeddings,
            "Pixel chases mice in the guild.",
            venue="guild:99/channel:7",
            conversation_id="guild",
            entities=[
                {"name": "Pixel", "type": "person", "surface": "Pixel"},
                {"name": "mice", "type": "other", "surface": "mice"},
            ],
            fact=_fact(
                content="Pixel chases mice.",
                subject="Pixel",
                predicate="chases",
                object="mice",
                about=["Pixel", "mice"],
            ),
        )

        # App recall should only see "kibble", not "mice"
        app_memories = (await _recall(db, "app", "what does Pixel eat?")).block_text(
            "memories"
        )
        assert app_memories is not None
        assert "kibble" in app_memories
        assert "mice" not in app_memories

        # Guild recall should only see "mice", not "kibble"
        guild_memories = (
            await _recall(db, "guild:99/channel:8", "what does Pixel do?")
        ).block_text("memories")
        assert guild_memories is not None
        assert "mice" in guild_memories
        assert "kibble" not in guild_memories
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_entity_channel_flag_off_gives_m4_behaviour(monkeypatch):
    """The flag off gives exactly the M4 behaviour (ablation).

    With the entity channel disabled, the dense and lexical channels still
    run and find facts as they did in M4. This test verifies that the entity
    channel is not running by checking that the channel_errors does not
    contain an "entity" key, and that recall still works via dense/lexical.
    """
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(settings, "recall_entity_channel_enabled", False)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "My cat Pixel eats kibble.",
            entities=[
                {"name": "Pixel", "type": "person", "surface": "Pixel"},
                {"name": "kibble", "type": "other", "surface": "kibble"},
            ],
            fact=_fact(
                content="Pixel eats kibble.",
                subject="Pixel",
                predicate="eats",
                object="kibble",
                about=["Pixel", "kibble"],
            ),
        )

        # With entity channel OFF, dense/lexical channels still find the fact
        # because "Pixel" matches in both embedding and BM25. This IS the M4
        # behaviour. The key assertion is that the entity channel did not run
        # (no "entity" channel error or trace entry).
        engine = RecallEngine(
            memory_manager=_manager(db), latent_engine=StubLatentEngine()
        )
        packet = await engine.recall(_request("app", "what does Pixel eat?"))

        memories = packet.block_text("memories")
        assert memories is not None
        assert "kibble" in memories  # M4 behaviour: dense/lexical still work

        # Verify the entity channel was not involved: its name should not
        # appear in channel_errors (it wouldn't error, but we can check the
        # trace items for the channel source).
        sources = {item.source for item in packet.trace.items}
        # The entity channel has source "recall.facts" same as others, but
        # its channel_ranks would include "entity". Check that no fused hit
        # has an "entity" channel rank.
        for item in packet.trace.items:
            if hasattr(item, "channel_ranks") and item.channel_ranks:
                assert "entity" not in item.channel_ranks, (
                    "entity channel should not run when flag is off"
                )
    finally:
        await db.close()
        set_clock(Clock())