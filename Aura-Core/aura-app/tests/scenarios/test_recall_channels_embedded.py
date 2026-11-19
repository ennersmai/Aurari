"""Embedded-SurrealDB tests for the dense and lexical channels (card W3-02).

Drives the real in-memory embedded SurrealDB (``mem://``) through the
W2-01 runner's adapter, with the real schema applied as the runner applies
it at connect time, and uses the runner's
:class:`HashedBagOfWordsEmbeddings` so every embedding is deterministic and
offline.

Checks:

* the dense channel returns the nearest memory first, with cosine
  similarity ``1 - distance`` and 0-based ranks;
* the lexical channel finds a memory by a code symbol (``parse_route``)
  and by a name;
* both channels honour the ``user_id`` filter;
* a deprecated memory never appears in either channel;
* empty input returns ``[]`` without querying the database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from aura.engines.recall.channels import ChannelHit, dense_channel, lexical_channel
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)

_RUST = "Mai likes the Rust language"
_CAT = "The cat sleeps on the sofa"
_CONFIG = "function parse_route in config.rs"


async def _create_memory(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
    content: str,
    *,
    user_id: str = "alice",
    deprecated: bool = False,
) -> str:
    """Create one memory through the real schema and return its record id."""
    created = await db.query(
        "CREATE memory CONTENT $data",
        {
            "data": {
                "content": content,
                "timestamp": _START,
                "importance": 0.5,
                "emotional_signature": {},
                "embedding": await embeddings.embed(content),
                "user_id": user_id,
                "deprecated": deprecated,
            }
        },
    )
    return str(created[0]["id"])


async def _seed(db: EmbeddedSurrealDB) -> dict[str, str]:
    """Create the three baseline memories and return ids keyed by short name."""
    embeddings = HashedBagOfWordsEmbeddings()
    return {
        "rust": await _create_memory(db, embeddings, _RUST),
        "cat": await _create_memory(db, embeddings, _CAT),
        "config": await _create_memory(db, embeddings, _CONFIG),
    }


@pytest.mark.asyncio
async def test_dense_returns_nearest_memory_first():
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _seed(db)
        query = await HashedBagOfWordsEmbeddings().embed("Rust language")

        hits = await dense_channel(db, query, "alice", None)

        assert hits, "dense channel returned no candidates"
        assert all(isinstance(hit, ChannelHit) for hit in hits)
        assert hits[0].memory_id == ids["rust"]
        assert hits[0].rank == 0
        assert hits[0].score > hits[1].score
        assert [hit.rank for hit in hits] == list(range(len(hits)))
        # score is cosine similarity: 1 - distance, so it stays in [-1, 1].
        assert all(-1.0 <= hit.score <= 1.0 for hit in hits)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_lexical_finds_memory_by_code_symbol():
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _seed(db)

        hits = await lexical_channel(db, "parse_route", "alice", None)

        assert hits, "lexical channel returned no candidates"
        assert hits[0].memory_id == ids["config"]
        assert hits[0].rank == 0
        assert all(isinstance(hit, ChannelHit) for hit in hits)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_lexical_finds_memory_by_name():
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _seed(db)

        hits = await lexical_channel(db, "Mai", "alice", None)

        assert hits, "lexical channel returned no candidates"
        assert hits[0].memory_id == ids["rust"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_user_id_filter_excludes_other_users_in_both_channels():
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _seed(db)
        embeddings = HashedBagOfWordsEmbeddings()
        bob_rust = await _create_memory(
            db, embeddings, "Bob likes the Rust language", user_id="bob"
        )
        bob_config = await _create_memory(
            db, embeddings, "function parse_route in bob.rs", user_id="bob"
        )

        query = await embeddings.embed("Rust language")
        dense_hits = await dense_channel(db, query, "alice", None)
        dense_ids = {hit.memory_id for hit in dense_hits}
        assert ids["rust"] in dense_ids
        assert bob_rust not in dense_ids

        lexical_hits = await lexical_channel(db, "parse_route", "alice", None)
        lexical_ids = {hit.memory_id for hit in lexical_hits}
        assert ids["config"] in lexical_ids
        assert bob_config not in lexical_ids
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_deprecated_memory_never_appears():
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _seed(db)
        embeddings = HashedBagOfWordsEmbeddings()
        deprecated_rust = await _create_memory(
            db, embeddings, "Mai likes the Rust language", deprecated=True
        )
        deprecated_config = await _create_memory(
            db, embeddings, "function parse_route in deprecated.rs", deprecated=True
        )

        query = await embeddings.embed("Rust language")
        dense_ids = {hit.memory_id for hit in await dense_channel(db, query, "alice", None)}
        assert deprecated_rust not in dense_ids
        assert ids["rust"] in dense_ids

        lexical_ids = {
            hit.memory_id
            for hit in await lexical_channel(db, "parse_route", "alice", None)
        }
        assert deprecated_config not in lexical_ids
        assert ids["config"] in lexical_ids
    finally:
        await db.close()


class _QueryMustNotRun:
    """A database stand-in that fails the test if a query is attempted."""

    async def query(self, sql: str, vars: dict[str, Any] | None = None) -> Any:
        raise AssertionError(f"empty input must not query the database: {sql}")


@pytest.mark.asyncio
async def test_empty_input_returns_empty():
    # No query is attempted for empty input.
    assert await dense_channel(_QueryMustNotRun(), None, "alice", None) == []
    assert await dense_channel(_QueryMustNotRun(), [], "alice", None) == []
    assert await lexical_channel(_QueryMustNotRun(), "", "alice", None) == []
    assert await lexical_channel(_QueryMustNotRun(), "   ", "alice", None) == []

    # And against a real database the result is the same empty list.
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        await _seed(db)
        assert await dense_channel(db, None, "alice", None) == []
        assert await lexical_channel(db, "", "alice", None) == []
    finally:
        await db.close()