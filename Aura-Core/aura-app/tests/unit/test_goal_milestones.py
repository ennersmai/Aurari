"""P2-32: refine_goal, Sage milestone plan, milestone evidence, orphan and conflict flags.

Real schema (embedded SurrealDB), fake model client, FakeClock restored after each test.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from aura.autonomy.controls import Decision
from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows, to_record_id
from aura.engines.goal import crystallize, evidence
from aura.engines.goal import engine as engine_mod
from aura.engines.goal.engine import GoalEngine
from aura.models.goal import Goal
from aura.tools import consult, refine_goal
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FULL = dict(outcome="ship it", done_criteria=["tests pass"], owner="aura",
            horizon="this week", first_action="write the test")


class FakeLayers:
    def __init__(self):
        self.calls: list[dict] = []
        self.answers: list = []  # popped per call; a str is returned, an Exception raised

    async def plain_call(self, model, system, user, max_tokens, temperature):
        self.calls.append({"model": model, "system": system, "user": user})
        a = self.answers.pop(0) if self.answers else "{}"
        if isinstance(a, Exception):
            raise a
        return a


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(engine_mod, "get_db_client", lambda: d)

    async def _no_sleep(_):
        return None

    monkeypatch.setattr(engine_mod.asyncio, "sleep", _no_sleep)
    monkeypatch.setattr(settings, "goals_v3_enabled", True)
    yield d
    set_clock(Clock())
    await d.close()


@pytest.fixture
def layers(monkeypatch):
    fake = FakeLayers()
    monkeypatch.setattr(consult, "_get_layers", lambda: fake)
    return fake


@pytest.fixture
def agenda_gate(monkeypatch):
    allow = AsyncMock(return_value=Decision(True, "level_open"))
    monkeypatch.setattr("aura.autonomy.controls.may_initiate", allow)
    return allow


def _now():
    return get_clock().now()


async def _make(db, eng, gid="g1", **kw):
    row = {"name": "n" + gid, "description": "d", "goal_type": "creative", "origin": "t",
           "created": _START, "updated": _START}
    await db.query("CREATE $rid CONTENT $row", {"rid": to_record_id(f"goal:{gid}"), "row": row})
    goal = Goal(goal_id=gid, name="n" + gid, description="d", goal_type="creative", origin="t",
                created=_START, updated=_START, **kw)
    eng.active_goals.append(goal)
    return goal


def _engine(db):
    eng = GoalEngine()
    eng.db = db
    eng.active_goals = []
    return eng


async def _stored(db, gid):
    return extract_rows(await db.query("SELECT * FROM $rid", {"rid": to_record_id(f"goal:{gid}")}))[0]


async def _agenda(db):
    return extract_rows(await db.query("SELECT * FROM agenda_item"))


def _plan(*milestones):
    return json.dumps({"milestones": list(milestones)})


def _ms(name, kind="mai_confirms", **spec):
    return {"name": name, "evidence_spec": {"kind": kind, **spec}}


def _advance(days=0, hours=0):
    set_clock(FakeClock(_START + timedelta(days=days, hours=hours)))


def _swift(layers):
    return [c for c in layers.calls if c["model"] == settings.swift_model_for()]


# ---- evidence kinds ---------------------------------------------------------------------

GID = "goal:g1"


def _g(milestones, **kw):
    return Goal(goal_id=GID, name="n", description="d", goal_type="creative", origin="t",
                created=_START, updated=_START, milestones=milestones, **kw)


def _m(kind, **spec):
    return {"name": kind, "evidence_spec": {"kind": kind, **spec}, "status": "open", "evidence_refs": []}


async def _met(goal, db):
    return {m.kind: m.ref for m in await evidence.check_milestones(goal, _START, db)}


async def test_file_exists_and_commit(db, tmp_path, monkeypatch):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr(settings, "workspaces", {"w": str(root)})
    git = ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "init", "-q"], check=True)
    (root / "a.txt").write_text("x")
    goal = _g([_m("file_exists", workspace="w", path="a.txt"),
               _m("commit", workspace="w", contains="add widget")])
    assert list(await _met(goal, db)) == ["file_exists"]  # no commit yet
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "Add Widget parser"], check=True)
    met = await _met(goal, db)
    assert len(met["commit"]) == 40
    goal.milestones[1]["evidence_spec"]["contains"] = "something else"
    assert "commit" not in await _met(goal, db)


async def test_test_pass_task_node_and_metric(db):
    mk = ("CREATE task SET task_id = 't', goal = 'work', created_at = time::now(), "
          "updated_at = time::now(), goal_id = $g, status = 'complete', tests_passed = $p")
    goal = _g([_m("test_pass"), _m("metric_threshold", metric="tasks_complete", op=">=", value=2),
               _m("task_node_done", node_id="n1")])
    assert await _met(goal, db) == {}
    await db.query(mk, {"g": to_record_id(GID), "p": True})
    assert set(await _met(goal, db)) == {"test_pass"}  # one complete task is below the threshold of 2
    await db.query(mk, {"g": to_record_id(GID), "p": False})
    assert set(await _met(goal, db)) == {"test_pass", "metric_threshold"}
    g = await db.query("CREATE task_graph SET goal = $g, created_at = $n, updated_at = $n",
                       {"g": GID, "n": _START})
    await db.query("CREATE task_node SET graph = $gr, node_id = 'n1', kind = 'think', brief = 'b', "
                   "success_criteria = 's', status = 'done', created_at = $n, updated_at = $n",
                   {"gr": g[0]["id"], "n": _START})
    assert "task_node_done" in await _met(goal, db)


async def test_mai_confirms_and_model_specs_are_never_decided_by_code(db):
    goal = _g([_m("mai_confirms"), _m("metric_threshold", metric="mood", op=">=", value=1)])
    assert evidence.classify(goal.milestones[0]["evidence_spec"]) == "owner"
    assert evidence.classify(goal.milestones[1]["evidence_spec"]) == "model"
    assert await _met(goal, db) == {}


def test_plan_normalisation_turns_unknown_or_unusable_specs_into_mai_confirms():
    out = crystallize.normalize_milestones([
        _ms("a", "commit", workspace="w", contains="x"),
        _ms("b", "telepathy"),
        _ms("c", "commit"),  # no workspace: code cannot check it
        _ms("d", "metric_threshold", metric="mood", op=">=", value=3),
        {"name": "", "evidence_spec": {}},
        "junk",
    ])
    assert [m["evidence_spec"]["kind"] for m in out] == [
        "commit", "mai_confirms", "mai_confirms", "metric_threshold"]
    assert all(m["status"] == "open" and m["evidence_refs"] == [] for m in out)


def test_plan_is_capped_by_the_config_field(monkeypatch):
    monkeypatch.setattr(settings, "goals_v3_milestone_max", 2)
    assert len(crystallize.normalize_milestones([_ms("a"), _ms("b"), _ms("c")])) == 2


# ---- crystal: one Sage call, then evidence ------------------------------------------------

async def test_goal_reaching_crystal_gets_one_sage_call_and_becomes_active(db, layers):
    eng = _engine(db)
    goal = await _make(db, eng, stage="forming", **FULL)
    layers.answers = [_plan(_ms("first"), _ms("second", "test_pass"))]
    await eng.v3_tick()
    assert len(layers.calls) == 1 and layers.calls[0]["model"] == settings.sage_model_for()
    assert goal.stage == "active" and [m["name"] for m in goal.milestones] == ["first", "second"]
    await eng.v3_tick()
    await eng.v3_tick()
    assert len(layers.calls) == 1
    row = await _stored(db, "g1")
    assert row["stage"] == "active" and len(row["milestones"]) == 2 and row["plan_requested_at"]


async def test_failed_sage_plan_retries_only_after_the_configured_hours(db, layers):
    eng = _engine(db)
    goal = await _make(db, eng, stage="forming", **FULL)
    layers.answers = [RuntimeError("boom"), _plan(_ms("m"))]
    await eng.v3_tick()
    assert goal.stage == "crystal" and not goal.milestones and len(layers.calls) == 1
    _advance(hours=1)
    await eng.v3_tick()
    assert len(layers.calls) == 1
    _advance(hours=settings.goals_v3_plan_retry_hours + 1)
    await eng.v3_tick()
    assert len(layers.calls) == 2 and goal.stage == "active"


async def test_incomplete_checklist_never_calls_sage(db, layers):
    eng = _engine(db)
    goal = await _make(db, eng, stage="forming", outcome="x")
    await eng.v3_tick()
    assert layers.calls == [] and goal.stage == "forming"


async def test_progress_only_from_evidence_and_llm_never_marks_done(
    db, layers, agenda_gate, tmp_path, monkeypatch
):
    root = tmp_path / "ws"
    root.mkdir()
    monkeypatch.setattr(settings, "workspaces", {"w": str(root)})
    eng = _engine(db)
    goal = await _make(db, eng, stage="forming", **FULL)
    layers.answers = [_plan(
        _ms("file", "file_exists", workspace="w", path="out.txt"),
        _ms("owner"),
        _ms("metric", "metric_threshold", metric="mood", op=">=", value=1),
    )]
    # Swift insists the uncheckable milestone is done: it may only flag it for Mai.
    layers.answers.append(json.dumps({"results": [{"index": 2, "verdict": "looks_met", "reason": "yes"}]}))
    await eng.v3_tick()
    assert goal.progress == 0.0
    assert [m["status"] for m in goal.milestones] == ["open", "open", "open"]
    assert goal.milestones[2]["needs_confirmation"] is True
    assert len(layers.calls) == 2 and len(_swift(layers)) == 1
    items = await _agenda(db)
    assert len(items) == 1 and items[0]["kind"] == "question_for_you" and items[0]["refs"] == ["g1"]
    await eng.v3_tick()  # nothing new: flagged once
    assert len(await _agenda(db)) == 1 and goal.progress == 0.0
    (root / "out.txt").write_text("x")
    await eng.v3_tick()
    assert goal.milestones[0]["status"] == "done" and goal.milestones[0]["evidence_refs"]
    assert goal.progress == pytest.approx(1 / 3)
    assert (await _stored(db, "g1"))["progress"] == pytest.approx(1 / 3)
    # Mai confirms the two that wait for her: progress follows, the goal completes and closes.
    await eng.confirm_milestone("g1", 1)
    assert goal.progress == pytest.approx(2 / 3)
    await eng.confirm_milestone("g1", 2)
    assert goal.progress == 1.0 and goal.status == "completed"
    assert goal.stage == "closed" and goal.close_reason.startswith("completed")
    assert (await _stored(db, "g1"))["stage"] == "closed"


async def test_code_checkable_milestone_cannot_be_confirmed_by_hand(db):
    eng = _engine(db)
    await _make(db, eng, stage="active", milestones=[_m("test_pass")], **FULL)
    with pytest.raises(ValueError):
        await eng.confirm_milestone("g1", 0)


async def test_swift_at_most_once_per_goal_per_day(db, layers, agenda_gate):
    eng = _engine(db)
    await _make(db, eng, stage="forming", **FULL)
    layers.answers = [_plan(_ms("m", "metric_threshold", metric="mood", op=">=", value=1))]
    layers.answers += ['{"results": []}'] * 5
    await eng.v3_tick()
    assert len(_swift(layers)) == 1
    await eng.v3_tick()
    _advance(hours=23)
    await eng.v3_tick()
    assert len(_swift(layers)) == 1
    _advance(hours=25)
    await eng.v3_tick()
    assert len(_swift(layers)) == 2
    assert (await _stored(db, "g1"))["swift_checked_at"]


async def test_mai_confirms_alone_makes_no_swift_call(db, layers):
    eng = _engine(db)
    await _make(db, eng, stage="forming", **FULL)
    layers.answers = [_plan(_ms("only mai"))]
    await eng.v3_tick()
    await eng.v3_tick()
    assert [c["model"] for c in layers.calls] == [settings.sage_model_for()]


# ---- closing paths ------------------------------------------------------------------------

async def test_complete_cancel_and_abandon_close_the_stage(db, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "goal_stall_days", 7)
    eng = _engine(db)
    done = await _make(db, eng, "done", stage="forming")
    cancelled = await _make(db, eng, "gone", stage="forming")
    stale = await _make(db, eng, "stale", stage="forming")
    await eng.update_goal_progress("done", 1.0, "all met")
    await eng.cancel_goal("gone", "not wanted")
    _advance(days=8)
    await eng._check_abandonment(stale, _now())
    for g, text in ((done, "completed"), (cancelled, "cancelled: not wanted"), (stale, "abandoned")):
        assert g.stage == "closed" and g.close_reason.startswith(text)
        row = await _stored(db, g.goal_id)
        assert row["stage"] == "closed" and row["close_reason"].startswith(text)
    assert (await _stored(db, "gone"))["status"] == "cancelled"


async def test_reopen_leaves_closed_stage(db):
    eng = _engine(db)
    g = await _make(db, eng, "r", stage="forming")
    g.status = "abandoned"
    await eng._close_stage(g, "abandoned: x")
    assert g.stage == "closed"
    await eng.reopen_goal("r")
    assert g.stage == "forming" and g.close_reason is None
    assert "close_reason" not in await _stored(db, "r")


# ---- refine_goal --------------------------------------------------------------------------

async def _tool(eng, monkeypatch, **args):
    monkeypatch.setattr(refine_goal, "_engine", lambda: eng)
    return await refine_goal.run({"_requester_role": "owner", **args})


async def test_refine_goal_is_owner_only_and_flagged(db, monkeypatch):
    eng = _engine(db)
    await _make(db, eng, "m1", owner="mai")
    monkeypatch.setattr(refine_goal, "_engine", lambda: eng)
    base = {"goal_id": "m1", "fields": {"horizon": "soon"}}
    for role in ("guest", None):
        r = await refine_goal.run({**base, "_requester_role": role})
        assert r["status"] == "ERROR" and "owner" in r["message"]
    assert eng.active_goals[0].horizon is None
    monkeypatch.setattr(settings, "goals_v3_enabled", False)
    assert (await refine_goal.run({**base, "_requester_role": "owner"}))["status"] == "ERROR"
    assert eng.active_goals[0].horizon is None


async def test_mai_goal_outcome_is_proposed_until_confirmed(db, monkeypatch):
    eng = _engine(db)
    goal = await _make(db, eng, "m1", owner="mai", stage="forming")
    r = await _tool(eng, monkeypatch, goal_id="m1", fields={
        "outcome": "learn Rust", "done_criteria": ["build a cli"], "horizon": "3 months",
        "first_action": "read chapter 1"})
    assert r["status"] == "OK" and "proposed" in r["message"]
    assert goal.outcome is None and goal.done_criteria is None  # not Mai's words yet
    assert goal.horizon == "3 months" and goal.first_action == "read chapter 1"
    assert goal.proposed == {"outcome": "learn Rust", "done_criteria": ["build a cli"]}
    assert goal.stage == "forming"
    assert (await _stored(db, "m1"))["proposed"]["outcome"] == "learn Rust"
    bad = await _tool(eng, monkeypatch, goal_id="m1", confirm=True, fields={"outcome": "other"})
    assert bad["status"] == "ERROR"
    ok = await _tool(eng, monkeypatch, goal_id="m1", confirm=True)
    assert ok["status"] == "OK"
    assert goal.outcome == "learn Rust" and goal.done_criteria == ["build a cli"]
    assert goal.proposed is None and goal.stage == "crystal"
    row = await _stored(db, "m1")
    assert row["outcome"] == "learn Rust" and "proposed" not in row and row["stage"] == "crystal"


async def test_confirm_without_a_proposal_is_refused(db, monkeypatch):
    eng = _engine(db)
    await _make(db, eng, "m1", owner="mai", stage="forming")
    assert (await _tool(eng, monkeypatch, goal_id="m1", confirm=True))["status"] == "ERROR"


async def test_mai_said_applies_directly_and_crystallizes(db, monkeypatch):
    eng = _engine(db)
    goal = await _make(db, eng, "m1", owner="mai", stage="seed")
    r = await _tool(eng, monkeypatch, goal_id="m1", mai_said=True, fields={
        "outcome": "o", "done_criteria": ["d"], "horizon": "h", "first_action": "f"})
    assert r["status"] == "OK" and goal.stage == "crystal" and goal.proposed is None


async def test_crystal_outcome_change_needs_mai(db, monkeypatch):
    eng = _engine(db)
    goal = await _make(db, eng, "a1", stage="forming", **FULL)
    await eng._maybe_crystallize(goal)
    assert goal.stage == "crystal"
    r = await _tool(eng, monkeypatch, goal_id="a1", fields={"outcome": "something else"})
    assert r["status"] == "ERROR" and goal.outcome == "ship it"
    r = await _tool(eng, monkeypatch, goal_id="a1", mai_said=True, fields={"outcome": "something else"})
    assert r["status"] == "OK" and goal.outcome == "something else" and goal.stage == "forming"
    await eng.v3_tick()  # the tick does not undo Mai's change
    assert goal.stage == "forming"
    r = await _tool(eng, monkeypatch, goal_id="a1", mai_said=True, fields={"outcome": "something else"})
    assert r["status"] == "OK" and goal.stage == "crystal"  # her next explicit refine re-confirms it


async def test_aura_goal_is_refined_directly_and_bad_input_is_refused(db, monkeypatch):
    eng = _engine(db)
    aura = await _make(db, eng, "a1", owner="aura", stage="seed")
    r = await _tool(eng, monkeypatch, goal_id="a1", fields={"outcome": "o"})
    assert r["status"] == "OK" and aura.outcome == "o" and aura.stage == "forming"
    mai = await _make(db, eng, "m1", owner="mai")
    r = await _tool(eng, monkeypatch, goal_id="m1", fields={"owner": "aura"})
    assert r["status"] == "ERROR" and mai.owner == "mai"
    assert (await _tool(eng, monkeypatch, goal_id="a1", fields={"owner": "bob"}))["status"] == "ERROR"
    assert aura.owner == "aura"
    assert (await _tool(eng, monkeypatch, goal_id="a1", fields={"colour": "red"}))["status"] == "ERROR"
    assert (await _tool(eng, monkeypatch, goal_id="nope", fields={"outcome": "o"}))["status"] == "ERROR"


# ---- orphans and conflicts ----------------------------------------------------------------

async def test_orphan_flagged_once_with_refs(db, agenda_gate, monkeypatch):
    monkeypatch.setattr(settings, "goals_v3_orphan_days", 14)
    eng = _engine(db)
    orphan = await _make(db, eng, "o1", owner="aura", origin_link={"kind": "aura_curiosity", "ref": "x"})
    linked = await _make(db, eng, "l1", owner="aura", origin_link={"kind": "mai_said", "ref": "mem"})
    approved = await _make(db, eng, "ap", owner="aura", origin_link={"kind": "aura_drive", "approved": True})
    child = await _make(db, eng, "ch", owner="aura", origin_link={"kind": "parent", "ref": "goal:l1"})
    lost = await _make(db, eng, "lc", owner="aura", origin_link={"kind": "parent", "ref": "goal:o1"})
    _advance(days=13)
    await eng._v3_flags(_now())
    assert await _agenda(db) == []
    _advance(days=15)
    await eng._v3_flags(_now())
    items = await _agenda(db)
    assert sorted(i["refs"][0] for i in items) == ["lc", "o1"]
    assert all(i["kind"] == "observation" for i in items)
    assert orphan.orphan_flagged_at and lost.orphan_flagged_at
    assert not (linked.orphan_flagged_at or approved.orphan_flagged_at or child.orphan_flagged_at)
    await eng._v3_flags(_now())
    _advance(days=40)
    await eng._v3_flags(_now())
    assert len(await _agenda(db)) == 2
    assert (await _stored(db, "o1"))["orphan_flagged_at"]


async def test_evidence_keeps_goal_from_being_orphan(db, agenda_gate):
    eng = _engine(db)
    await _make(db, eng, "o1", owner="aura", last_evidence_at=_START + timedelta(days=10))
    _advance(days=20)
    await eng._v3_flags(_now())
    assert await _agenda(db) == []


def _commit_ms():
    return [_m("commit", workspace="w", contains="x")]


async def test_conflict_on_shared_resource_flagged_once(db, agenda_gate):
    eng = _engine(db)
    a = await _make(db, eng, "a", stage="active", milestones=_commit_ms(), **{**FULL, "horizon": "this month"})
    b = await _make(db, eng, "b", stage="active", milestones=_commit_ms(), **{**FULL, "horizon": "2 weeks"})
    await _make(db, eng, "c", stage="forming", milestones=[_m("task_node_done")])
    await eng._v3_flags(_now())
    items = await _agenda(db)
    assert len(items) == 1 and items[0]["kind"] == "needs_decision"
    assert sorted(items[0]["refs"]) == ["a", "b"] and "opencode" in items[0]["content"]
    assert a.conflict_flags == ["b"] and b.conflict_flags == ["a"]
    for _ in range(3):
        await eng._v3_flags(_now())
    assert len(await _agenda(db)) == 1
    assert (await _stored(db, "a"))["conflict_flags"] == ["b"]


async def test_no_conflict_when_a_horizon_has_ended(db, agenda_gate):
    eng = _engine(db)
    await _make(db, eng, "a", stage="active", milestones=_commit_ms(), **{**FULL, "horizon": "1 week"})
    await _make(db, eng, "b", stage="active", milestones=_commit_ms(), **{**FULL, "horizon": "2 weeks"})
    _advance(days=10)  # a's horizon is over
    await eng._v3_flags(_now())
    assert await _agenda(db) == []


async def test_contradictory_outcomes_use_swift_only_when_both_crystal_and_once(db, layers, agenda_gate):
    eng = _engine(db)
    await _make(db, eng, "a", stage="crystal", **{**FULL, "outcome": "save every euro"})
    await _make(db, eng, "b", stage="crystal", **{**FULL, "outcome": "buy a boat"})
    await _make(db, eng, "c", stage="forming", outcome="whatever")
    layers.answers = [json.dumps({"contradictory": True, "reason": "money"})]
    await eng._v3_flags(_now())
    assert len(layers.calls) == 1 and len(_swift(layers)) == 1
    assert "save every euro" in layers.calls[0]["user"] and "whatever" not in layers.calls[0]["user"]
    items = await _agenda(db)
    assert len(items) == 1 and sorted(items[0]["refs"]) == ["a", "b"]
    _advance(days=3)
    await eng._v3_flags(_now())
    assert len(layers.calls) == 1 and len(await _agenda(db)) == 1


async def test_not_contradictory_is_not_asked_again(db, layers, agenda_gate):
    eng = _engine(db)
    await _make(db, eng, "a", stage="crystal", **FULL)
    await _make(db, eng, "b", stage="crystal", **FULL)
    layers.answers = [json.dumps({"contradictory": False, "reason": ""})]
    await eng._v3_flags(_now())
    _advance(days=5)
    await eng._v3_flags(_now())
    assert len(layers.calls) == 1 and await _agenda(db) == []


async def test_refused_gate_creates_nothing_and_is_not_marked(db, monkeypatch):
    monkeypatch.setattr("aura.autonomy.controls.may_initiate",
                        AsyncMock(return_value=Decision(False, "level_silent")))
    eng = _engine(db)
    g = await _make(db, eng, "o1", owner="aura")
    _advance(days=20)
    await eng._v3_flags(_now())
    assert await _agenda(db) == [] and g.orphan_flagged_at is None


# ---- ablation and wiring ------------------------------------------------------------------

async def test_flag_off_tick_does_nothing_new(db, layers, monkeypatch):
    monkeypatch.setattr(settings, "goals_v3_enabled", False)
    eng = _engine(db)
    eng._consider_new_goal = AsyncMock()
    goal = await _make(db, eng, stage="forming", **FULL)
    await eng.tick()
    assert layers.calls == [] and goal.stage == "forming" and not goal.milestones
    assert goal.orphan_flagged_at is None


async def test_flag_on_tick_runs_the_v3_step(db, layers):
    eng = _engine(db)
    eng._consider_new_goal = AsyncMock()
    goal = await _make(db, eng, stage="forming", **FULL)
    layers.answers = [_plan(_ms("m"))]
    await eng.tick()
    assert goal.stage == "active" and len(layers.calls) == 1


async def test_v2_criteria_do_not_overwrite_milestone_progress(db, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    eng = _engine(db)
    eng._consider_new_goal = AsyncMock()
    crit = [{"id": "c", "name": "c", "kind": "test_pass", "spec": {}, "status": "open"}]
    milestones = [{"name": "a", "evidence_spec": {"kind": "mai_confirms"}, "status": "done",
                   "evidence_refs": ["owner"]},
                  {"name": "b", "evidence_spec": {"kind": "mai_confirms"}, "status": "open",
                   "evidence_refs": []}]
    goal = await _make(db, eng, stage="active", criteria=crit, last_evidence_at=_START,
                       milestones=milestones, **FULL)
    await eng.tick()
    assert goal.progress == 0.5


async def test_crystallize_skill_seeds_once_and_tool_hidden_with_flag_off(db, monkeypatch):
    from aura.engines.learning.skill_store import SkillStore
    from aura.executor.tool_registry import ToolRegistry, load_builtin_tools

    store = SkillStore(db)
    doc = await crystallize.seed_crystallize_skill(store)
    assert doc.name == "crystallize" and doc.state == "trusted"
    assert (await crystallize.seed_crystallize_skill(store)).id == doc.id
    assert len(await store.list_versions(doc.id)) == 1
    version = await store.get_version(doc.id, 1)
    assert "—" not in version.body and "refine_goal" in version.tools
    reg = ToolRegistry()
    for rec in load_builtin_tools():
        reg.register(rec)
    assert "refine_goal" in [r.name for r in reg.all()]
    monkeypatch.setattr(settings, "goals_v3_enabled", False)
    assert "refine_goal" not in [r.name for r in reg.all()]
    for text in (crystallize.PLAN_SYSTEM, crystallize.CHECK_SYSTEM, crystallize.CONFLICT_SYSTEM):
        assert "—" not in text
