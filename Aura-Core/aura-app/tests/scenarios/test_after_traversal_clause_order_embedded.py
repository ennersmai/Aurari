"""Embedded-SurrealDB test for the clause order in the ``next_experience``
after-traversal query in ``MemoryManager._fetch_thought_cluster`` (card BF-01).

W2-26 fixed four edge queries that put ``FETCH`` before ``LIMIT``, but
missed this fifth query in ``_fetch_thought_cluster``:

``SELECT out.context.user_query AS prompt, ... FROM next_experience WHERE in = $eid FETCH out LIMIT 2``

SurrealQL's ``SELECT`` clause order requires ``LIMIT`` before ``FETCH``.
BF-01 moves ``LIMIT 2`` before ``FETCH out``, keeping every other token,
parameter name and binding unchanged.

Following ``tests/scenarios/test_edge_queries_clause_order_embedded.py``
(W2-26), this test runs both the new and old query strings on the
in-memory embedded SurrealDB (``mem://``) with suitable empty bindings:
the new string runs without raising, and the old string raises a parse
error.
"""

from __future__ import annotations

import pytest

from tests.scenarios.runner import EmbeddedSurrealDB

NEW_QUERY = """\
                                SELECT out.context.user_query AS prompt,
                                       out.domain AS domain,
                                       out.timestamp AS timestamp
                                FROM next_experience
                                WHERE in = $eid
                                LIMIT 2
                                FETCH out
                                """

OLD_QUERY = """\
                                SELECT out.context.user_query AS prompt,
                                       out.domain AS domain,
                                       out.timestamp AS timestamp
                                FROM next_experience
                                WHERE in = $eid
                                FETCH out
                                LIMIT 2
                                """

_BINDINGS = {"eid": "experience:none"}


@pytest.mark.asyncio
async def test_after_traversal_new_clause_order_runs():
    """The corrected query (``LIMIT 2`` before ``FETCH out``) runs without raising."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        result = await db.query(NEW_QUERY, _BINDINGS)
        assert isinstance(result, list)
        assert result == []
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_after_traversal_old_clause_order_raises():
    """The old query (``FETCH out`` before ``LIMIT 2``) raises a parse error."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        with pytest.raises(Exception):
            await db.query(OLD_QUERY, _BINDINGS)
    finally:
        await db.close()
