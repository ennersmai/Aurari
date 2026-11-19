"""Embedded-SurrealDB tests for the Memory v2 schema (card W3-09).

``scripts/schema_v2.surql`` defines the v2 memory data model from PRD
sections 4.1 to 4.5: the ``entity``, ``episode``, ``fact``, ``question``,
``theme`` and ``prediction`` node tables, seven typed relations, and the
HNSW / full-text / standard indexes.  These tests drive the real
in-memory embedded SurrealDB (``mem://``) through the runner's adapter,
with both schema files applied exactly as the app applies them at boot
(``init_schema.surql`` then ``schema_v2.surql``).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from surrealdb.errors import InternalError, ValidationError
from surrealdb.types import RecordID

from tests.scenarios.runner import EmbeddedSurrealDB, _scripts_dir

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)
_DIM = 768

# The exact query shapes the recall path uses (src/aura/engines/recall/channels.py).
_KNN_QUERY = (
    "SELECT id, vector::distance::knn() AS dist FROM fact "
    "WHERE embedding <|5,COSINE|> $vec"
)
_FULLTEXT_QUERY = (
    "SELECT id, search::score(1) AS score FROM fact "
    "WHERE content @1,OR@ $text ORDER BY score DESC"
)


def _embedding() -> list[float]:
    """A deterministic 768-dim unit vector."""
    vec = [0.0] * _DIM
    vec[0] = 1.0
    return vec


def _schema_statements() -> list[str]:
    """Return ``schema_v2.surql`` statements cleaned the way the runner does."""
    raw = (_scripts_dir() / "schema_v2.surql").read_text(encoding="utf-8")
    cleaned = "\n".join(
        line
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    return [stmt.strip() for stmt in cleaned.split(";") if stmt.strip()]


async def _create_entity(db: EmbeddedSurrealDB, name: str = "Pixel") -> RecordID:
    rows = await db.query(
        "CREATE entity CONTENT $data",
        {
            "data": {
                "name": name,
                "type": "person",
                "aliases": ["PIXEL", "Pi"],
                "created_at": _START,
            }
        },
    )
    return rows[0]["id"]


async def _create_episode(db: EmbeddedSurrealDB, speaker: RecordID) -> RecordID:
    rows = await db.query(
        "CREATE episode CONTENT $data",
        {
            "data": {
                "user_text": "Mai has a cat named Pixel",
                "aura_text": "I will remember Pixel.",
                "speaker": speaker,
                "venue": "app",
                "recorded_at": _START,
            }
        },
    )
    return rows[0]["id"]


async def _create_fact(db: EmbeddedSurrealDB) -> RecordID:
    rows = await db.query(
        "CREATE fact CONTENT $data",
        {
            "data": {
                "content": "Mai has a cat named Pixel",
                "kind": "fact",
                "provenance": "observed",
                "visibility": "owner",
                "confidence": 0.9,
                "recorded_at": _START,
                "embedding": _embedding(),
            }
        },
    )
    return rows[0]["id"]


@pytest.mark.asyncio
async def test_schema_v2_applies_twice():
    """Applying every statement in ``schema_v2.surql`` twice does not raise.

    ``EmbeddedSurrealDB.connect`` already applies both schema files once,
    swallowing errors the way the app does.  This applies the v2 file two
    more times strictly (no error is swallowed), which only succeeds
    because every statement uses ``IF NOT EXISTS``.
    """
    statements = _schema_statements()
    assert any("DEFINE TABLE IF NOT EXISTS entity" in s for s in statements)
    assert all("IF NOT EXISTS" in s or s.upper().startswith("USE ") for s in statements)

    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        for _ in range(2):
            for statement in statements:
                await db.query(statement)  # strict: would raise on a redefinition
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_nodes_can_be_created_and_related_with_derived_from_and_about():
    """An entity, episode and fact exist and link through the typed relations."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        entity_id = await _create_entity(db)
        episode_id = await _create_episode(db, entity_id)
        fact_id = await _create_fact(db)

        # The entity aliases are stored lowercased and the episode defaults hold.
        entity = (await db.select(entity_id))[0]
        assert entity["aliases"] == ["pixel", "pi"]
        episode = (await db.select(episode_id))[0]
        assert episode["extraction_status"] == "pending"
        assert episode["extraction_attempts"] == 0
        assert episode["salience"] == 0
        assert episode["ephemeral"] is False
        assert episode["speaker"] == entity_id

        derived = await db.query(
            "RELATE $fact->derived_from->$episode",
            {"fact": fact_id, "episode": episode_id},
        )
        about = await db.query(
            "RELATE $fact->about->$entity",
            {"fact": fact_id, "entity": entity_id},
        )
        assert derived[0]["in"] == fact_id
        assert derived[0]["out"] == episode_id
        assert about[0]["in"] == fact_id
        assert about[0]["out"] == entity_id
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_derived_from_to_an_entity_is_rejected():
    """``derived_from`` only accepts a fact as its origin."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        entity_id = await _create_entity(db)
        episode_id = await _create_episode(db, entity_id)

        with pytest.raises((ValidationError, InternalError)):
            await db.query(
                "RELATE $entity->derived_from->$episode",
                {"entity": entity_id, "episode": episode_id},
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fact_with_unknown_provenance_is_rejected():
    """A fact whose provenance is not one of the five values is rejected."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        with pytest.raises((ValidationError, InternalError)):
            await db.query(
                "CREATE fact CONTENT $data",
                {
                    "data": {
                        "content": "Mai guessed something",
                        "kind": "fact",
                        "provenance": "guess",
                        "visibility": "owner",
                        "confidence": 0.5,
                        "recorded_at": _START,
                    }
                },
            )
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_knn_and_fulltext_queries_return_the_created_fact():
    """The HNSW and BM25 indexes both find the created fact."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        fact_id = await _create_fact(db)

        knn_rows = await db.query(_KNN_QUERY, {"vec": _embedding()})
        fulltext_rows = await db.query(_FULLTEXT_QUERY, {"text": "cat Pixel"})

        assert [str(row["id"]) for row in knn_rows] == [str(fact_id)]
        assert [str(row["id"]) for row in fulltext_rows] == [str(fact_id)]
        assert knn_rows[0]["dist"] == pytest.approx(0.0)
        assert fulltext_rows[0]["score"] > 0
    finally:
        await db.close()