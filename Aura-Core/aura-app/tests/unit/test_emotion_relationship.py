"""Relationship tests (W4-14, Emotion PRD 6.3, T10). Fake clock, fake DB, no model."""

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.emotion import relationship as rel_math
from aura.engines.emotion.system_events import tool_succeeded, memory_write_failed
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

OWNER = {"affection": 0.5, "trust": 0.7, "familiarity": 0.6, "tension": 0.0}
STRANGER = {"affection": 0.0, "trust": 0.3, "familiarity": 0.0, "tension": 0.0}


class FakeDB:
    """Holds entity rows by record-id string; records every UPDATE."""

    def __init__(self, entities: dict[str, dict[str, Any]] | None = None):
        self.entities = entities if entities is not None else {}
        self.writes: list[dict[str, Any]] = []
        self.updates: list[tuple[str, dict[str, Any]]] = []

    async def create(self, table: str, data: dict[str, Any]) -> Any:
        self.writes.append({"table": table, "data": data})
        return {"id": f"{table}:test"}

    async def query(self, sql: str, params: dict | None = None) -> list:
        if sql.startswith("SELECT affection"):
            row = self.entities.get(str(params["rid"]))
            return [dict(row)] if row is not None else []
        if sql.startswith("UPDATE"):
            key = str(params["rid"])
            self.updates.append((key, params))
            self.entities[key].update(
                {k: v for k, v in params.items() if k != "rid"}
            )
            return [{}]
        return []


@pytest.fixture
def clock():
    c = FakeClock(T0)
    set_clock(c)
    yield c
    set_clock(Clock())


def _engine(db: FakeDB, monkeypatch, flag: bool = True):
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    monkeypatch.setattr(settings, "emotion_relationships_enabled", flag)
    from aura.engines.emotion.engine import EmotionEngine

    eng = EmotionEngine(config=EmotionPhysicsConfig())
    eng.db = db
    eng._message_bus = None
    eng.tick_rate = 0
    return eng


@pytest.fixture
def ws():
    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        yield


def _warm(person: str | None, kind: str = "message", **kw) -> AppraisalEvent:
    params = dict(congruence=0.6, warmth=0.8, intensity=0.8, agency="other", control=0.8)
    params.update(kw)
    return AppraisalEvent(
        kind=kind, source="conversation", person_id=person,
        appraisal=Appraisal(**params),
    )


def _hostile(person: str | None) -> AppraisalEvent:
    return AppraisalEvent(
        kind="message", source="conversation", person_id=person,
        appraisal=Appraisal(congruence=-0.9, warmth=-0.9, intensity=1.0,
                            agency="other", control=0.9, certainty=0.8),
    )


def _db() -> FakeDB:
    none_row = {"affection": None, "trust": None, "familiarity": None, "tension": None}
    return FakeDB({"entity:owner": dict(none_row), "entity:discord_9": dict(none_row)})


# -- maths -------------------------------------------------------------------

def test_starting_values_owner_and_stranger():
    assert rel_math.resolve(None, True, settings) == OWNER
    assert rel_math.resolve({"affection": None}, False, settings) == STRANGER
    got = rel_math.resolve({"affection": 0.9, "trust": None}, False, settings)
    assert got["affection"] == 0.9 and got["trust"] == 0.3


def test_owner_baseline_matches_global_baseline():
    base = EmotionPhysicsConfig().baseline
    got = rel_math.baseline_for(OWNER, settings)
    assert got["love"] == pytest.approx(base.love)
    assert got["trust"] == pytest.approx(base.trust)
    assert rel_math.baseline_for(STRANGER, settings)["love"] == 0.0


def test_familiarity_diminishing_returns():
    a = Appraisal()
    rel = dict(STRANGER)
    gains = []
    for _ in range(4):
        new = rel_math.step(rel, a, settings)
        gains.append(new["familiarity"] - rel["familiarity"])
        rel = new
    assert gains[0] == pytest.approx(0.03)
    assert gains[1] == pytest.approx(0.03 * 0.97)
    assert all(g1 > g2 > 0 for g1, g2 in zip(gains, gains[1:]))


