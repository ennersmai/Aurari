"""B1-06: owner controls API and the kill switch (T14)."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from aura.api.routes import autonomy as autonomy_routes
from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, controls, delivery, registry, trace
from aura.autonomy.controls import may_initiate
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.executor import delegation, task_graph, task_scheduler
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class FakeGraphStore:
    def __init__(self, graphs):
        self.graphs = graphs

    async def get_graph(self, gid):
        return self.graphs.get(gid)


class FakeRunner:
    def __init__(self, task_id, autonomous):
        self.config = SimpleNamespace(autonomous=autonomous)
        self.task_id = task_id
        self.work = asyncio.ensure_future(asyncio.sleep(60))
        self.aborted = False

    async def abort(self):
        self.aborted = True
        self.work.cancel()
        await asyncio.gather(self.work, return_exceptions=True)


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    for mod in (agenda_mod, controls, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda d=d: d)
    controls.reset_cache()
    channel.reset()
    registry.reset()
    monkeypatch.setattr(delivery, "_deliverer", None)
    app = FastAPI()
    app.include_router(autonomy_routes.router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    yield SimpleNamespace(db=d, client=client)
    await client.aclose()
    registry.reset()
    set_clock(Clock())
    controls.reset_cache()
    channel.reset()
    await d.close()


async def _traces(d, action):
    return extract_rows(await d.query("SELECT * FROM autonomy_trace WHERE action = $a", {"a": action}))


async def test_kill_stops_autonomous_work_within_2s_and_spares_owner_work(env, monkeypatch):
    loop_tasks = [asyncio.create_task(asyncio.sleep(60)) for _ in range(3)]
    for i, t in enumerate(loop_tasks):
        registry.register_autonomous_task(t, "pursue_goal", f"goal:{i}")
    auto_run, owner_run = FakeRunner("task:a", True), FakeRunner("task:o", False)
    monkeypatch.setattr(delegation, "_RUNNERS", {"task:a": auto_run, "task:o": owner_run})

    auto_graph = asyncio.create_task(asyncio.sleep(60))
    owner_graph = asyncio.create_task(asyncio.sleep(60))
    sched = task_scheduler.TaskGraphScheduler()
    sched._tasks = {"g_auto": auto_graph, "g_owner": owner_graph}
    store = FakeGraphStore(
        {
            "g_auto": SimpleNamespace(created_by_turn=None, conversation_id=None),
            "g_owner": SimpleNamespace(created_by_turn="turn:1", conversation_id="c1"),
        }
    )
    monkeypatch.setattr(task_scheduler, "get_task_scheduler", lambda: sched)
    monkeypatch.setattr(task_graph, "get_task_graph_store", lambda: store)

    t0 = time.monotonic()
    r = await env.client.post("/autonomy/kill")
    elapsed = time.monotonic() - t0
    try:
        assert r.status_code == 200
        body = r.json()
        assert elapsed < 2.0
        assert all(t.cancelled() for t in loop_tasks)
        assert auto_run.aborted and not owner_run.aborted
        assert auto_graph.cancelled() and not owner_graph.done()
        assert body["left_running_owner_graphs"] == ["g_owner"]
        kinds = sorted(s["kind"] for s in body["stopped"])
        assert kinds == ["delegation", "pursue_goal", "pursue_goal", "pursue_goal", "task_graph"]
        assert registry.registered() == []
        # refused afterwards, read synchronously
        assert controls.is_killed() is True
        d = await may_initiate("needs_decision")
        assert not d.allowed and d.reason == "killed"
        assert len(await _traces(env.db, "controls:kill")) == 1
        assert len(await _traces(env.db, "kill_switch")) == 1
        assert "autonomy_state" in [e["type"] for e in channel.events_since(0)]
    finally:
        owner_graph.cancel()
        owner_run.work.cancel()
        await asyncio.gather(owner_graph, owner_run.work, auto_graph, return_exceptions=True)


async def test_resume_clears_without_restarting(env):
    t = asyncio.create_task(asyncio.sleep(60))
    registry.register_autonomous_task(t, "x", "ref")
    await env.client.post("/autonomy/kill")
    assert t.cancelled()
    r = await env.client.post("/autonomy/resume")
    assert r.json()["killed"] is False and controls.is_killed() is False
    assert registry.registered() == [] and t.cancelled()
    assert len(await _traces(env.db, "controls:resume")) == 1


async def test_level_mute_and_get(env):
    r = await env.client.get("/autonomy")
    assert r.json()["level"] == "important" and r.json()["autonomy_enabled"] is True
    assert (await env.client.put("/autonomy/level", json={"level": "open"})).json()["level"] == "open"
    assert (await env.client.put("/autonomy/level", json={"level": "loud"})).status_code == 422
    await env.client.post("/autonomy/mute", json={"kind": "curiosity"})
    got = (await env.client.get("/autonomy")).json()
    assert got["level"] == "open" and got["muted_kinds"] == ["curiosity"]
    assert "start" in got["quiet_hours"] and got["killed"] is False
    await env.client.post("/autonomy/unmute", json={"kind": "curiosity"})
    assert (await env.client.get("/autonomy")).json()["muted_kinds"] == []
    # persisted: read back from the database
    controls.reset_cache()
    assert (await controls.get_controls(env.db)).level == "open"
    states = [e for e in channel.events_since(0) if e["type"] == "autonomy_state"]
    assert len(states) == 3
    assert len(await _traces(env.db, "controls:level")) == 1


async def test_done_callback_removes_finished_task(env):
    t = asyncio.create_task(asyncio.sleep(0))
    registry.register_autonomous_task(t, "x", "r")
    await t
    await asyncio.sleep(0)
    assert registry.registered() == []


async def test_interrupt_for_user_runs_callbacks(env):
    calls = []
    registry.add_interrupt_callback(lambda: calls.append(1))
    registry.add_interrupt_callback(lambda: 1 / 0)
    await registry.interrupt_for_user()
    assert calls == [1]


def _engine(monkeypatch, env):
    from aura.engines.goal import engine as eng

    monkeypatch.setattr(eng, "get_db_client", lambda: env.db)
    ge = eng.GoalEngine()
    return ge


async def test_goal_engine_gate_blocks_pursuit_when_silent(env, monkeypatch):
    from aura.models.goal import Goal

    ge = _engine(monkeypatch, env)
    ran = []

    async def impl(*a, **k):
        ran.append(1)
        return {"goal_id": "g"}

    monkeypatch.setattr(ge, "_pursue_goal_impl", impl)
    await controls.set_level("silent", env.db)
    with pytest.raises(ValueError, match="level_silent"):
        await ge.pursue_goal_autonomously("g", 1, None)
    assert ran == []
    ge.active_goals = [Goal(goal_id="g", name="n", description="d", goal_type="maintenance", origin="test", priority=0.9, progress=0.0)]
    assert await ge.check_goals_needing_autonomous_pursuit() == []

    await controls.set_level("open", env.db)
    assert (await ge.pursue_goal_autonomously("g", 1, None)) == {"goal_id": "g"}
    assert ran == [1]


async def test_goal_engine_pursuit_is_registered_and_killed(env, monkeypatch):
    ge = _engine(monkeypatch, env)
    started = asyncio.Event()

    async def impl(*a, **k):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(ge, "_pursue_goal_impl", impl)
    await controls.set_level("open", env.db)
    caller = asyncio.create_task(ge.pursue_goal_autonomously("g", 5, None))
    await started.wait()
    assert registry.registered() == [{"kind": "pursue_goal", "owner_ref": "g"}]
    await env.client.post("/autonomy/kill")
    with pytest.raises(ValueError, match="kill switch"):
        await caller


async def test_flag_off_leaves_pursuit_unchanged(env, monkeypatch):
    monkeypatch.setattr(settings, "autonomy_enabled", False)
    ge = _engine(monkeypatch, env)

    async def impl(*a, **k):
        return {"goal_id": "g"}

    monkeypatch.setattr(ge, "_pursue_goal_impl", impl)
    await controls.set_level("silent", env.db)
    assert await ge.pursue_goal_autonomously("g", 1, None) == {"goal_id": "g"}
    assert registry.registered() == []
