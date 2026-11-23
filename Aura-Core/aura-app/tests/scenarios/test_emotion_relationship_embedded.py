"""Relationship scenario tests (W4-14, T10): embedded SurrealDB with the real schema.

The owner and a guest are created with the memory write path's ensure_person,
then events are appraised and the entity rows are read back. No model is called.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.emotion.engine import EmotionEngine
from aura.engines.memory.v2.episodes import ensure_person
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock():
    c = FakeClock(_START)
    set_clock(c)
    yield c
    set_clock(Clock())


@pytest.fixture
async def db():
    d = EmbeddedSurrealDB()
    await d.connect()
    yield d
    await d.close()


@pytest.fixture
async def engine(db, clock, monkeypatch):
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    monkeypatch.setattr(settings, "emotion_relationships_enabled", True)
    eng = EmotionEngine(config=EmotionPhysicsConfig())
    eng.db = db
    eng._message_bus = None
    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        yield eng


def _event(person: str | None, **kw) -> AppraisalEvent:
    params = dict(congruence=0.6, warmth=0.8, intensity=0.8, agency="other", control=0.8)
    params.update(kw)
    return AppraisalEvent(
        kind="message", source="conversation", person_id=person,
        appraisal=Appraisal(**params),
    )


async def _row(db, key: str) -> dict:
    rows = await db.query("SELECT * FROM $rid", {"rid": to_record_id(f"entity:{key}")})
    return rows[0]


async def test_fields_written_to_the_speaker_entity_only(db, engine, clock):
    await ensure_person(db, "owner", None)
    await ensure_person(db, "discord_9", "Guest")
    before = await _row(db, "owner")
    assert before.get("familiarity") is None  # NONE until the first event

    await engine.appraise(_event("discord_9"))

    guest = await _row(db, "discord_9")
    assert guest["familiarity"] == pytest.approx(0.03)
    assert guest["affection"] > 0.0 and guest["trust"] > 0.3
    assert guest["relationship_updated_at"] == _START
    owner = await _row(db, "owner")
    assert owner.get("familiarity") is None and owner.get("relationship_updated_at") is None
    assert guest["name"] == "Guest"  # the entity's other fields survive


async def test_no_person_no_write_and_no_entity_created(db, engine, clock):
    await ensure_person(db, "owner", None)
    await engine.appraise(_event(None))
    await engine.appraise(_event("discord_404"))  # no entity yet: nothing is created
    owner = await _row(db, "owner")
    assert owner.get("familiarity") is None
    rows = await db.query("SELECT id FROM entity", {})
    assert len(rows) == 1


async def test_owner_larger_response_than_new_guest(db, engine, clock):
    await ensure_person(db, "owner", None)
    await ensure_person(db, "discord_9", "Guest")
    await engine.appraise(_event("owner"))
    await engine.appraise(_event("discord_9"))
    rows = await db.query("SELECT person_id, impulses FROM emotion_event ORDER BY at ASC", {})
    sums = {r["person_id"]: sum(r["impulses"].values()) for r in rows}
    assert sums["owner"] > sums["discord_9"]


async def test_get_state_differs_by_person_with_real_rows(db, engine, clock):
    await ensure_person(db, "owner", None)
    await ensure_person(db, "discord_9", "Guest")
    for _ in range(5):
        await engine.appraise(_event("owner"))
    owner = await engine.get_state("owner")
    guest = await engine.get_state("discord_9")
    assert owner.vector.love > guest.vector.love
    assert owner.vector.trust > guest.vector.trust
