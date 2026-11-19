"""W3-06: the recall gate — rule-only skipping of memory retrieval.

Tests for :func:`aura.engines.recall.gate.needs_recall` and the engine wiring
that reuses the previous packet's memories candidates for a greeting when
``settings.recall_gate_enabled`` is on.

The engine tests use a fake memory manager built with ``MemoryManager.__new__``
(so ``__init__`` opens no database and loads no model), whose
``retrieve_for_l3_parts`` and ``get_cold_start_context`` are mocks, while
``_format_memories_xml`` and ``_format_cold_start_xml`` are the real methods.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.config import settings
from aura.engines.memory.manager import MemoryManager
from aura.engines.recall.engine import RecallEngine
from aura.engines.recall.gate import needs_recall
from aura.engines.recall.models import RecallRequest
from aura.models.learning import Insight, LearningContext
from aura.models.memory import ColdStartContext, Memory

GATE_PHRASES = [
    "hi",
    "hello",
    "hey",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "cool",
    "nice",
    "great",
    "got it",
    "good morning",
    "good night",
    "bye",
    "lol",
    "yes",
    "no",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_manager(
    memories: list[Memory] | None = None,
    cluster_data: dict | None = None,
    cold: ColdStartContext | None = None,
) -> MemoryManager:
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
    latent.get_intuition_context.return_value = xml or ""
    return latent


def _make_memory(memory_id: str, content: str, importance: float = 0.5) -> Memory:
    return Memory(memory_id=memory_id, content=content, importance=importance)


def _request(user_input: str, session_id: str = "s1", **kwargs) -> RecallRequest:
    kwargs.setdefault("include_cold_start", False)
    kwargs.setdefault("include_latent", False)
    return RecallRequest(
        user_id="u1",
        user_input=user_input,
        session_id=session_id,
        **kwargs,
    )


@pytest.fixture
def restore_settings():
    """Snapshot the gate settings and restore them after the test."""
    snapshot = {
        "recall_gate_enabled": settings.recall_gate_enabled,
        "recall_gate_phrases": list(settings.recall_gate_phrases),
        "recall_dedup_enabled": settings.recall_dedup_enabled,
        "recall_budget_enabled": settings.recall_budget_enabled,
    }
    yield
    for key, value in snapshot.items():
        setattr(settings, key, value)


# ---------------------------------------------------------------------------
# needs_recall: rules only
# ---------------------------------------------------------------------------


def test_config_gate_defaults():
    """The flag is off by default and the phrases are the card's list."""
    assert settings.recall_gate_enabled is False
    assert list(settings.recall_gate_phrases) == GATE_PHRASES


@pytest.mark.parametrize("phrase", GATE_PHRASES)
def test_each_phrase_skips(phrase):
    """Every configured phrase reports that it needs no recall."""
    assert needs_recall(phrase) is False


@pytest.mark.parametrize(
    "text",
    [
        "  HeLLo!!!  ",
        "Thanks.",
        "thank you!",
        "Good morning :)",
        "OK...",
        "BYE?",
        "   ",
        "?!",
        "",
    ],
)
def test_punctuation_case_and_whitespace_ignored(text):
    """Case, punctuation and surrounding whitespace do not change the answer."""
    assert needs_recall(text) is False


@pytest.mark.parametrize(
    "text",
    [
        "What's my dog's name?",
        "how are you",
        "hello, what did I say yesterday?",
        "tell me about the project",
    ],
)
def test_questions_and_real_turns_run(text):
    """Anything that is not an empty acknowledgement needs retrieval."""
    assert needs_recall(text) is True


# ---------------------------------------------------------------------------
# Engine wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_greeting_reuses_previous_memories_without_retrieval(restore_settings):
    """A real turn caches its memories; the next greeting reuses them.

    The memories retrieval mock is awaited exactly once, the block text is
    unchanged, and the traces record ``"ran"`` then ``"skipped"``.
    """
    settings.recall_gate_enabled = True

    memories = [_make_memory("memory:dog", "the user's dog is called Biscuit")]
    mm = _make_manager(memories=memories, cluster_data={})
    engine = RecallEngine(memory_manager=mm, latent_engine=_make_latent())

    first = await engine.recall(_request("what is my dog's name?"))
    assert first.trace.gate == "ran"
    assert first.block_text("memories") is not None
    mm.retrieve_for_l3_parts.assert_awaited_once()

    second = await engine.recall(_request("hello!"))
    assert second.trace.gate == "skipped"
    assert second.block_text("memories") == first.block_text("memories")
    assert "Biscuit" in second.block_text("memories")
    # The retrieval was not run again.
    mm.retrieve_for_l3_parts.assert_awaited_once()


