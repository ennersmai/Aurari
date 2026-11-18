"""W1-09: semantic memories do not fade.

Memory PRD F4: semantic memories are generalised knowledge, not episodes,
so they must not decay out of the active set simply because they are old.

This card makes two decay functions return 1.0 for semantic memories and
excludes ``memory_type = 'semantic'`` from the tier 1 / tier 2 pruning
queries in ``DreamingEngine._tiered_pruning`` (which hard-delete ephemeral
memories). A semantic memory 90 days old therefore has decay 1.0 and
survives a pruning pass.
"""

import logging
from datetime import datetime, timedelta, timezone

import pytest

from aura.engines.dreaming.engine import DreamingEngine
from aura.engines.memory.manager import MemoryManager
from tests.conftest import FakeDatabaseClient


def _make_dreaming_engine(db: FakeDatabaseClient) -> DreamingEngine:
    """Build a DreamingEngine without running ``__init__`` (which would open
    a real database connection) and wire in the fake database."""
    engine = DreamingEngine.__new__(DreamingEngine)
    engine.db = db
    engine.logger = logging.getLogger("aura.engines.dreaming_engine")
    engine._llm_layers = None
    engine._learning_engine = None
    engine.last_dream_cycle = None
    engine.dream_interval = 21600.0
    return engine


def _semantic_row(age_days: int) -> dict:
    """A semantic memory row ``age_days`` old, not core, not ephemeral."""
    now = datetime.now(timezone.utc)
    return {
        "id": "memory:sem-90",
        "content": "the user prefers concise answers",
        "memory_type": "semantic",
        "ephemeral": False,
        "core_memory": False,
        "deprecated": False,
        "recall_count": 0,
        "emotional_intensity": 0.0,
        "timestamp": (now - timedelta(days=age_days)).isoformat(),
    }


# ---------------------------------------------------------------------------
# Decay returns 1.0 for semantic memories
# ---------------------------------------------------------------------------

def test_memory_manager_decay_factor_is_one_for_semantic():
    """``MemoryManager._compute_decay_factor`` returns 1.0 for a semantic
    memory regardless of age, in the same place the core check returns 1.0."""
    mm = MemoryManager.__new__(MemoryManager)
    row = _semantic_row(90)
    assert mm._compute_decay_factor(row) == 1.0


def test_dreaming_engine_decay_is_one_for_semantic():
    """``DreamingEngine._compute_decay`` returns 1.0 for a semantic memory
    regardless of age."""
    row = _semantic_row(90)
    assert DreamingEngine._compute_decay(row) == 1.0


def test_episodic_memory_still_decays():
    """Sanity check: an episodic memory of the same age is *not* treated as
    immune — the semantic short-circuit only fires on ``memory_type ==
    'semantic'``."""
    mm = MemoryManager.__new__(MemoryManager)
    row = _semantic_row(90)
    row["memory_type"] = "episodic"
    # A 90-day-old episodic memory with no recalls decays to ~0.
    assert mm._compute_decay_factor(row) < 0.05
    assert DreamingEngine._compute_decay(row) < 0.05


# ---------------------------------------------------------------------------
# Pruning does not touch semantic memories
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_semantic_memory_survives_pruning():
    """A semantic memory 90 days old is still present and
    ``deprecated = false`` after ``_tiered_pruning``."""
    db = FakeDatabaseClient()
    table = db._get_table("memory")
    mid = "memory:sem-90"
    table[mid] = _semantic_row(90)

    engine = _make_dreaming_engine(db)
    pruned = await engine._tiered_pruning()

    # Nothing ephemeral is in the store, so tiers 1 and 2 prune nothing.
    assert pruned == 0
    # The semantic memory survives untouched.
    assert mid in table
    assert table[mid].get("deprecated") is False


@pytest.mark.asyncio
async def test_tier_queries_exclude_semantic():
    """The tier 1 and tier 2 pruning queries must exclude
    ``memory_type = 'semantic'``. Capture every SQL the engine sends and
    assert the ephemeral-pruning queries carry the exclusion."""
    db = FakeDatabaseClient()
    table = db._get_table("memory")
    table["memory:sem-90"] = _semantic_row(90)

    queries: list[str] = []
    original_query = db.query

    async def _capture(sql, vars=None):
        queries.append(sql)
        return await original_query(sql, vars)

    db.query = _capture  # type: ignore[assignment]
    engine = _make_dreaming_engine(db)
    await engine._tiered_pruning()

    ephemeral_prune_queries = [
        sql for sql in queries
        if "from memory" in sql.lower() and "ephemeral = true" in sql.lower()
    ]
    assert ephemeral_prune_queries, "expected tier 1/tier 2 pruning queries"
    for sql in ephemeral_prune_queries:
        assert "memory_type != 'semantic'" in sql.lower(), (
            f"tier pruning query does not exclude semantic memories: {sql}"
        )