def test_tension_rises_then_eases_with_repair():
    rel = dict(STRANGER)
    hostile = Appraisal(congruence=-0.8, warmth=-0.5, agency="other")
    rel = rel_math.step(rel, hostile, settings)
    assert rel["tension"] == pytest.approx(0.03 * 0.8)
    kind = Appraisal(congruence=0.0, warmth=0.5, agency="other")
    eased = rel_math.step(rel, kind, settings)
    assert eased["tension"] == pytest.approx(0.03 * 0.8 - 0.02 * 0.5)
    for _ in range(20):
        eased = rel_math.step(eased, kind, settings)
    assert eased["tension"] == 0.0  # clamped at the floor


def test_affection_and_trust_steps_and_clamping():
    good = Appraisal(congruence=0.6, warmth=0.8, certainty=0.5, agency="other")
    new = rel_math.step(STRANGER, good, settings)
    assert new["affection"] == pytest.approx(0.02 * 0.7)
    assert new["trust"] == pytest.approx(0.3 + 0.02 * 0.6 * 0.5)
    # agency not the other person: no affection or trust change
    mine = rel_math.step(STRANGER, good.model_copy(update={"agency": "self"}), settings)
    assert mine["affection"] == 0.0 and mine["trust"] == 0.3
    # broken expectation, negative warmth
    bad = Appraisal(congruence=-1.0, warmth=-1.0, certainty=1.0, agency="other")
    mid = {"affection": 0.5, "trust": 0.5, "familiarity": 0.5, "tension": 0.5}
    down = rel_math.step(mid, bad, settings)
    assert down["trust"] == pytest.approx(0.5 - 0.03)
    assert down["affection"] == pytest.approx(0.5 - 0.005)
    # clamping at both ends
    top = {"affection": 1.0, "trust": 1.0, "familiarity": 1.0, "tension": 1.0}
    out = rel_math.step(
        top, Appraisal(congruence=1.0, warmth=1.0, certainty=1.0, agency="other"), settings
    )
    assert all(0.0 <= v <= 1.0 for v in out.values())
    assert out["affection"] == 1.0 and out["trust"] == 1.0
    zero = {"affection": 0.0, "trust": 0.0, "familiarity": 0.0, "tension": 0.0}
    low = rel_math.step(zero, bad, settings)
    assert low["affection"] == 0.0 and low["trust"] == 0.0


def test_scale_impulses_warmth_and_stranger_cap():
    imp = {"joy": 0.5, "anger": 0.8, "sadness": 0.1}
    owner = rel_math.scale_impulses(imp, OWNER, 0.5, settings)
    assert owner["joy"] == pytest.approx(0.5 * (1 + 0.5 * 0.55))
    assert owner["anger"] == 0.8  # owner is not capped
    stranger = rel_math.scale_impulses(imp, STRANGER, 0.5, settings)
    assert stranger["joy"] == 0.5  # factor 1.0 for (0 + 0) / 2
    assert stranger["anger"] == pytest.approx(0.3)
    assert stranger["sadness"] == 0.1
    # no warmth boost without positive warmth
    assert rel_math.scale_impulses(imp, OWNER, 0.0, settings)["joy"] == 0.5


# -- engine ------------------------------------------------------------------

def _pos_sum(event_record: dict) -> float:
    return sum(v for v in event_record["impulses"].values())


async def test_t10_owner_responds_more_than_new_guest(clock, ws, monkeypatch):
    db = _db()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_warm("owner"))
    await eng.appraise(_warm("discord_9"))
    owner, guest = [w["data"] for w in db.writes]
    assert owner["person_id"] == "owner" and guest["person_id"] == "discord_9"
    assert _pos_sum(owner) > _pos_sum(guest) * 1.2


