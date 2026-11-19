"""Scenario tests for the M3 fast path: noise, abstention, gate and latency (W3-08).

The three M3 flags (``recall_channels_enabled``, ``recall_gate_enabled`` and
``recall_abstain_enabled``) are switched on with ``monkeypatch``; every scenario
runs through :func:`tests.scenarios.runner.run` with ``via="recall"``, the
runner's in-memory embedded SurrealDB, real schema and deterministic
:class:`~tests.scenarios.runner.HashedBagOfWordsEmbeddings` stub.

``ProbeResult`` only exposes gold hits, character/token counts and the trace
turn id.  The tests therefore wrap ``RecallEngine.recall`` with a spy that keeps
the real :class:`~aura.engines.recall.models.ContextPacket` returned for each
probe, so a test can look at the memories block itself, ``packet.abstain`` and
``trace.gate``.  The wrapped method is the real one; the runner still drives
the manager, the schema, the clock and the engine.

The probe set in ``docs/metrics/probes/README.md`` is still a placeholder, so
these scenarios stand in for its noise and abstention probes until Mai provides
the real ones.

Card W3-08, PRD memory M3 gate, 6.2 (fast path under 250 ms at p95) and 8.3.
"""

from __future__ import annotations

import statistics
import time
from pathlib import Path
from typing import Any

import pytest

from aura.clock import get_clock
from aura.config import settings
from aura.engines.recall import RecallEngine, RecallRequest
from tests.conftest import write_baseline
from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    Probe,
    Scenario,
    StubLatentEngine,
    Turn,
    _build_manager,
    run,
)

# The exact line the memories block carries on an abstention (W3-07).
ABSTAIN_LINE = (
    '<memories abstain="true">Nothing relevant to this message is stored in '
    "memory. Do not claim to remember anything about it.</memories>"
)

_M3_METRICS_PATH = Path("docs/metrics/m3.md")

_USER_ID = "mai"
_CONVERSATION_ID = "conv-m3"

# Thirty unrelated memories.  None contains "cat" or "called", so only the Pixel
# memory can answer the cat question through the lexical channel.
_NOISE_TEXTS = [
    "I bought a loaf of bread this morning",
    "The meeting with the design team is on Tuesday",
    "My sister lives in Lisbon",
    "We painted the kitchen pale green",
    "The train to Edinburgh leaves at nine",
    "I finished reading a book about volcanoes",
    "The garden needs watering",
    "I am learning to play the violin",
    "The bakery on the corner opens early",
    "Our neighbour has a new bicycle",
    "I fixed the leaking tap in the bathroom",
    "The museum is free on Sundays",
    "I prefer tea to coffee",
    "The office printer is broken again",
    "We walked along the river at sunset",
    "I ordered a new pair of boots",
    "The concert was louder than expected",
    "My laptop battery drains quickly",
    "I planted tomatoes in the back garden",
    "The bus was late this morning",
    "I wrote a long email to the landlord",
    "The library closes at six",
    "We watched a film about the ocean",
    "I need to renew my passport",
    "The heating is making a strange noise",
    "My phone screen has a small crack",
    "I made soup for dinner",
    "The park was full of children",
    "I found an old photograph in a drawer",
    "The shop across the street sells plants",
]

_LATENCY_MEMORIES = 200
_LATENCY_CALLS = 50

# The runner's probes ask with ``include_cold_start=True``, and the cold-start
# block's three most recent memories are deduplicated ahead of the memories
# block.  These three later turns keep the target memory out of that recent
# trio so it can reach the memories block itself.
_FILLER_TEXTS = [
    "The weather is mild today",
    "I sorted the recycling",
    "I sharpened the kitchen knives",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _enable_m3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switch all three M3 flags on for one test (no default is changed)."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "recall_gate_enabled", True)
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)


def _capture_packets(monkeypatch: pytest.MonkeyPatch) -> list[tuple[RecallRequest, Any]]:
    """Wrap ``RecallEngine.recall`` so ``run``'s real packets can be inspected.

    Returns a list that the spy appends ``(request, packet)`` to, in probe
    order.  The wrapper awaits the real method and returns its packet
    unchanged.
    """
    captured: list[tuple[RecallRequest, Any]] = []
    real_recall = RecallEngine.recall

    async def _spy(self: RecallEngine, request: RecallRequest) -> Any:
        packet = await real_recall(self, request)
        captured.append((request, packet))
        return packet

    monkeypatch.setattr(RecallEngine, "recall", _spy)
    return captured


