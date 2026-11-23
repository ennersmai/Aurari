"""Supervisor fix (2026-11-24): init_schema made legacy task fields required, so
TaskQueueService.create_task failed on a database built from the real scripts.

Every TaskQueueService write is exercised here against the real schema, and every
written field is read back."""

from datetime import datetime, timedelta, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.executor.task_queue import TaskQueueService
from aura.models.task import TaskStepRecord
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def env():
    db = EmbeddedSurrealDB()
    await db.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    svc = TaskQueueService()
    svc.db = db
    yield svc, clock
    set_clock(Clock())
    await db.close()


def _step(n: int = 1) -> TaskStepRecord:
    return TaskStepRecord(
        step_number=n, step_type="tool_call", title=f"step {n}", detail="d",
        tool_name="write_file", tool_args={"path": "a.py"}, result="ok",
        duration_ms=12, active_file="a.py", emotion={"joy": 0.5},
    )


@pytest.mark.asyncio
async def test_create_task_on_real_schema(env):
    svc, _ = env
    task = await svc.create_task(goal="g", workspace_path="", session_id="main")
    loaded = await svc.get_task(task.task_id)
    assert loaded is not None
    assert loaded.goal == "g"


@pytest.mark.asyncio
async def test_create_and_get_reads_every_field(env):
    svc, _ = env
    t = await svc.create_task("build it", workspace_path="/ws", session_id="oc-1", delegated=True)
    got = await svc.get_task(t.task_id)
    assert got.task_id == t.task_id and got.goal == "build it"
    assert got.status == "queued" and type(got.status) is str
    assert got.workspace_path == "/ws" and got.session_id == "oc-1"
    assert got.delegated is True
    assert got.task_memory_namespace == t.task_memory_namespace != ""
    assert got.created_at == _START and got.updated_at == _START
    assert got.completed_at is None and got.blocker is None and got.blocker_info is None
    assert got.steps == [] and got.current_step_index == 0 and got.resonance_scores == []
    assert got.requested_by_role is None and got.reviewed is None
    plain = await svc.create_task("plain")
    assert (await svc.get_task(plain.task_id)).delegated is False
    assert await svc.get_task("task:missing") is None


@pytest.mark.asyncio
async def test_status_transitions(env):
    svc, clock = env
    t = await svc.create_task("g")
    clock.advance(10)
    t1 = _START + timedelta(seconds=10)
    r = await svc.start_task(t.task_id)
    assert r.status == "running" and r.updated_at == t1 and r.created_at == _START
    clock.advance(10)
    r = await svc.pause_task(t.task_id)
    assert r.status == "paused" and r.updated_at == t1 + timedelta(seconds=10)
    clock.advance(10)
    r = await svc.resume_task(t.task_id)
    assert r.status == "running" and r.blocker is None
    clock.advance(10)
    done = _START + timedelta(seconds=40)
    r = await svc.complete_task(t.task_id)
    assert r.status == "complete" and r.completed_at == done and r.updated_at == done
    assert [x.task_id for x in await svc.get_task_history()] == [t.task_id]

    f = await svc.create_task("g2")
    clock.advance(5)
    r = await svc.fail_task(f.task_id, reason="boom")
    assert r.status == "failed" and r.blocker == "boom"
    assert r.completed_at == done + timedelta(seconds=5)

    w = await svc.create_task("g3")
    await svc.set_waiting_approval(w.task_id, "need ok")
    r = await svc.get_task(w.task_id)
    assert r.status == "waiting_approval" and r.blocker == "need ok"
    assert r.updated_at == clock.now()


@pytest.mark.asyncio
async def test_needs_owner_and_delegation_fields(env):
    svc, clock = env
    t = await svc.create_task("g", delegated=True)
    await svc.db.merge(t.task_id, {"status": "needs_owner", "updated_at": clock.now(), "blocker": "r"})
    await svc.db.merge(t.task_id, {"requested_by_role": "owner", "reviewed": True})
    got = await svc.get_task(t.task_id)
    assert got.status == "needs_owner" and got.requested_by_role == "owner" and got.reviewed is True
    assert got.blocker == "r"


