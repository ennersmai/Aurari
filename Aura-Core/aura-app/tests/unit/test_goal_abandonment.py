"""B3-03: stall and abandonment tests (T8)."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.goal import engine as engine_mod
from aura.engines.goal.engine import GoalEngine
from aura.models.goal import Goal
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GID = "goal:g1"


def _crit(cid, kind, spec=None, status="open"):
    return {"id": cid, "name": f"crit {cid}", "kind": kind, "spec": spec or {},
            "status": status, "met_at": None, "evidence_ref": None}


def _goal(criteria=None, **kw):
    kw.setdefault("created", _START)
    kw.setdefault("goal_id", GID)
    return Goal(name="test goal", description="d", goal_type="creative", origin="t",
                criteria=criteria, **kw)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(engine_mod, "get_db_client", lambda: d)

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(engine_mod.asyncio, "sleep", _no_sleep)
    yield d
    set_clock(Clock())
    await d.close()


async def _insert_goal(db, goal):
    row = {"name": "n", "description": "d", "goal_type": "creative", "origin": "t",
           "created": _START, "updated": _START, "criteria": goal.criteria}
    await db.query("CREATE $rid CONTENT $row", {"rid": to_record_id(goal.goal_id), "row": row})


async def _engine(db, goal):
    await _insert_goal(db, goal)
    eng = GoalEngine()
    eng.active_goals = [goal]
    eng._consider_new_goal = lambda *a, **k: None
    return eng


async def _noop(*a, **k):
    return None


async def test_abandoned_after_stall_days(db, monkeypatch):
    """A goal stalled past the limit becomes abandoned, never completed, progress not set to 1.0."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "goal_stall_days", 7)

    goal = _goal([_crit("c1", "owner_confirms")], progress=0.05, last_evidence_at=None)
    eng = await _engine(db, goal)

    # Advance clock 8 days (past the 7-day stall limit)
    set_clock(FakeClock(_START.replace(day=9)))

    await eng.tick()

    assert goal.status == "abandoned"
    assert goal.completed is None
    assert goal.progress == 0.05  # progress unchanged
    assert goal.abandon_reason == "no evidence for 8 days"


async def test_fresh_evidence_prevents_abandonment(db, monkeypatch):
    """A goal with fresh evidence is not abandoned."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "goal_stall_days", 7)

    # Goal with evidence from 3 days ago
    three_days_ago = _START.replace(day=4)
    goal = _goal([_crit("c1", "owner_confirms")], progress=0.3, last_evidence_at=three_days_ago)
    eng = await _engine(db, goal)

    # Advance clock to day 10 (7 days from creation, but only 7 days from last evidence)
    set_clock(FakeClock(_START.replace(day=10)))

    await eng.tick()

    # Last evidence was day 4, now day 10 = 6 days, less than 7-day limit
    assert goal.status == "active"
    assert goal.abandon_reason is None


async def test_abandonment_agenda_item_created_once(db, monkeypatch):
    """The agenda item is created once per abandonment."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "goal_stall_days", 7)
    monkeypatch.setattr(settings, "autonomy_enabled", True)

    goal = _goal([_crit("c1", "owner_confirms")], progress=0.05)
    eng = await _engine(db, goal)

    # Mock may_initiate to allow (imported from aura.autonomy.controls in the function)
    from aura.autonomy.controls import Decision
    mock_decision = Decision(allowed=True, reason="level_open")
    monkeypatch.setattr("aura.autonomy.controls.may_initiate", AsyncMock(return_value=mock_decision))

    # Mock AgendaService.create (imported from aura.autonomy.agenda in the function)
    mock_agenda_create = AsyncMock()
    monkeypatch.setattr("aura.autonomy.agenda.AgendaService.create", mock_agenda_create)

    # Advance clock 8 days
    set_clock(FakeClock(_START.replace(day=9)))

    await eng.tick()

    # Agenda item should be created once
    mock_agenda_create.assert_called_once()
    call_args = mock_agenda_create.call_args
    assert call_args[1]["kind"] == "observation"
    assert GID in call_args[1]["refs"]
    assert "abandoned" in call_args[1]["content"]

    # Second tick should not create another agenda item
    mock_agenda_create.reset_mock()
    await eng.tick()
    mock_agenda_create.assert_not_called()


