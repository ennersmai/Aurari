"""B3-02: criteria checker and evidence-based progress (T7) on the real schema."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.goal import engine as engine_mod
from aura.engines.goal import evidence
from aura.engines.goal.engine import GoalEngine
from aura.models.goal import Goal
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GID = "goal:g1"


def _crit(cid, kind, spec=None, status="open"):
    return {"id": cid, "name": f"crit {cid}", "kind": kind, "spec": spec or {},
            "status": status, "met_at": None, "evidence_ref": None}


def _goal(criteria=None, **kw):
    return Goal(goal_id=GID, name="n", description="d", goal_type="creative", origin="t",
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


async def _met_ids(goal, db):
    return {m.criterion_id for m in await evidence.check(goal, _START, db)}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr(settings, "workspaces", {"w": str(root)})
    return root


async def test_file_exists_positive_negative_and_outside_workspace(db, ws, tmp_path):
    (ws / "out.txt").write_text("x")
    (tmp_path / "secret.txt").write_text("x")
    goal = _goal([
        _crit("yes", "file_exists", {"workspace": "w", "path": "out.txt"}),
        _crit("missing", "file_exists", {"workspace": "w", "path": "nope.txt"}),
        _crit("escape", "file_exists", {"workspace": "w", "path": "../secret.txt"}),
        _crit("abs", "file_exists", {"workspace": "w", "path": str(tmp_path / "secret.txt")}),
        _crit("unregistered", "file_exists", {"workspace": "zzz", "path": "out.txt"}),
    ])
    assert await _met_ids(goal, db) == {"yes"}


async def test_test_pass(db):
    goal = _goal([_crit("t", "test_pass")])
    assert await _met_ids(goal, db) == set()
    mk = "CREATE task SET task_id = 't', goal = 'work', created_at = time::now(), updated_at = time::now(), goal_id = $g, status = $s, tests_passed = $p"
    await db.query(mk, {"g": to_record_id(GID), "s": "complete", "p": False})
    await db.query(mk, {"g": to_record_id(GID), "s": "failed", "p": True})
    await db.query(mk, {"g": to_record_id("goal:other"), "s": "complete", "p": True})
    assert await _met_ids(goal, db) == set()
    await db.query(mk, {"g": to_record_id(GID), "s": "complete", "p": True})
    assert await _met_ids(goal, db) == {"t"}


async def _graph(db, goal_ref, statuses):
    g = await db.query(
        "CREATE task_graph SET goal = $g, created_at = $n, updated_at = $n",
        {"g": goal_ref, "n": _START},
    )
    for i, st in enumerate(statuses):
        await db.query(
            "CREATE task_node SET graph = $gr, node_id = $nid, kind = 'think', brief = 'b', "
            "success_criteria = 's', status = $st, created_at = $n, updated_at = $n",
            {"gr": g[0]["id"], "nid": f"n{i}", "st": st, "n": _START},
        )


async def test_task_node_done(db):
    goal = _goal([_crit("n", "task_node_done")])
    assert await _met_ids(goal, db) == set()  # no graph
    await _graph(db, "goal:other", ["done"])
    assert await _met_ids(goal, db) == set()  # someone else's graph
    await _graph(db, GID, ["done", "running"])
    assert await _met_ids(goal, db) == set()
    only = lambda nid: _goal([_crit("n", "task_node_done", {"node_id": nid})])
    assert await _met_ids(only("n0"), db) == {"n"}
    assert await _met_ids(only("n1"), db) == set()
    await db.query("UPDATE task_node SET status = 'done'")
    assert await _met_ids(goal, db) == {"n"}


async def test_question_resolved(db):
    goal = _goal([_crit("q", "question_resolved", {"question_id": "question:q1"})])
    await db.query(
        "CREATE question:q1 SET content = 'c', visibility = 'v', status = 'open', recorded_at = $n",
        {"n": _START},
    )
    assert await _met_ids(goal, db) == set()
    await db.query("UPDATE question:q1 SET status = 'resolved'")
    assert await _met_ids(goal, db) == {"q"}


async def test_owner_confirms_is_never_decided_by_the_checker(db):
    assert await _met_ids(_goal([_crit("o", "owner_confirms")]), db) == set()


async def _noop(*a, **k):
    return None


async def _engine(db, goal):
    await _insert_goal(db, goal)
    eng = GoalEngine()
    eng.active_goals = [goal]
    eng._consider_new_goal = _noop
    return eng


async def _boom():
    raise AssertionError("mood must not be consulted when v2 is on")


async def test_mood_without_work_stays_at_zero_over_many_ticks(db, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    goal = _goal([_crit("o", "owner_confirms"),
                  _crit("f", "file_exists", {"workspace": "w", "path": "x"})],
                 emotional_alignment={"joy": 0.9})
    eng = await _engine(db, goal)
    eng._emotion_engine = SimpleNamespace(get_current_state=_boom)
    for _ in range(25):
        await eng.tick()
    assert goal.progress == 0.0 and goal.status == "active" and goal.last_evidence_at is None


async def test_progress_moves_per_criterion_and_completes_only_when_all_met(db, ws, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    goal = _goal([_crit("f1", "file_exists", {"workspace": "w", "path": "a.txt"}),
                  _crit("f2", "file_exists", {"workspace": "w", "path": "b.txt"})])
    eng = await _engine(db, goal)
    await eng.tick()
    assert goal.progress == 0.0
    (ws / "a.txt").write_text("x")
    await eng.tick()
    assert goal.progress == 0.5 and goal.status == "active"
    assert goal.last_evidence_at == _START
    assert goal.evidence[-1]["criterion_id"] == "f1"
    rows = await db.query("SELECT * FROM $rid", {"rid": to_record_id(GID)})
    assert rows[0]["progress"] == 0.5 and rows[0]["criteria"][0]["status"] == "met"
    (ws / "b.txt").write_text("x")
    await eng.check_evidence()  # event path, no tick
    assert goal.progress == 1.0 and goal.status == "completed"


async def test_goal_without_criteria_keeps_progress(db, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    goal = _goal(None, progress=0.3)
    eng = await _engine(db, goal)
    await eng.tick()
    assert goal.progress == 0.3


async def test_flag_off_still_raises_progress_by_mood(db, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", False)
    goal = _goal(None, emotional_alignment={"joy": 0.9})
    eng = await _engine(db, goal)

    async def _state():
        return SimpleNamespace(vector=SimpleNamespace(model_dump=lambda: {"joy": 0.9}))

    eng._emotion_engine = SimpleNamespace(get_current_state=_state)
    await eng.tick()
    assert goal.progress > 0.0