def _scenario(turns: list[Turn], probes: list[Probe], name: str) -> Scenario:
    return Scenario(
        name=name,
        turns=turns,
        dream_at_days=[],
        probes=probes,
    )


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile of an ascending list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = (len(sorted_values) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    weight = index - low
    return sorted_values[low] * (1.0 - weight) + sorted_values[high] * weight


# ---------------------------------------------------------------------------
# Noise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_noise_pixel_memory_reaches_the_memories_block(monkeypatch):
    """Thirty unrelated memories plus the cat fact; the cat fact is recalled."""
    _enable_m3(monkeypatch)
    captured = _capture_packets(monkeypatch)

    turns = [
        Turn(
            user_id=_USER_ID,
            conversation_id=_CONVERSATION_ID,
            text="Mai's cat is called Pixel",
            at_day=0.0,
        )
    ]
    turns += [
        Turn(
            user_id=_USER_ID,
            conversation_id=f"{_CONVERSATION_ID}-noise-{i}",
            text=text,
            at_day=float(i + 1),
        )
        for i, text in enumerate(_NOISE_TEXTS)
    ]

    probes = [
        Probe(
            user_id=_USER_ID,
            question="what is my cat called?",
            gold=["Pixel"],
            at_day=float(len(_NOISE_TEXTS) + 1),
        )
    ]

    results = await run(_scenario(turns, probes, "m3_noise"), via="recall")

    assert len(results) == 1
    assert results[0].gold_found["Pixel"] is True

    assert len(captured) == 1
    _request, packet = captured[0]
    memories = packet.block_text("memories")
    assert memories is not None
    assert "Pixel" in memories


# ---------------------------------------------------------------------------
# Lexical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lexical_code_symbol_is_found_by_the_question(monkeypatch):
    """A memory mentioning ``parse_route`` answers a question about it."""
    _enable_m3(monkeypatch)
    captured = _capture_packets(monkeypatch)

    turns = [
        Turn(
            user_id=_USER_ID,
            conversation_id=_CONVERSATION_ID,
            text="parse_route is defined in src/aura/router.py",
            at_day=0.0,
        )
    ]
    turns += [
        Turn(
            user_id=_USER_ID,
            conversation_id=f"{_CONVERSATION_ID}-filler-{i}",
            text=text,
            at_day=float(i + 1) / 10.0,
        )
        for i, text in enumerate(_FILLER_TEXTS)
    ]
    probes = [
        Probe(
            user_id=_USER_ID,
            question="where is parse_route defined?",
            gold=["parse_route"],
            at_day=1.0,
        )
    ]

    results = await run(_scenario(turns, probes, "m3_lexical"), via="recall")

    assert len(results) == 1
    assert results[0].gold_found["parse_route"] is True

    assert len(captured) == 1
    _request, packet = captured[0]
    memories = packet.block_text("memories")
    assert memories is not None
    assert "parse_route" in memories


# ---------------------------------------------------------------------------
# Abstention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abstention_note_only_for_the_unanswerable_question(monkeypatch):
    """The mountain question abstains; the cat question does not."""
    _enable_m3(monkeypatch)
    captured = _capture_packets(monkeypatch)

    turns = [
        Turn(
            user_id=_USER_ID,
            conversation_id=_CONVERSATION_ID,
            text="Mai's cat is called Pixel",
            at_day=0.0,
        )
    ]
    turns += [
        Turn(
            user_id=_USER_ID,
            conversation_id=f"{_CONVERSATION_ID}-filler-{i}",
            text=text,
            at_day=float(i + 1) / 10.0,
        )
        for i, text in enumerate(_FILLER_TEXTS)
    ]
    probes = [
        Probe(
            user_id=_USER_ID,
            question="what is my cat called?",
            gold=["Pixel"],
            at_day=1.0,
        ),
        Probe(
            user_id=_USER_ID,
            question="what is my favourite mountain?",
            gold=[ABSTAIN_LINE],
            at_day=2.0,
        ),
    ]

    results = await run(_scenario(turns, probes, "m3_abstention"), via="recall")

    assert len(results) == 2
    assert results[0].gold_found["Pixel"] is True
    assert results[1].gold_found[ABSTAIN_LINE] is True

    assert len(captured) == 2
    _cat_request, cat_packet = captured[0]
    _mountain_request, mountain_packet = captured[1]

    assert cat_packet.abstain is False
    cat_memories = cat_packet.block_text("memories")
    assert cat_memories is not None
    assert cat_memories != ABSTAIN_LINE
    assert "Pixel" in cat_memories

    assert mountain_packet.abstain is True
    assert mountain_packet.block_text("memories") == ABSTAIN_LINE


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thanks_after_the_cat_question_skips_and_reuses(monkeypatch):
    """``thanks!`` after the cat question skips retrieval and reuses Pixel."""
    _enable_m3(monkeypatch)
    captured = _capture_packets(monkeypatch)

    turns = [
        Turn(
            user_id=_USER_ID,
            conversation_id=_CONVERSATION_ID,
            text="Mai's cat is called Pixel",
            at_day=0.0,
        )
    ]
    turns += [
        Turn(
            user_id=_USER_ID,
            conversation_id=f"{_CONVERSATION_ID}-filler-{i}",
            text=text,
            at_day=float(i + 1) / 10.0,
        )
        for i, text in enumerate(_FILLER_TEXTS)
    ]
    probes = [
        Probe(
            user_id=_USER_ID,
            question="what is my cat called?",
            gold=["Pixel"],
            at_day=1.0,
        ),
        Probe(
            user_id=_USER_ID,
            question="thanks!",
            gold=["Pixel"],
            at_day=1.0,
        ),
    ]

    results = await run(_scenario(turns, probes, "m3_gate"), via="recall")

    assert len(results) == 2
    assert results[1].gold_found["Pixel"] is True

    assert len(captured) == 2
    cat_request, cat_packet = captured[0]
    thanks_request, thanks_packet = captured[1]

    assert cat_request.user_input == "what is my cat called?"
    assert cat_packet.trace.gate == "ran"

    assert thanks_request.user_input == "thanks!"
    assert thanks_packet.trace.gate == "skipped"
    # The skipped turn reuses the cat turn's memories instead of retrieving.
    thanks_memories = thanks_packet.block_text("memories")
    assert thanks_memories is not None
    assert "Pixel" in thanks_memories
    assert thanks_memories == cat_packet.block_text("memories")


# ---------------------------------------------------------------------------
# Latency
# ---------------------------------------------------------------------------


async def _seed_latency_memories(db: EmbeddedSurrealDB) -> None:
    """Create exactly ``_LATENCY_MEMORIES`` retrievable memories."""
    embeddings = HashedBagOfWordsEmbeddings()
    subjects = [
        "the garden project",
        "the train timetable",
        "a book about volcanoes",
        "the bakery order",
        "the office printer",
        "a walk along the river",
        "the music practice",
        "the kitchen repairs",
    ]
    for i in range(_LATENCY_MEMORIES):
        content = (
            f"Memory {i} is about {subjects[i % len(subjects)]} "
            f"and note {i * 7 % 97}."
        )
        await db.query(
            "CREATE memory CONTENT $data",
            {
                "data": {
                    "content": content,
                    "timestamp": get_clock().now(),
                    "importance": 0.5,
                    "emotional_signature": {},
                    "embedding": await embeddings.embed(content),
                    "user_id": _USER_ID,
                    "deprecated": False,
                    "ephemeral": False,
                }
            },
        )


@pytest.mark.asyncio
async def test_fast_path_latency_records_p50_and_p95(monkeypatch):
    """Time 50 fast-path ``recall`` calls over 200 memories and record them.

    The test asserts nothing about the measured numbers.  With
    ``RECORD_BASELINE=1`` it writes p50, p95 and the date to
    ``docs/metrics/m3.md`` through :func:`tests.conftest.write_baseline`.
    """
    _enable_m3(monkeypatch)

    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        await _seed_latency_memories(db)

        manager = _build_manager(db)
        engine = RecallEngine(
            memory_manager=manager, latent_engine=StubLatentEngine()
        )

        durations_ms: list[float] = []
        for i in range(_LATENCY_CALLS):
            request = RecallRequest(
                user_id=_USER_ID,
                user_input=f"what is memory number {i} about?",
                limit=5,
                include_cold_start=False,
                include_latent=False,
            )
            started = time.perf_counter()
            packet = await engine.recall(request)
            durations_ms.append((time.perf_counter() - started) * 1000.0)
            # The gate must not have skipped these questions: each call is a
            # real fast-path retrieval.  This is not an assertion about latency.
            assert packet.trace.gate == "ran"

        assert len(durations_ms) == _LATENCY_CALLS

        ordered = sorted(durations_ms)
        p50_ms = statistics.median(durations_ms)
        p95_ms = _percentile(ordered, 0.95)

        data = {
            "card": "W3-08",
            "date": get_clock().now().date().isoformat(),
            "calls": _LATENCY_CALLS,
            "seeded_memories": _LATENCY_MEMORIES,
            "flags": {
                "recall_channels_enabled": True,
                "recall_gate_enabled": True,
                "recall_abstain_enabled": True,
            },
            "p50_ms": round(p50_ms, 3),
            "p95_ms": round(p95_ms, 3),
            "min_ms": round(ordered[0], 3),
            "max_ms": round(ordered[-1], 3),
        }
        written = write_baseline(_M3_METRICS_PATH, data)

        if written:
            assert _M3_METRICS_PATH.exists()

        print(
            f"\nM3 fast path: {_LATENCY_CALLS} recall() calls over "
            f"{_LATENCY_MEMORIES} memories, p50 {data['p50_ms']} ms, "
            f"p95 {data['p95_ms']} ms"
        )
    finally:
        await db.close()