"""B2-04: event triggers, the cycle runner and the pre-emption hook."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.autonomy import channel, controls, drives, registry
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.goal.engine import GoalEngine
from aura.models.proposal import Cost, Proposal, ProposalKind
from aura.orchestrator import workspace as wsmod
from aura.orchestrator.message_bus import MessageBus
from aura.orchestrator.workspace import EVENT_NAMES, Budget, Workspace
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
BIG = Budget(tokens=1000, seconds=100.0)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    drives.reset_cache()
    controls.reset_cache()
    registry.reset()
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "drives_enabled", False)
    await controls.set_level("open", db=d)
    d.clock = clock
    ws = Workspace()
    ws.db = d
    wsmod.set_workspace(ws)
    d.ws = ws
    yield d
    wsmod.set_workspace(None)
    drives.reset_cache()
    controls.reset_cache()
    registry.reset()
    set_clock(Clock())
    await d.close()


async def _drain(ws):
    while ws._bg:
        await asyncio.gather(*list(ws._bg))


def _p(ref="r1", kind=ProposalKind.INVESTIGATE):
    return Proposal(source="t", kind=kind, summary="s", refs=[ref], urgency=1.0, value=1.0,
                    cost=Cost(tokens=10, seconds=1.0))


async def _trace(db):
    return extract_rows(await db.query("SELECT * FROM autonomy_trace"))


async def test_t1_idle_six_hours_nothing_autonomous(db, monkeypatch):
    sent = []

    async def spy(event_type, payload=None, **kw):
        sent.append(event_type)
        return {}

    monkeypatch.setattr(channel, "publish", spy)
    ws = db.ws
    for _ in range(72):  # six hours in five-minute fallback ticks
        db.clock.set(db.clock.now() + timedelta(minutes=5))
        await ws.check_stuck()
    for name in ("agenda_due", "prediction_settled"):
        ws.on_event(name)
    await _drain(ws)
    assert "aura_message" not in sent
    assert not [r for r in await _trace(db) if r["action"].startswith("attend:winner")]
    assert registry.registered() == []
    assert ws.all() == []


async def test_t12_pause_token_pauses_within_two_seconds(db):
    ws = db.ws
    token = ws.pause_token()
    steps = []

    async def autonomous():
        for i in range(1000):
            await token.wait_if_paused()
            steps.append(i)
            await asyncio.sleep(0.01)

    task = asyncio.create_task(autonomous())
    await asyncio.sleep(0.05)
    t0 = time.monotonic()
    ws.on_event("user_message")  # synchronous pre-emption
    assert token.paused
    await asyncio.sleep(0.05)
    n = len(steps)
    await asyncio.sleep(0.2)
    assert len(steps) == n  # no step while paused
    assert time.monotonic() - t0 < 2.0
    ws.turn_finished()
    await asyncio.sleep(0.1)
    assert len(steps) > n  # resumed after the turn
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await _drain(ws)


async def test_user_message_sets_flag_and_interrupts_synchronously(db):
    called = []
    registry.add_interrupt_callback(lambda: called.append(1))
    db.ws.on_event("user_message")
    assert called == [1] and db.ws._user_pending  # before any await
    await _drain(db.ws)


@pytest.mark.parametrize("name", EVENT_NAMES)
async def test_each_event_schedules_exactly_one_cycle(db, name):
    ws = db.ws
    ws.run_cycle = AsyncMock(return_value=None)
    ws.on_event(name)
    await _drain(ws)
    assert ws.run_cycle.await_count == 1


async def test_unknown_event_ignored(db):
    ws = db.ws
    ws.run_cycle = AsyncMock()
    ws.on_event("bogus")
    await _drain(ws)
    assert ws.run_cycle.await_count == 0


async def test_events_update_drives(db, monkeypatch):
    monkeypatch.setattr(settings, "drives_enabled", True)
    ws = db.ws
    seen = []
    orig = drives.on_event

    async def spy(name, payload=None, now=None, db=None):
        seen.append(name)
        return await orig(name, payload, now, db)

    monkeypatch.setattr(drives, "on_event", spy)
    for n in ("user_message", "task_result", "dream_completed"):
        ws.on_event(n)
    await _drain(ws)
    ws.turn_finished()
    assert sorted(seen) == ["dream_completed", "exchange_happened", "task_done"]


async def test_cycle_dispatches_to_handler_and_traces_no_handler(db):
    ws = db.ws
    got = []

    async def handler(w):
        got.append(w.proposal.refs)

    ws.register_handler(ProposalKind.INVESTIGATE, handler)
    ws.post(_p("a"))
    ws.post(_p("b", ProposalKind.PRACTICE))
    await ws.run_cycle(BIG)
    await ws.run_cycle(BIG)
    assert got == [["a"]]
    actions = [r["action"] for r in await _trace(db)]
    assert "cycle:no_handler:practice" in actions
    assert ws.all() == []  # both consumed


async def test_handler_error_is_logged_not_raised(db):
    ws = db.ws

    async def boom(w):
        raise RuntimeError("x")

    ws.register_handler(ProposalKind.INVESTIGATE, boom)
    ws.post(_p())
    assert await ws.run_cycle(BIG) is not None


async def test_fallback_posts_no_proposals_and_clears_stuck_flag(db):
    ws = db.ws
    ws.note_user_message()
    ws._active_turns = 1
    db.clock.set(db.clock.now() + timedelta(seconds=settings.workspace_fallback_seconds + 1))
    await ws.check_stuck()
    assert not ws._user_pending
    assert ws.all() == []


async def test_task_result_reaches_goal_engine_only(db):
    bus = MessageBus()
    got = []

    async def goal(m):
        got.append(m.data["kind"])

    async def other(m):
        got.append("other")

    bus.subscribe("goal_engine", goal)
    bus.subscribe("someone", other)
    await bus.start()
    ws = Workspace(bus)
    ws.db = db
    ws.on_event("task_result", {"task_id": "t1"})
    await _drain(ws)
    await asyncio.sleep(0.2)
    await bus.stop()
    assert got == ["task_result"]


def _goal_engine():
    ge = GoalEngine()
    ge._consider_new_goal = AsyncMock()
    ge.current_boredom_level = 0.99
    ge.active_goals = []
    return ge


async def test_boredom_branch_skipped_when_on_runs_when_off(db, monkeypatch):
    from aura.autonomy import trace

    calls = []

    async def rec(source, action, why, **kw):
        calls.append(action)
        return True

    monkeypatch.setattr(trace, "record", rec)
    real_sleep = asyncio.sleep
    monkeypatch.setattr("aura.engines.goal.engine.asyncio.sleep", lambda s: real_sleep(0))
    ge = _goal_engine()
    await ge.tick()
    await ge.tick()
    ge._consider_new_goal.assert_not_awaited()
    assert calls == ["tick:boredom_goals_disabled"]  # said once

    monkeypatch.setattr(settings, "workspace_enabled", False)  # ablation
    ge2 = _goal_engine()
    await ge2.tick()
    ge2._consider_new_goal.assert_awaited_with("boredom")


async def test_flag_off_hook_is_inert(db, monkeypatch):
    monkeypatch.setattr(settings, "workspace_enabled", False)
    ws = db.ws
    ws.run_cycle = AsyncMock()
    wsmod.fire_event("user_message")
    wsmod.turn_finished()
    await _drain(ws)
    assert ws.run_cycle.await_count == 0 and not ws._user_pending


async def test_both_entry_points_fire_hook_once(db, turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    fired = []
    db.ws.on_event = lambda name, payload=None: fired.append(name)
    await orch.process_query("hello", user_id="u1")
    assert fired == ["user_message"]
    orch.llm_layers._stream_chunks_queue.append(["a", "b"])
    async for _ in orch.stream_query("hello", user_id="u1"):
        pass
    assert fired == ["user_message", "user_message"]
