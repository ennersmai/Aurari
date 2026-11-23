"""M6 gate probes (card W4-12): long topics and 90 simulated days.

Real embedded SurrealDB, deterministic embeddings, a ``FakeClock``. Every turn
goes through the real write path: ``store_episode`` then ``run_extraction``
with a scripted fake client (some first extractions fail, so the dream retry
phase has to finish them). A dream cycle (``enter_rem_sleep``, with
``last_dream_cycle`` advanced as the engine does) runs every simulated night.
The same fake client answers the summary calls with a deterministic summary
built from the member facts' first words. Probes run after the night's dream on
days 30, 60 and 90.
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import store_episode
from aura.engines.memory.v2.extraction import run_extraction
from aura.engines.recall import RecallEngine, RecallRequest
from tests.conftest import write_baseline
from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    StubLatentEngine,
    _build_dreaming,
)
from tests.scenarios.test_recall_entity_channel_embedded import _manager

_M6_METRICS_PATH = Path(__file__).resolve().parents[2] / "docs" / "metrics" / "m6.md"
_START0 = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
_DAYS = 90
_PROBE_DAYS = (30, 60, 90)

_FLAGS = (
    "memory_v2_write_enabled", "memory_v2_recall_enabled", "recall_channels_enabled",
    "recall_gate_enabled", "recall_abstain_enabled", "recall_dedup_enabled",
    "recall_budget_enabled", "recall_entity_channel_enabled",
    "recall_temporal_channel_enabled", "recall_graph_channel_enabled",
    "recall_rerank_enabled", "recall_feedback_enabled", "recall_themes_enabled",
    "dreaming_v2_enabled",
)

# Three long topics: entity name and the vocabulary of its facts.
_VOCAB = {
    "Renovation": ["tiles", "paint", "pipes", "beams", "windows",
                   "cabinets", "flooring", "wiring", "plaster", "doors"],
    "Marathon": ["tempo", "intervals", "hills", "stretching", "shoes",
                 "pacing", "recovery", "gels", "cadence", "taper"],
    "Novel": ["chapter", "outline", "plot", "dialogue", "editing",
              "characters", "setting", "draft", "ending", "prologue"],
}
_ORDER = list(_VOCAB)

_LONG_Q = [
    ("Renovation", "how is the house renovation going?"),
    ("Renovation", "what has happened with the house renovation so far?"),
    ("Marathon", "how is my marathon training going?"),
    ("Marathon", "what have I been doing for marathon training?"),
    ("Novel", "how is the novel writing going?"),
]

# Stated in the first week.
_SINGLES = [
    (1, "My cat is named Biscuit.", "what is my cat called?"),
    (2, "I am allergic to peanuts.", "what am I allergic to?"),
    (3, "My passport expires in 2031.", "when does my passport expire?"),
    (4, "My favourite tea is jasmine.", "which tea do I like best?"),
    (5, "My bike is a green Brompton.", "what bike do I ride?"),
]

# (day, statement, predicate, object, old object it replaces).
_UPDATES = [
    (2, "I live in Lisbon.", "live in", "Lisbon", None),
    (12, "I live in Porto.", "live in", "Porto", "Lisbon"),
    (3, "I work as a teacher.", "work as", "teacher", None),
    (24, "I work as a nurse.", "work as", "nurse", "teacher"),
    (40, "I live in Faro.", "live in", "Faro", "Porto"),
    (75, "I work as a doctor.", "work as", "doctor", "nurse"),
]
_UPDATE_Q = {"live in": "where do I live?", "work as": "what do I work as?"}

_EMPTY = {"entities": [], "facts": [], "questions": [], "predictions": []}
_CHATTER = ["thanks", "hello", "hey", "hi"]
_RESULTS: dict[str, object] = {}


def _topic_fact(topic: str, day: int, k: int) -> str:
    vocab = _VOCAB[topic]
    a, b, c = vocab[day % 10], vocab[(day * 3 + k) % 10], vocab[(day * 7 + 2) % 10]
    return f"{topic} work on day {day}: {a} then {b} and {c} number {day}{k}."


def _fact_json(content, subject=None, predicate=None, obj=None, about=()):
    return {
        "content": content, "kind": "fact", "subject": subject, "predicate": predicate,
        "object": obj, "about": list(about), "asserted_by": "user", "implied": False,
        "negates": False,
    }


class FakeLLM:
    """Scripted extraction (by turn marker) and deterministic summaries."""

    def __init__(self):
        self.scripts: dict[int, dict] = {}
        self.fail_first: set[int] = set()
        self.calls: dict[int, int] = {}
        self.summaries = 0

    async def complete(self, messages, model=None, temperature=0, **kwargs) -> str:
        prompt = messages[-1]["content"]
        if "FACTS:" in prompt:
            self.summaries += 1
            body = prompt.split("FACTS:\n", 1)[1].splitlines()
            lines = [ln[2:] for ln in body if ln.startswith("- ")]
            return "Summary: " + "; ".join(" ".join(ln.split()[:4]) for ln in lines[:8])
        found = re.findall(r"\[t(\d+)\]", prompt.rsplit("Current episode:", 1)[-1])
        if not found:  # chatter carries no marker (a marker would defeat the gate)
            return json.dumps(_EMPTY)
        n = int(found[-1])
        self.calls[n] = self.calls.get(n, 0) + 1
        if n in self.fail_first and self.calls[n] == 1:
            raise RuntimeError("scripted extraction failure")
        return json.dumps(self.scripts[n])


class _NoLegacyMemory:
    """Stands in for the global MemoryManager the legacy dream phases write a
    cycle note through (it would load the real embedding model every night)."""

    async def store_memory(self, *args, **kwargs):
        return None


class _Layers:
    def __init__(self, client):
        self.client = client


def _build_schedule() -> dict[int, list]:
    """day -> [(hour, user_text, turn number, extraction script, fail first)]."""
    sched: dict[int, list] = {d: [] for d in range(1, _DAYS + 1)}
    counter = 0

    def add(day, hour, text, facts, entities=(), fail=False):
        nonlocal counter
        if day not in sched:
            return
        counter += 1
        script = {"entities": list(entities), "facts": facts, "questions": [], "predictions": []}
        sched[day].append((hour, f"{text} [t{counter}]", counter, script, fail))

    for day in range(1, _DAYS + 1):
        for k in (0, 1):
            topic = _ORDER[(day + k) % 3]
            text = _topic_fact(topic, day, k)
            ent = {"name": topic, "type": "project", "surface": topic}
            add(day, 9 + 3 * k, text, [_fact_json(text, about=[topic])], [ent],
                fail=(day * 2 + k) % 17 == 5)
        sched[day].append((18, _CHATTER[day % 4], 0, _EMPTY, False))  # ephemeral chatter
    for day, text, _q in _SINGLES:
        add(day, 20, text, [_fact_json(text)], fail=(day == 3))
    for day, text, pred, obj, _old in _UPDATES:
        add(day, 21, text, [_fact_json(text, "I", pred, obj)])
    for day in sched:
        sched[day].sort(key=lambda t: t[0])
    return sched


async def _block(db, question: str) -> str:
    engine = RecallEngine(memory_manager=_manager(db), latent_engine=StubLatentEngine())
    packet = await engine.recall(
        RecallRequest(user_id="owner", user_input=question, limit=20,
                      include_cold_start=False, include_latent=False,
                      token_budget=100_000, venue="app")
    )
    return packet.block_text("memories") or ""


async def _count(db, where: str, table: str) -> int:
    rows = await db.query(f"SELECT count() AS n FROM {table} {where} GROUP ALL")
    return int(rows[0]["n"]) if rows else 0


async def _probe(db, day: int, topic_facts: dict[str, list[str]]) -> dict:
    out: dict = {"day": day}
    long_hits, theme_hits, detail = 0, 0, []
    for topic, question in _LONG_Q:
        block = await _block(db, question)
        theme_line = any(
            ln.lstrip().startswith("<theme") and f"{topic} work" in ln
            for ln in block.splitlines()
        )
        facts = sum(1 for c in topic_facts[topic] if c in block)
        long_hits += theme_line or facts >= 2
        theme_hits += theme_line
        detail.append((question, theme_line, facts))
    out.update(long_topic=long_hits, long_topic_theme_line=theme_hits, long_detail=detail)

    single, missed = 0, []
    for _d, text, question in _SINGLES:
        if text in await _block(db, question):
            single += 1
        else:
            missed.append(question)
    out.update(single_fact=single, single_missed=missed)

    newest: dict[str, str] = {}
    for d, _t, pred, obj, _old in _UPDATES:
        if d <= day:
            newest[pred] = obj
    updated, bad = 0, []
    for pred, new in newest.items():
        block = await _block(db, _UPDATE_Q[pred])
        olds = [o for d, _t, p, _ob, o in _UPDATES if p == pred and d <= day and o]
        has_new = new in block
        has_old = any(o in block for o in olds)
        if has_new and not has_old:
            updated += 1
        else:
            bad.append((pred, has_new, has_old))
    out.update(updated=updated, updated_total=len(newest), updated_bad=bad)

    out.update(
        facts=await _count(db, "", "fact"),
        facts_current=await _count(db, "WHERE valid_to IS NONE", "fact"),
        facts_archived=await _count(db, "WHERE archived = true", "fact"),
        themes=await _count(db, "", "theme"),
        entities=await _count(db, "", "entity"),
        episodes=await _count(db, "", "episode"),
        episodes_archived=await _count(db, "WHERE archived = true", "episode"),
        episodes_pending=await _count(db, "WHERE extraction_status = 'pending'", "episode"),
    )
    return out


@pytest.mark.asyncio
async def test_m6_long_topics_and_90_days(monkeypatch):
    for name in _FLAGS:
        monkeypatch.setattr(settings, name, True)
    embeddings = HashedBagOfWordsEmbeddings()
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: embeddings)

    monkeypatch.setattr(
        "aura.engines.memory.manager.get_memory_manager", lambda: _NoLegacyMemory()
    )

    sched = _build_schedule()
    llm = FakeLLM()
    for day_turns in sched.values():
        for _h, _t, n, script, fail in day_turns:
            llm.scripts[n] = script
            if fail:
                llm.fail_first.add(n)
    topic_facts = {
        t: [_topic_fact(t, d, k) for d in range(1, _DAYS + 1) for k in (0, 1)
            if _ORDER[(d + k) % 3] == t]
        for t in _VOCAB
    }

    db = EmbeddedSurrealDB()
    await db.connect()
    started = time.monotonic()
    probes: list[dict] = []
    retried = extracted = turns = 0
    try:
        dreaming = _build_dreaming(db)
        dreaming.set_dependencies(llm_layers=_Layers(llm))
        for day in range(1, _DAYS + 1):
            for hour, text, _n, _script, _fail in sched[day]:
                set_clock(FakeClock(_START0 + timedelta(days=day, hours=hour)))
                episode_id = await store_episode(
                    db, embeddings, user_text=text, aura_text="Noted.", speaker="owner",
                    venue="app", conversation_id=f"d{day}",
                    emotional_signature={"joy": 0.1}, salience=0.4,
                )
                await run_extraction(db, llm, episode_id)
                turns += 1
            now = _START0 + timedelta(days=day, hours=23)
            set_clock(FakeClock(now))
            report = await dreaming.enter_rem_sleep()
            dreaming.last_dream_cycle = now
            retried += report.retried
            extracted += report.extracted
            if day in _PROBE_DAYS:
                set_clock(FakeClock(now + timedelta(minutes=30)))
                probes.append(await _probe(db, day, topic_facts))
        elapsed = time.monotonic() - started
    finally:
        await db.close()
        set_clock(Clock())

    for p in probes:
        print("M6", {k: v for k, v in p.items() if k != "long_detail"})
        print("M6 long", p["long_detail"])
    print("M6 turns", turns, "retried", retried, "extracted", extracted,
          "summary_calls", llm.summaries, "seconds", round(elapsed, 1))
    _RESULTS["probes"] = probes

    assert retried >= 1 and extracted >= 1, "the retry phase never finished an episode"
    for p in probes:
        d = p["day"]
        assert p["long_topic"] >= 4, f"day {d}: long-topic {p['long_topic']}/5 {p['long_detail']}"
        assert p["single_fact"] == 5, f"day {d}: single-fact missed {p['single_missed']}"
        assert p["updated"] == p["updated_total"], f"day {d}: updated facts wrong {p['updated_bad']}"
        assert p["themes"] <= 3, f"day {d}: {p['themes']} themes for three topics"

    data = {
        "card": "W4-12", "date": "2026-11-23", "days": _DAYS, "turns": turns,
        "retried": retried, "extracted_by_retry": extracted,
        "summary_calls": llm.summaries, "seconds": round(elapsed, 1),
        "probe_days": [{k: v for k, v in p.items() if k != "long_detail"} for p in probes],
        "flags": {f: True for f in _FLAGS},
    }
    if write_baseline(_M6_METRICS_PATH, data):
        assert _M6_METRICS_PATH.exists()
