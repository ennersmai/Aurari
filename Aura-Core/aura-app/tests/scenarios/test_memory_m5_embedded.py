"""M5 gate probes (card W4-07): multi-hop and temporal recall, M5 on vs off.

Real embedded SurrealDB, deterministic embeddings, scripted extractions. A
question counts as answered when the target fact's content is in the rendered
memories block. Target facts share no content word with their question, so with
M5 off (entity, temporal, graph, rerank off; M3/M4 on) they are mostly missed.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import store_episode
from aura.engines.memory.v2.facts import write_facts
from aura.engines.recall import RecallEngine, RecallRequest
from tests.conftest import write_baseline
from tests.scenarios.runner import HashedBagOfWordsEmbeddings, StubLatentEngine
from tests.scenarios.test_recall_entity_channel_embedded import (
    _extraction,
    _fact,
    _learn,
    _manager,
    _open_db,
)

_M5_METRICS_PATH = Path(__file__).resolve().parents[2] / "docs" / "metrics" / "m5.md"
_NOW = datetime(2026, 11, 15, 14, 30, tzinfo=timezone.utc)  # a Sunday
_RESULTS: dict[str, dict[str, float]] = {}

_M3_M4_FLAGS = {
    "memory_v2_write_enabled": True,
    "memory_v2_recall_enabled": True,
    "recall_channels_enabled": True,
    "recall_gate_enabled": True,
    "recall_abstain_enabled": True,
}
_M5_FLAGS = (
    "recall_entity_channel_enabled",
    "recall_temporal_channel_enabled",
    "recall_graph_channel_enabled",
    "recall_rerank_enabled",
)


def _set_flags(monkeypatch, m5: bool) -> None:
    for name, value in _M3_M4_FLAGS.items():
        monkeypatch.setattr(settings, name, value)
    for name in _M5_FLAGS:
        monkeypatch.setattr(settings, name, m5)
    # Small dense/lexical windows so they cannot return the whole database.
    monkeypatch.setattr(settings, "recall_dense_k", 2)
    monkeypatch.setattr(settings, "recall_lexical_k", 2)


async def _block(db, question: str) -> str:
    engine = RecallEngine(
        memory_manager=_manager(db), latent_engine=StubLatentEngine()
    )
    packet = await engine.recall(
        RecallRequest(
            user_id="owner",
            user_input=question,
            limit=20,
            include_cold_start=False,
            include_latent=False,
            token_budget=100_000,
            venue="app",
        )
    )
    return packet.block_text("memories") or ""


_CHAINS = [
    ("sister", "Ana", "where does my sister live?"),
    ("brother", "Rui", "what is my brother profession?"),
    ("mother", "Marta", "where was my mother born?"),
    ("dentist", "Lena", "when is my dentist available?"),
    ("neighbour", "Omar", "what does my neighbour play?"),
]
_CHAIN_FACTS = {
    "Ana": "Ana resides in Porto.",
    "Rui": "Rui works as a carpenter.",
    "Marta": "Marta was born in Faro.",
    "Lena": "Lena is free on Tuesdays.",
    "Omar": "Omar plays the violin.",
}


async def _seed_multihop(db):
    emb = HashedBagOfWordsEmbeddings()
    for i, (rel, name, _q) in enumerate(_CHAINS):
        ent = {"name": name, "type": "person", "surface": name}
        await _learn(
            db, emb, f"My {rel} is called {name}.", conversation_id=f"a{i}",
            entities=[ent],
            fact=_fact(content=f"My {rel} is called {name}.", subject=rel,
                       predicate="is called", object=name, about=[name]),
        )
        await _learn(
            db, emb, _CHAIN_FACTS[name], conversation_id=f"b{i}", entities=[ent],
            fact=_fact(content=_CHAIN_FACTS[name], subject=name,
                       predicate="has", object="x", about=[name]),
        )
    for i, thing in enumerate(["tea", "chess", "rain", "trains", "violins", "jazz"]):
        await _learn(
            db, emb, f"I like {thing} a lot number {i}.", conversation_id=f"f{i}",
            fact=_fact(content=f"I like {thing} a lot number {i}.", subject="I",
                       predicate="like", object=thing, about=[]),
        )


async def _learn_at(db, when, content: str) -> None:
    set_clock(FakeClock(when))
    emb = HashedBagOfWordsEmbeddings()
    episode_id = await store_episode(
        db, emb, user_text=content, aura_text="Noted.", speaker="owner",
        venue="app", conversation_id=f"c-{when.isoformat()}",
        emotional_signature={"joy": 0.1}, salience=0.3,
    )
    rows = await db.query("SELECT * FROM $rid", {"rid": episode_id})
    await write_facts(
        db, emb, rows[0],
        _extraction([], _fact(content=content, subject="I", predicate="did",
                              object="x", about=[])),
    )
    set_clock(FakeClock(_NOW))


_TEMPORAL = [
    (_NOW - timedelta(days=1), "The plumber fixed the boiler.", "what did I say yesterday?"),
    (datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc), "We repainted the garage door.", "what happened last week?"),
    (datetime(2026, 3, 10, 9, 0, tzinfo=timezone.utc), "The cat visited the vet.", "what happened in March?"),
    (_NOW - timedelta(days=3), "Granddad mailed a parcel.", "what happened 3 days ago?"),
    (datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc), "The orchard produced pears.", "what happened on 2026-10-01?"),
]
_TEMPORAL_DISTRACTORS = [
    (_NOW - timedelta(days=40), "A neighbour borrowed the ladder."),
    (_NOW - timedelta(days=100), "The roof leaked during a storm."),
    (_NOW - timedelta(days=200), "The bakery changed its opening hours."),
    (_NOW - timedelta(hours=3), "The kettle stopped working."),
    (datetime(2025, 3, 10, 9, 0, tzinfo=timezone.utc), "The fence got a new gate."),
]


async def _run_multihop(monkeypatch, m5: bool) -> tuple[int, list[str]]:
    _set_flags(monkeypatch, m5)
    db = await _open_db()
    set_clock(FakeClock(_NOW))
    try:
        await _seed_multihop(db)
        hits, missed = 0, []
        for _rel, name, question in _CHAINS:
            if _CHAIN_FACTS[name] in await _block(db, question):
                hits += 1
            else:
                missed.append(question)
        return hits, missed
    finally:
        await db.close()
        set_clock(Clock())


async def _run_temporal(monkeypatch, m5: bool) -> tuple[int, list[str]]:
    _set_flags(monkeypatch, m5)
    db = await _open_db()
    set_clock(FakeClock(_NOW))
    try:
        for when, content in _TEMPORAL_DISTRACTORS:
            await _learn_at(db, when, content)
        for when, content, _q in _TEMPORAL:
            await _learn_at(db, when, content)
        hits, missed = 0, []
        for _when, content, question in _TEMPORAL:
            if content in await _block(db, question):
                hits += 1
            else:
                missed.append(question)
        return hits, missed
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_multihop_probes(monkeypatch):
    off, _ = await _run_multihop(monkeypatch, False)
    on, missed = await _run_multihop(monkeypatch, True)
    _RESULTS["multi_hop"] = {"total": 5, "m5_off": off, "m5_on": on}
    print("multihop off/on", off, on, missed)
    assert on >= 4, f"multi-hop answered {on}/5, missed {missed}"


@pytest.mark.asyncio
async def test_temporal_probes(monkeypatch):
    off, _ = await _run_temporal(monkeypatch, False)
    on, missed = await _run_temporal(monkeypatch, True)
    _RESULTS["temporal"] = {"total": 5, "m5_off": off, "m5_on": on}
    print("temporal off/on", off, on, missed)
    assert on >= 4, f"temporal answered {on}/5, missed {missed}"
    data = {
        "card": "W4-07",
        "date": "2026-11-23",
        "sets": {
            k: {**v, "share_off": v["m5_off"] / v["total"],
                "share_on": v["m5_on"] / v["total"]}
            for k, v in _RESULTS.items()
        },
        "flags": {**_M3_M4_FLAGS, **{f: True for f in _M5_FLAGS}},
    }
    written = write_baseline(_M5_METRICS_PATH, data)
    if written:
        assert _M5_METRICS_PATH.exists()