async def test_reopen_abandoned_goal(db, monkeypatch):
    """Reopen an abandoned goal resets last_evidence_at to now."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "goal_stall_days", 7)

    goal = _goal([_crit("c1", "owner_confirms")], progress=0.2, last_evidence_at=None)
    eng = await _engine(db, goal)

    # Abandon the goal
    set_clock(FakeClock(_START.replace(day=9)))
    await eng.tick()

    assert goal.status == "abandoned"
    assert goal.abandon_reason is not None

    # Reopen the goal
    reopened_at = _START.replace(day=10)
    set_clock(FakeClock(reopened_at))
    reopened = await eng.reopen_goal(GID)

    assert reopened is goal
    assert goal.status == "active"
    assert goal.abandon_reason is None
    assert goal.last_evidence_at == reopened_at
    assert goal.progress == 0.2  # progress unchanged


async def test_flag_off_keeps_old_stale_complete_behaviour(db, monkeypatch):
    """Flag off keeps the old stale-complete behaviour (ablation)."""
    monkeypatch.setattr(settings, "goals_v2_enabled", False)

    goal = _goal(None, progress=0.05)
    eng = await _engine(db, goal)

    # Advance clock 25 hours (>24 hours)
    set_clock(FakeClock(_START.replace(hour=13, day=2)))

    await eng.tick()

    # Old behaviour: goal becomes completed at 100% progress
    assert goal.status == "completed"
    assert goal.progress == 1.0
    assert goal.completed is not None


async def test_abandonment_only_when_active(db, monkeypatch):
    """Only active goals can be abandoned."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "goal_stall_days", 7)

    # Test completed goal
    goal = _goal([_crit("c1", "owner_confirms")], progress=1.0, status="completed")
    eng = await _engine(db, goal)

    set_clock(FakeClock(_START.replace(day=9)))
    await eng.tick()

    assert goal.status == "completed"  # unchanged

    # Test cancelled goal
    goal2 = _goal([_crit("c1", "owner_confirms")], progress=0.05, status="cancelled", goal_id="goal:g2")
    await _insert_goal(db, goal2)
    eng.active_goals.append(goal2)

    await eng.tick()

    assert goal2.status == "cancelled"  # unchanged


async def test_reopen_non_abandoned_goal_returns_false(db, monkeypatch):
    """Reopen on non-abandoned goal returns False."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)

    goal = _goal([_crit("c1", "owner_confirms")], progress=0.3, status="active")
    eng = await _engine(db, goal)

    success = await eng.reopen_goal(GID)
    assert success is None

    # Also test completed goal
    goal.status = "completed"
    success = await eng.reopen_goal(GID)
    assert success is None

async def test_reopen_after_restart_reads_goal_from_db(db, monkeypatch):
    """Abandoned goals are not loaded at startup; reopen reads the row from the DB."""
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    await db.query(
        "CREATE $rid CONTENT $row",
        {"rid": to_record_id("goal:g2"), "row": {
            "name": "n", "description": "d", "goal_type": "creative", "origin": "t",
            "created": _START, "updated": _START, "status": "abandoned",
            "abandon_reason": "no evidence for 9 days"}},
    )
    eng = GoalEngine()
    eng.active_goals = []
    set_clock(FakeClock(_START.replace(day=12)))
    goal = await eng.reopen_goal("g2")
    assert goal is not None and goal.status == "active"
    rows = await db.query("SELECT * FROM $rid", {"rid": to_record_id("goal:g2")})
    assert rows[0]["status"] == "active"
    assert rows[0].get("abandon_reason") is None
