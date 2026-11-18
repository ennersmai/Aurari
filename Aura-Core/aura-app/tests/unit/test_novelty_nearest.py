"""W1-07: novelty against the nearest memories.

Before W1-07 the novelty block in ``_compute_formation_score`` selected the five
*most recent* memories (``ORDER BY timestamp DESC LIMIT 5``) and recomputed the
cosine similarity to each in Python. That meant a new memory that was identical
to an old one from long ago was never compared against it (the old memory was not
in the recent five), so it received no novelty penalty.

After W1-07 the block selects the five *most similar* memories
(``ORDER BY sim DESC LIMIT 5``) using SurrealDB's
``vector::similarity::cosine(embedding, $emb) AS sim`` and uses the returned
``sim`` directly. So an identical old memory is now picked up and penalised,
while a genuinely novel memory still scores novelty 1.0 even when the five most
recent memories are all about one (unrelated) topic.
"""

import pytest
from unittest.mock import AsyncMock

from aura.engines.memory.manager import MemoryManager


def _make_manager(rows_for_query: list[dict]) -> MemoryManager:
    """Build a MemoryManager whose db.query returns ``rows_for_query``.

    The novelty block is the first ``db.query`` call inside
    ``_compute_formation_score`` (the surprise block may issue a second one),
    so returning a fixed list from the mock is enough to drive both tests.
    """
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    mm.db.query.return_value = rows_for_query
    mm.embeddings = AsyncMock()
    return mm


def _formation_score(novelty: float) -> float:
    """Reproduce the formation-score formula with the other three signals
    pinned to their defaults so the score reflects only ``novelty``.

    In ``_compute_formation_score``:
        emo_intensity = _compute_emotional_intensity({}) == 0.0
        depth         = 0.3 * 0.5 + 0.0 + 0.0 == 0.15   (response_length=0)
        surprise      = 0.5                              (no pre_retrieval_ids)
        score = novelty*0.30 + 0.0*0.30 + 0.15*0.20 + 0.5*0.20
    """
    return novelty * 0.30 + 0.0 * 0.30 + 0.15 * 0.20 + 0.5 * 0.20


@pytest.mark.asyncio
async def test_identical_old_memory_gets_heavy_penalty():
    """A new memory identical (sim > 0.88) to an old one is now selected because
    the query orders by similarity, not recency, so it receives the heavy
    novelty penalty (novelty drops from 1.0 to 0.6)."""
    # The db returns one row whose sim is above the 0.88 heavy-penalty threshold.
    rows = [{"embedding": [0.1] * 8, "sim": 0.95}]
    mm = _make_manager(rows)

    score = await mm._compute_formation_score(
        content="the user lives in sofia",
        embedding=[0.1] * 8,
        emotional_signature={},
        user_id="u1",
    )
    # novelty should be 1.0 - 0.4 == 0.6
    assert score == pytest.approx(_formation_score(0.6))


@pytest.mark.asyncio
async def test_novel_memory_gets_full_novelty_even_when_recent_five_share_a_topic():
    """A new memory unlike anything stored gets novelty 1.0 even when the five
    memories the query returns are all about one (different) topic. Because the
    query now orders by similarity, those five are simply the *least dissimilar*
    memories; if none crosses the 0.75 penalty threshold, novelty stays 1.0."""
    # Five recent memories about "cats", all with low similarity to the new
    # memory about "quantum computing". sim values are below 0.75.
    rows = [
        {"embedding": [0.0] * 8, "sim": 0.12},
        {"embedding": [0.0] * 8, "sim": 0.10},
        {"embedding": [0.0] * 8, "sim": 0.08},
        {"embedding": [0.0] * 8, "sim": 0.05},
        {"embedding": [0.0] * 8, "sim": 0.01},
    ]
    mm = _make_manager(rows)

    score = await mm._compute_formation_score(
        content="quantum entanglement explained",
        embedding=[0.9] * 8,
        emotional_signature={},
        user_id="u1",
    )
    # novelty stays 1.0 -> no penalty applied
    assert score == pytest.approx(_formation_score(1.0))


@pytest.mark.asyncio
async def test_medium_similarity_gets_light_penalty():
    """A memory whose nearest neighbour sits between the two thresholds
    (0.75 < sim <= 0.88) gets the light penalty (novelty 1.0 -> 0.85)."""
    rows = [{"embedding": [0.2] * 8, "sim": 0.80}]
    mm = _make_manager(rows)

    score = await mm._compute_formation_score(
        content="the user likes tea",
        embedding=[0.2] * 8,
        emotional_signature={},
        user_id="u1",
    )
    # novelty should be 1.0 - 0.15 == 0.85
    assert score == pytest.approx(_formation_score(0.85))


@pytest.mark.asyncio
async def test_novelty_query_orders_by_sim_not_timestamp():
    """The SurrealQL the novelty block sends must order by ``sim`` (the cosine
    similarity alias) and select ``sim`` via ``vector::similarity::cosine``;
    it must no longer order by ``timestamp`` or recompute cosine in Python."""
    rows = [{"embedding": [0.0] * 8, "sim": 0.10}]
    mm = _make_manager(rows)

    await mm._compute_formation_score(
        content="something new",
        embedding=[0.5] * 8,
        emotional_signature={},
        user_id="u1",
    )

    # The first db.query call is the novelty block.
    sql = mm.db.query.call_args_list[0].args[0]
    assert "vector::similarity::cosine(embedding, $emb) AS sim" in sql
    assert "ORDER BY sim DESC" in sql
    assert "ORDER BY timestamp DESC" not in sql
    # The new embedding is passed as the $emb parameter, not interpolated.
    params = mm.db.query.call_args_list[0].args[1]
    assert params.get("emb") == [0.5] * 8
