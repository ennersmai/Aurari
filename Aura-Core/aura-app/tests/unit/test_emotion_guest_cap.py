"""Guest venue cap tests (W4-15, Emotion PRD 7, T11). Fake clock, fake DB, no model."""

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
CAP = 0.5


class FakeDB:
    """Stores emotion_event rows; answers the guest-window query like the table would."""

    def __init__(self):
        self.rows: list[dict[str, Any]] = []
        self.window_queries: list[tuple[str, dict]] = []

    async def create(self, table: str, data: dict[str, Any]) -> Any:
        assert table == "emotion_event"
        self.rows.append(dict(data))
        return {"id": "emotion_event:test"}

    async def query(self, sql: str, params: dict | None = None) -> list:
        if "FROM emotion_event" in sql and "$kind" in sql:
            self.window_queries.append((sql, params))
            return [
                {"at": r["at"], "size": r["size"]}
                for r in self.rows
                if r["kind"] == params["kind"]
                and r["person_id"] not in (None, params["owner"])
                and r["at"] > params["since"]
            ]
        return []


@pytest.fixture
def clock():
    c = FakeClock(T0)
    set_clock(c)
    yield c
    set_clock(Clock())


@pytest.fixture(autouse=True)
def ws():
    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        yield


def _engine(db: FakeDB, monkeypatch, flag: bool = True):
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    monkeypatch.setattr(settings, "emotion_relationships_enabled", False)
    monkeypatch.setattr(settings, "emotion_guest_cap_enabled", flag)
    monkeypatch.setattr(settings, "emotion_guest_cap_per_hour", CAP)
    from aura.engines.emotion.engine import EmotionEngine

    eng = EmotionEngine(config=EmotionPhysicsConfig())
    eng.db = db
    eng._message_bus = None
    eng.tick_rate = 0
    return eng


def _hostile(person: str | None, kind: str = "message") -> AppraisalEvent:
    return AppraisalEvent(
        kind=kind, source="conversation", person_id=person,
        appraisal=Appraisal(
            congruence=-0.9, warmth=-0.9, intensity=0.9, agency="other", control=0.2
        ),
    )


def _sizes(db: FakeDB, person: str | None = None) -> list[float]:
    return [r["size"] for r in db.rows if person is None or r["person_id"] == person]


def _max_diff(a, b) -> float:
    da, dbb = a.model_dump(), b.model_dump()
    return max(abs(da[k] - dbb[k]) for k in da)


