"""Embedded-SurrealDB test for ``boost_on_recall`` (card W2-12).

The scenario runner (W2-01) found that ``MemoryManager.boost_on_recall``
bound the caller's *string* record id straight into ``UPDATE $mid``.
The embedded SurrealDB engine (and strict server modes) treat the whole
string ``"memory:abc"`` as a table name when it is bound to a parameter
the database expects to be a record id, so the boost raised::

    Cannot execute UPDATE statement using value: 'memory:<id>'

and the memory's ``recall_count`` never advanced.  W2-12 fixes this by
converting the string to a typed ``RecordID`` via the shared
``aura.db.query_utils.to_record_id`` helper before binding it.

This test drives the real ``MemoryManager`` over an in-memory embedded
SurrealDB (``EmbeddedSurrealDB`` / ``_build_manager`` from the W2-01
runner) — no server, no model download, no network.
"""

from __future__ import annotations

import pytest
from surrealdb import RecordID

from aura.db.query_utils import to_record_id
from tests.scenarios.runner import EmbeddedSurrealDB, _build_manager


@pytest.mark.asyncio
async def test_boost_on_recall_advances_recall_count_by_two():
    """Two ``boost_on_recall`` calls raise ``recall_count`` by exactly two.

    Stores one memory through ``store_memory``, reads its ``recall_count``
    with a parameterised ``SELECT`` bound to a ``RecordID``, calls
    ``boost_on_recall`` twice with the *string* id the manager returns,
    and asserts the count went from 0 to 2.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        manager = _build_manager(db)

        # Store one memory.  ``store_memory`` returns the string record id
        # it created (``"memory:<hex>"``).  Empty content is a valid string
        # under the schema and lets the deterministic embedding stub
        # short-circuit (it returns ``None`` for blank text), so the store
        # succeeds offline without needing the real embedding model.
        memory_id = await manager.store_memory(
            content="",
            user_id="alice",
            conversation_id="conv-1",
            emotional_signature={},
            importance=0.5,
            tags=["conversation", "interaction"],
            resonance_score=None,
            formation_context=None,
            response_length=0,
        )
        assert isinstance(memory_id, str) and memory_id.startswith("memory:")

        # Bind a RecordID when reading the row back.
        rid = RecordID("memory", memory_id.split(":", 1)[1])
        rows = await db.query("SELECT recall_count FROM $rid", {"rid": rid})
        before = rows[0]["recall_count"] if rows else None
        assert before == 0, f"expected recall_count 0 before boosting, got {before!r}"

        # Call boost_on_recall with the *string* id (the app's call shape).
        await manager.boost_on_recall(memory_id, boost=0.05)
        await manager.boost_on_recall(memory_id, boost=0.05)

        rows_after = await db.query("SELECT recall_count FROM $rid", {"rid": rid})
        after = rows_after[0]["recall_count"] if rows_after else None
        assert after == 2, f"expected recall_count 2 after two boosts, got {after!r}"
    finally:
        await db.close()


def test_to_record_id_converts_table_id_string():
    """``"memory:abc"`` becomes ``RecordID("memory", "abc")``."""
    result = to_record_id("memory:abc")
    assert isinstance(result, RecordID)
    assert str(result) == "memory:abc"


def test_to_record_id_returns_bare_table_name_unchanged():
    """``"memory"`` (no colon) is returned unchanged."""
    result = to_record_id("memory")
    assert result == "memory"
    assert not isinstance(result, RecordID)


def test_to_record_id_returns_existing_record_id_unchanged():
    """A value that is already a ``RecordID`` is returned unchanged."""
    original = RecordID("memory", "abc")
    result = to_record_id(original)
    assert result is original
