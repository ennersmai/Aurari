"""Embedded-SurrealDB tests for owner name resolution (card W3-15a).

These tests verify that the owner's names resolve to the owner entity,
not to a separate person entity.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.memory.v2.episodes import ensure_person, store_episode
from aura.engines.memory.v2.extraction import Extraction, run_extraction
from aura.engines.memory.v2.facts import write_facts
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeClient:
    """A client that returns one canned extraction reply."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    async def complete(self, messages, model, temperature=0.7, **kwargs):
        self.calls.append(
            {"messages": messages, "model": model, "temperature": temperature}
        )
        return self.reply


async def _open_db() -> EmbeddedSurrealDB:
    db = EmbeddedSurrealDB()
    await db.connect()
    return db


async def _store(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
    text: str,
    *,
    speaker: str = "owner",
    venue: str = "app",
    conversation_id: str | None = "c1",
    display_name: str | None = None,
) -> dict:
    """Store one episode and return its stored row."""
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
        display_name=display_name,
    )
    rows = await db.query("SELECT * FROM $rid", {"rid": episode_id})
    assert len(rows) == 1
    return rows[0]


def _extraction(entities, facts) -> Extraction:
    return Extraction.model_validate(
        {
            "entities": entities,
            "facts": facts,
            "questions": [],
            "predictions": [],
        }
    )


def _fact(**overrides):
    fact = {
        "content": "The owner lives in Lisbon.",
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


async def _facts(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM fact ORDER BY recorded_at ASC")


async def _edges(db: EmbeddedSurrealDB, table: str) -> list[dict]:
    return await db.query(f"SELECT * FROM {table}")


async def _entity(db: EmbeddedSurrealDB, key: str) -> dict | None:
    rows = await db.query("SELECT * FROM $rid", {"rid": to_record_id(f"entity:{key}")})
    if rows:
        return rows[0]
    return None


# ---------------------------------------------------------------------------
# ensure_person alias merging for the owner
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ensure_person_owner_name_and_aliases(monkeypatch):
    """With owner_display_name='Mai', ensure_person gives name 'Mai' and
    aliases containing 'owner' and 'mai'."""
    monkeypatch.setattr(settings, "owner_display_name", "Mai")
    monkeypatch.setattr(settings, "owner_aliases", [])

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        owner_id = await ensure_person(db, "owner", None)

        entity = await _entity(db, "owner")
        assert entity is not None
        assert entity["name"] == "Mai"
        assert "owner" in entity["aliases"]
        assert "mai" in entity["aliases"]
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_ensure_person_owner_second_call_keeps_aliases(monkeypatch):
    """A second call with another display name keeps the earlier aliases."""
    monkeypatch.setattr(settings, "owner_display_name", "Mai")
    monkeypatch.setattr(settings, "owner_aliases", [])

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await ensure_person(db, "owner", None)
        await ensure_person(db, "owner", "Another Name")

        entity = await _entity(db, "owner")
        assert entity is not None
        assert entity["name"] == "Mai"  # name stays as owner_display_name
        assert "owner" in entity["aliases"]
        assert "mai" in entity["aliases"]
        # The second call's name is not added as an alias (only config aliases
        # and the canonical name are added for the owner)
        assert "another name" not in entity["aliases"]
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_ensure_person_owner_aliases_from_config(monkeypatch):
    """owner_aliases=['M'] adds 'm' to the aliases."""
    monkeypatch.setattr(settings, "owner_display_name", "Mai")
    monkeypatch.setattr(settings, "owner_aliases", ["M"])

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await ensure_person(db, "owner", None)

        entity = await _entity(db, "owner")
        assert entity is not None
        assert "owner" in entity["aliases"]
        assert "mai" in entity["aliases"]
        assert "m" in entity["aliases"]
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# Guest statement about owner resolves to owner entity
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guest_statement_about_owner_resolves_to_owner(monkeypatch):
    """A Discord guest in a guild says 'Mai lives in Porto' (subject='Mai').
    The stored fact is about entity:owner with provenance hearsay."""
    monkeypatch.setattr(settings, "owner_display_name", "Mai")
    monkeypatch.setattr(settings, "owner_aliases", [])

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        owner = await ensure_person(db, "owner", "Mai")
        episode = await _store(
            db,
            embeddings,
            "Mai lives in Porto.",
            speaker="discord_42",
            venue="guild:99/channel:7",
        )
        extraction = _extraction(
            [
                {"name": "Mai", "type": "person", "surface": "Mai"},
                {"name": "Porto", "type": "place", "surface": "Porto"},
            ],
            [
                _fact(
                    content="Mai lives in Porto.",
                    subject="Mai",
                    object="Porto",
                    about=["Porto"],
                ),
            ],
        )

        await write_facts(db, embeddings, episode, extraction)

        facts = await _facts(db)
        assert len(facts) == 1
        fact = facts[0]
        assert fact["provenance"] == "hearsay"
        assert fact["confidence"] == pytest.approx(0.3)

        # The fact should be about the owner entity
        about = await _edges(db, "about")
        owner_edges = [edge for edge in about if edge["out"] == owner]
        assert len(owner_edges) >= 1, "Fact should be about entity:owner"
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# App turn with user_id='Mai' adds alias 'mai' even when owner_display_name empty
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_app_turn_adds_owner_name_alias(monkeypatch):
    """An app turn with user_id='Mai' adds the alias 'mai' even when
    owner_display_name is empty."""
    monkeypatch.setattr(settings, "owner_display_name", "")
    monkeypatch.setattr(settings, "owner_aliases", [])

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        # Simulate the _post_response_chain call with speaker="owner",
        # venue="app", user_id="Mai"
        episode = await _store(
            db,
            embeddings,
            "Hello Aura.",
            speaker="owner",
            venue="app",
            display_name="Mai",
        )

        entity = await _entity(db, "owner")
        assert entity is not None
        assert entity["name"] == "owner"  # empty owner_display_name -> "owner"
        assert "owner" in entity["aliases"]
        assert "mai" in entity["aliases"]
    finally:
        await db.close()
        set_clock(Clock())