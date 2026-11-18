"""W2-17: ``RecallEngine.recall`` — one entry point over today's channels.

Tests for :class:`aura.engines.recall.engine.RecallEngine`. The engine wires
today's four read-path stores (insights, latent, cold-start, retrieved
memories) into the budgeted assembly step from W2-14. It builds
:class:`Candidate` lists from each channel, calls :func:`assemble`, and wraps
the result blocks into a :class:`ContextPacket` with a trace.

The tests use a fake memory manager whose ``retrieve_for_l3_parts`` and
``get_cold_start_context`` are mocks, while ``_format_cold_start_xml`` and
``_format_memories_xml`` are the real ``MemoryManager`` methods (the manager is
built with ``MemoryManager.__new__`` so ``__init__`` does not open a database or
load the embedding model), plus a fake latent engine. This lets the
byte-identical pass-through cases (a) verify the engine does not reformat
anything the channels return.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.clock import FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.manager import MemoryManager
from aura.engines.recall.engine import RecallEngine
from aura.engines.recall.models import RecallRequest
from aura.models.learning import Insight, LearningContext
from aura.models.memory import ColdStartContext, Memory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(
    memories: list[Memory] | None = None,
    cluster_data: dict | None = None,
    cold: ColdStartContext | None = None,
) -> MemoryManager:
    """Build a MemoryManager without running ``__init__``.

    ``retrieve_for_l3_parts`` and ``get_cold_start_context`` are mocks that
    return the provided values; ``_format_cold_start_xml`` and
    ``_format_memories_xml`` are the real ``MemoryManager`` methods, so the
    pass-through cases (a) can assert byte-identical output.
    """
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    mm.embeddings = None
    mm.retrieve_for_l3_parts = AsyncMock(
        return_value=(memories or [], cluster_data or {})
    )
    mm.get_cold_start_context = AsyncMock(return_value=cold or ColdStartContext())
    return mm


def _make_latent(xml: str | None = None) -> MagicMock:
    latent = MagicMock()
    if xml is None:
        latent.get_intuition_context.return_value = ""
    else:
        latent.get_intuition_context.return_value = xml
    return latent


def _make_memory(memory_id: str, content: str, importance: float = 0.5) -> Memory:
    return Memory(memory_id=memory_id, content=content, importance=importance)


def _make_insight(insight_id: str, content: str, confidence: float = 0.8) -> Insight:
    return Insight(
        insight_id=insight_id,
        content=content,
        type="FACT",
        domain="general",
        user_id="u1",
        confidence=confidence,
    )


@pytest.fixture
def restore_settings():
    """Snapshot the recall settings and restore them after the test, so a
    monkeypatched budget/dedup flag does not leak across tests."""
    snapshot = {
        "recall_dedup_enabled": settings.recall_dedup_enabled,
        "recall_budget_enabled": settings.recall_budget_enabled,
        "recall_token_budget": settings.recall_token_budget,
        "recall_trace_keep": settings.recall_trace_keep,
    }
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


# ---------------------------------------------------------------------------
# (a) byte-identical pass-through with dedup and budget disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_passthrough_memories_and_cold_start_match_real_formatters(
    restore_settings,
):
    """With dedup and budget disabled, ``block_text("memories")`` equals
    ``_format_memories_xml(memories, cluster_data)`` and
    ``block_text("cold_start")`` equals the cold context's ``xml_block`` — the
    byte-identical pass-through cases."""
    settings.recall_dedup_enabled = False
    settings.recall_budget_enabled = False

    memories = [
        _make_memory("memory:one", "the user likes tea", importance=0.6),
        _make_memory("memory:two", "the user lives in Sofia", importance=0.4),
    ]
    cluster_data = {"memory:one": {"abstractions": [{"content": "x"}]}}

    cold_xml = (
        "<cold_start_context>\n"
        "  <core_memories>\n"
        "    <memory importance='0.90'>core fact</memory>\n"
        "  </core_memories>\n"
        "</cold_start_context>"
    )
    cold = ColdStartContext(
        core_memories=[_make_memory("memory:core", "core fact", importance=0.9)],
        recent_memories=[],
        top_insights=[],
        active_cultural_node=None,
        xml_block=cold_xml,
    )
    mm = _make_manager(memories=memories, cluster_data=cluster_data, cold=cold)
    latent = _make_latent()

    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    request = RecallRequest(
        user_id="u1",
        user_input="hello",
        include_cold_start=True,
        include_latent=False,
        depth=2,
        limit=5,
    )
    packet = await engine.recall(request)

    expected_memories_xml = mm._format_memories_xml(memories, cluster_data)
    assert packet.block_text("memories") == expected_memories_xml
    assert packet.block_text("cold_start") == cold_xml
    assert packet.block_text("latent") is None  # include_latent=False
    assert packet.block_text("insights") is None  # no learning context
    assert packet.abstain is False


# ---------------------------------------------------------------------------
# (b) a memory in both cold-start recent and retrieved memories appears once,
#     in cold_start; the second copy is a duplicate; tokens_after < tokens_before
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b_overlapping_memory_kept_once_in_cold_start(restore_settings):
    """A memory that is in both cold-start recent and the retrieved memories
    appears once, in ``cold_start`` (which comes before ``memories`` in
    ``BLOCK_ORDER``). The trace marks the memories copy ``duplicate``, and
    ``tokens_after < tokens_before``."""
    shared = _make_memory("memory:shared", "the user likes tea", importance=0.6)
    memories = [shared]
    cold = ColdStartContext(
        core_memories=[],
        recent_memories=[shared],
        top_insights=[],
        active_cultural_node=None,
        xml_block="",
    )
    mm = _make_manager(memories=memories, cluster_data={}, cold=cold)
    latent = _make_latent()

    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    request = RecallRequest(
        user_id="u1",
        user_input="tea",
        include_cold_start=True,
        include_latent=False,
        depth=1,
        limit=5,
    )
    packet = await engine.recall(request)

    # The shared memory appears in cold_start but not in the memories block
    # (it was deduplicated because cold_start comes first in BLOCK_ORDER and
    # the two share the "mem:memory:shared" dedup key).
    assert packet.block_text("cold_start") is not None
    assert "the user likes tea" in packet.block_text("cold_start")
    memories_block = packet.block_text("memories")
    if memories_block is not None:
        assert "the user likes tea" not in memories_block

    trace = packet.trace
    fates = {item.key: item.fate for item in trace.items}
    # The memories-block candidate for the shared memory is a duplicate.
    assert fates.get("memory:shared") == "duplicate"
    assert trace.tokens_after < trace.tokens_before


# ---------------------------------------------------------------------------
# (c) an insight whose text equals a cold-start top insight (after
#     normalisation) is kept in insights and dropped from cold_start
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_c_insight_text_matching_cold_start_top_insight_dedups_cold_start(
    restore_settings,
):
    """An insight whose text equals a cold-start top insight (after case and
    whitespace normalisation) is kept in ``insights`` (which comes first in
    ``BLOCK_ORDER``) and dropped from ``cold_start``."""
    settings.recall_dedup_enabled = True
    settings.recall_budget_enabled = False  # isolate dedup behaviour

    text = "The User  Lives   in Sofia"  # case/whitespace differences
    insight = _make_insight("insight:one", text, confidence=0.9)
    learning_context = LearningContext(insights=[insight], mastery_level=0.5)

    cold_insight_dict = {"content": "the user lives in sofia", "type": "FACT", "confidence": 0.9}
    cold = ColdStartContext(
        core_memories=[],
        recent_memories=[],
        top_insights=[cold_insight_dict],
        active_cultural_node=None,
        xml_block="",
    )
    mm = _make_manager(memories=[], cluster_data={}, cold=cold)
    latent = _make_latent()

    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    request = RecallRequest(
        user_id="u1",
        user_input="sofia",
        learning_context=learning_context,
        include_cold_start=True,
        include_latent=False,
        depth=1,
        limit=5,
    )
    packet = await engine.recall(request)

    # The insight is kept in the insights block.
    assert packet.block_text("insights") is not None
    assert "The User  Lives   in Sofia" in packet.block_text("insights")

    # The cold-start block still renders its wrapper, but the top insight that
    # shared the insight's normalised text is dropped — so it does not appear
    # in the cold-start block.
    cold_text = packet.block_text("cold_start")
    assert cold_text is not None  # wrapper still present
    assert "the user lives in sofia" not in cold_text.lower()

    trace = packet.trace
    fates = {item.key: item.fate for item in trace.items}
    # The cold-start top insight is a duplicate of the insight.
    assert fates.get("cold_insight:0") == "duplicate"


# ---------------------------------------------------------------------------
# (d) a tiny token_budget drops memories from the end; the first survives
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_d_tiny_budget_drops_memories_from_end_first_survives(
    restore_settings,
):
    """A tiny ``token_budget`` drops memories from the end (fate
    ``over_budget``). The first memory survives when it fits."""
    settings.recall_dedup_enabled = False
    settings.recall_budget_enabled = True

    memories = [
        _make_memory("memory:aaa", "aaa", importance=0.5),
        _make_memory("memory:bbb", "bbb", importance=0.5),
        _make_memory("memory:ccc", "ccc", importance=0.5),
    ]
    mm = _make_manager(memories=memories, cluster_data={})
    latent = _make_latent()

    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    # The memories renderer is the real ``_format_memories_xml``: one memory
    # renders to ~28 tokens (the ``<relevant_memories>`` wrapper plus the
    # ``<memory timestamp='...' importance='0.50'>aaa</memory>`` line), and two
    # memories render to ~45 tokens. The memories block share is 0.45 of the
    # budget, so a ``token_budget`` of 70 gives an allowance of
    # ``int(70 * 0.45) == 31`` tokens — enough for the first memory alone (28)
    # but not for the first two joined (45), so bbb and ccc are dropped from
    # the end as ``over_budget`` and aaa survives.
    request = RecallRequest(
        user_id="u1",
        user_input="query",
        token_budget=70,
        include_cold_start=False,
        include_latent=False,
        depth=1,
        limit=5,
    )
    packet = await engine.recall(request)

    trace = packet.trace
    fates = {item.key: item.fate for item in trace.items}
    assert fates["memory:aaa"] == "kept"
    assert fates["memory:bbb"] == "over_budget"
    assert fates["memory:ccc"] == "over_budget"

    memories_text = packet.block_text("memories")
    assert memories_text is not None
    assert "aaa" in memories_text
    assert "bbb" not in memories_text
    assert "ccc" not in memories_text


# ---------------------------------------------------------------------------
# (e) retrieve_for_l3_parts raising leaves channel_errors["memories"] set and
#     still returns the other blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e_memories_channel_failure_records_error_keeps_other_blocks(
    restore_settings,
):
    """If ``retrieve_for_l3_parts`` raises, ``channel_errors["memories"]`` is
    set and the other blocks are still returned."""
    settings.recall_dedup_enabled = False
    settings.recall_budget_enabled = False

    mm = MemoryManager.__new__(MemoryManager)
    mm.db = AsyncMock()
    mm.embeddings = None
    mm.retrieve_for_l3_parts = AsyncMock(side_effect=RuntimeError("db down"))
    mm.get_cold_start_context = AsyncMock(
        return_value=ColdStartContext(
            core_memories=[_make_memory("memory:core", "core fact", importance=0.9)],
            recent_memories=[],
            top_insights=[],
            active_cultural_node=None,
            xml_block="<cold_start_context>\n</cold_start_context>",
        )
    )
    latent = _make_latent("<latent_intuition>x</latent_intuition>")

    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    request = RecallRequest(
        user_id="u1",
        user_input="hello",
        include_cold_start=True,
        include_latent=True,
        depth=2,
        limit=5,
    )
    packet = await engine.recall(request)

    assert packet.trace.channel_errors.get("memories") == "db down"
    # The other blocks still came through.
    assert packet.block_text("cold_start") is not None
    assert packet.block_text("latent") == "<latent_intuition>x</latent_intuition>"


# ---------------------------------------------------------------------------
# (f) include_cold_start=False means get_cold_start_context is not awaited;
#     include_latent=False means get_intuition_context is not called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_f_include_flags_gate_channels(restore_settings):
    """``include_cold_start=False`` means ``get_cold_start_context`` is not
    awaited. ``include_latent=False`` means ``get_intuition_context`` is not
    called."""
    settings.recall_dedup_enabled = False
    settings.recall_budget_enabled = False

    mm = _make_manager(memories=[], cluster_data={})
    latent = _make_latent("<latent_intuition>x</latent_intuition>")

    engine = RecallEngine(memory_manager=mm, latent_engine=latent)
    request = RecallRequest(
        user_id="u1",
        user_input="hello",
        include_cold_start=False,
        include_latent=False,
        depth=1,
        limit=5,
    )
    await engine.recall(request)

    mm.get_cold_start_context.assert_not_awaited()
    latent.get_intuition_context.assert_not_called()


# ---------------------------------------------------------------------------
# (g) recall_trace_keep=2 keeps only the last two traces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_g_trace_cap_keeps_last_two(restore_settings):
    """With ``recall_trace_keep`` monkeypatched to 2, three recalls leave only
    the last two traces, and ``get_trace`` returns ``None`` for the first."""
    settings.recall_trace_keep = 2
    settings.recall_dedup_enabled = False
    settings.recall_budget_enabled = False

    mm = _make_manager(memories=[], cluster_data={})
    latent = _make_latent()
    engine = RecallEngine(memory_manager=mm, latent_engine=latent)

    turn_ids: list[str] = []
    for _ in range(3):
        request = RecallRequest(
            user_id="u1",
            user_input="hello",
            include_cold_start=False,
            include_latent=False,
            depth=1,
            limit=5,
        )
        packet = await engine.recall(request)
        turn_ids.append(packet.trace.turn_id)

    # The first turn was evicted; the last two are kept.
    assert engine.get_trace(turn_ids[0]) is None
    assert engine.get_trace(turn_ids[1]) is not None
    assert engine.get_trace(turn_ids[2]) is not None


# ---------------------------------------------------------------------------
# (h) created_at equals the FakeClock's time
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_h_created_at_uses_clock(restore_settings):
    """``trace.created_at`` equals the installed ``FakeClock``'s time."""
    settings.recall_dedup_enabled = False
    settings.recall_budget_enabled = False

    fixed = datetime(2026, 3, 14, 15, 9, 26, tzinfo=timezone.utc)
    fake = FakeClock(fixed)
    set_clock(fake)
    try:
        mm = _make_manager(memories=[], cluster_data={})
        latent = _make_latent()
        engine = RecallEngine(memory_manager=mm, latent_engine=latent)
        request = RecallRequest(
            user_id="u1",
            user_input="hello",
            include_cold_start=False,
            include_latent=False,
            depth=1,
            limit=5,
        )
        packet = await engine.recall(request)
    finally:
        set_clock(FakeClock())  # restore a non-deterministic clock

    assert packet.trace.created_at == fixed
