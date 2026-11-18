"""W1-08: stop deleting memories by age.

Before W1-08 the dreaming engine's ``_tiered_pruning`` had a "Tier 3" block
that soft-deleted (``deprecated = true``) every non-core, non-ephemeral
memory whose computed decay had fallen below ``_DECAY_THRESHOLD`` (0.05).
That meant an ordinary episodic memory that was simply old — 60 days, no
recalls — would be marked deprecated and disappear from the active set,
even though the memory PRD (F1) says decay should *rank* memories out of
view, not *remove* them.

After W1-08 the Tier 3 block is gone. Tiers 1 and 2 (which hard-delete
*ephemeral* memories) are unchanged, and ``_compute_decay`` is kept because
retrieval ranking still uses decay. A non-ephemeral memory 60 days old with
no recalls stays ``deprecated = false`` after ``_tiered_pruning``.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from aura.engines.dreaming.engine import DreamingEngine
from tests.conftest import FakeDatabaseClient


def _make_engine(db: FakeDatabaseClient) -> DreamingEngine:
    """Build a DreamingEngine without running ``__init__`` (which would open a
    real database connection) and wire in the fake database."""
    engine = DreamingEngine.__new__(DreamingEngine)
    engine.db = db
    engine.logger = logging.getLogger("aura.engines.dreaming_engine")
    engine._llm_layers = None
    engine._learning_engine = None
    engine.last_dream_cycle = None
    engine.dream_interval = 21600.0
    return engine


@pytest.mark.asyncio
async def test_old_non_ephemeral_memory_survives_pruning():
    """A non-ephemeral memory 60 days old with no recalls is still
    ``deprecated = false`` after ``_tiered_pruning``.

    Before W1-08 the Tier 3 block would have computed a decay well below
    0.05 for such a memory and merged ``deprecated = true`` onto it.
    """
    db = FakeDatabaseClient()

    now = datetime.now(timezone.utc)
    old_ts = (now - timedelta(days=60)).isoformat()

    mid = "memory:old-episodic"
    # Insert directly into the ``memory`` table (the fake db's ``create``
    # keys on the full record id, which would put the row in the wrong
    # table for the query handlers).
    table = db._get_table("memory")
    table[mid] = {
        "id": mid,
        "content": "a walk by the river six weeks ago",
        "ephemeral": False,
        "core_memory": False,
        "deprecated": False,
        "recall_count": 0,
        "emotional_intensity": 0.0,
        "timestamp": old_ts,
        "memory_type": "episodic",
    }

    engine = _make_engine(db)
    pruned = await engine._tiered_pruning()

    # Nothing ephemeral is in the store, so tiers 1 and 2 prune nothing.
    assert pruned == 0
    # The Tier 3 block is gone, so the memory is not soft-deleted.
    assert mid in table
    assert table[mid].get("deprecated") is False


@pytest.mark.asyncio
async def test_tier3_query_is_no_longer_emitted():
    """``_tiered_pruning`` must not send the Tier 3 query (the one selecting
    non-core, non-ephemeral memories for decay-based soft delete). We wrap the
    fake db's ``query`` so every SQL the engine sends is captured, then assert
    none of them match the Tier 3 shape.
    """
    db = FakeDatabaseClient()
    table = db._get_table("memory")
    table["memory:old"] = {
        "id": "memory:old",
        "ephemeral": False,
        "core_memory": False,
        "deprecated": False,
        "recall_count": 0,
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
    }

    queries: list[str] = []
    original_query = db.query

    async def _capture(sql, vars=None):
        queries.append(sql)
        return await original_query(sql, vars)

    db.query = _capture  # type: ignore[assignment]
    engine = _make_engine(db)
    await engine._tiered_pruning()

    for sql in queries:
        low = sql.lower()
        # The Tier 3 query selects non-core, non-ephemeral memories by
        # ``core_memory = false AND ephemeral = false``. No query sent by
        # _tiered_pruning should contain both of those conditions now.
        assert not (
            "core_memory = false" in low and "ephemeral = false" in low
        ), f"Tier 3 query still emitted: {sql}"

    # _compute_decay must still exist (the card forbids removing it).
    assert hasattr(DreamingEngine, "_compute_decay")
