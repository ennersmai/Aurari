"""B2-01: drives as persisted scalars (embedded SurrealDB, FakeClock)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.autonomy import channel, controls, drives
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.memory.v2.episodes import store_episode
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
BASE = 0.3


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    drives.reset_cache()
    monkeypatch.setattr(settings, "drives_enabled", True)
    monkeypatch.setattr(settings, "drive_decay_per_hour", 0.0)
    d.clock = clock
    yield d
    drives.reset_cache()
    set_clock(Clock())
    await d.close()


async def _rows(db):
    return extract_rows(await db.query("SELECT * FROM drive_state"))


async def test_each_event_moves_only_listed_drives(db):
    expected = {
        "question_opened": {"curiosity"},
        "question_resolved": {"curiosity", "competence"},
        "prediction_failed": {"curiosity", "coherence", "competence"},
        "goal_unfinished_tick": {"competence"},
        "task_done": {"competence", "rest"},
        "finding_pending": {"connection"},
        "finding_delivered": {"connection"},
        "exchange_happened": {"connection"},
        "contradiction_open": {"coherence"},
        "contradiction_settled": {"coherence"},
        "dream_completed": {"rest", "coherence"},
        "consolidation_debt": {"rest"},
    }
    assert set(expected) == set(drives.EVENTS)
    for name, moved in expected.items():
        drives.reset_cache()
        await db.query("DELETE drive_state")
        vals = await drives.on_event(name, {"count": 5}, db=db)
        assert {d for d in drives.DRIVES if abs(vals[d] - BASE) > 1e-9} == moved, name


async def test_clamped_to_unit_interval(db):
    for _ in range(40):
        vals = await drives.on_event("question_opened", db=db)
    assert vals["curiosity"] == 1.0
    for _ in range(60):
        vals = await drives.on_event("question_resolved", db=db)
    assert vals["curiosity"] == 0.0
    assert all(0.0 <= v <= 1.0 for v in vals.values())


async def test_decay_from_fake_clock(db, monkeypatch):
    monkeypatch.setattr(settings, "drive_decay_per_hour", 0.5)
    await drives.on_event("contradiction_open", db=db)  # coherence 0.36
    await drives.on_event("contradiction_open", db=db)  # 0.42
    before = drives.current().levels["coherence"]
    db.clock.advance(2 * 3600)
    vals = await drives.on_event("exchange_happened", db=db)
    import math

    assert vals["coherence"] == pytest.approx(BASE + (before - BASE) * math.exp(-1.0))
    # No decay when no time passes.
    again = await drives.on_event("exchange_happened", db=db)
    assert again["coherence"] == pytest.approx(vals["coherence"])


async def test_consolidation_debt_counts_pending_episodes(db, monkeypatch):
    emb = HashedBagOfWordsEmbeddings()
    for i in range(3):
        await store_episode(
            db, emb, user_text=f"hello {i}", aura_text="hi", speaker="owner",
            venue="app", conversation_id="c1", emotional_signature={}, salience=0.4,
        )
    vals = await drives.on_event("consolidation_debt", db=db)
    assert vals["rest"] == pytest.approx(BASE + 3 * settings.drive_delta_consolidation_debt_rest)


def test_emotion_factor_bounded_and_ablation(monkeypatch):
    monkeypatch.setattr(settings, "drives_enabled", True)
    monkeypatch.setattr(settings, "drive_emotion_span", 100.0)  # absurd span: clamp must hold
    monkeypatch.setattr(settings, "drive_emotion_modulation_enabled", True)
    m = drives.DriveModel.fresh()
    for ev in ({"curiosity": 1e9, "fascination": 1e9, "boredom": 1e9}, {"curiosity": -1e9, "fascination": -1e9, "boredom": -1e9}):
        for d in ("curiosity", "competence"):
            f = drives.emotion_factor(d, ev)
            assert 0.8 <= f <= 1.2
            assert drives.gain(d, ev, m) == pytest.approx(BASE * f)
    assert drives.emotion_factor("curiosity", {"curiosity": 1e9}) == 1.2
    assert drives.emotion_factor("curiosity", {"curiosity": -1e9}) == 0.8
    # Other drives are never modulated.
    assert drives.emotion_factor("rest", {"boredom": 1.0, "curiosity": 1.0}) == 1.0
    # Ablation: off gives exactly the raw level.
    monkeypatch.setattr(settings, "drive_emotion_modulation_enabled", False)
    assert drives.gain("curiosity", {"curiosity": 1.0, "fascination": 1.0}, m) == BASE
    assert drives.gain("competence", {"boredom": 1.0}, m) == BASE


async def test_persistence_round_trip(db):
    await drives.on_event("question_opened", db=db)
    await drives.on_event("task_done", db=db)
    saved = drives.current().as_dict()
    rows = await _rows(db)
    assert len(rows) == 1
    assert rows[0]["updated_at"] is not None
    drives.reset_cache()
    loaded = await drives.load(db)
    assert loaded.as_dict() == pytest.approx(saved)
    assert loaded.updated_at == _START


async def test_updates_at_silent_and_publishes(db, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    controls.reset_cache()
    await controls.set_level("silent", db)
    channel.reset()
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    vals = await drives.on_event("question_opened", db=db)
    assert vals["curiosity"] > BASE
    events = [e for e in channel.events_since(0) if e["type"] == "drive_state"]
    assert len(events) == 1
    controls.reset_cache()


async def test_flag_off_does_nothing_and_writes_no_row(db, monkeypatch):
    monkeypatch.setattr(settings, "drives_enabled", False)
    assert await drives.on_event("question_opened", db=db) is None
    assert await _rows(db) == []
    assert drives.gain("curiosity") == 0.0
