"""Embedded-SurrealDB tests for the clause order in the four remaining
edge queries (card W2-26).

W2-13 fixed the clause order in the spreading-activation edge query
(``retrieve_with_spreading_activation``).  Its log entry reported that
four more queries in ``MemoryManager`` put ``FETCH in`` before ``LIMIT``,
which SurrealDB rejects (the ``SELECT`` clause order is ``WHERE``,
``SPLIT``, ``GROUP``, ``ORDER``, ``LIMIT``, ``START``, ``FETCH``,
``TIMEOUT``, ``PARALLEL``, ``EXPLAIN`` — ``FETCH`` comes *after*
``LIMIT``).  These four queries are:

1. ``_fetch_thought_cluster``, the ``abstracted_into`` sources query:
   ``... WHERE out = $mid FETCH in LIMIT 5``
2. ``_fetch_thought_cluster``, the ``next_experience`` before-traversal
   query: ``... FETCH in LIMIT 2``
3. ``traverse_timeline``, the forward-step query: ``... FETCH in
   LIMIT 1``
4. ``fetch_supporting_evidence``, the ``abstracted_into`` evidence
   query: ``... FETCH in LIMIT 10``

W2-26 moves ``LIMIT <n>`` before ``FETCH in`` in each, keeping every
other token, parameter name and binding unchanged.

This test drives the real in-memory embedded SurrealDB (``mem://``)
through the W2-01 runner's adapter — no server, no model download, no
network.  For each of the four corrected queries it asserts the new
clause order runs without raising (with suitable empty bindings), and
that the old clause order (``FETCH in`` before ``LIMIT``) raises a parse
error — proving the test detects the bug W2-26 fixes.
"""

from __future__ import annotations

import pytest

from tests.scenarios.runner import EmbeddedSurrealDB

# ---------------------------------------------------------------------------
# Query 1: _fetch_thought_cluster, abstracted_into sources query.
# New (correct): LIMIT 5 before FETCH in.
# ---------------------------------------------------------------------------

NEW_QUERY_1 = """\
                SELECT in.content AS content, in.timestamp AS timestamp
                FROM abstracted_into
                WHERE out = $mid
                LIMIT 5
                FETCH in
                """

OLD_QUERY_1 = """\
                SELECT in.content AS content, in.timestamp AS timestamp
                FROM abstracted_into
                WHERE out = $mid
                FETCH in
                LIMIT 5
                """

# ---------------------------------------------------------------------------
# Query 2: _fetch_thought_cluster, next_experience before-traversal query.
# New (correct): LIMIT 2 before FETCH in.
# ---------------------------------------------------------------------------

NEW_QUERY_2 = """\
                                SELECT in.context.user_query AS prompt,
                                       in.domain AS domain,
                                       in.timestamp AS timestamp
                                FROM next_experience
                                WHERE out = $eid
                                LIMIT 2
                                FETCH in
                                """

OLD_QUERY_2 = """\
                                SELECT in.context.user_query AS prompt,
                                       in.domain AS domain,
                                       in.timestamp AS timestamp
                                FROM next_experience
                                WHERE out = $eid
                                FETCH in
                                LIMIT 2
                                """

# ---------------------------------------------------------------------------
# Query 3: traverse_timeline, forward-step query.
# New (correct): LIMIT 1 before FETCH in.
# ---------------------------------------------------------------------------

NEW_QUERY_3 = """\
                        SELECT in.id AS id,
                               in.context.user_query AS prompt,
                               in.aura_response.response AS response,
                               in.domain AS domain,
                               in.timestamp AS timestamp,
                               elapsed_ms
                        FROM next_experience
                        WHERE out = $eid
                        LIMIT 1
                        FETCH in
                        """

OLD_QUERY_3 = """\
                        SELECT in.id AS id,
                               in.context.user_query AS prompt,
                               in.aura_response.response AS response,
                               in.domain AS domain,
                               in.timestamp AS timestamp,
                               elapsed_ms
                        FROM next_experience
                        WHERE out = $eid
                        FETCH in
                        LIMIT 1
                        """

# ---------------------------------------------------------------------------
# Query 4: fetch_supporting_evidence, abstracted_into evidence query.
# New (correct): LIMIT 10 before FETCH in.
# ---------------------------------------------------------------------------

NEW_QUERY_4 = """\
                    SELECT in.content AS content,
                           in.timestamp AS timestamp,
                           in.emotional_signature AS emotional_signature,
                           in.importance AS importance
                    FROM abstracted_into
                    WHERE out = $iid
                    LIMIT 10
                    FETCH in
                    """

OLD_QUERY_4 = """\
                    SELECT in.content AS content,
                           in.timestamp AS timestamp,
                           in.emotional_signature AS emotional_signature,
                           in.importance AS importance
                    FROM abstracted_into
                    WHERE out = $iid
                    FETCH in
                    LIMIT 10
                    """

# (new, old, bindings) for each of the four queries.
_QUERIES = [
    (NEW_QUERY_1, OLD_QUERY_1, {"mid": "memory:none"}),
    (NEW_QUERY_2, OLD_QUERY_2, {"eid": "experience:none"}),
    (NEW_QUERY_3, OLD_QUERY_3, {"eid": "experience:none"}),
    (NEW_QUERY_4, OLD_QUERY_4, {"iid": "memory:none"}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "new_query,old_query,bindings",
    _QUERIES,
    ids=["thought_cluster_sources", "thought_cluster_before", "traverse_timeline", "supporting_evidence"],
)
async def test_edge_query_new_clause_order_runs(new_query, old_query, bindings):
    """The corrected query (``LIMIT`` before ``FETCH``) runs without raising.

    The parameters are bound to placeholder record-id strings that match
    no rows, so the query simply returns an empty list.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        result = await db.query(new_query, bindings)
        # An empty list (no matching rows) is the expected, accepted result.
        assert isinstance(result, list)
        assert result == []
    finally:
        await db.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "new_query,old_query,bindings",
    _QUERIES,
    ids=["thought_cluster_sources", "thought_cluster_before", "traverse_timeline", "supporting_evidence"],
)
async def test_edge_query_old_clause_order_raises(new_query, old_query, bindings):
    """The old query (``FETCH`` before ``LIMIT``) raises a parse error.

    This proves the test detects the bug W2-26 fixes: SurrealQL's
    ``SELECT`` clause order requires ``LIMIT`` to come before ``FETCH``,
    so the old string is rejected by the embedded engine.  The runner's
    adapter forwards ``self._client.query`` and does not swallow parse
    errors, so the error propagates.  If a future adapter change
    swallows parse errors, call the underlying embedded client directly
    (``db._client.query``) instead — the same parse error is raised
    there.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        with pytest.raises(Exception):
            await db.query(old_query, bindings)
    finally:
        await db.close()
