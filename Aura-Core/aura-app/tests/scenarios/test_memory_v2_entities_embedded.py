"""Embedded-SurrealDB tests for memory v2 entity resolution (card W3-14).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter and deterministic embedding stub, with both
memory schema files applied exactly as the app applies them at boot. They
cover ``aura.engines.memory.v2.entities.resolve_entity``:

* an exact alias resolves without an embedding call;
* a new surface form close in embedding resolves to the existing entity and
  becomes an alias;
* an unrelated name creates a new entity;
* ``"I"``/``"me"``/``"myself"`` resolve to the speaker's person entity;
* resolving the same name twice creates one entity.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.engines.memory.v2.entities import resolve_entity
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _open_db() -> EmbeddedSurrealDB:
    db = EmbeddedSurrealDB()
    await db.connect()
    return db


async def _entities(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM entity ORDER BY created_at ASC")


class _NoEmbedding:
    """Embeddings stub that fails if anything tries to embed.

    An exact alias (and a self-name) must resolve from the database alone.
    """

    async def embed(self, text):
        raise AssertionError(f"unexpected embedding call for {text!r}")

    async def embed_batch(self, texts):
        raise AssertionError(f"unexpected embedding calls for {texts!r}")


@pytest.mark.asyncio
async def test_exact_alias_resolves_without_embedding():
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        created = await resolve_entity(
            db, HashedBagOfWordsEmbeddings(), "Miso", "other", "owner"
        )

        # Case and extra whitespace are normalised away, and the resolving
        # call must not reach the embedding model.
        again = await resolve_entity(db, _NoEmbedding(), "  MISO  ", "other", "owner")

        assert again == created
        assert len(await _entities(db)) == 1
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_close_surface_form_resolves_and_is_added_as_alias():
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        created = await resolve_entity(db, embeddings, "Miso Pixel", "other", "owner")

        # Same tokens in another order: a different alias, but an identical
        # embedding, so it resolves to the existing entity.
        resolved = await resolve_entity(db, embeddings, "pixel miso", "other", "owner")

        assert resolved == created
        entities = await _entities(db)
        assert len(entities) == 1
        assert entities[0]["name"] == "Miso Pixel"
        assert set(entities[0]["aliases"]) == {"miso pixel", "pixel miso"}
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_unrelated_name_creates_a_new_entity():
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        cat = await resolve_entity(db, embeddings, "Miso Pixel", "other", "owner")
        router = await resolve_entity(db, embeddings, "Quantum Router", "tool", "owner")

        assert router != cat
        entities = await _entities(db)
        assert len(entities) == 2
        assert {row["name"] for row in entities} == {"Miso Pixel", "Quantum Router"}
        by_name = {row["name"]: row for row in entities}
        assert by_name["Quantum Router"]["type"] == "tool"
        assert by_name["Quantum Router"]["aliases"] == ["quantum router"]
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_i_resolves_to_the_speakers_person_entity():
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        first = await resolve_entity(db, _NoEmbedding(), "I", "person", "discord_42")
        me = await resolve_entity(db, _NoEmbedding(), "me", "person", "discord_42")
        myself = await resolve_entity(
            db, _NoEmbedding(), "Myself", "person", "discord_42"
        )

        assert first == me == myself
        entities = await _entities(db)
        assert len(entities) == 1
        assert str(entities[0]["id"]) == "entity:discord_42"
        assert entities[0]["type"] == "person"
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_resolving_the_same_name_twice_creates_one_entity():
    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        first = await resolve_entity(db, embeddings, "Zephyr", "project", "owner")
        second = await resolve_entity(db, embeddings, "Zephyr", "project", "owner")

        assert second == first
        assert len(await _entities(db)) == 1
    finally:
        await db.close()
        set_clock(Clock())