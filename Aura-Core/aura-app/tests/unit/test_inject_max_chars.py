"""W1-12: cap injected memory length.

Memory PRD section 2.3: injected memory context could be arbitrarily long,
blowing out the L3 prompt. This card adds a ``memory_inject_max_chars``
setting (default 600) and truncates each memory's ``content`` to that length
in both ``_format_memories_xml`` and the XML built by
``get_cold_start_context``, appending ``...`` when the content is cut. It also
limits cold-start core memories to the 10 highest by importance.

What is stored is never truncated — only what is injected into the prompt.
"""

import pytest
from unittest.mock import AsyncMock

from aura.config import settings
from aura.engines.memory.manager import MemoryManager, _truncate_for_inject
from aura.models.memory import Memory


def _make_manager() -> MemoryManager:
    """Build a MemoryManager without running ``__init__`` (which would open a
    real database connection and load the embedding model)."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    mm.embeddings = None
    return mm


def _make_memory(content: str, memory_id: str = "memory:abc") -> Memory:
    return Memory(
        memory_id=memory_id,
        content=content,
    )


# ---------------------------------------------------------------------------
# _truncate_for_inject / _format_memories_xml
# ---------------------------------------------------------------------------


def test_truncate_helper_caps_at_setting_and_appends_marker():
    """A string longer than ``memory_inject_max_chars`` is cut to that length
    and ``...`` is appended; a shorter string is returned unchanged."""
    long_text = "x" * 5000
    out = _truncate_for_inject(long_text)
    assert len(out) == settings.memory_inject_max_chars + len("...")
    assert out.endswith("...")
    assert out[: settings.memory_inject_max_chars] == "x" * settings.memory_inject_max_chars

    short_text = "x" * 100
    assert _truncate_for_inject(short_text) == short_text


def test_format_memories_xml_truncates_long_memory_to_max_chars_plus_marker():
    """The card's test: a 5,000-character memory is injected as 600 characters
    plus the ``...`` marker."""
    assert settings.memory_inject_max_chars == 600

    mm = _make_manager()
    long_content = "y" * 5000
    mem = _make_memory(long_content, memory_id="memory:long1")

    xml = mm._format_memories_xml([mem], cluster_data={})

    # The non-cluster branch emits ``<memory ...>{content}</memory>``.
    assert "<memory " in xml
    # The injected content is exactly 600 chars + the marker.
    assert "y" * settings.memory_inject_max_chars + "..." in xml
    # The full 5,000-char content must NOT appear.
    assert long_content not in xml


def test_format_memories_xml_short_memory_is_not_truncated():
    """A memory shorter than the cap is injected verbatim, with no marker."""
    mm = _make_manager()
    short_content = "the user likes tea"
    mem = _make_memory(short_content, memory_id="memory:short1")

    xml = mm._format_memories_xml([mem], cluster_data={})

    assert short_content in xml
    assert "..." not in xml


def test_format_memories_xml_truncates_inside_thought_cluster():
    """When a memory has cluster data, its content is emitted inside a
    ``<core_memory>`` element; that content must also be truncated."""
    mm = _make_manager()
    long_content = "z" * 5000
    mem = _make_memory(long_content, memory_id="memory:cluster1")

    xml = mm._format_memories_xml(
        [mem],
        cluster_data={"memory:cluster1": {"timeline_before": []}},
    )

    assert "<core_memory>" in xml
    assert "z" * settings.memory_inject_max_chars + "..." in xml
    assert long_content not in xml


# ---------------------------------------------------------------------------
# get_cold_start_context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cold_start_xml_truncates_core_and_recent_content():
    """Both the ``<core_memories>`` and ``<recent_context>`` sections of the
    cold-start XML truncate content to ``memory_inject_max_chars`` plus the
    marker."""
    mm = _make_manager()

    long_core = "c" * 5000
    long_recent = "r" * 5000

    core_row = {
        "id": "memory:core1",
        "memory_id": "memory:core1",
        "content": long_core,
        "core_memory": True,
        "importance": 0.9,
    }
    recent_row = {
        "id": "memory:recent1",
        "memory_id": "memory:recent1",
        "content": long_recent,
        "ephemeral": False,
        "importance": 0.5,
    }

    # get_cold_start_context issues 5 queries in this order via gather:
    #   0. core memories      -> [core_row]
    #   1. recent memories    -> [recent_row]
    #   2. insights           -> []
    #   3. cultural node       -> []
    #   4. emotion baseline   -> []
    mm.db.query.side_effect = [
        [core_row],
        [recent_row],
        [],
        [],
        [],
    ]

    ctx = await mm.get_cold_start_context(user_id="u1")

    cap = settings.memory_inject_max_chars
    assert "c" * cap + "..." in ctx.xml_block
    assert "r" * cap + "..." in ctx.xml_block
    assert long_core not in ctx.xml_block
    assert long_recent not in ctx.xml_block


@pytest.mark.asyncio
async def test_cold_start_core_memories_query_limited_to_ten():
    """The core-memories query must now carry ``LIMIT 10`` (the 10 highest by
    importance). The query already orders by ``importance DESC``."""
    mm = _make_manager()

    mm.db.query.side_effect = [
        [],   # core memories
        [],   # recent memories
        [],   # insights
        [],   # cultural node
        [],   # emotion baseline
    ]

    await mm.get_cold_start_context(user_id="u1")

    # The first db.query call is the core-memories query.
    core_call = mm.db.query.call_args_list[0]
    sql = core_call.args[0]
    assert "FROM memory" in sql
    assert "core_memory = true" in sql
    assert "ORDER BY importance DESC" in sql
    assert "LIMIT 10" in sql
