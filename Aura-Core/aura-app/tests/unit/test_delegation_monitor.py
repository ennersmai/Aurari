"""Tests for the delegation blocker monitor, heartbeat, emotion per step and re-attach (G4-02).

Fake OpenCode client, fake LLM, fake queue and decision service only.
"""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.connections.opencode_client import WorkEvent
from aura.executor import delegation
from aura.executor.delegation import DelegationConfig, DelegationRunner
from aura.executor.task_queue import TaskQueueService
from aura.models.task import Task, TaskStatus, TaskStepRecord

SESSION = "ses_mon1"


class FakeClient:
    """Fake OpenCodeClient; events are pushed by the test through a queue."""

    def __init__(self, running: bool = True) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.aborted: list[str] = []
        self.running = running
        self.closed = False

    async def create_session(self, workspace: Any, agent: str, title: str) -> str:
        return SESSION

    async def send(self, session_id: str, prompt: str) -> None:
        pass

    async def events(self, session_id: str) -> AsyncIterator[WorkEvent]:
        while True:
            ev = await self.queue.get()
            if ev is None:
                return
            yield ev

    async def abort(self, session_id: str) -> None:
        self.aborted.append(session_id)

    async def session_running(self, session_id: str) -> bool:
        return self.running

    async def close(self) -> None:
        self.closed = True

    async def result(self, session_id: str) -> Any:
        return SimpleNamespace(session_id=session_id, summary="", files_changed=[], additions=0, deletions=0)

    async def answer_permission(self, *a: Any) -> None:
        pass


class FakeQueue:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.failed: list[tuple[str, str]] = []
        self.persisted: list[TaskStepRecord] = []
        self.blocker_calls: list[dict] = []
        self.db = MagicMock()
        self.db.merge = AsyncMock(side_effect=self._merge)

    async def create_task(self, goal: str, workspace_path: str = "", session_id: str = "main", delegated: bool = False) -> Task:
        t = Task(task_id="task:1", goal=goal, workspace_path=workspace_path, session_id=session_id, delegated=delegated)
        self.tasks[t.task_id] = t
        return t

    async def _merge(self, task_id: str, data: dict) -> None:
        if "status" in data:
            self.tasks[task_id].status = TaskStatus(data["status"])

    async def fail_task(self, task_id: str, reason: str = "") -> Task:
        self.failed.append((task_id, reason))
        self.tasks[task_id].status = TaskStatus.FAILED
        return self.tasks[task_id]

    async def persist_step(self, task_id: str, step: TaskStepRecord) -> None:
        self.persisted.append(step)

    async def set_blocker_info(self, task_id: str, data: dict) -> None:
        self.blocker_calls.append(dict(data))


class FakeLLM:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    async def complete(self, messages: list, model: str, **kw: Any) -> str:
        self.calls.append({"messages": messages, "model": model})
        if self.fail:
            raise RuntimeError("llm down")
        return "  Ask the owner to check the file path.  "


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    set_clock(FakeClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)))
    monkeypatch.setattr(settings, "workspaces", {"test": "/fake/workspace"})
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", False)
    # Long heartbeat by default so only the heartbeat tests see it.
    monkeypatch.setattr(settings, "delegation_heartbeat_seconds", 3600.0)
    monkeypatch.setattr(DelegationRunner, "_resolve_workspace_path", lambda self: Path("/fake/workspace"))
    monkeypatch.setattr(DelegationRunner, "_build_brief", AsyncMock(return_value="the brief"))
    monkeypatch.setattr(delegation, "_get_emotion_engine", lambda: None)
    delegation._RUNNERS.clear()
    yield
    delegation._RUNNERS.clear()
    set_clock(Clock())


@pytest.fixture
def queue(monkeypatch) -> FakeQueue:
    q = FakeQueue()
    monkeypatch.setattr(delegation, "get_task_queue", lambda: q)
    return q


