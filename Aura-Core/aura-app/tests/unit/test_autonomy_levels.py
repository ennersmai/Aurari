"""P2-33: autonomy slider 0-3, daily budgets, tier cap, the chat command, goal
proposals, self-improvement graphs and origin="autonomous" (embedded SurrealDB)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from surrealdb import RecordID

from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, command, controls, delivery, initiative, registry, trace
from aura.autonomy.controls import may_initiate
from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.executor import delegation, task_graph, task_scheduler
from aura.executor.decisions import DecisionService
from aura.executor.task_graph import TaskGraphStore
from aura.models.task_graph import GraphStatus
from aura.tiers import reset_tier_cache
from tests.scenarios.runner import EmbeddedSurrealDB

_NOON = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
APP_DIR = Path(__file__).resolve().parents[2]  # aura-app, which holds Aura's own source

# The Part 11 table, row by row: what each level adds.
LEVEL_ROWS = {
    1: {"needs_decision", "task_done"},
    2: {"finding", "question_for_you", "observation", "reminder", "share", "start_conversation",
        "propose_goal", "investigate", "practice", "consolidate", "sage_call"},
    3: {"pursue_goal", "task_graph", "self_improvement", "delegation", "some_unknown_kind"},
}
ALL_KINDS = set().union(*LEVEL_ROWS.values())


@pytest.fixture
async def db(monkeypatch, tmp_path):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_NOON))
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "workspaces", {})
    for mod in (agenda_mod, controls, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda d=d: d)
    reset_tier_cache()
    controls.reset_cache()
    channel.reset()
    registry.reset()
    monkeypatch.setattr(delivery, "_deliverer", None)
    yield d
    registry.reset()
    controls.reset_cache()
    channel.reset()
    reset_tier_cache()
    set_clock(Clock())
    await d.close()


async def _allowed(db, kinds=ALL_KINDS, spend=False):
    return {k for k in kinds if (await may_initiate(k, spend=spend, db=db)).allowed}


async def _traces(db, action=None):
    sql = "SELECT * FROM autonomy_trace" + (" WHERE action = $a" if action else "") + " ORDER BY at ASC"
    return extract_rows(await db.query(sql, {"a": action} if action else None))


# -- levels ------------------------------------------------------------------------

async def test_each_level_allows_exactly_its_table_row(db):
    expected: set[str] = set()
    for level in range(4):
        expected |= LEVEL_ROWS.get(level, set())
        await controls.set_level(level, db)
        assert await _allowed(db) == expected, level
    await controls.set_level(1, db)
    # level 1: a reminder only when the owner created it (B1-01 important, unchanged)
    assert (await may_initiate("reminder", owner_created=True, db=db)).allowed
    await controls.set_level(0, db)
    d = await may_initiate("reminder", owner_created=True, db=db)
    assert not d.allowed and d.reason == "level_0_reactive"


async def test_every_decision_is_traced_with_level_and_budget(db):
    await controls.set_level(2, db)
    await may_initiate("share", source="t", refs=["agenda_item:1"], db=db)
    get_clock().advance(1)  # traces are ordered by time
    await may_initiate("pursue_goal", source="t", db=db)
    a, r = await _traces(db)
    assert a["allowed"] is True and a["why"] == "level_2" and a["refs"] == ["agenda_item:1"]
    assert a["cost"]["level"] == 2 and a["cost"]["tier_cap"] == 3
    assert a["cost"]["budget"] == {"resource": "messages", "day": "2026-01-01", "used": 1,
                                   "limit": 6, "spent": True}
    assert r["allowed"] is False and r["why"] == "level_2_excludes_kind" and r["cost"]["needs_level"] == 3


@pytest.mark.parametrize("legacy,number", [("silent", 0), ("important", 1), ("open", 3)])
async def test_stored_b1_row_is_migrated(db, legacy, number):
    await db.query("UPSERT autonomy_control:main CONTENT $d", {"d": {
        "level": legacy, "muted_kinds": ["x"], "killed": False, "updated_at": _NOON}})
    c = await controls.load_controls(db)
    assert c.level == number and c.muted_kinds == ["x"]
    row = extract_rows(await db.query("SELECT * FROM autonomy_control:main"))[0]
    assert row["autonomy_level"] == number and row["level"] == controls.LEVEL_NAMES[number]
    controls.reset_cache()
    assert (await controls.load_controls(db)).level == number


async def test_set_level_rejects_out_of_range(db):
    for bad in (4, -1, "loud", True):
        with pytest.raises(ValueError):
            await controls.set_level(bad, db)
    assert (await controls.set_level("2", db)).level == 2


# -- tier cap ----------------------------------------------------------------------

@pytest.mark.parametrize("stack,cap", [(0, 1), (1, 2), (2, 3)])
async def test_effective_level_is_capped_by_tier(db, monkeypatch, stack, cap):
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", stack)
    await controls.set_level(3, db)
    c = await controls.get_controls(db)
    assert controls.effective_level(c) == cap
    expected = set().union(*(LEVEL_ROWS[n] for n in range(1, cap + 1)))
    assert await _allowed(db) == expected
    state = await command.state_for(c, db)
    assert state["level"] == 3 and state["effective_level"] == cap and state["tier_cap"] == cap


# -- budgets -----------------------------------------------------------------------

async def test_message_budget_per_level_and_daily_reset(db, monkeypatch):
    monkeypatch.setattr(settings, "app_timezone", "Europe/Paris")  # local midnight = 23:00 UTC
    await controls.set_level(1, db)
    results = [(await may_initiate("task_done", db=db)).allowed for _ in range(4)]
    assert results == [True, True, True, False]
    d = await may_initiate("task_done", db=db)
    assert d.reason == "budget_exhausted:messages"
    # an owner-created reminder spends nothing and is not blocked by the budget
    assert (await may_initiate("reminder", owner_created=True, db=db)).allowed
    get_clock().set(datetime(2026, 1, 1, 22, 59, tzinfo=timezone.utc))  # 23:59 in Paris
    assert not (await may_initiate("task_done", db=db)).allowed
    get_clock().set(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc))  # 00:00 next local day
    assert (await may_initiate("task_done", db=db)).allowed
    state = await controls.budget_state(db=db)
    assert state["day"] == "2026-01-02"
    assert state["resources"]["messages"] == {"used": 1, "limit": 3}


async def test_budget_rows_follow_the_table(db):
    await controls.set_level(2, db)
    assert controls.budget_limits(2) == {"messages": 6, "sage_calls": 5, "task_graphs": 0}
    sage = [(await may_initiate("sage_call", db=db)).allowed for _ in range(6)]
    assert sage == [True] * 5 + [False]
    await controls.set_level(3, db)
    assert controls.budget_limits(3) == {"messages": 10, "sage_calls": 10, "task_graphs": 1}
    graphs = [(await may_initiate("task_graph", db=db)).allowed for _ in range(2)]
    assert graphs == [True, False]
    assert controls.budget_limits(0) == {"messages": 0, "sage_calls": 0, "task_graphs": 0}


async def test_spend_false_checks_without_spending(db, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_budget_messages_level1", 1)
    await controls.set_level(1, db)
    for _ in range(3):
        assert (await may_initiate("needs_decision", spend=False, db=db)).allowed
    assert (await may_initiate("needs_decision", db=db)).allowed
    d = await may_initiate("needs_decision", spend=False, db=db)
    assert not d.allowed and d.reason == "budget_exhausted:messages"


async def test_deliverer_holds_items_over_the_daily_message_budget(db, monkeypatch):
    monkeypatch.setattr(settings, "quiet_hours_start", "00:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "00:00")
    monkeypatch.setattr(settings, "autonomy_budget_messages_level1", 2)
    await controls.set_level(1, db)
    svc = agenda_mod.AgendaService(db)
    for i in range(3):
        await svc.create("task_done", f"done {i}", [f"task:{i}"], 0.9)
    assert len(await delivery.get_deliverer().deliver_due()) == 2
    assert [i.state for i in await svc.list()].count("pending") == 1
    refused = [t for t in await _traces(db, "initiate:task_done") if not t["allowed"]]
    assert refused and refused[-1]["why"] == "budget_exhausted:messages"
    get_clock().advance(86400)
    assert len(await delivery.get_deliverer().deliver_due()) == 1


# -- ablation ----------------------------------------------------------------------

async def test_flag_off_refuses_as_before_and_writes_no_budget(db, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_enabled", False)
    await controls.set_level(3, db)
    for k in ALL_KINDS:
        d = await may_initiate(k, db=db)
        assert not d.allowed and d.reason == "autonomy_disabled"
    assert extract_rows(await db.query("SELECT * FROM autonomy_budget")) == []
    assert await command.handle_chat("autonomy 2", "owner", "app", db) is None
    assert (await controls.get_controls(db)).level == 3


# -- chat command ------------------------------------------------------------------

async def test_owner_chat_command_sets_the_level(db):
    reply = await command.handle_chat("Autonomy 2", "owner", "app", db)
    assert reply == "Autonomy set to 2 (proactive)."
    assert (await controls.get_controls(db)).level == 2
    assert "autonomy_state" in [e["type"] for e in channel.events_since(0)]
    get_clock().advance(1)  # traces are ordered by time
    assert await command.handle_chat("autonomy 0.", "owner", "dm:owner", db) == "Autonomy set to 0 (reactive)."
    assert "0 (reactive)" in (await _traces(db, "controls:level"))[-1]["why"]
    assert (await controls.get_controls(db)).level == 0


async def test_chat_command_is_owner_only_and_venue_checked(db):
    await controls.set_level(1, db)
    assert await command.handle_chat("autonomy 3", "guest", "app", db) is None
    assert await command.handle_chat("autonomy 3", "trusted", "dm:someone", db) is None
    get_clock().advance(1)  # traces are ordered by time
    reply = await command.handle_chat("autonomy 3", "owner", "guild:1/2", db)
    assert reply is not None and "app" in reply
    assert await command.handle_chat("autonomy is fun 3", "owner", "app", db) is None
    assert "0 (reactive)" in await command.handle_chat("autonomy 9", "owner", "app", db)
    assert (await controls.get_controls(db)).level == 1
    refused = await _traces(db, "controls:level")
    assert refused[-1]["allowed"] is False and "guild:1/2" in refused[-1]["why"]


async def test_capped_level_is_explained_in_chat(db, monkeypatch):
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 0)
    reply = await command.handle_chat("autonomy 3", "owner", "app", db)
    assert reply == "Autonomy set to 3 (autonomous). This tier caps it, so I act at 1 (attentive)."


# -- goal proposals (level 2) -------------------------------------------------------

@pytest.fixture
def engine(db, monkeypatch):
    from aura.engines.goal import engine as engine_mod

    monkeypatch.setattr(engine_mod, "get_db_client", lambda: db)
    eng = engine_mod.GoalEngine()
    eng.last_goal_generation = datetime(2000, 1, 1, tzinfo=timezone.utc)

    async def formulate(trigger, context):
        # Stand-in for the template generator: stores a valid row (the legacy one writes a
        # goal_id field the SCHEMAFULL goal table rejects) and returns the goal.
        from aura.models.goal import Goal

        goal = Goal(goal_id="goal:new1", name="Explore", description="Research a topic",
                    goal_type="curiosity_driven", origin=f"autonomous_{trigger}", created=_NOON)
        await db.query("CREATE goal:new1 CONTENT $d", {"d": {
            "name": goal.name, "description": goal.description, "goal_type": goal.goal_type,
            "origin": goal.origin, "status": "active", "created": _NOON, "updated": _NOON}})
        eng.active_goals.append(goal)
        return goal

    eng.formulate_goal = formulate
    return eng


async def _goal_rows(db):
    return extract_rows(await db.query("SELECT * FROM goal"))


async def test_new_goal_needs_level_2_and_becomes_a_proposal(db, engine, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    await controls.set_level(1, db)
    await engine._consider_new_goal("boredom")
    assert await _goal_rows(db) == []

    await controls.set_level(2, db)
    await engine._consider_new_goal("boredom")
    rows = await _goal_rows(db)
    assert len(rows) == 1 and rows[0]["status"] == "paused"
    decisions = extract_rows(await db.query("SELECT * FROM decision WHERE action = 'goal_proposal'"))
    assert len(decisions) == 1 and decisions[0]["status"] == "pending"
    items = extract_rows(await db.query("SELECT * FROM agenda_item"))
    assert len(items) == 1 and items[0]["kind"] == "needs_decision"
    goal_id = f"goal:{rows[0]['id'].id}"
    assert goal_id in items[0]["refs"]
    # pursuit never picks a proposal (it is not active)
    await controls.set_level(3, db)
    assert await engine.check_goals_needing_autonomous_pursuit() == []

    # Mai approves: active, and linked to her approval so it is not an orphan (P2-32)
    did = f"decision:{decisions[0]['id'].id}"
    await DecisionService(db=db).answer(did, True, "owner")
    row = (await _goal_rows(db))[0]
    assert row["status"] == "active"
    assert row["origin_link"] == {"kind": "aura_drive", "ref": did, "approved": True}
    engine.active_goals = []
    await engine._load_active_goals()
    assert engine._is_linked(engine.active_goals[0]) is True


async def test_rejected_proposal_is_cancelled(db, engine):
    await controls.set_level(2, db)
    await engine._consider_new_goal("boredom")
    d = extract_rows(await db.query("SELECT * FROM decision WHERE action = 'goal_proposal'"))[0]
    await DecisionService(db=db).answer(f"decision:{d['id'].id}", False, "owner")
    row = (await _goal_rows(db))[0]
    assert row["status"] == "cancelled" and row["stage"] == "closed"
    assert not row.get("origin_link")


async def test_flag_off_goal_creation_unchanged(db, engine, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_enabled", False)
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    await engine._consider_new_goal("boredom")
    assert await _goal_rows(db) == []  # B3-06: off under goals v2, as before
    monkeypatch.setattr(settings, "goals_v2_enabled", False)
    await engine._consider_new_goal("boredom")
    rows = await _goal_rows(db)
    assert len(rows) == 1 and rows[0]["status"] == "active"  # legacy: no proposal
    assert extract_rows(await db.query("SELECT * FROM decision")) == []
    assert await _traces(db) == []


# -- task graphs, self-improvement, origin ------------------------------------------

PLAN = {"goal": "tidy the logging module", "nodes": [
    {"id": "a", "kind": "research", "brief": "read the logging code", "success_criteria": "notes"},
    {"id": "b", "kind": "code", "brief": "refactor it", "success_criteria": "tests pass", "depends_on": ["a"]},
]}


@pytest.fixture
def titan(monkeypatch):
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 2)
    started: list[str] = []
    monkeypatch.setattr(initiative, "_start", started.append)
    return started


def _goal(goal_type="creative", status="active"):
    return SimpleNamespace(goal_id="goal:g1", name="Better logs", goal_type=goal_type, status=status)


async def test_graph_needs_level_3_and_records_origin(db, titan):
    await controls.set_level(2, db)
    r = await initiative.start_task_graph(_goal(), PLAN, db=db)
    assert r == {"started": False, "reason": "level_2_excludes_kind"} and titan == []
    await controls.set_level(3, db)
    r = await initiative.start_task_graph(_goal(), PLAN, db=db)
    assert r["started"] is True and titan == [r["graph_id"]]
    graph = await TaskGraphStore(db).get_graph(r["graph_id"])
    assert graph.origin == "autonomous" and graph.conversation_id is None
    # the daily task graph budget (1) is spent
    r2 = await initiative.start_task_graph(_goal(), PLAN, db=db)
    assert r2 == {"started": False, "reason": "budget_exhausted:task_graphs"}


async def test_graph_refused_off_titan_and_for_unapproved_goal(db, titan, monkeypatch):
    await controls.set_level(3, db)
    r = await initiative.start_task_graph(_goal(status="paused"), PLAN, db=db)
    assert r["started"] is False and "not approved" in r["reason"]
    monkeypatch.setattr(settings, "model_stack_index", 1)  # Core caps at 2 as well
    r = await initiative.start_task_graph(_goal(), PLAN, db=db)
    assert r["reason"] == "level_2_excludes_kind"
    assert extract_rows(await db.query("SELECT * FROM task_graph")) == []


async def test_self_improvement_refused_without_the_workspace(db, titan, monkeypatch):
    await controls.set_level(3, db)
    elsewhere = APP_DIR.parent / "aura-launcher"
    monkeypatch.setattr(settings, "workspaces", {"other": str(elsewhere)} if elsewhere.is_dir() else {})
    r = await initiative.start_task_graph(_goal("self_improvement"), PLAN, db=db)
    assert r == {"started": False, "reason": "self_improvement_needs_registered_aura_workspace"}
    assert extract_rows(await db.query("SELECT * FROM task_graph")) == []
    assert extract_rows(await db.query("SELECT * FROM decision")) == []
    refused = await _traces(db, "graph:self_improvement")
    assert refused and refused[-1]["allowed"] is False


async def test_self_improvement_graph_needs_approval_per_graph(db, titan, monkeypatch):
    await controls.set_level(3, db)
    monkeypatch.setattr(settings, "workspaces", {"aura": str(APP_DIR)})
    assert initiative.aura_repo_workspace() == "aura"

    bad = {**PLAN, "nodes": [{**PLAN["nodes"][1], "id": "x", "depends_on": [], "brief": "workspace: shop\nfix"}]}
    r = await initiative.start_task_graph(_goal("self_improvement"), bad, db=db)
    assert r["started"] is False and "shop" in r["reason"]

    first = await initiative.start_task_graph(_goal("self_improvement"), PLAN, db=db)
    second = await initiative.start_task_graph(_goal("self_improvement"), PLAN, db=db)
    assert first["reason"] == second["reason"] == "waiting_for_owner" and titan == []
    store = TaskGraphStore(db)
    g1 = await store.get_graph(first["graph_id"])
    assert g1.status == GraphStatus.PLANNED and g1.origin == "autonomous" and "workspace: aura" in g1.goal
    # nothing spent before approval
    assert (await controls.budget_state(db=db))["resources"]["task_graphs"]["used"] == 0

    svc = DecisionService(db=db)
    await svc.answer(first["decision_id"], True, "owner")
    assert titan == [first["graph_id"]]
    # the second approval the same day is over the task graph budget: cancelled, not started
    await svc.answer(second["decision_id"], True, "owner")
    assert titan == [first["graph_id"]]
    assert (await store.get_graph(second["graph_id"])).status == GraphStatus.CANCELLED


async def test_rejected_self_improvement_graph_is_cancelled(db, titan, monkeypatch):
    await controls.set_level(3, db)
    monkeypatch.setattr(settings, "workspaces", {"aura": str(APP_DIR)})
    r = await initiative.start_task_graph(_goal("self_improvement"), PLAN, db=db)
    await DecisionService(db=db).answer(r["decision_id"], False, "owner")
    assert titan == []
    assert (await TaskGraphStore(db).get_graph(r["graph_id"])).status == GraphStatus.CANCELLED


async def test_self_improvement_proposal_refused_without_workspace(db, engine):
    from aura.models.goal import Goal

    await controls.set_level(2, db)
    goal = Goal(goal_id="goal:si", name="Improve my recall", description="d",
                goal_type="self_improvement", origin="autonomous_boredom", created=_NOON)
    await db.query("CREATE goal:si CONTENT $d", {"d": {
        "name": goal.name, "description": "d", "goal_type": "self_improvement",
        "origin": goal.origin, "status": "active", "created": _NOON, "updated": _NOON}})
    engine.active_goals = [goal]
    assert await initiative.propose_goal(engine, goal, db=db) is False
    assert (await _goal_rows(db))[0]["status"] == "cancelled"
    assert extract_rows(await db.query("SELECT * FROM decision")) == []


async def test_kill_switch_stops_autonomous_graphs_and_delegations(db, monkeypatch):
    graph_task = asyncio.create_task(asyncio.sleep(60))
    owner_task = asyncio.create_task(asyncio.sleep(60))
    sched = task_scheduler.TaskGraphScheduler()
    sched._tasks = {"g_auto": graph_task, "g_owner": owner_task}
    graphs = {
        # self-started but reporting into a conversation: still stopped, by origin
        "g_auto": SimpleNamespace(origin="autonomous", created_by_turn=None, conversation_id="c1"),
        "g_owner": SimpleNamespace(origin=None, created_by_turn="turn:1", conversation_id="c1"),
    }
    store = SimpleNamespace(get_graph=lambda gid: asyncio.sleep(0, graphs.get(gid)))
    monkeypatch.setattr(task_scheduler, "get_task_scheduler", lambda: sched)
    monkeypatch.setattr(task_graph, "get_task_graph_store", lambda: store)

    class Runner:
        def __init__(self, tid, origin):
            self.task_id = tid
            self.config = delegation.DelegationConfig(goal="g", workspace="w", agent="a",
                                                      success_criteria="s", tokens=1, minutes=1, origin=origin)
            self.aborted = False

        async def abort(self):
            self.aborted = True

    auto, owner = Runner("task:a", "autonomous"), Runner("task:o", None)
    monkeypatch.setattr(delegation, "_RUNNERS", {"task:a": auto, "task:o": owner})
    try:
        result = await registry.kill(db)
        assert graph_task.cancelled() and not owner_task.done()
        assert auto.aborted and not owner.aborted
        assert result["left_running_owner_graphs"] == ["g_owner"]
        assert not (await may_initiate("task_graph", db=db)).allowed
    finally:
        owner_task.cancel()
        await asyncio.gather(graph_task, owner_task, return_exceptions=True)


async def test_delegation_origin_is_stored_and_reattached(db):
    cfg = delegation.DelegationConfig(goal="g", workspace="w", agent="a", success_criteria="s",
                                      tokens=1, minutes=1)
    assert cfg.origin is None and cfg.autonomous is False  # owner work: unchanged default
    from aura.models.task import Task

    task = Task(task_id="task:x", goal="g", origin="autonomous")
    runner_cfg = delegation.DelegationConfig(goal=task.goal, workspace="", agent="", success_criteria="",
                                             tokens=1, minutes=1, origin=getattr(task, "origin", None))
    assert runner_cfg.autonomous is True
    assert registry._is_autonomous_config(runner_cfg)


async def test_self_started_delegation_passes_the_gate(db, monkeypatch):
    calls = []

    async def fake_start(**kw):
        calls.append(kw)
        return "task:1"

    monkeypatch.setattr(delegation, "start_delegation", fake_start)
    await controls.set_level(2, db)
    assert await initiative.start_delegation(db=db, goal="g", origin="owner") is None
    await controls.set_level(3, db)
    assert await initiative.start_delegation(db=db, goal="g", origin="owner") == "task:1"
    assert calls == [{"goal": "g", "origin": "autonomous"}]


async def test_task_graph_origin_field_round_trips(db):
    from aura.models.task_graph import TaskNode

    store = TaskGraphStore(db)
    node = TaskNode(id="a", kind="think", brief="b", success_criteria="s")
    plain = await store.create_graph("g", [node], 1.0, 10, conversation_id="c")
    auto = await store.create_graph("g", [node], 1.0, 10, origin="autonomous")
    assert plain.origin is None and auto.origin == "autonomous"
    assert registry.is_autonomous_graph(auto) and not registry.is_autonomous_graph(plain)
    row = extract_rows(await db.query("SELECT origin FROM $rid", {"rid": RecordID("task_graph", auto.id.partition(":")[2])}))
    assert row[0]["origin"] == "autonomous"
