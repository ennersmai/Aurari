"""W1-05: memory queries are parameterised.

The card requires that a ``user_id`` containing a single quote does not raise
and returns no rows.  Before W1-05 these queries interpolated ``user_id``
(and other values) into f-strings, so a quote would either break the query or
allow injection.  After W1-05 the values travel in the parameters dictionary,
so a quote is just data.
"""

import pytest
from unittest.mock import AsyncMock

from aura.engines.memory.manager import MemoryManager


def _make_manager() -> MemoryManager:
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    # Every query returns no rows.
    mm.db.query.return_value = []
    mm.embeddings = AsyncMock()
    mm.embeddings.embed.return_value = [0.0] * 8
    return mm


@pytest.mark.asyncio
async def test_user_id_with_single_quote_does_not_raise_and_returns_no_rows():
    """A user_id containing a single quote is passed as a parameter, not
    interpolated, so it cannot break the query and simply returns no rows."""
    tricky = "o'brien"
    mm = _make_manager()

    # _fetch_candidates — the main retrieval path.
    candidates = await mm._fetch_candidates(
        query="hello",
        pool_size=24,
        importance_min=0.2,
        user_id=tricky,
    )
    assert candidates == []

    # _compute_formation_score — uses user_id in the novelty sub-query.
    score = await mm._compute_formation_score(
        content="hello",
        embedding=[0.0] * 8,
        emotional_signature={"joy": 0.5},
        user_id=tricky,
    )
    assert isinstance(score, float)

    # _create_related_edges — uses user_id in the neighbour query.
    await mm._create_related_edges("memory:abc123", [0.0] * 8, tricky)

    # None of the calls should have raised; the db mock recorded each query
    # call with the user_id carried in the parameters dict, not in the SQL.
    for call in mm.db.query.call_args_list:
        sql, params = call.args[0], (call.args[1] if len(call.args) > 1 else call.kwargs)
        # The literal user_id must never appear in the SQL string itself.
        assert tricky not in sql