@pytest.fixture
def decisions(monkeypatch):
    svc = SimpleNamespace(_client=None, create=AsyncMock(return_value={}))
    monkeypatch.setattr(delegation, "get_decision_service", lambda: svc)
    return svc


@pytest.fixture
def llm(monkeypatch) -> FakeLLM:
    fake = FakeLLM()
    monkeypatch.setattr(delegation, "_get_llm_client", lambda: fake)
    return fake


async def _start(client: FakeClient, tokens: int = 100000, minutes: int = 10) -> DelegationRunner:
    runner = DelegationRunner(DelegationConfig(
        goal="fix the bug", workspace="test", agent="aura-build", success_criteria="tests pass",
        tokens=tokens, minutes=minutes,
    ))
    runner._client = client
    await runner.run()
    await _settle()  # let the monitor start (it stamps its heartbeat clock)
    return runner


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


async def _finish(client: FakeClient, runner: DelegationRunner) -> None:
    client.queue.put_nowait(None)
    await runner._monitor_task
    await _settle()


def _tool(type_: str, data: dict | None = None) -> WorkEvent:
    return WorkEvent(kind="tool", session_id=SESSION, type=type_, data=data or {})


def _failed(msg: str = "boom") -> WorkEvent:
    return _tool("session.tool.failed", {"error": {"message": msg}})


def _called(tool: str = "bash", args: dict | None = None) -> WorkEvent:
    return _tool("session.tool.called", {"tool": tool, "arguments": args if args is not None else {"command": "ls"}})


async def _push(client: FakeClient, *events: WorkEvent) -> None:
    for e in events:
        client.queue.put_nowait(e)
    await _settle()


def _blocker_decisions(decisions) -> list[dict]:
    return [c.kwargs for c in decisions.create.call_args_list]


# ---------------------------------------------------------------------------
# Blocker kinds
# ---------------------------------------------------------------------------

async def test_error_streak_fires_once_with_one_decision(queue, decisions, llm):
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _failed(), _failed())
    assert decisions.create.await_count == 0  # two failures: below the streak of 3
    await _push(client, _failed(), _failed(), _failed())
    assert decisions.create.await_count == 1
    kw = _blocker_decisions(decisions)[0]
    assert kw["kind"] == "needs_decision"
    assert kw["task_id"] == "task:1"
    assert "failed tool calls in a row" in kw["message"]
    assert "Tool: unknown" in kw["message"]  # the recent step summaries
    assert queue.blocker_calls[0]["type"] == "repeated_failure"
    await _finish(client, runner)


async def test_success_resets_error_streak(queue, decisions, llm):
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _failed(), _failed(), _tool("session.tool.success"), _failed(), _failed())
    assert decisions.create.await_count == 0
    await _finish(client, runner)


async def test_repeat_loop_normalises_args_and_fires_once(queue, decisions, llm):
    client = FakeClient()
    runner = await _start(client)
    # Same arguments in a different key order still count as the same call.
    await _push(
        client,
        _called("edit", {"a": 1, "b": 2}), _called("edit", {"b": 2, "a": 1}), _called("edit", {"a": 1, "b": 2}),
    )
    assert decisions.create.await_count == 0  # 3 of 4
    await _push(client, _called("edit", {"b": 2, "a": 1}), _called("edit", {"a": 1, "b": 2}))
    assert decisions.create.await_count == 1
    assert queue.blocker_calls[0]["type"] == "reasoning_loop"
    assert queue.blocker_calls[0]["tool"] == "edit"
    await _finish(client, runner)


async def test_different_args_are_not_a_loop(queue, decisions, llm):
    client = FakeClient()
    runner = await _start(client)
    await _push(client, *[_called("edit", {"n": i}) for i in range(8)])
    assert decisions.create.await_count == 0
    await _finish(client, runner)


