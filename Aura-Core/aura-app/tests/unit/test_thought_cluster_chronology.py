"""W1-11: correct the chronology in thought clusters.

Memory PRD F10: the chronology built by ``_fetch_thought_cluster`` picked the
*globally latest* experience when a memory had no ``conversation_id``, and when
it did have one it picked the latest experience in that conversation regardless
of whether that experience was later than the memory itself. So a memory from
the second turn of a conversation could be paired with the fifth turn's
experience, producing a backwards chronology.

This card makes two changes in ``_fetch_thought_cluster``:

1. If the memory has no ``conversation_id``, the chronology section is skipped
   entirely (the branch that took the globally latest experience is removed).
2. When the memory has a ``conversation_id``, the experience selected is the one
   in that conversation with the latest timestamp that is not later than the
   memory's own timestamp (``AND timestamp <= $ts``, ``ORDER BY timestamp DESC
   LIMIT 1``).

The tests below drive ``_fetch_thought_cluster`` with a mocked database whose
``query`` returns a scripted sequence of rows, so the chronology wiring can be
exercised without a real SurrealDB.
"""

import pytest
from unittest.mock import AsyncMock

from aura.engines.memory.manager import MemoryManager


def _make_manager() -> tuple[MemoryManager, AsyncMock]:
    """Build a MemoryManager without running ``__init__`` and give it an
    AsyncMock database whose ``query`` calls the tests script via
    ``side_effect``."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    mm.embeddings = None
    return mm, mm.db


# Timestamps for a five-turn conversation, one minute apart.
T1 = "2026-01-01T10:00:00Z"
T2 = "2026-01-01T10:01:00Z"
T3 = "2026-01-01T10:02:00Z"
T4 = "2026-01-01T10:03:00Z"
T5 = "2026-01-01T10:04:00Z"

CONV = "conv-abc"
MID = "memory:from-turn-2"


@pytest.mark.asyncio
async def test_memory_from_second_turn_gets_first_as_before_and_third_as_after():
    """In a conversation with five experiences, a memory whose timestamp is the
    second turn selects the second experience as its anchor (the latest
    experience not later than the memory). Traversing ``next_experience`` edges
    from that anchor yields the first experience as "before" and the third as
    "after"."""
    mm, db = _make_manager()

    # _fetch_thought_cluster issues db.query calls in this order:
    #   0. abstracted_into out   -> []  (no abstractions)
    #   1. abstracted_into in    -> []  (no sources)
    #   2. mem_row               -> the memory row (conv_id + timestamp)
    #   3. exp_match              -> the second experience (latest <= mem_ts)
    #   4. after (next_experience out from exp2) -> the third experience
    #   5. before (next_experience in to exp2)    -> the first experience
    db.query.side_effect = [
        [],                                          # abstractions out
        [],                                          # sources in
        [{"conversation_id": CONV, "timestamp": T2}],  # the memory row
        [{"id": "experience:turn-2"}],               # exp_match: second turn
        [                                            # after: third turn
            {
                "prompt": "turn three question",
                "domain": "general",
                "timestamp": T3,
            },
        ],
        [                                            # before: first turn
            {
                "prompt": "turn one question",
                "domain": "general",
                "timestamp": T1,
            },
        ],
    ]

    cluster = await mm._fetch_thought_cluster(MID)

    # The second experience is the anchor; the first turn is "before" it and
    # the third turn is "after" it.
    assert cluster.get("timeline_before") == [
        {"prompt": "turn one question", "domain": "general", "timestamp": T1},
    ]
    assert cluster.get("timeline_after") == [
        {"prompt": "turn three question", "domain": "general", "timestamp": T3},
    ]
    # No abstractions or sources were returned.
    assert "abstractions" not in cluster
    assert "sources" not in cluster


@pytest.mark.asyncio
async def test_memory_with_no_conversation_gets_no_chronology():
    """A memory with no ``conversation_id`` skips the chronology section
    entirely: no experience query is sent and the cluster has no
    ``timeline_before`` / ``timeline_after`` keys."""
    mm, db = _make_manager()

    # Only the abstraction / source queries and the mem_row query are issued;
    # the chronology section is skipped because conv_id is None.
    db.query.side_effect = [
        [],                                          # abstractions out
        [],                                          # sources in
        [{"conversation_id": None, "timestamp": T2}],  # memory row, no conv
    ]

    cluster = await mm._fetch_thought_cluster(MID)

    assert "timeline_before" not in cluster
    assert "timeline_after" not in cluster

    # Exactly three queries: abstractions-out, sources-in, mem_row. No
    # experience / next_experience queries.
    assert db.query.await_count == 3


@pytest.mark.asyncio
async def test_experience_query_is_scoped_to_conversation_and_bounded_by_memory_ts():
    """The experience-selection query must be scoped to the memory's
    conversation (``$cid``) and bounded by the memory's own timestamp
    (``AND timestamp <= $ts``), ordered by ``timestamp DESC LIMIT 1``. It must
    no longer take the globally latest experience."""
    mm, db = _make_manager()

    db.query.side_effect = [
        [],                                            # abstractions out
        [],                                            # sources in
        [{"conversation_id": CONV, "timestamp": T2}],  # memory row
        [{"id": "experience:turn-2"}],                 # exp_match
        [],                                            # after
        [],                                            # before
    ]

    await mm._fetch_thought_cluster(MID)

    # The 4th db.query call (index 3) is the experience-selection query.
    exp_call = db.query.await_args_list[3]
    sql = exp_call.args[0]
    params = exp_call.args[1]

    assert "FROM experience" in sql
    assert "context.conversation_id = $cid" in sql
    assert "metadata.conversation_id = $cid" in sql
    assert "AND timestamp <= $ts" in sql
    assert "ORDER BY timestamp DESC" in sql
    assert "LIMIT 1" in sql
    # Parameters carry the conversation id and the memory's timestamp.
    assert params.get("cid") == CONV
    assert params.get("ts") == T2

    # The removed branch must not appear: no globally-latest experience query.
    assert "context.user_query != NONE" not in sql
    # No query sent by this function should select the globally latest
    # experience.
    for call in db.query.await_args_list:
        assert "context.user_query != NONE" not in call.args[0]
