"""W2-15: split the formatting out of ``retrieve_for_l3`` and ``get_cold_start_context``.

Memory M2 needs the Recall Engine to deduplicate and trim items *before* they
are formatted. This card moves the retrieval half of ``retrieve_for_l3`` into
``retrieve_for_l3_parts`` (returning ``(memories, cluster_data)``) and the
cold-start XML builder into ``_format_cold_start_xml``. Both are pure
extractions: the queries, limits, boost behaviour and XML text are unchanged,
and the existing callers ``retrieve_for_l3`` / ``get_cold_start_context`` keep
the same observable output.

The tests build a ``MemoryManager`` via ``__new__`` (so ``__init__`` does not
open a database connection or load the embedding model) with an ``AsyncMock``
db, matching ``tests/unit/test_inject_max_chars.py``.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from aura.engines.memory.manager import MemoryManager
from aura.models.memory import Memory


def _make_manager() -> MemoryManager:
    """Build a MemoryManager without running ``__init__``."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    # _fetch_thought_cluster queries all resolve to no rows, so it returns {}.
    mm.db.query.return_value = []
    mm.embeddings = None
    # Never run the real boost (it would hit the DB via create_task).
    mm._batch_boost_on_recall = AsyncMock()
    return mm


def _make_memories() -> list[Memory]:
    return [
        Memory(memory_id="memory:one", content="the user likes tea", importance=0.6),
        Memory(memory_id="memory:two", content="the user lives in Sofia", importance=0.4),
    ]


# ---------------------------------------------------------------------------
# (a) retrieve_for_l3 == _format_memories_xml(*retrieve_for_l3_parts)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_for_l3_equals_format_of_parts():
    """``retrieve_for_l3`` returns exactly ``_format_memories_xml(*parts)``."""
    mm = _make_manager()
    memories = _make_memories()
    mm.retrieve_memories = AsyncMock(return_value=memories)

    parts_mems, parts_cluster = await mm.retrieve_for_l3_parts(query="q", user_id="u1")
    # Drain the scheduled boost task so it does not leak between tests.
    await asyncio.sleep(0)
    expected_xml = mm._format_memories_xml(parts_mems, parts_cluster)

    result_mems, result_xml = await mm.retrieve_for_l3(query="q", user_id="u1")
    await asyncio.sleep(0)

    assert result_mems == parts_mems == memories
    assert result_xml == expected_xml
    # Sanity: the XML really contains both memories.
    assert "the user likes tea" in result_xml
    assert "the user lives in Sofia" in result_xml


@pytest.mark.asyncio
async def test_retrieve_for_l3_returns_empty_when_no_memories():
    """No memories => ``([], "")``, as before the split."""
    mm = _make_manager()
    mm.retrieve_memories = AsyncMock(return_value=[])

    result_mems, result_xml = await mm.retrieve_for_l3(query="q", user_id="u1")
    await asyncio.sleep(0)

    assert result_mems == []
    assert result_xml == ""


@pytest.mark.asyncio
async def test_retrieve_for_l3_parts_returns_empty_parts_when_no_memories():
    """``retrieve_for_l3_parts`` returns ``([], {})`` when nothing is found."""
    mm = _make_manager()
    mm.retrieve_memories = AsyncMock(return_value=[])

    parts_mems, parts_cluster = await mm.retrieve_for_l3_parts(query="q", user_id="u1")

    assert parts_mems == []
    assert parts_cluster == {}


# ---------------------------------------------------------------------------
# (b) _batch_boost_on_recall is scheduled exactly once per retrieve_for_l3 call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_for_l3_schedules_boost_once_per_call():
    """``_batch_boost_on_recall`` is scheduled exactly once per call, with the
    ids of every returned memory."""
    mm = _make_manager()
    memories = _make_memories()
    mm.retrieve_memories = AsyncMock(return_value=memories)

    await mm.retrieve_for_l3(query="q", user_id="u1")
    await asyncio.sleep(0)

    assert mm._batch_boost_on_recall.call_count == 1
    assert mm._batch_boost_on_recall.await_count == 1
    mm._batch_boost_on_recall.assert_awaited_once_with(["memory:one", "memory:two"])


@pytest.mark.asyncio
async def test_retrieve_for_l3_does_not_boost_when_no_memories():
    """The boost is only scheduled when at least one memory is found."""
    mm = _make_manager()
    mm.retrieve_memories = AsyncMock(return_value=[])

    await mm.retrieve_for_l3(query="q", user_id="u1")
    await asyncio.sleep(0)

    mm._batch_boost_on_recall.assert_not_called()


# ---------------------------------------------------------------------------
# (c) _format_cold_start_xml wrapper
# ---------------------------------------------------------------------------


def test_format_cold_start_xml_empty_lists_still_renders_wrapper():
    """An empty cold start still renders the wrapper, exactly as before."""
    mm = _make_manager()

    xml = mm._format_cold_start_xml([], [], [], None)

    assert xml == "<cold_start_context>\n</cold_start_context>"
