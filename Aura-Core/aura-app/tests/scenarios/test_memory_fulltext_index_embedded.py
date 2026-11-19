"""Embedded-SurrealDB tests for the memory full-text index (card W3-01).

``scripts/init_schema.surql`` defines a ``memory_text`` analyzer (class
tokenizer, lowercase/ascii/snowball(english) filters) and a ``FULLTEXT``
BM25 index named ``memory_content_ft`` on ``memory.content``, right after
the ``memory_embedding`` HNSW index.  This test drives the real in-memory
embedded SurrealDB (``mem://``) through the W2-01 runner's adapter, with
the real schema applied as the runner applies it at connect time, and
checks that:

* ``what do you know about rust?`` ranks the Rust memory first;
* ``parse_route`` ranks the ``config.rs`` memory first;
* ``sleeping cats`` ranks the cat memory first (snowball stemming:
  ``sleeping`` -> ``sleep``, ``cats`` -> ``cat``);
* applying the schema (and the two new definitions) twice does not raise.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest

from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    _apply_surql_file,
    _scripts_dir,
)

# The three memories the card asks for.
_MEMORIES = [
    "Mai likes the Rust language",
    "The cat sleeps on the sofa",
    "function parse_route in config.rs",
]

# The exact query shape from the card: the full-text index is referenced
# as ``@1`` and its BM25 score is read with ``search::score(1)``.
_FULLTEXT_QUERY = (
    "SELECT id, search::score(1) AS score FROM memory "
    "WHERE content @1,OR@ $t ORDER BY score DESC"
)

_START = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _new_schema_statements() -> list[str]:
    """Return the analyzer and full-text index statements from the schema.

    The file is cleaned the same way the runner cleans it (drop ``--``
    line comments and ``/* */`` block comments, split on ``;``), then only
    the two statements this card adds are kept.
    """
    raw = (_scripts_dir() / "init_schema.surql").read_text(encoding="utf-8")
    cleaned = "\n".join(
        line
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    return [
        stmt.strip()
        for stmt in cleaned.split(";")
        if "memory_text" in stmt or "memory_content_ft" in stmt
    ]


async def _create_memories(db: EmbeddedSurrealDB) -> list[str]:
    """Create the three memories and return their record ids as strings."""
    ids: list[str] = []
    for content in _MEMORIES:
        created = await db.query(
            "CREATE memory CONTENT $data",
            {
                "data": {
                    "content": content,
                    "timestamp": _START,
                    "importance": 0.5,
                    "emotional_signature": {},
                }
            },
        )
        ids.append(str(created[0]["id"]))
    return ids


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text,expected_index",
    [
        ("what do you know about rust?", 0),
        ("parse_route", 2),
        ("sleeping cats", 1),
    ],
    ids=["rust", "parse_route", "sleeping_cats"],
)
async def test_fulltext_search_ranks_expected_memory_first(text, expected_index):
    """The full-text query returns the expected memory first, by BM25 score."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        ids = await _create_memories(db)
        rows = await db.query(_FULLTEXT_QUERY, {"t": text})

        assert rows, f"full-text query {text!r} returned no rows"
        assert rows[0]["id"] is not None
        assert str(rows[0]["id"]) == ids[expected_index]
        # ORDER BY score DESC really is descending.
        scores = [row["score"] for row in rows]
        assert scores == sorted(scores, reverse=True)
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fulltext_schema_applies_twice():
    """Re-applying the analyzer and index definitions does not raise.

    ``EmbeddedSurrealDB.connect`` already applies the whole schema once
    (swallowing errors, as the app does).  This test additionally applies
    the two new definitions strictly (no error is swallowed) twice more,
    which only succeeds because they use ``OVERWRITE``, and then re-runs
    the whole schema file through the runner's helper exactly as the app
    does at boot.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        definitions = _new_schema_statements()
        assert len(definitions) == 2, definitions
        for _ in range(2):
            for statement in definitions:
                await db.query(statement)  # strict: would raise on a redefinition

        # The runner/app path for the whole file must also stay quiet.
        assert db._client is not None
        await _apply_surql_file(
            db._client, "init_schema.surql", "Core schema (structural)"
        )
    finally:
        await db.close()