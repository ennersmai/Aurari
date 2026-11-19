"""Embedded-SurrealDB tests for memory v2 episode storage (card W3-12).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter and deterministic embedding stub, with both
memory schema files applied exactly as the app applies them at boot. They
cover the two pieces of ``aura.engines.memory.v2.episodes``:

* ``ensure_person`` upserts one ``entity:<key>`` person record and reuses it.
* ``store_episode`` appends one episode per turn, chains episodes in the same
  ``(venue, conversation_id)`` with ``next``, and marks gate-skipped turns
  ephemeral.

The last two tests drive ``Orchestrator._post_response_chain`` to pin the
flag-off ablation and the "a failing embed never affects the turn" rule.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import ensure_person, store_episode
from aura.models.emotion import EmotionState, EmotionVector
from aura.orchestrator.coordinator import Orchestrator
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _open_db() -> EmbeddedSurrealDB:
    db = EmbeddedSurrealDB()
    await db.connect()
    return db


async def _episodes(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM episode ORDER BY recorded_at ASC")


async def _next_relations(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM next")


async def _store(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
    *,
    user_text: str,
    aura_text: str = "Aura replies.",
    speaker: str = "owner",
    venue: str = "app",
    conversation_id: str | None = "c1",
    salience: float = 0.4,
):
    return await store_episode(
        db,
        embeddings,
        user_text=user_text,
        aura_text=aura_text,
        speaker=speaker,
        venue=venue,
        conversation_id=conversation_id,
        emotional_signature={"joy": 0.2},
        salience=salience,
    )


# ---------------------------------------------------------------------------
# next chains
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_two_turns_in_one_venue_create_two_episodes_linked_by_next():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        first = await _store(db, embeddings, user_text="hello")
        clock.advance(60)
        second = await _store(db, embeddings, user_text="how are you?")

        episodes = await _episodes(db)
        assert [row["id"] for row in episodes] == [first, second]

        relations = await _next_relations(db)
        assert len(relations) == 1
        assert relations[0]["in"] == first
        assert relations[0]["out"] == second
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_a_turn_in_another_venue_starts_a_new_chain():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        first = await _store(db, embeddings, user_text="hello")
        clock.advance(60)
        second = await _store(db, embeddings, user_text="app follow-up")
        clock.advance(60)
        third = await _store(
            db,
            embeddings,
            user_text="guild hello",
            venue="guild:1/channel:2",
        )
        clock.advance(60)
        fourth = await _store(
            db,
            embeddings,
            user_text="guild follow-up",
            venue="guild:1/channel:2",
        )

        relations = await _next_relations(db)
        pairs = {(row["in"], row["out"]) for row in relations}
        assert pairs == {(first, second), (third, fourth)}
        assert (second, third) not in pairs
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# ephemeral turns
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_thanks_is_stored_ephemeral():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        thanks = await _store(db, embeddings, user_text="thanks!")
        clock.advance(60)
        question = await _store(db, embeddings, user_text="what is my cat called?")

        rows = {row["id"]: row for row in await _episodes(db)}
        assert rows[thanks]["ephemeral"] is True
        assert rows[question]["ephemeral"] is False
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# speaker entities
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_speaker_entity_exists_and_is_reused_across_turns():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        first = await _store(db, embeddings, user_text="hello")
        clock.advance(60)
        second = await _store(db, embeddings, user_text="still here")

        entities = await db.query("SELECT * FROM entity")
        assert len(entities) == 1
        speaker = entities[0]
        assert str(speaker["id"]) == "entity:owner"
        assert speaker["type"] == "person"
        assert speaker["name"] == "owner"
        assert speaker["aliases"] == ["owner"]

        rows = {row["id"]: row for row in await _episodes(db)}
        assert rows[first]["speaker"] == speaker["id"]
        assert rows[second]["speaker"] == speaker["id"]

        # A second ensure_person call returns the same id, not a new record.
        again = await ensure_person(db, "owner", "Mai")
        assert again == speaker["id"]
        assert len(await db.query("SELECT * FROM entity")) == 1
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# _post_response_chain: flag off and embed failure
# ---------------------------------------------------------------------------
def _make_orchestrator(db: EmbeddedSurrealDB) -> Orchestrator:
    """Build an Orchestrator wired only for ``_post_response_chain``."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.logger = logging.getLogger("aura.orchestrator.episodes-test")

    state = EmotionState(
        timestamp=_START.replace(tzinfo=None),
        vector=EmotionVector(),
        dominant=("neutral", 0.0),
        description="Neutral",
    )
    emotion_engine = MagicMock()
    emotion_engine.get_current_state = AsyncMock(return_value=state)
    emotion_engine.config = SimpleNamespace(baseline=EmotionVector())
    orch.emotion_engine = emotion_engine

    orch.learning_engine = AsyncMock()
    orch.learning_engine.log_experience = AsyncMock()

    # L4 would call the LLM; this test only exercises the episode write.
    orch._apply_l4_emotion_analysis = AsyncMock()

    orch.db = db
    return orch


async def _post_response(
    orch: Orchestrator,
    *,
    venue: str = "app",
    speaker: str = "owner",
    user_input: str = "hello",
    response: str = "hi there",
):
    state = await orch.emotion_engine.get_current_state()
    await orch._post_response_chain(
        user_input=user_input,
        response=response,
        emotional_before=state,
        user_id=speaker,
        conversation_id="c1",
        goal_context=None,
        learning_context=None,
        enable_l2=False,
        resonance_score=0.0,
        venue=venue,
        speaker=speaker,
    )


@pytest.mark.asyncio
async def test_flag_off_writes_no_episode(monkeypatch):
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    db = await _open_db()
    try:
        orch = _make_orchestrator(db)

        await _post_response(orch)

        assert await _episodes(db) == []
        # Today's experience write still happens.
        orch.learning_engine.log_experience.assert_awaited_once()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_failing_embed_stores_nothing_and_does_not_raise(monkeypatch):
    monkeypatch.setattr(settings, "memory_v2_write_enabled", True)
    db = await _open_db()
    try:
        class BrokenEmbeddings:
            async def embed(self, text):
                raise RuntimeError("embedding model unavailable")

        orch = _make_orchestrator(db)
        with patch(
            "aura.llm.embeddings.get_embeddings_client",
            return_value=BrokenEmbeddings(),
        ):
            # The call must not raise into the turn.
            await _post_response(orch, venue="guild:1/channel:2", speaker="discord_42")

        assert await _episodes(db) == []
        assert await db.query("SELECT * FROM entity") == []
        orch.learning_engine.log_experience.assert_awaited_once()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_flag_on_stores_the_turn_with_its_venue_and_speaker(monkeypatch):
    monkeypatch.setattr(settings, "memory_v2_write_enabled", True)
    db = await _open_db()
    try:
        orch = _make_orchestrator(db)
        with patch(
            "aura.llm.embeddings.get_embeddings_client",
            return_value=HashedBagOfWordsEmbeddings(),
        ):
            await _post_response(
                orch,
                venue="guild:1/channel:2",
                speaker="discord_42",
                user_input="what is my cat called?",
            )

        episodes = await _episodes(db)
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode["user_text"] == "what is my cat called?"
        assert episode["aura_text"] == "hi there"
        assert episode["venue"] == "guild:1/channel:2"
        assert str(episode["speaker"]) == "entity:discord_42"
        assert episode["ephemeral"] is False
        assert 0.0 <= episode["salience"] <= 1.0
        assert episode["embedding"] is not None
        assert len(episode["embedding"]) == 768
    finally:
        await db.close()