async def test_hundred_hostile_guest_messages_stay_within_cap(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    start = eng.current_vector.model_copy()
    for _ in range(100):
        await eng.appraise(_hostile("discord_42"))
        clock.advance(30)
    assert len(db.rows) == 100
    assert sum(_sizes(db)) <= CAP + 1e-9
    assert _max_diff(eng.current_vector, start) <= CAP + 1e-9
    # Without a cap the same run would move the state well past the budget.
    assert sum(_sizes(db)) > CAP * 0.9
    assert any(r["capped"] for r in db.rows)
    assert _sizes(db)[-1] == 0.0 and db.rows[-1]["capped"] is True
    assert db.rows[-1]["impulses"] == {}


async def test_uncapped_run_would_exceed_cap(clock, monkeypatch):
    """Guards the test above: the hostile stream really is bigger than the cap."""
    db = FakeDB()
    eng = _engine(db, monkeypatch, flag=False)
    for _ in range(100):
        await eng.appraise(_hostile("discord_42"))
    assert sum(_sizes(db)) > CAP * 2
    assert all("capped" not in r for r in db.rows)


async def test_budget_frees_as_window_slides(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    for _ in range(20):
        await eng.appraise(_hostile("g1"))
    assert _sizes(db)[-1] == 0.0
    vec = eng.current_vector.model_copy()
    await eng.appraise(_hostile("g1"))
    assert _max_diff(eng.current_vector, vec) == 0.0

    clock.set(T0 + timedelta(hours=1, seconds=1))
    n = len(db.rows)
    await eng.appraise(_hostile("g1"))
    assert db.rows[n]["size"] > 0.0
    assert _max_diff(eng.current_vector, vec) > 0.0


async def test_partial_budget_scales_the_event_to_fit(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    await eng.appraise(_hostile("g1"))
    first = db.rows[0]["size"]
    monkeypatch.setattr(settings, "emotion_guest_cap_per_hour", first * 1.5)
    await eng.appraise(_hostile("g1"))
    second = db.rows[1]
    assert 0.0 < second["size"] <= first * 0.5 + 1e-9
    assert second["capped"] is True
    assert db.rows[0]["capped"] is False


async def test_owner_never_capped_and_uses_no_budget(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    for _ in range(5):
        await eng.appraise(_hostile("owner"))
    assert all("capped" not in r for r in db.rows)
    owner_total = sum(_sizes(db))
    assert owner_total > CAP  # more than the guest budget moved, uncapped
    # No budget was used.
    assert len(eng._guest_window) == 0
    assert await eng._guest_budget_remaining() == CAP


async def test_tool_events_with_a_person_id_use_no_budget(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    for _ in range(5):
        await eng.appraise(_hostile("web_search", kind="tool"))
    assert all("capped" not in r for r in db.rows)
    assert sum(_sizes(db)) > CAP
    assert len(eng._guest_window) == 0


async def test_events_without_person_id_are_not_capped(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    for _ in range(30):
        await eng.appraise(_hostile(None))
    assert all("capped" not in r for r in db.rows)
    assert len(eng._guest_window) == 0


async def test_window_rebuilt_from_table_after_reload(clock, monkeypatch):
    db = FakeDB()
    eng = _engine(db, monkeypatch)
    for _ in range(20):
        await eng.appraise(_hostile("g1"))
    used = sum(_sizes(db))
    assert used <= CAP + 1e-9

    # Restart: a new engine over the same table, same clock.
    eng2 = _engine(db, monkeypatch)
    await eng2.initialize()
    assert sum(s for _, s in eng2._guest_window) == pytest.approx(used)
    sql, params = db.window_queries[-1]
    assert "$since" in sql and isinstance(params["since"], datetime)
    vec = eng2.current_vector.model_copy()
    n = len(db.rows)
    await eng2.appraise(_hostile("g1"))
    assert db.rows[n]["size"] <= max(0.0, CAP - used) + 1e-9
    assert sum(_sizes(db)) <= CAP + 1e-9
    assert _max_diff(eng2.current_vector, vec) <= max(0.0, CAP - used) + 1e-9

    # Rows older than an hour are not counted on reload.
    clock.set(T0 + timedelta(hours=2))
    eng3 = _engine(db, monkeypatch)
    await eng3.initialize()
    assert len(eng3._guest_window) == 0


async def test_ablation_flag_off_is_old_behaviour(clock, monkeypatch):
    off_db, on_db = FakeDB(), FakeDB()
    off = _engine(off_db, monkeypatch, flag=False)
    for _ in range(10):
        await off.appraise(_hostile("g1"))
    assert all("capped" not in r for r in off_db.rows)
    assert len(off._guest_window) == 0
    assert off_db.window_queries == []

    # Same run with the cap enabled but a huge budget matches flag-off exactly.
    on = _engine(on_db, monkeypatch, flag=True)
    monkeypatch.setattr(settings, "emotion_guest_cap_per_hour", 1000.0)
    for _ in range(10):
        await on.appraise(_hostile("g1"))
    assert on.current_vector == off.current_vector
    assert _sizes(on_db) == _sizes(off_db)

    # With a tight budget it differs, so the comparison above is meaningful.
    tight_db = FakeDB()
    tight = _engine(tight_db, monkeypatch, flag=True)
    for _ in range(10):
        await tight.appraise(_hostile("g1"))
    assert tight.current_vector != off.current_vector
