"""B3-01: goal schema v2 (criteria, evidence, abandoned) on the real schema."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from aura.api.routes import goal as goal_routes
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.models.goal import Goal
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _crit(cid, kind="owner_confirms", status="open"):
    return {"id": cid, "name": f"crit {cid}", "kind": kind, "spec": {}, "status": status,
            "met_at": None, "evidence_ref": None}


def _goal(gid="goal:g1", **kw):
    return Goal(goal_id=gid, name="n", description="d", goal_type="creative", origin="t", **kw)


@pytest.fixture
async def db():
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    yield d
    set_clock(Clock())
    await d.close()


async def _insert(db, gid, extra=None):
    row = {"name": "n", "description": "d", "goal_type": "creative", "origin": "t",
           "created": _START, "updated": _START, **(extra or {})}
    await db.query("CREATE $rid CONTENT $row", {"rid": to_record_id(gid), "row": row})


async def _row(db, gid):
    rows = await db.query("SELECT * FROM $rid", {"rid": to_record_id(gid)})
    return rows[0]


def test_model_round_trip_with_and_without_new_fields():
    legacy = _goal()
    assert legacy.criteria is None and legacy.evidence is None
    assert legacy.abandon_reason is None and legacy.last_evidence_at is None
    g = _goal(criteria=[_crit("a")], evidence=[{"k": 1}], abandon_reason="x",
              last_evidence_at=_START, status="abandoned")
    again = Goal(**g.model_dump())
    assert again == g and again.status == "abandoned"


def test_progress_from_criteria():
    assert _goal().progress_from_criteria() is None
    assert _goal(criteria=[]).progress_from_criteria() is None
    g = _goal(criteria=[_crit("a", status="met"), _crit("b"), _crit("c"), _crit("d", status="met")])
    assert g.progress_from_criteria() == 0.5


async def test_table_stores_new_fields_and_abandoned(db):
    await _insert(db, "goal:new", {
        "status": "abandoned", "abandon_reason": "stalled", "last_evidence_at": _START,
        "criteria": [{**_crit("a"), "spec": {"path": "x"}}], "evidence": [{"ref": "r"}],
    })
    row = await _row(db, "goal:new")
    assert row["status"] == "abandoned" and row["abandon_reason"] == "stalled"
    assert row["criteria"][0]["spec"] == {"path": "x"}
    assert row["evidence"] == [{"ref": "r"}] and row["last_evidence_at"] == _START


async def test_legacy_row_loads_with_none(db):
    await _insert(db, "goal:old")
    row = await _row(db, "goal:old")
    for f in ("criteria", "evidence", "abandon_reason", "last_evidence_at"):
        assert row.get(f) is None
    g = Goal(**{**row, "goal_id": "goal:old"})
    assert g.criteria is None and g.progress_from_criteria() is None


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    g = _goal("goal:g1", criteria=[_crit("own"), _crit("f", kind="file_exists")])
    engine = SimpleNamespace(active_goals=[g], db=db)
    goal_routes.set_goal_engine(engine)
    app = FastAPI()
    app.include_router(goal_routes.router, prefix="/goal")
    yield TestClient(app), engine
    goal_routes.set_goal_engine(None)


async def test_routes(client, db):
    await _insert(db, "goal:g1")
    c, engine = client
    body = {"criteria": [{"id": "new", "name": "N", "kind": "test_pass", "spec": {"a": 1}},
                         {"id": "f", "name": "renamed", "kind": "file_exists"}]}
    r = c.post("/goal/goal:g1/criteria", json=body)
    assert r.status_code == 200
    ids = [x["id"] for x in r.json()["goal"]["criteria"]]
    assert ids == ["own", "f", "new"]
    stored = (await _row(db, "goal:g1"))["criteria"]
    assert [x["id"] for x in stored] == ["own", "f", "new"] and stored[1]["name"] == "renamed"
    # list and get routes return the new fields
    got = c.get("/goal/goal:g1").json()["goal"]
    assert len(got["criteria"]) == 3 and "abandon_reason" in got and "evidence" in got
    assert c.get("/goal/active").json()["goals"][0]["criteria"]
    assert c.post("/goal/goal:nope/criteria", json=body).status_code == 404
    bad = {"criteria": [{"id": "z", "name": "z", "kind": "mood_matches"}]}
    assert c.post("/goal/goal:g1/criteria", json=bad).status_code == 422


async def test_owner_confirm_only_owner_confirms_kind(client, db):
    await _insert(db, "goal:g1")
    c, engine = client
    assert c.post("/goal/goal:g1/criteria/f/confirm").status_code == 400
    assert c.post("/goal/goal:g1/criteria/missing/confirm").status_code == 404
    assert engine.active_goals[0].criteria[1]["status"] == "open"
    r = c.post("/goal/goal:g1/criteria/own/confirm")
    assert r.status_code == 200
    row = await _row(db, "goal:g1")
    own = row["criteria"][0]
    assert own["status"] == "met" and own["met_at"] == _START and own["evidence_ref"] == "owner"
    assert row["last_evidence_at"] == _START and row["evidence"][0]["criterion_id"] == "own"
    assert Goal(**{**row, "goal_id": "goal:g1"}).progress_from_criteria() == 0.5


async def test_flag_off_ablation(client, db, monkeypatch):
    await _insert(db, "goal:g1")
    c, engine = client
    monkeypatch.setattr(settings, "goals_v2_enabled", False)
    body = {"criteria": [{"id": "n", "name": "N", "kind": "test_pass"}]}
    assert c.post("/goal/goal:g1/criteria", json=body).status_code == 409
    assert c.post("/goal/goal:g1/criteria/own/confirm").status_code == 409
    assert engine.active_goals[0].criteria[0]["status"] == "open"
    assert (await _row(db, "goal:g1")).get("criteria") is None


async def test_engine_loads_stored_goals_without_goal_id_field(db):
    """The goal table has no goal_id field; the loader takes it from the record id."""
    from aura.engines.goal.engine import GoalEngine

    await _insert(db, "goal:g9", {"status": "active"})
    eng = GoalEngine.__new__(GoalEngine)
    eng.db = db
    eng.active_goals = []
    import logging
    eng.logger = logging.getLogger("t")
    await eng._load_active_goals()
    assert [g.goal_id for g in eng.active_goals] == ["g9"]