async def test_token_budget_80_percent_fires_once_before_the_stop(queue, decisions, llm):
    client = FakeClient()
    runner = await _start(client, tokens=1000)
    await _push(client, _tool("session.tool.success", {"usage": {"total_tokens": 700}}))
    assert decisions.create.await_count == 0
    await _push(client, _tool("session.tool.success", {"usage": {"total_tokens": 100}}))
    await _push(client, _tool("session.tool.success", {"usage": {"total_tokens": 50}}))
    assert decisions.create.await_count == 1  # fired at 800, not again at 850
    assert "token budget" in _blocker_decisions(decisions)[0]["message"]
    assert queue.failed == []  # still running, the 100% stop is separate
    await _push(client, _tool("session.tool.success", {"usage": {"total_tokens": 500}}))
    assert queue.failed and queue.failed[0][1].startswith("budget exceeded: tokens")
    await runner._monitor_task


async def test_time_budget_80_percent_fires_once_before_the_stop(queue, decisions, llm):
    client = FakeClient()
    runner = await _start(client, minutes=10)
    get_clock().advance(60 * 7)
    await _push(client, _tool("session.tool.progress"))
    assert decisions.create.await_count == 0
    get_clock().advance(60)  # 8 of 10 minutes
    await _push(client, _tool("session.tool.progress"), _tool("session.tool.progress"))
    assert decisions.create.await_count == 1
    assert "time budget" in _blocker_decisions(decisions)[0]["message"]
    assert queue.failed == []
    get_clock().advance(60 * 3)
    await _push(client, _tool("session.tool.progress"))
    assert queue.failed and queue.failed[0][1].startswith("budget exceeded: time")
    await runner._monitor_task


# ---------------------------------------------------------------------------
# Suggestion
# ---------------------------------------------------------------------------

async def test_suggestion_is_stored_on_the_blocker(queue, decisions, llm, monkeypatch):
    monkeypatch.setattr(settings, "delegation_error_streak", 1)
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _failed("no such file"))
    await _settle()
    assert len(llm.calls) == 1
    assert llm.calls[0]["model"] == settings.active_l2_model
    prompt = llm.calls[0]["messages"][0]["content"]
    assert "the brief" in prompt and "one paragraph" in prompt
    assert queue.blocker_calls[-1]["suggested_action"] == "Ask the owner to check the file path."
    assert queue.blocker_calls[0]["suggested_action"] == ""  # blocker first, suggestion after
    await _finish(client, runner)


async def test_failed_suggestion_keeps_blocker_and_stream(queue, decisions, llm, monkeypatch):
    monkeypatch.setattr(settings, "delegation_error_streak", 1)
    llm.fail = True
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _failed(), _tool("session.tool.success"), _tool("session.tool.progress"))
    assert len(llm.calls) == 1
    assert decisions.create.await_count == 1
    assert len(queue.blocker_calls) == 1 and queue.blocker_calls[0]["suggested_action"] == ""
    # The stream kept being processed after the failed call: tool steps are persisted.
    assert [s.step_type for s in queue.persisted] == ["tool", "tool", "tool"]
    await _finish(client, runner)


async def test_suggestion_does_not_block_the_monitor(queue, decisions, monkeypatch):
    monkeypatch.setattr(settings, "delegation_error_streak", 1)
    gate = asyncio.Event()

    class SlowLLM:
        async def complete(self, messages, model, **kw):
            await gate.wait()
            return "late"

    monkeypatch.setattr(delegation, "_get_llm_client", lambda: SlowLLM())
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _failed(), _tool("session.tool.success"))
    assert [s.step_type for s in queue.persisted] == ["tool", "tool"]  # not awaited inside the loop
    assert len(runner._bg_tasks) == 1
    await _finish(client, runner)  # monitor end cancels the pending suggestion
    assert runner._bg_tasks == set()


# ---------------------------------------------------------------------------
# Heartbeat
# ---------------------------------------------------------------------------

def _fast_timer(monkeypatch) -> None:
    """Interval 60 fake seconds, but the timer task wakes every 10 ms of real time."""
    monkeypatch.setattr(settings, "delegation_heartbeat_seconds", 60.0)

    async def quick(self) -> None:
        await asyncio.sleep(0.01)

    monkeypatch.setattr(DelegationRunner, "_heartbeat_wait", quick)


