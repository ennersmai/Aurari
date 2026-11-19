"""Embedded-SurrealDB tests for recall over memory v2 facts (card W3-17).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter and deterministic embedding stub, with both
memory schema files applied exactly as the app applies them at boot. Facts are
written through ``write_facts`` so their provenance, confidence and visibility
are the ones the app produces.

With ``recall_channels_enabled`` and ``memory_v2_recall_enabled`` both on, the
memories block must:

* recall an app fact in the app and nowhere else (not a guild, not a guest DM);
* recall a guild fact in that guild and nowhere else;
* recall a guest DM fact only in that DM;
* never recall a superseded fact;
* render one ``<fact age="<n>d" provenance="<p>" confidence="<c>">`` line per
  fact, with the age from ``recorded_at`` and the clock.

With only ``recall_channels_enabled`` on, the memory-table path still runs (the
ablation).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

import aura.engines.recall.engine as engine_module
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
# Visibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_visibility_filters_facts_by_venue(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "I live in Lisbon.",
            entities=[{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            fact=_fact(),
        )
        await _learn(
            db,
            embeddings,
            "Guild Alpha's mascot is a fox.",
            venue="guild:99/channel:7",
            conversation_id="guild",
            entities=[{"name": "fox", "type": "other", "surface": "fox"}],
            fact=_fact(
                content="Guild Alpha's mascot is a fox.",
                subject="Guild Alpha's mascot",
                predicate="is",
                object="fox",
                about=["fox"],
            ),
        )
        await _learn(
            db,
            embeddings,
            "My bicycle is blue.",
            speaker="discord_42",
            venue="dm:discord_42",
            conversation_id="dm",
            entities=[
                {"name": "bicycle", "type": "other", "surface": "my bicycle"}
            ],
            fact=_fact(
                content="My bicycle is blue.",
                subject="my bicycle",
                predicate="is",
                object="blue",
                about=["bicycle"],
            ),
        )

        # The app sees the owner fact and neither the guild nor the DM fact.
        app_memories = (await _recall(db, "app")).block_text("memories")
        assert app_memories is not None
        assert "Lisbon" in app_memories
        assert "mascot" not in app_memories
        assert "bicycle" not in app_memories

        # The guild sees its own fact only.
        guild_memories = (
            await _recall(db, "guild:99/channel:8")
        ).block_text("memories")
        assert guild_memories is not None
        assert "mascot" in guild_memories
        assert "Lisbon" not in guild_memories
        assert "bicycle" not in guild_memories

        # A guest DM sees its own fact only.
        dm_memories = (
            await _recall(db, "dm:discord_42")
        ).block_text("memories")
        assert dm_memories is not None
        assert "bicycle" in dm_memories
        assert "Lisbon" not in dm_memories
        assert "mascot" not in dm_memories
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_app_fact_is_not_recalled_in_a_guild_or_a_guest_dm(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "I live in Lisbon.",
            entities=[{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            fact=_fact(),
        )

        assert (await _recall(db, "app")).block_text("memories") is not None
        assert (await _recall(db, "guild:1/channel:2")).block_text(
            "memories"
        ) is None
        assert (await _recall(db, "dm:discord_42")).block_text("memories") is None
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_guild_fact_is_recalled_in_that_guild_only(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "Guild Alpha's mascot is a fox.",
            venue="guild:99/channel:7",
            entities=[{"name": "fox", "type": "other", "surface": "fox"}],
            fact=_fact(
                content="Guild Alpha's mascot is a fox.",
                subject="Guild Alpha's mascot",
                predicate="is",
                object="fox",
                about=["fox"],
            ),
        )

        assert (await _recall(db, "guild:99/channel:8")).block_text(
            "memories"
        ) is not None
        assert (await _recall(db, "guild:100/channel:8")).block_text(
            "memories"
        ) is None
        assert (await _recall(db, "app")).block_text("memories") is None
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_guest_dm_fact_is_recalled_only_in_that_dm(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "My bicycle is blue.",
            speaker="discord_42",
            venue="dm:discord_42",
            conversation_id="dm",
            entities=[
                {"name": "bicycle", "type": "other", "surface": "my bicycle"}
            ],
            fact=_fact(
                content="My bicycle is blue.",
                subject="my bicycle",
                predicate="is",
                object="blue",
                about=["bicycle"],
            ),
        )

        assert (await _recall(db, "dm:discord_42")).block_text(
            "memories"
        ) is not None
        assert (await _recall(db, "dm:discord_99")).block_text("memories") is None
        assert (await _recall(db, "app")).block_text("memories") is None
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Superseded facts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_superseded_fact_is_never_recalled(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "I live in Lisbon.",
            entities=[{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            fact=_fact(),
        )

        clock.advance(3600)
        await _learn(
            db,
            embeddings,
            "I moved to Porto.",
            conversation_id="c2",
            entities=[{"name": "Porto", "type": "place", "surface": "Porto"}],
            fact=_fact(
                content="I moved to Porto.",
                object="Porto",
                about=["Porto"],
            ),
        )

        stored = await db.query(
            "SELECT * FROM fact WHERE valid_to IS NONE ORDER BY recorded_at ASC"
        )
        assert [row["object"] for row in stored] == ["Porto"]

        memories = (await _recall(db, "app", "Where do I live?")).block_text(
            "memories"
        )
        assert memories is not None
        assert "Porto" in memories
        assert "Lisbon" not in memories
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rendered_fact_line_carries_age_provenance_and_confidence(
    monkeypatch,
):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _learn(
            db,
            embeddings,
            "I live in Lisbon.",
            entities=[{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            fact=_fact(),
        )

        clock.advance(timedelta(days=3).total_seconds())
        memories = (await _recall(db, "app", "Where do I live?")).block_text(
            "memories"
        )

        assert memories is not None
        assert memories.startswith("<memories>")
        assert memories.rstrip().endswith("</memories>")
        assert (
            '<fact age="3d" provenance="observed" confidence="0.80">'
            "I live in Lisbon.</fact>"
        ) in memories
        assert memories.count("<fact ") == 1
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Ablation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v2_flag_off_runs_the_memory_table_path(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", False)

    def _must_not_run(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a fact channel ran with the v2 recall flag off")

    monkeypatch.setattr(engine_module, "fact_dense_channel", _must_not_run)
    monkeypatch.setattr(engine_module, "fact_lexical_channel", _must_not_run)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        content = "My friend Zephyrine lives in Oslo"
        await db.query(
            "CREATE memory CONTENT $data",
            {
                "data": {
                    "content": content,
                    "timestamp": _START,
                    "importance": 0.5,
                    "emotional_signature": {},
                    "embedding": await embeddings.embed(content),
                    "user_id": "owner",
                    "deprecated": False,
                }
            },
        )
        engine = RecallEngine(
            memory_manager=_manager(db), latent_engine=StubLatentEngine()
        )

        packet = await engine.recall(_request("app", "Who is Zephyrine?"))

        memories = packet.block_text("memories")
        assert memories is not None
        assert "Zephyrine" in memories
        # The trace items name the memory-table channel source, not the fact
        # source, so the ablation is visible in the packet too.
        sources = {item.source for item in packet.trace.items}
        assert "recall.channels" in sources
        assert "recall.facts" not in sources
    finally:
        await db.close()
        set_clock(Clock())