"""Embedded-SurrealDB tests for memory v2 fact writing (card W3-15).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter and deterministic embedding stub, with both
memory schema files applied exactly as the app applies them at boot. They
cover ``aura.engines.memory.v2.facts.write_facts``:

* the owner's own statement is ``observed`` with owner visibility;
* a guild guest's statement about the owner is ``hearsay`` with low confidence,
  even when the extraction marked it implied;
* a DM fact is private to its speaker;
* an ``asserted_by="aura"`` fact is never stored;
* the ``derived_from``, ``about`` and ``mentions`` edges are written;
* ``run_extraction`` hands a successful extraction to the fact writer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
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


# ---------------------------------------------------------------------------
# provenance and visibility
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_owner_self_fact_is_observed_with_owner_visibility():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "I live in Lisbon.")
        extraction = _extraction(
            [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            [_fact()],
        )

        created = await write_facts(db, embeddings, episode, extraction)

        facts = await _facts(db)
        assert len(facts) == 1
        assert created == [facts[0]["id"]]
        fact = facts[0]
        assert fact["provenance"] == "observed"
        assert fact["confidence"] == pytest.approx(0.8)
        assert fact["visibility"] == "owner"
        assert fact["subject"] == "I"
        assert fact["valid_from"] == fact["recorded_at"]
        assert fact["recorded_at"] == _START
        assert len(fact["embedding"]) == 768
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_guild_guest_statement_about_owner_is_hearsay():
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
                # Even an implied statement from a guest about the owner must
                # stay hearsay (rule 6).
                _fact(
                    content="Mai might live in Porto.",
                    subject="Mai",
                    object="Porto",
                    about=["Porto"],
                    implied=True,
                ),
            ],
        )

        await write_facts(db, embeddings, episode, extraction)

        facts = await _facts(db)
        assert len(facts) == 2
        for fact in facts:
            assert fact["provenance"] == "hearsay"
            assert fact["confidence"] == pytest.approx(0.3)
            assert fact["visibility"] == "guild:99"

        # The subject is the owner entity even though a guest said it.
        about = await _edges(db, "about")
        owner_edges = [edge for edge in about if edge["out"] == owner]
        assert len(owner_edges) == 2
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_dm_fact_is_private_to_its_speaker():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(
            db,
            embeddings,
            "I live in Lisbon.",
            speaker="discord_42",
            venue="dm:discord_42",
            conversation_id="dm-42",
        )
        extraction = _extraction(
            [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            [_fact()],
        )

        await write_facts(db, embeddings, episode, extraction)

        facts = await _facts(db)
        assert len(facts) == 1
        assert facts[0]["visibility"] == "private:discord_42"
        assert facts[0]["provenance"] == "observed"
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_implied_fact_is_inferred():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "I probably live in Lisbon.")
        extraction = _extraction(
            [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            [_fact(implied=True)],
        )

        await write_facts(db, embeddings, episode, extraction)

        facts = await _facts(db)
        assert len(facts) == 1
        assert facts[0]["provenance"] == "inferred"
        assert facts[0]["confidence"] == pytest.approx(0.5)
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# rule 5 and the edges
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_aura_asserted_fact_is_not_stored():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "Tell me about Lisbon.")
        extraction = _extraction(
            [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            [_fact(asserted_by="aura", content="Lisbon is the capital of Portugal.")],
        )

        created = await write_facts(db, embeddings, episode, extraction)

        assert created == []
        assert await _facts(db) == []
        assert await _edges(db, "derived_from") == []
        assert await _edges(db, "about") == []
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_derived_from_about_and_mentions_edges_exist():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        owner = await ensure_person(db, "owner", "Mai")
        episode = await _store(db, embeddings, "I live in Lisbon.")
        extraction = _extraction(
            [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            [_fact()],
        )

        created = await write_facts(db, embeddings, episode, extraction)
        fact_id = created[0]

        derived = await _edges(db, "derived_from")
        assert len(derived) == 1
        assert derived[0]["in"] == fact_id
        assert derived[0]["out"] == episode["id"]

        mentions = await _edges(db, "mentions")
        assert len(mentions) == 1
        assert mentions[0]["in"] == episode["id"]
        assert str(mentions[0]["out"]).startswith("entity:")

        about = await _edges(db, "about")
        assert len(about) == 2
        assert {edge["in"] for edge in about} == {fact_id}
        assert {str(edge["out"]) for edge in about} == {
            "entity:owner",
            str(mentions[0]["out"]),
        }
        # The owner subject is linked even though the extraction only listed
        # Lisbon in ``about``.
        assert owner in {edge["out"] for edge in about}
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# run_extraction integration
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_run_extraction_writes_facts_after_a_successful_extraction(
    monkeypatch,
):
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "I live in Lisbon.")

        payload = {
            "entities": [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}],
            "facts": [_fact()],
            "questions": [],
            "predictions": [],
        }
        client = FakeClient(json.dumps(payload))
        monkeypatch.setattr(
            "aura.llm.embeddings.get_embeddings_client", lambda: embeddings
        )

        await run_extraction(db, client, episode["id"])

        facts = await _facts(db)
        assert len(facts) == 1
        assert facts[0]["provenance"] == "observed"
        assert facts[0]["visibility"] == "owner"
    finally:
        await db.close()
        set_clock(Clock())