async def test_writes_to_the_right_entity_only(clock, ws, monkeypatch):
    db = _db()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_warm("owner"))
    assert [k for k, _ in db.updates] == ["entity:owner"]
    row = db.entities["entity:owner"]
    assert row["familiarity"] == pytest.approx(0.6 + 0.03 * 0.4)
    assert db.updates[0][1]["at"] == T0
    assert db.entities["entity:discord_9"]["familiarity"] is None
    params = db.updates[0][1]
    assert type(params["rid"]).__name__ == "RecordID"


async def test_nothing_written_without_person_id(clock, ws, monkeypatch):
    db = _db()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_warm(None))
    await eng.appraise(_warm(None, kind="system_event"))
    await eng.appraise(memory_write_failed())
    await eng.appraise(tool_succeeded("web_search"))  # person_id is the tool name
    assert db.updates == []
    assert eng._rel_baseline is None
    assert memory_write_failed().person_id is None


async def test_unknown_entity_is_not_created(clock, ws, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_warm("discord_77"))
    assert db.updates == []


async def test_stranger_single_hostile_message_is_capped(clock, ws, monkeypatch):
    db = _db()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_hostile("discord_9"))
    stranger = db.writes[-1]["data"]["impulses"]
    negative = {d: v for d, v in stranger.items() if d in rel_math.NEGATIVE_DIMENSIONS}
    assert negative
    assert max(negative.values()) <= settings.emotion_stranger_hostility_cap + 1e-12
    await eng.appraise(_hostile("owner"))
    owner = db.writes[-1]["data"]["impulses"]
    assert max(v for d, v in owner.items() if d in rel_math.NEGATIVE_DIMENSIONS) > 0.5


async def test_baseline_follows_speaker_and_keeps_mood_shift(clock, ws, monkeypatch):
    db = _db()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_warm("discord_9", warmth=0.0, congruence=0.0))
    stranger = eng._effective_baseline()
    assert stranger.love == 0.0 and stranger.trust == pytest.approx(0.3 * 0.2 / 0.7)
    await eng.appraise(_warm("owner", warmth=0.0, congruence=0.0))
    owner = eng._effective_baseline()
    assert owner.love == pytest.approx(0.05) and owner.trust == pytest.approx(0.2)
    # mood shift still applies on top
    monkeypatch.setattr(settings, "emotion_mood_enabled", True)
    eng._mood["valence"] = 1.0
    shifted = eng._effective_baseline()
    assert shifted.love == pytest.approx(0.05 + 0.1)
    assert shifted.trust == pytest.approx(0.2 + 0.1)
    assert eng.config.baseline.love == 0.05


async def test_get_state_two_people_differ(clock, ws, monkeypatch):
    db = _db()
    eng = _engine(db, monkeypatch)
    a = await eng.get_state("owner")
    b = await eng.get_state("discord_9")
    assert a.vector.love != b.vector.love and a.vector.trust != b.vector.trust
    assert a.vector.love == pytest.approx(0.05)
    assert b.vector.love == 0.0
    assert a.vector.joy == b.vector.joy
    plain = await eng.get_state()
    assert plain.vector.love == eng.current_vector.love


# -- ablation ----------------------------------------------------------------

async def test_ablation_flag_off_is_the_old_behaviour(clock, ws, monkeypatch):
    events = [_warm("owner"), _hostile("discord_9"), _warm("discord_9"), _hostile("owner")]

    async def run(flag: bool):
        db = _db()
        eng = _engine(db, monkeypatch, flag=flag)
        for ev in events:
            clock.advance(60)
            await eng.tick()
            await eng.appraise(ev)
        return eng, db

    off, off_db = await run(False)
    assert off_db.updates == [] and off._rel_baseline is None
    assert off._effective_baseline() == off.config.baseline
    state = await off.get_state("owner")
    assert state.vector == off.current_vector

    # Same events with the flag on end somewhere else, so the flag does something.
    on, _ = await run(True)
    assert on.current_vector != off.current_vector

    # Flag off equals the pre-change engine: impulses are the table's, unscaled.
    from aura.engines.emotion.appraisal import impulses_for
    recorded = [w["data"]["impulses"] for w in off_db.writes if w["table"] == "emotion_event"]
    assert recorded == [impulses_for(e.appraisal, e.user_state) for e in events]
