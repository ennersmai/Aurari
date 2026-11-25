"""P2-31: goal stage, crystal checklist, transitions, migration."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.db.query_utils import extract_rows, to_record_id
from aura.engines.goal import engine as engine_mod
from aura.engines.goal.engine import GoalEngine
from aura.models.goal import Goal
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FULL = dict(outcome="ship it", done_criteria=["tests pass"], owner="mai",
            horizon="this week", first_action="write the test")


def _goal(gid="g1", **kw):
    return Goal(goal_id=gid, name="n" + gid, description="d", goal_type="creative",
                origin="t", created=_START, updated=_START, **kw)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(engine_mod, "get_db_client", lambda: d)
    yield d
    set_clock(Clock())
    await d.close()


async def _insert(db, gid, **extra):
    row = {"name": "n", "description": "d", "goal_type": "creative", "origin": "t",
           "created": _START, "updated": _START, **extra}
    await db.query("CREATE $rid CONTENT $row", {"rid": to_record_id(f"goal:{gid}"), "row": row})


async def _stored(db, gid):
    return extract_rows(await db.query("SELECT * FROM $rid", {"rid": to_record_id(f"goal:{gid}")}))[0]


def test_checklist_lists_missing():
    g = _goal(outcome="x", owner="aura")
    c = g.crystallization()
    assert c["missing"] == ["done_criteria", "horizon", "first_action"]
    assert not c["complete"] and c["items"]["outcome"] and c["items"]["owner"]
    assert _goal(**FULL).crystallization()["complete"]
    assert not _goal(**{**FULL, "outcome": "  "}).crystallization()["complete"]


def test_b3_criteria_count_as_done_criteria():
    crit = [{"id": "c", "name": "n", "kind": "test_pass", "spec": {}, "status": "open"}]
    g = _goal(**{**FULL, "done_criteria": None}, criteria=crit)
    assert g.crystallization()["complete"]


async def test_transitions_forward_only(db):
    await _insert(db, "g1")
    eng = GoalEngine()
    eng.active_goals = [_goal()]
    ok, why = await eng.advance_stage("g1", "crystal")
    assert not ok and "outcome" in why
    await eng.update_checklist("g1", **FULL)
    assert eng.active_goals[0].stage == "forming"
    assert (await eng.advance_stage("g1", "crystal"))[0]
    assert not (await eng.advance_stage("g1", "forming"))[0]
    assert not (await eng.advance_stage("g1", "crystal"))[0]
    assert "milestones" in (await eng.advance_stage("g1", "active"))[1]
    eng.active_goals[0].milestones = [{"name": "m", "evidence_spec": {}, "status": "open",
                                       "evidence_refs": []}]
    assert (await eng.advance_stage("g1", "active"))[0]
    assert not (await eng.advance_stage("g1", "closed"))[0]  # needs a reason
    assert (await eng.advance_stage("g1", "closed", close_reason="done"))[0]
    row = await _stored(db, "g1")
    assert row["stage"] == "closed" and row["close_reason"] == "done"
    assert row["stage_changed"] is not None


async def test_outcome_change_returns_crystal_to_forming(db):
    await _insert(db, "g1")
    eng = GoalEngine()
    eng.active_goals = [_goal(stage="crystal", **FULL)]
    await eng.change_outcome("g1", "ship it")  # unchanged: stays crystal
    assert eng.active_goals[0].stage == "crystal"
    await eng.change_outcome("g1", "something else")
    assert eng.active_goals[0].stage == "forming"
    assert (await _stored(db, "g1"))["stage"] == "forming"
    with pytest.raises(ValueError):
        eng.active_goals[0].stage = "crystal"
        await eng.update_checklist("g1", outcome="third")


async def test_migration_idempotent_and_keeps_fields(db):
    await _insert(db, "old", progress=0.4)
    await _insert(db, "new", stage="crystal")
    eng = GoalEngine()
    assert await eng.migrate_stages() == 1
    assert await eng.migrate_stages() == 0
    old = await _stored(db, "old")
    assert old["stage"] == "forming" and old["progress"] == 0.4 and old["origin"] == "t"
    assert (await _stored(db, "new"))["stage"] == "crystal"


async def test_loaded_goal_has_stage_after_initialize(db):
    await _insert(db, "old")
    eng = GoalEngine()
    await eng.initialize()
    assert [g.stage for g in eng.active_goals] == ["forming"]
    assert eng.active_goals[0].crystallization()["missing"]


async def test_update_checklist_rejects_bad_owner_before_saving(db):
    """A bad owner value is refused and nothing is written (supervisor review)."""
    import pydantic

    await _insert(db, "g1")
    eng = GoalEngine()
    eng.active_goals = [_goal()]
    with pytest.raises(pydantic.ValidationError):
        await eng.update_checklist("g1", owner="bob")
    assert eng.active_goals[0].owner is None
    assert (await _stored(db, "g1")).get("owner") is None
