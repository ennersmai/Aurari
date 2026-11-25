"""B1-01: autonomy controls, the gate, quiet hours and the trace (embedded SurrealDB)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.autonomy import controls
from aura.autonomy.controls import may_initiate, quiet_hours_active
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    controls.reset_cache()
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    yield d
    controls.reset_cache()
    set_clock(Clock())
    await d.close()


async def _traces(db):
    return extract_rows(await db.query("SELECT * FROM autonomy_trace ORDER BY at ASC"))


KINDS = ["needs_decision", "task_done", "reminder", "idle_thought", "curiosity"]


async def _allowed(db):
    return {k for k in KINDS if (await may_initiate(k, db=db)).allowed}


async def test_levels_allow_exactly_their_kinds(db):
    await controls.set_level("silent", db)
    assert await _allowed(db) == set()
    await controls.set_level("important", db)
    assert await _allowed(db) == {"needs_decision", "task_done"}
    await controls.set_level("open", db)
    assert await _allowed(db) == set(KINDS)


async def test_owner_reminder_exception_at_important(db):
    assert (await may_initiate("reminder", db=db)).allowed is False
    assert (await may_initiate("reminder", owner_created=True, db=db)).allowed is True
    await controls.set_level("silent", db)
    assert (await may_initiate("reminder", owner_created=True, db=db)).allowed is False


async def test_default_level_and_bad_level(db, monkeypatch):
    assert (await controls.get_controls(db)).level == 1  # "important" (P2-33 mapping)
    with pytest.raises(ValueError):
        await controls.set_level("loud", db)


async def test_muted_kind_refused_and_unmuted(db):
    await controls.set_level("open", db)
    await controls.mute_kind("curiosity", db)
    d = await may_initiate("curiosity", db=db)
    assert not d.allowed and d.reason == "kind_muted"
    assert (await may_initiate("task_done", db=db)).allowed
    await controls.unmute_kind("curiosity", db)
    assert (await may_initiate("curiosity", db=db)).allowed


async def test_killed_refuses_everything_and_is_sync(db):
    await controls.set_level("open", db)
    assert controls.is_killed() is False
    await controls.set_killed(True, db)
    assert controls.is_killed() is True
    for k in KINDS:
        d = await may_initiate(k, owner_created=True, db=db)
        assert not d.allowed and d.reason == "killed"
    await controls.set_killed(False, db)
    assert controls.is_killed() is False
    assert (await may_initiate("task_done", db=db)).allowed


async def test_master_flag_off_refuses_with_reason_in_trace(db, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_enabled", False)
    await controls.set_level("open", db)
    d = await may_initiate("task_done", db=db)
    assert not d.allowed and d.reason == "autonomy_disabled"
    rows = await _traces(db)
    assert rows[-1]["why"] == "autonomy_disabled" and rows[-1]["allowed"] is False


async def test_singleton_survives_reread(db):
    await controls.set_level("open", db)
    await controls.mute_kind("curiosity", db)
    await controls.set_killed(True, db)
    controls.reset_cache()
    c = await controls.load_controls(db)
    assert c.level == 3 and c.muted_kinds == ["curiosity"] and c.killed is True
    assert c.killed_at == _START and c.updated_at == _START
    controls.reset_cache()
    await controls.set_killed(False, db)
    rows = extract_rows(await db.query("SELECT * FROM autonomy_control"))
    assert len(rows) == 1 and rows[0]["killed"] is False
    assert rows[0].get("killed_at") is None


async def test_trace_rows_for_allowed_and_refused(db):
    await controls.set_level("important", db)
    await may_initiate("task_done", source="sched", refs=["task_graph:1"], db=db)
    from aura.clock import get_clock

    get_clock().advance(5)
    await may_initiate("curiosity", db=db)
    rows = await _traces(db)
    assert len(rows) == 2
    a, r = rows
    assert a["source"] == "sched" and a["action"] == "initiate:task_done"
    assert a["allowed"] is True and a["refs"] == ["task_graph:1"]
    assert a["cost"]["level"] == 1 and a["at"] == _START and a["why"] == "level_1"
    assert r["allowed"] is False and r["action"] == "initiate:curiosity"


async def test_trace_cost_object_round_trips(db):
    from aura.autonomy import trace

    await trace.record("x", "act", "because", cost={"usd": 0.5, "tokens": 10}, db=db)
    assert (await _traces(db))[0]["cost"] == {"usd": 0.5, "tokens": 10}


@pytest.mark.parametrize("tz,hour,expected", [
    ("UTC", 23, True), ("UTC", 3, True), ("UTC", 8, False), ("UTC", 12, False),
    ("UTC", 22, True), ("UTC", 7, True),
    ("Europe/Paris", 21, True),   # 22:00 local in January
    ("Europe/Paris", 7, False),   # 08:00 local
    ("America/New_York", 3, True),   # 22:00 local previous day
    ("America/New_York", 13, True),  # 08:00 local is 13:00 UTC -> false below
])
def test_quiet_hours_across_midnight(monkeypatch, tz, hour, expected):
    monkeypatch.setattr(settings, "app_timezone", tz)
    monkeypatch.setattr(settings, "quiet_hours_start", "22:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "08:00")
    set_clock(FakeClock(datetime(2026, 1, 1, hour, 0, tzinfo=timezone.utc)))
    try:
        # New York at 13:00 UTC is 08:00 local: outside the window.
        if tz == "America/New_York" and hour == 13:
            expected = False
        assert quiet_hours_active(None) is expected
    finally:
        set_clock(Clock())


def test_quiet_hours_same_day_window(monkeypatch):
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "quiet_hours_start", "13:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "14:00")
    set_clock(FakeClock(datetime(2026, 1, 1, 13, 30, tzinfo=timezone.utc)))
    try:
        assert quiet_hours_active() is True
    finally:
        set_clock(Clock())
    assert quiet_hours_active(datetime(2026, 1, 1, 14, 0, tzinfo=timezone.utc)) is False


def test_config_defaults():
    from aura.config import Settings

    s = Settings()
    assert s.autonomy_default_level == "important"
    assert (s.quiet_hours_start, s.quiet_hours_end) == ("22:00", "08:00")
    assert s.autonomy_enabled is False and s.curiosity_enabled is False