async def test_heartbeat_on_a_silent_session(queue, decisions, llm, monkeypatch):
    _fast_timer(monkeypatch)
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _tool("session.tool.success", {"tool": "bash"}))  # one real step
    get_clock().advance(125)  # past the interval, and 2 minutes in
    await asyncio.sleep(0.1)  # the timer wakes with no event on the stream
    beats = [s for s in queue.persisted if s.step_type == "status"]
    assert len(beats) == 1  # the fake clock only moved once
    assert beats[0].title == "still working: Tool: bash, 1 steps, 2 min"
    heartbeat = runner._heartbeat_task
    await _finish(client, runner)
    assert heartbeat.done() and runner._heartbeat_task is None


async def test_no_heartbeat_before_the_interval(queue, decisions, llm, monkeypatch):
    _fast_timer(monkeypatch)
    client = FakeClient()
    runner = await _start(client)
    get_clock().advance(5)
    await asyncio.sleep(0.05)
    assert [s for s in queue.persisted if s.step_type == "status"] == []
    await _finish(client, runner)


async def test_heartbeat_checked_on_event(queue, decisions, llm, monkeypatch):
    monkeypatch.setattr(settings, "delegation_heartbeat_seconds", 60.0)
    client = FakeClient()
    runner = await _start(client)
    get_clock().advance(61)
    await _push(client, _tool("session.tool.progress"))  # kind tool, not a step, only the beat appears
    assert [s.step_type for s in queue.persisted if s.step_type == "status"] == ["status"]
    await _finish(client, runner)


async def test_no_leaked_tasks_after_abort(queue, decisions, llm, monkeypatch):
    monkeypatch.setattr(delegation, "get_task_queue", lambda: queue)
    client = FakeClient()
    runner = await _start(client)
    heartbeat = runner._heartbeat_task
    await runner.abort()
    assert heartbeat is None or heartbeat.done() or runner._heartbeat_task is None
    await _settle()
    assert runner._heartbeat_task is None and runner._bg_tasks == set()


# ---------------------------------------------------------------------------
# Emotion per step
# ---------------------------------------------------------------------------

class FakeEmotionEngine:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def get_current_state(self) -> Any:
        if self.fail:
            raise RuntimeError("engine down")
        vector = SimpleNamespace(get_top_n=lambda n: [("joy", 0.61234567), ("trust", 0.4), ("calm", 0.2)][:n])
        return SimpleNamespace(vector=vector)


async def test_step_carries_top_three_emotions(queue, decisions, llm, monkeypatch):
    monkeypatch.setattr(delegation, "_get_emotion_engine", lambda: FakeEmotionEngine())
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _tool("session.tool.success", {"tool": "bash"}))
    assert queue.persisted[0].emotion == {"joy": 0.6123, "trust": 0.4, "calm": 0.2}
    assert queue.persisted[0].model_dump(mode="json")["emotion"]["joy"] == 0.6123
    await _finish(client, runner)


async def test_emotion_failure_never_blocks_the_step(queue, decisions, llm, monkeypatch):
    monkeypatch.setattr(delegation, "_get_emotion_engine", lambda: FakeEmotionEngine(fail=True))
    client = FakeClient()
    runner = await _start(client)
    await _push(client, _tool("session.tool.success", {"tool": "bash"}))
    assert len(queue.persisted) == 1 and queue.persisted[0].emotion is None
    await _finish(client, runner)


# ---------------------------------------------------------------------------
# Re-attach
# ---------------------------------------------------------------------------

def _delegated_task(task_id: str = "task:9", session_id: str = SESSION, delegated: bool = True) -> Task:
    return Task(
        task_id=task_id, goal="old goal", workspace_path="test", session_id=session_id,
        status=TaskStatus.RUNNING, delegated=delegated,
    )