@pytest.mark.asyncio
async def test_persist_step_and_interrupt(env):
    svc, clock = env
    t = await svc.create_task("g")
    clock.advance(3)
    await svc.persist_step(t.task_id, _step(1))
    await svc.persist_step(t.task_id, _step(2))
    got = await svc.get_task(t.task_id)
    assert got.current_step_index == 2 and got.updated_at == clock.now()
    assert len(got.steps) == 2
    s = got.steps[0]
    assert (s.step_number, s.step_type, s.title, s.detail) == (1, "tool_call", "step 1", "d")
    assert s.tool_name == "write_file" and s.tool_args == {"path": "a.py"} and s.result == "ok"
    assert s.success is True and s.duration_ms == 12 and s.active_file == "a.py"
    assert s.emotion == {"joy": 0.5} and s.timestamp == _START.timestamp() + 3

    await svc.mark_step_interrupted(t.task_id, 2)
    got = await svc.get_task(t.task_id)
    assert got.status == "paused"
    assert got.steps[1].title == "[INTERRUPTED] step 2" and got.steps[1].success is False
    assert got.steps[0].title == "step 1" and got.steps[0].tool_args == {"path": "a.py"}


@pytest.mark.asyncio
async def test_blocker_info_and_resonance(env):
    svc, clock = env
    t = await svc.create_task("g")
    clock.advance(1)
    await svc.set_blocker_info(t.task_id, {
        "type": "repeated_failure", "tool": "bash", "attempts": 3,
        "last_error": "e", "last_reasoning": "r", "suggested_action": "ask",
    })
    got = await svc.get_task(t.task_id)
    bi = got.blocker_info
    assert bi.type == "repeated_failure" and bi.tool == "bash" and bi.attempts == 3
    assert (bi.last_error, bi.last_reasoning, bi.suggested_action) == ("e", "r", "ask")
    assert got.updated_at == clock.now()

    await svc.set_waiting_approval(t.task_id, "stuck")
    clock.advance(1)
    await svc.clear_blocker(t.task_id)
    got = await svc.get_task(t.task_id)
    assert got.status == "running" and got.blocker is None and got.blocker_info is None
    assert got.updated_at == clock.now()

    await svc.add_resonance_score(t.task_id, 0.75)
    assert (await svc.get_task(t.task_id)).resonance_scores == [0.75]


@pytest.mark.asyncio
async def test_delegated_queries_and_recovery(env, monkeypatch):
    svc, clock = env
    d_open = await svc.create_task("open", delegated=True)
    d_done = await svc.create_task("done", delegated=True)
    plain = await svc.create_task("plain")
    await svc.start_task(d_open.task_id)
    await svc.start_task(plain.task_id)
    await svc.complete_task(d_done.task_id)
    got = await svc.get_delegated_tasks()
    assert {x.task_id for x in got} == {d_open.task_id, d_done.task_id}
    assert all(x.delegated is True for x in got)
    assert {x.task_id for x in await svc.get_active_tasks()} == {plain.task_id, d_open.task_id}
    assert {x.status for x in await svc.get_tasks()} == {"running", "complete"}

    async def no_reattach(task):
        return False

    monkeypatch.setattr(svc, "_try_reattach", no_reattach)
    clock.advance(60)
    rec = await svc.recover_interrupted_tasks()
    assert {x.task_id for x in rec} == {d_open.task_id, plain.task_id}
    for tid in (d_open.task_id, plain.task_id):
        r = await svc.get_task(tid)
        assert r.status == "paused" and r.blocker == "System restart — task was interrupted"
        assert r.updated_at == clock.now()
    assert (await svc.get_task(d_open.task_id)).delegated is True


@pytest.mark.asyncio
async def test_delete_task(env):
    svc, _ = env
    t = await svc.create_task("g")
    assert await svc.delete_task(t.task_id) is True
    assert await svc.get_task(t.task_id) is None