@pytest.mark.asyncio
async def test_greeting_with_no_previous_packet_has_empty_memories(restore_settings):
    """With no cached packet for the pair, the skipped block is empty."""
    settings.recall_gate_enabled = True

    mm = _make_manager(memories=[_make_memory("memory:dog", "Biscuit")])
    engine = RecallEngine(memory_manager=mm, latent_engine=_make_latent())

    packet = await engine.recall(_request("hi"))

    assert packet.trace.gate == "skipped"
    assert packet.block_text("memories") is None
    mm.retrieve_for_l3_parts.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_is_per_user_and_session(restore_settings):
    """Another session does not see the first session's cached memories."""
    settings.recall_gate_enabled = True

    mm = _make_manager(memories=[_make_memory("memory:dog", "Biscuit")])
    engine = RecallEngine(memory_manager=mm, latent_engine=_make_latent())

    await engine.recall(_request("what is my dog's name?", session_id="s1"))
    packet = await engine.recall(_request("hello", session_id="s2"))

    assert packet.trace.gate == "skipped"
    assert packet.block_text("memories") is None
    mm.retrieve_for_l3_parts.assert_awaited_once()


@pytest.mark.asyncio
async def test_cache_drops_the_oldest_entry_past_200(restore_settings):
    """After 201 distinct pairs the first is evicted; the last is kept."""
    settings.recall_gate_enabled = True

    mm = _make_manager(memories=[_make_memory("memory:dog", "Biscuit")])
    engine = RecallEngine(memory_manager=mm, latent_engine=_make_latent())

    for i in range(201):
        await engine.recall(_request("tell me about it", session_id=f"s{i}"))

    assert mm.retrieve_for_l3_parts.await_count == 201
    assert len(engine._gate_cache) == 200
    assert ("u1", "s0") not in engine._gate_cache
    assert ("u1", "s200") in engine._gate_cache

    # An evicted pair has no previous packet: the skipped block is empty.
    packet = await engine.recall(_request("hi", session_id="s0"))
    assert packet.trace.gate == "skipped"
    assert packet.block_text("memories") is None
    assert mm.retrieve_for_l3_parts.await_count == 201

    # The newest pair still reuses its packet.
    packet = await engine.recall(_request("hi", session_id="s200"))
    assert packet.block_text("memories") is not None
    assert mm.retrieve_for_l3_parts.await_count == 201


@pytest.mark.asyncio
async def test_flag_off_nothing_changes(restore_settings):
    """Ablation: with the flag off, greetings still retrieve and gate is None."""
    settings.recall_gate_enabled = False

    memories = [_make_memory("memory:dog", "Biscuit")]
    mm = _make_manager(memories=memories, cluster_data={})
    engine = RecallEngine(memory_manager=mm, latent_engine=_make_latent())

    first = await engine.recall(_request("hello"))
    second = await engine.recall(_request("hello"))

    assert first.trace.gate is None
    assert second.trace.gate is None
    assert mm.retrieve_for_l3_parts.await_count == 2
    assert second.block_text("memories") is not None
    # The gate cache is not populated when the flag is off.
    assert len(engine._gate_cache) == 0


@pytest.mark.asyncio
async def test_insights_latent_and_cold_start_are_not_gated(restore_settings):
    """A skipped turn still builds the other three blocks."""
    settings.recall_gate_enabled = True

    insight = Insight(
        insight_id="insight:one",
        content="the user likes tea",
        type="FACT",
        domain="general",
        user_id="u1",
        confidence=0.9,
    )
    learning_context = LearningContext(insights=[insight], mastery_level=0.5)
    cold = ColdStartContext(
        core_memories=[_make_memory("memory:core", "core fact", importance=0.9)],
        recent_memories=[],
        top_insights=[],
        active_cultural_node=None,
        xml_block="<cold_start_context>\n</cold_start_context>",
    )
    mm = _make_manager(memories=[], cluster_data={}, cold=cold)
    engine = RecallEngine(
        memory_manager=mm,
        latent_engine=_make_latent("<latent_intuition>x</latent_intuition>"),
    )

    # Prime the cache with a real turn, then greet.
    await engine.recall(
        _request(
            "what do you remember?",
            learning_context=learning_context,
            include_cold_start=True,
            include_latent=True,
        )
    )
    packet = await engine.recall(
        _request(
            "thanks!",
            learning_context=learning_context,
            include_cold_start=True,
            include_latent=True,
        )
    )

    assert packet.trace.gate == "skipped"
    assert packet.block_text("insights") is not None
    assert packet.block_text("latent") == "<latent_intuition>x</latent_intuition>"
    assert packet.block_text("cold_start") is not None
    # The cold-start store was still called on the skipped turn.
    assert mm.get_cold_start_context.await_count == 2