def _patch_client(monkeypatch, client: FakeClient) -> None:
    monkeypatch.setattr(delegation, "OpenCodeProcess", lambda: object())
    monkeypatch.setattr(delegation, "OpenCodeClient", lambda process: client)


async def test_reattach_with_running_session_starts_a_monitor(queue, decisions, llm, monkeypatch):
    client = FakeClient(running=True)
    _patch_client(monkeypatch, client)
    task = _delegated_task()
    assert await delegation.try_reattach(task) is True
    runner = delegation.get_runner("task:9")
    assert runner is not None and runner.session_id == SESSION and runner.client is client
    assert decisions._client is client
    # The monitor is live: an event becomes a step on the existing task.
    await _push(client, _tool("session.tool.success", {"tool": "bash"}))
    assert len(queue.persisted) == 1
    await _finish(client, runner)
    assert delegation.running_runners() == []


async def test_reattach_with_ended_session_does_nothing(queue, decisions, monkeypatch):
    client = FakeClient(running=False)
    _patch_client(monkeypatch, client)
    assert await delegation.try_reattach(_delegated_task()) is False
    assert delegation.running_runners() == [] and client.closed


async def test_reattach_error_gives_false(queue, decisions, monkeypatch):
    client = FakeClient()
    client.session_running = AsyncMock(side_effect=RuntimeError("down"))
    _patch_client(monkeypatch, client)
    assert await delegation.try_reattach(_delegated_task()) is False
    assert delegation.running_runners() == []


async def test_reattach_skips_non_delegated(queue, decisions, monkeypatch):
    client = FakeClient()
    _patch_client(monkeypatch, client)
    assert await delegation.try_reattach(_delegated_task(delegated=False)) is False


def _recovery_service(tasks: list[Task]) -> tuple[TaskQueueService, MagicMock]:
    svc = TaskQueueService.__new__(TaskQueueService)
    db = MagicMock()
    db.query = AsyncMock(return_value=[[t.model_dump(mode="json") for t in tasks]])
    db.merge = AsyncMock()
    svc.db = db
    return svc, db


async def test_recovery_reattaches_running_and_pauses_the_rest(queue, decisions, llm, monkeypatch):
    live = FakeClient(running=True)
    _patch_client(monkeypatch, live)
    svc, db = _recovery_service([
        _delegated_task("task:9"),
        _delegated_task("task:10", session_id="main", delegated=False),  # an ordinary task
    ])
    interrupted = await svc.recover_interrupted_tasks()
    assert [t.task_id for t in interrupted] == ["task:10"]
    merged = [c.args[0] for c in db.merge.call_args_list]
    assert merged == ["task:10"]  # task:9 was not marked paused
    assert delegation.get_runner("task:9") is not None
    await _finish(live, delegation.get_runner("task:9"))


async def test_recovery_marks_ended_session_interrupted(queue, decisions, monkeypatch):
    _patch_client(monkeypatch, FakeClient(running=False))
    svc, db = _recovery_service([_delegated_task("task:9")])
    interrupted = await svc.recover_interrupted_tasks()
    assert [t.task_id for t in interrupted] == ["task:9"]
    assert db.merge.call_args.args[1]["status"] == TaskStatus.PAUSED.value
    assert delegation.running_runners() == []


async def test_emit_appraisal_reaches_engine_only_with_flag(monkeypatch):
    """Supervisor fix: _emit_appraisal imported a function that does not exist,
    so delegation outcomes were never appraised."""
    from aura.config import settings
    from aura.executor import delegation as d

    calls = []

    class Engine:
        async def appraise(self, event):
            calls.append(event)

    monkeypatch.setattr(d, "_get_emotion_engine", lambda: Engine())
    runner = d.DelegationRunner.__new__(d.DelegationRunner)
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", False)
    await runner._emit_appraisal("succeeded")
    assert calls == []
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", True)
    await runner._emit_appraisal("succeeded")
    await runner._emit_appraisal("failed")
    assert [e.appraisal.congruence > 0 for e in calls] == [True, False]
