"""Embedded-SurrealDB test for the spreading-activation edge query clause
order (card W2-13).

The scenario runner (W2-01) found that the edge query in
``MemoryManager.retrieve_with_spreading_activation`` put ``FETCH in, out``
before ``LIMIT 50``::

    SELECT in, out, similarity
    FROM related_to
    WHERE in IN $sids OR out IN $sids
    FETCH in, out
    LIMIT 50

The SurrealQL ``SELECT`` clause order is ``WHERE``, ``SPLIT``, ``GROUP``,
``ORDER``, ``LIMIT``, ``START``, ``FETCH``, ``TIMEOUT``, ``PARALLEL``,
``EXPLAIN`` — ``FETCH`` comes *after* ``LIMIT``.  The embedded SurrealDB
engine rejects the old order with a parse error ("Unexpected token
``LIMIT``, expected Eof"), so the spreading-activation pass 2 silently
caught the failure and never traversed the graph.  W2-13 fixes this by
moving ``LIMIT 50`` before ``FETCH in, out``.

This test drives the real in-memory embedded SurrealDB (``mem://``)
through the W2-01 runner's adapter — no server, no model download, no
network.  It proves the fix works *and* that the test detects the bug
(the old string is rejected).
"""

from __future__ import annotations

import pytest

from tests.scenarios.runner import EmbeddedSurrealDB

# The exact new query string, matching the one in
# ``MemoryManager.retrieve_with_spreading_activation`` after W2-13.
NEW_QUERY = """\
                SELECT in, out, similarity
                FROM related_to
                WHERE in IN $sids OR out IN $sids
                LIMIT 50
                FETCH in, out
                """

# The old (buggy) query string, with ``FETCH in, out`` before ``LIMIT 50``.
# Kept here so the test can prove it still raises a parse error — i.e. the
# test detects the bug W2-13 fixes.
OLD_QUERY = """\
                SELECT in, out, similarity
                FROM related_to
                WHERE in IN $sids OR out IN $sids
                FETCH in, out
                LIMIT 50
                """


@pytest.mark.asyncio
async def test_spreading_edge_query_new_clause_order_runs():
    """The corrected query (``LIMIT`` before ``FETCH``) runs without raising.

    ``$sids`` bound to an empty list is fine — the query simply matches
    no rows and the adapter returns an empty list.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        result = await db.query(NEW_QUERY, {"sids": []})
        # An empty list (no matching edges) is the expected, accepted result.
        assert isinstance(result, list)
        assert result == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_spreading_edge_query_old_clause_order_raises():
    """The old query (``FETCH`` before ``LIMIT``) raises a parse error.

    This proves the test detects the bug W2-13 fixes: SurrealQL's
    ``SELECT`` clause order requires ``LIMIT`` to come before ``FETCH``,
    so the old string is rejected by the embedded engine.  The runner's
    adapter forwards ``self._client.query`` and does not swallow parse
    errors, so the ``ValidationError`` propagates.  If a future adapter
    change swallows parse errors, call the underlying embedded client
    directly (``db._client.query``) instead — the same parse error is
    raised there.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        with pytest.raises(Exception):
            await db.query(OLD_QUERY, {"sids": []})
    finally:
        await db.close()
