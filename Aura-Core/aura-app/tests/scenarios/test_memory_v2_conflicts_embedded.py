"""Embedded-SurrealDB tests for the memory v2 conflict check (card W3-16).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter and deterministic embedding stub, with both
memory schema files applied exactly as the app applies them at boot. They
cover the four outcomes of ``aura.engines.memory.v2.conflicts.classify`` as
applied by ``write_facts``:

* an update supersedes the old fact (``valid_to`` and ``supersedes``);
* a repeated statement is a duplicate (confidence up, one fact);
* a guest's hearsay never supersedes an observed fact and opens a question;
* a negation contradicts;
* an unrelated fact is new.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import ensure_person, store_episode
from aura.engines.memory.v2.extraction import Extraction
from aura.engines.memory.v2.facts import write_facts
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


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
        "content": "I live in Lisbon.",
        "kind": "fact",
        "subject": "I",
        "predicate": "lives in",
        "object": "Lisbon",
        "about": ["Lisbon"],
        "asserted_by": "user",
        "implied": False,
        "negates": False,
    }
    fact.update(overrides)
    return fact


def _lisbon_entities():
    return [{"name": "Lisbon", "type": "place", "surface": "Lisbon"}]


async def _facts(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM fact ORDER BY recorded_at ASC")


async def _current_facts(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query(
        "SELECT * FROM fact WHERE valid_to IS NONE ORDER BY recorded_at ASC"
    )


async def _edges(db: EmbeddedSurrealDB, table: str) -> list[dict]:
    return await db.query(f"SELECT * FROM {table}")


# ---------------------------------------------------------------------------
# update: "I live in Lisbon" then "I moved to Porto"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_changed_fact_supersedes_the_old_one():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "I live in Lisbon.")
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(_lisbon_entities(), [_fact()]),
        )

        clock.advance(3600)
        episode = await _store(db, embeddings, "I moved to Porto.")
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(
                [{"name": "Porto", "type": "place", "surface": "Porto"}],
                [
                    _fact(
                        content="I moved to Porto.",
                        object="Porto",
                        about=["Porto"],
                    )
                ],
            ),
        )

        facts = await _facts(db)
        assert len(facts) == 2
        lisbon = next(f for f in facts if f["object"] == "Lisbon")
        porto = next(f for f in facts if f["object"] == "Porto")

        # Lisbon is kept but closed; Porto is the only current fact.
        assert lisbon["valid_to"] == _START + timedelta(hours=1)
        assert porto.get("valid_to") is None
        current = await _current_facts(db)
        assert [f["object"] for f in current] == ["Porto"]

        edges = await _edges(db, "supersedes")
        assert len(edges) == 1
        assert edges[0]["in"] == porto["id"]
        assert edges[0]["out"] == lisbon["id"]
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# duplicate: the same statement twice
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_repeated_statement_raises_confidence_and_creates_one_fact():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        for _ in range(2):
            episode = await _store(db, embeddings, "I live in Lisbon.")
            await write_facts(
                db,
                embeddings,
                episode,
                _extraction(_lisbon_entities(), [_fact()]),
            )
            clock.advance(60)

        facts = await _facts(db)
        assert len(facts) == 1
        assert facts[0]["confidence"] == pytest.approx(0.9)
        assert facts[0].get("valid_to") is None

        # The second episode is linked to the same fact, so both turns are
        # evidence for it.
        derived = await _edges(db, "derived_from")
        assert len([edge for edge in derived if edge["in"] == facts[0]["id"]]) == 2
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# contradiction: guest hearsay about the owner
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_guest_hearsay_does_not_supersede_an_observed_fact(monkeypatch):
    monkeypatch.setattr(settings, "owner_display_name", "Mai")
    monkeypatch.setattr(settings, "owner_aliases", [])

    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        owner = await ensure_person(db, "owner", "Mai")
        venue = "guild:99/channel:7"

        episode = await _store(
            db, embeddings, "I live in Lisbon.", speaker="owner", venue=venue
        )
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(_lisbon_entities(), [_fact()]),
        )

        clock.advance(60)
        episode = await _store(
            db,
            embeddings,
            "Mai lives in Berlin.",
            speaker="discord_42",
            venue=venue,
        )
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(
                [
                    {"name": "Mai", "type": "person", "surface": "Mai"},
                    {"name": "Berlin", "type": "place", "surface": "Berlin"},
                ],
                [
                    _fact(
                        content="Mai lives in Berlin.",
                        subject="Mai",
                        object="Berlin",
                        about=["Berlin"],
                    )
                ],
            ),
        )

        facts = await _facts(db)
        assert len(facts) == 2
        observed = next(f for f in facts if f["object"] == "Lisbon")
        hearsay = next(f for f in facts if f["object"] == "Berlin")

        assert observed["provenance"] == "observed"
        assert observed.get("valid_to") is None
        assert hearsay["provenance"] == "hearsay"
        assert hearsay.get("valid_to") is None

        # The guest's claim is about the owner, the same resolved subject.
        about = await _edges(db, "about")
        assert owner in {edge["out"] for edge in about}
        assert owner in {
            edge["out"] for edge in about if edge["in"] == hearsay["id"]
        }

        contradicts = await _edges(db, "contradicts")
        assert len(contradicts) == 1
        assert contradicts[0]["in"] == hearsay["id"]
        assert contradicts[0]["out"] == observed["id"]

        questions = await db.query("SELECT * FROM question")
        assert len(questions) == 1
        question = questions[0]
        assert question["visibility"] == "guild:99"
        assert question["status"] == "open"
        assert "I live in Lisbon." in question["content"]
        assert "Mai lives in Berlin." in question["content"]
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# contradiction: a negation
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_negation_creates_a_contradiction():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "I live in Lisbon.")
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(_lisbon_entities(), [_fact()]),
        )

        clock.advance(60)
        episode = await _store(db, embeddings, "I do not live in Lisbon.")
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(
                _lisbon_entities(),
                [
                    _fact(
                        content="I do not live in Lisbon.",
                        negates=True,
                    )
                ],
            ),
        )

        facts = await _facts(db)
        assert len(facts) == 2
        assert all(f.get("valid_to") is None for f in facts)

        contradicts = await _edges(db, "contradicts")
        assert len(contradicts) == 1
        assert contradicts[0]["out"] == facts[0]["id"]
        assert contradicts[0]["in"] == facts[1]["id"]

        questions = await db.query("SELECT * FROM question")
        assert len(questions) == 1
        assert "I live in Lisbon." in questions[0]["content"]
        assert "I do not live in Lisbon." in questions[0]["content"]
    finally:
        await db.close()
        set_clock(Clock())


# ---------------------------------------------------------------------------
# new: an unrelated fact
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unrelated_fact_is_new():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode = await _store(db, embeddings, "I live in Lisbon.")
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(_lisbon_entities(), [_fact()]),
        )

        clock.advance(60)
        episode = await _store(db, embeddings, "The garden has roses.")
        await write_facts(
            db,
            embeddings,
            episode,
            _extraction(
                [{"name": "garden", "type": "other", "surface": "the garden"}],
                [
                    _fact(
                        content="The garden has roses.",
                        subject="garden",
                        predicate="has",
                        object="roses",
                        about=["garden"],
                    )
                ],
            ),
        )

        facts = await _facts(db)
        assert len(facts) == 2
        assert all(f.get("valid_to") is None for f in facts)
        assert await _edges(db, "supersedes") == []
        assert await _edges(db, "contradicts") == []
        assert await db.query("SELECT * FROM question") == []
    finally:
        await db.close()
        set_clock(Clock())