"""Guest cap scenario (W4-15, T11): embedded SurrealDB with the real schema.

Proves the `capped` field persists on emotion_event and that the window is
rebuilt from the real table by a fresh engine.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.emotion.engine import EmotionEngine
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


def _make(db, monkeypatch):
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    monkeypatch.setattr(settings, "emotion_relationships_enabled", False)
    monkeypatch.setattr(settings, "emotion_guest_cap_enabled", True)
    monkeypatch.setattr(settings, "emotion_guest_cap_per_hour", 0.5)
    eng = EmotionEngine(config=EmotionPhysicsConfig())
    eng.db = db
    eng._message_bus = None
    return eng


def _hostile(person: str, kind: str = "message") -> AppraisalEvent:
    return AppraisalEvent(
        kind=kind, source="conversation", person_id=person,
        appraisal=Appraisal(
            congruence=-0.9, warmth=-0.9, intensity=0.9, agency="other", control=0.2
        ),
    )


async def test_capped_persists_and_window_rebuilds_from_table(db, clock, monkeypatch):
    eng = _make(db, monkeypatch)
    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        for _ in range(15):
            await eng.appraise(_hostile("discord_42"))
        await eng.appraise(_hostile("owner"))
    rows = await db.query(
        "SELECT person_id, size, capped FROM emotion_event WHERE person_id = $p",
        {"p": "discord_42"},
    )
    assert len(rows) == 15
    guest_total = sum(r["size"] for r in rows)
    assert 0.0 < guest_total <= 0.5 + 1e-9
    assert any(r["size"] == 0 and r["capped"] is True for r in rows)
    owner = await db.query(
        "SELECT capped FROM emotion_event WHERE person_id = $p", {"p": "owner"}
    )
    assert owner[0].get("capped") is None

    eng2 = _make(db, monkeypatch)
    await eng2._load_guest_window()
    assert sum(s for _, s in eng2._guest_window) == pytest.approx(guest_total)
    assert len(eng2._guest_window) == 15
