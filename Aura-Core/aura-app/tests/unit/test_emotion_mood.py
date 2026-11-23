"""Mood tests (W4-13, Emotion PRD 6.2, T12). Fake clock, fake DB, no model."""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.emotion import mood as mood_math
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
HL = 8 * 3600.0


class FakeDB:
    def __init__(self):
        self.writes: list[dict[str, Any]] = []
        self.state_rows: list[dict[str, Any]] = []

    async def create(self, table: str, data: dict[str, Any]) -> Any:
        self.writes.append({"table": table, "data": data})
        return {"id": f"{table}:test"}

    async def query(self, sql: str, params: dict | None = None) -> list:
        if "FROM emotion_state" in sql:
            return self.state_rows
        return []


@pytest.fixture
def clock():
    c = FakeClock(T0)
    set_clock(c)
    yield c
    set_clock(Clock())


@pytest.fixture
def engine(clock, monkeypatch):
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    monkeypatch.setattr(settings, "emotion_mood_enabled", True)
    from aura.engines.emotion.engine import EmotionEngine

    eng = EmotionEngine(config=EmotionPhysicsConfig())
    eng.db = FakeDB()
    eng._message_bus = None
    eng.tick_rate = 0
    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        yield eng


def _event(congruence: float, warmth: float = 0.0, intensity: float = 0.8,
           novelty: float = 0.0) -> AppraisalEvent:
    return AppraisalEvent(
        kind="message", source="conversation",
        appraisal=Appraisal(congruence=congruence, warmth=warmth, intensity=intensity,
                            novelty=novelty, control=0.8, agency="other"),
    )


async def _day(engine, clock, congruence: float, warmth: float, hours: float = 24.0):
    """Appraisals every 5 minutes, with a tick before each."""
    for _ in range(int(hours * 12)):
        clock.advance(300)
        await engine.tick()
        await engine.appraise(_event(congruence, warmth))


async def _rest(engine, clock, hours: float):
    for _ in range(int(hours * 12)):
        clock.advance(300)
        await engine.tick()


def _positive_shift(engine) -> float:
    eff = engine._effective_baseline().model_dump()
    base = engine.config.baseline.model_dump()
    return eff["joy"] - base["joy"]


# -- maths -------------------------------------------------------------------

def test_projection_on_fixed_inputs():
    base = {"joy": 0.2, "fear": 0.0}
    vec = {"joy": 0.5, "fear": 0.2}
    w = {"joy": 1.0, "fear": -1.0, "anger": 1.0}  # anger missing from vec: 0 deviation
    assert mood_math.project(vec, base, w) == pytest.approx(0.1)
    assert mood_math.project({"joy": 1.0}, {"joy": 0.0}, {"joy": 5.0}) == 1.0
    assert mood_math.project({"joy": 0.0}, {"joy": 1.0}, {"joy": 5.0}) == -1.0


def test_step_and_decay_on_fixed_inputs():
    m = {"valence": 0.0, "arousal": 0.0, "control": 0.0}
    target = {"valence": 1.0, "arousal": -1.0, "control": 0.5}
    out = mood_math.step(m, target, HL, HL)  # one half-life: half the gap
    assert out == pytest.approx({"valence": 0.5, "arousal": -0.5, "control": 0.25})
    assert mood_math.step(m, target, 0.0, HL) == m
    d = mood_math.decay({"valence": 0.8, "arousal": -0.4, "control": 0.0}, 2 * HL, HL)
    assert d == pytest.approx({"valence": 0.2, "arousal": -0.1, "control": 0.0})
    assert mood_math.baseline_shift(1.0, 0.1, 0.1) == 0.1
    assert mood_math.baseline_shift(-1.0, 0.5, 0.1) == -0.1


# -- T12 ---------------------------------------------------------------------

async def test_t12_negative_day_lowers_baseline_within_cap_and_recovers(engine, clock):
    configured = engine.config.baseline.model_dump()
    await _day(engine, clock, -0.8, -0.6)
    assert engine._mood["valence"] < -0.3
    shift = _positive_shift(engine)
    assert -0.1 - 1e-9 <= shift < -0.03
    assert engine.config.baseline.model_dump() == configured  # never changes
    low = shift
    await _rest(engine, clock, 72)
    assert abs(_positive_shift(engine)) < abs(low) * 0.1


async def test_t12_positive_day_raises_baseline_symmetrically(engine, clock):
    await _day(engine, clock, 0.8, 0.6)
    assert engine._mood["valence"] > 0.3
    high = _positive_shift(engine)
    assert 0.03 < high <= 0.1 + 1e-9
    await _rest(engine, clock, 72)
    assert abs(_positive_shift(engine)) < high * 0.2


async def test_state_carries_mood_when_on(engine, clock):
    await _day(engine, clock, 0.8, 0.6, hours=1)
    state = await engine.get_current_state()
    assert set(state.mood) == {"valence", "arousal", "control"}


# -- appraisal bias ----------------------------------------------------------

async def test_bias_within_cap_and_records_unbiased(engine, clock, monkeypatch):
    monkeypatch.setattr(settings, "emotion_mood_appraisal_bias_enabled", True)
    monkeypatch.setattr(settings, "emotion_mood_appraisal_bias", 5.0)  # cap must bind
    engine._mood["valence"] = 1.0
    await engine.appraise(_event(0.1, novelty=0.8))
    rec = engine.db.writes[-1]["data"]
    assert rec["appraisal"]["congruence"] == 0.1
    assert rec["mood_bias"] == pytest.approx(0.1)
    await engine.appraise(_event(0.5, warmth=0.5, novelty=0.8))  # not ambiguous
    assert engine.db.writes[-1]["data"]["mood_bias"] == 0.0


async def test_bias_absent_with_its_flag_off(engine, clock):
    engine._mood["valence"] = 1.0
    await engine.appraise(_event(0.1, novelty=0.8))
    assert "mood_bias" not in engine.db.writes[-1]["data"]


# -- restart -----------------------------------------------------------------

async def test_restart_decays_mood_by_elapsed_time(engine, clock):
    engine._mood = {"valence": 0.8, "arousal": -0.4, "control": 0.2}
    engine._mood_at = clock.now()
    await engine._persist_state()
    row = engine.db.writes[-1]["data"]
    assert row["mood"] == {"valence": 0.8, "arousal": -0.4, "control": 0.2}
    assert row["mood_at"] == T0

    engine.db.state_rows = [row]
    clock.advance(16 * 3600)  # two half-lives
    engine._mood = {"valence": 0.0, "arousal": 0.0, "control": 0.0}
    await engine._load_state()
    assert engine._mood == pytest.approx({"valence": 0.2, "arousal": -0.1, "control": 0.05})


# -- ablation ----------------------------------------------------------------

async def test_flag_off_is_unchanged(engine, clock, monkeypatch):
    monkeypatch.setattr(settings, "emotion_mood_enabled", False)
    assert engine._effective_baseline() is engine.config.baseline
    await engine.appraise(_event(0.8, warmth=0.6))
    clock.advance(600)
    await engine.tick()
    assert engine._mood == {"valence": 0.0, "arousal": 0.0, "control": 0.0}
    assert (await engine.get_current_state()).mood is None
    assert "mood_bias" not in engine.db.writes[-1]["data"]
    await engine._persist_state()
    assert "mood" not in engine.db.writes[-1]["data"]
