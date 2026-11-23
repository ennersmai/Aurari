"""Tests for the delegation registry and controls API (G4-01). Fake OpenCode client only."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI

from aura.api.routes.delegations import router as delegations_router
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.connections.opencode_client import OpenCodeUnavailable, WorkEvent
from aura.executor import delegation
from aura.executor.delegation import DelegationConfig, DelegationRunner
from aura.models.task import Task, TaskStatus, TaskStepRecord
from aura.tools import delegate as delegate_tool


class FakeClient:
    """Fake OpenCodeClient whose event stream stays open until released."""

    def __init__(self, session_id: str = "ses_fake1") -> None:
        self.session_id = session_id
        self.aborted: list[str] = []
        self.sent: list[tuple[str, str]] = []
        self.release = asyncio.Event()
        self.raise_on_create = False
        self._process = SimpleNamespace(
            connection=SimpleNamespace(base_url="http://127.0.0.1:4096", auth="secret")
        )

    async def create_session(self, workspace: Any, agent: str, title: str) -> str:
        if self.raise_on_create:
            raise OpenCodeUnavailable("down")
        return self.session_id

    async def send(self, session_id: str, prompt: str) -> None:
        self.sent.append((session_id, prompt))

    async def events(self, session_id: str) -> AsyncIterator[WorkEvent]:
        await self.release.wait()
        yield WorkEvent(kind="failed", session_id=session_id, type="x", data={"error": "released"})

    async def abort(self, session_id: str) -> None:
        self.aborted.append(session_id)

    async def result(self, session_id: str) -> Any:
        return SimpleNamespace(
            session_id=session_id, summary="did it", files_changed=["a.py", "b.py"],
            additions=7, deletions=2,
        )

    async def answer_permission(self, *a: Any) -> None:
        pass


class FakeQueue:
    """In-memory task queue with the methods the runner and routes use."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.counter = 0
        self.failed: list[tuple[str, str]] = []
        self.persisted: list[TaskStepRecord] = []
        self.db = MagicMock()
        self.db.merge = AsyncMock(side_effect=self._merge)

    async def create_task(self, goal: str, workspace_path: str = "", session_id: str = "main", delegated: bool = False) -> Task:
        self.counter += 1
        t = Task(task_id=f"task:{self.counter}", goal=goal, workspace_path=workspace_path, session_id=session_id, delegated=delegated)
        self.tasks[t.task_id] = t
        return t

    async def _merge(self, task_id: str, data: dict) -> None:
        t = self.tasks[task_id]
        if "session_id" in data:
            t.session_id = data["session_id"]
        if "status" in data:
            t.status = TaskStatus(data["status"])

    async def get_task(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    async def fail_task(self, task_id: str, reason: str = "") -> Task:
        self.failed.append((task_id, reason))
        t = self.tasks[task_id]
        t.status = TaskStatus.FAILED
        t.blocker = reason
        return t

    async def persist_step(self, task_id: str, step: TaskStepRecord) -> None:
        self.persisted.append(step)

    async def get_delegated_tasks(self, closed_limit: int = 50) -> list[Task]:
        return [t for t in self.tasks.values() if t.session_id != "main"]


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    set_clock(FakeClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)))
    monkeypatch.setattr(settings, "workspaces", {"test": "/fake/workspace"})
    monkeypatch.setattr(settings, "delegation_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "emotion_appraisal_enabled", False)
    monkeypatch.setattr(DelegationRunner, "_resolve_workspace_path", lambda self: Path("/fake/workspace"))
    monkeypatch.setattr(DelegationRunner, "_build_brief", AsyncMock(return_value="brief"))
    delegation._RUNNERS.clear()
    delegation.resume_all()
    yield
    delegation._RUNNERS.clear()
    delegation.resume_all()
    set_clock(Clock())


@pytest.fixture
def queue(monkeypatch) -> FakeQueue:
    q = FakeQueue()
    monkeypatch.setattr(delegation, "get_task_queue", lambda: q)
    from aura.api.routes import delegations as routes
    monkeypatch.setattr(routes, "get_task_queue", lambda: q)
    return q


@pytest.fixture
def decisions(monkeypatch):
    svc = SimpleNamespace(_client=None, pending=AsyncMock(return_value=[]))
    from aura.api.routes import delegations as routes
    monkeypatch.setattr(routes, "get_decision_service", lambda: svc)
    monkeypatch.setattr(delegation, "get_decision_service", lambda: svc)
    return svc


@pytest.fixture
async def api():
    app = FastAPI()
    app.include_router(delegations_router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _start(client: FakeClient) -> DelegationRunner:
    runner = DelegationRunner(DelegationConfig(
        goal="g", workspace="test", agent="aura-build", success_criteria="c", tokens=5000, minutes=5,
    ))
    runner._client = client
    await runner.run()
    return runner


async def _finish(*clients: FakeClient) -> None:
    """Let any monitors end so no task leaks."""
    for c in clients:
        c.release.set()
    for r in delegation.running_runners():
        if r._monitor_task:
            await r._monitor_task
    await asyncio.sleep(0)


async def test_registry_add_and_remove_on_completion(queue, decisions):
    client = FakeClient()
    runner = await _start(client)
    assert delegation.running_runners() == [runner]
    assert delegation.get_runner("task:1") is runner
    await _finish(client)
    assert delegation.running_runners() == []


async def test_registry_removed_when_run_fails(queue, decisions):
    client = FakeClient()
    client.raise_on_create = True
    runner = DelegationRunner(DelegationConfig(
        goal="g", workspace="test", agent="aura-build", success_criteria="c", tokens=5000, minutes=5,
    ))
    runner._client = client
    with pytest.raises(OpenCodeUnavailable):
        await runner.run()
    assert delegation.running_runners() == []


async def test_abort_calls_client_and_fails_task(queue, decisions, api):
    client = FakeClient()
    runner = await _start(client)
    r = await api.post("/delegations/task:1/abort")
    assert r.status_code == 200
    assert client.aborted == ["ses_fake1"]
    assert queue.failed == [("task:1", "aborted by owner")]
    assert queue.tasks["task:1"].status == TaskStatus.FAILED
    assert runner._monitor_task.done()
    assert delegation.running_runners() == []


async def test_abort_without_runner_uses_shared_client(queue, decisions, api):
    client = FakeClient()
    decisions._client = client
    t = await queue.create_task("g", session_id="ses_old", delegated=True)
    t.status = TaskStatus.RUNNING
    r = await api.post(f"/delegations/{t.task_id}/abort")
    assert r.status_code == 200
    assert client.aborted == ["ses_old"]
    assert queue.failed == [(t.task_id, "aborted by owner")]


async def test_abort_non_delegated_and_closed(queue, decisions, api):
    plain = await queue.create_task("plain", session_id="main")
    assert (await api.post(f"/delegations/{plain.task_id}/abort")).status_code == 404
    # An Aura sub-session task (non-"main" session id) is not a delegation.
    sub = await queue.create_task("sub", session_id="session:research")
    sub.status = TaskStatus.RUNNING
    assert (await api.post(f"/delegations/{sub.task_id}/abort")).status_code == 404
    closed = await queue.create_task("c", session_id="ses_x", delegated=True)
    closed.status = TaskStatus.COMPLETE
    assert (await api.post(f"/delegations/{closed.task_id}/abort")).status_code == 409
    assert (await api.post("/delegations/task:999/abort")).status_code == 404


async def test_guidance_reaches_send_and_is_recorded(queue, decisions, api):
    client = FakeClient()
    await _start(client)
    r = await api.post("/delegations/task:1/guidance", json={"text": "use pytest"})
    assert r.status_code == 200
    assert ("ses_fake1", "use pytest") in client.sent
    steps = queue.persisted
    assert [(s.step_type, s.detail) for s in steps] == [("guidance", "use pytest")]
    await _finish(client)


async def test_guidance_limits_and_state(queue, decisions, api, monkeypatch):
    client = FakeClient()
    await _start(client)
    too_long = "x" * (settings.delegation_guidance_max_chars + 1)
    assert (await api.post("/delegations/task:1/guidance", json={"text": too_long})).status_code == 422
    assert (await api.post("/delegations/task:1/guidance", json={"text": "  "})).status_code == 422
    exact = "x" * settings.delegation_guidance_max_chars
    assert (await api.post("/delegations/task:1/guidance", json={"text": exact})).status_code == 200
    queue.tasks["task:1"].status = TaskStatus.COMPLETE
    r = await api.post("/delegations/task:1/guidance", json={"text": "late"})
    assert r.status_code == 409
    assert len(client.sent) == 2  # the brief and the one accepted guidance
    await _finish(client)


async def test_pause_all_refuses_delegate_work_but_runner_continues(queue, decisions, api, monkeypatch):
    client = FakeClient()
    runner = await _start(client)
    assert (await api.post("/delegations/pause-all")).json()["paused"] is True
    start = AsyncMock(return_value="task:new")
    monkeypatch.setattr(delegation, "start_delegation", start)
    args = {"goal": "g", "workspace": "test", "agent": "aura-build", "success_criteria": "c"}
    res = await delegate_tool.run(args)
    assert res["success"] is False and "paused" in res["message"].lower()
    start.assert_not_awaited()
    assert delegation.running_runners() == [runner]
    assert not runner._monitor_task.done()
    assert (await api.post("/delegations/resume-all")).json()["paused"] is False
    res = await delegate_tool.run(args)
    assert res["success"] is True
    start.assert_awaited_once()
    await _finish(client)


async def test_abort_all_reaches_every_runner(queue, decisions, api):
    c1, c2 = FakeClient("ses_a"), FakeClient("ses_b")
    await _start(c1)
    await _start(c2)
    assert len(delegation.running_runners()) == 2
    r = await api.post("/delegations/abort-all")
    assert sorted(r.json()["aborted"]) == ["task:1", "task:2"]
    assert c1.aborted == ["ses_a"] and c2.aborted == ["ses_b"]
    assert delegation.running_runners() == []
    assert {t for t, _ in queue.failed} == {"task:1", "task:2"}


async def test_diff_comes_from_client(queue, decisions, api):
    client = FakeClient()
    await _start(client)
    r = await api.get("/delegations/task:1/diff")
    assert r.status_code == 200
    body = r.json()
    assert body["files_changed"] == ["a.py", "b.py"]
    assert (body["additions"], body["deletions"]) == (7, 2)
    await _finish(client)


async def test_opencode_url_has_no_auth(queue, decisions, api):
    assert (await api.get("/delegations/opencode-url")).json() == {"url": None}
    client = FakeClient()
    await _start(client)
    r = await api.get("/delegations/opencode-url")
    assert r.json() == {"url": "http://127.0.0.1:4096"}
    assert "secret" not in r.text
    await _finish(client)


async def test_list_and_detail(queue, decisions, api):
    plain = await queue.create_task("plain", session_id="main")
    client = FakeClient()
    await _start(client)
    decisions.pending.return_value = [{"id": "decision:⟨1abc⟩", "task_id": "task:2"}]
    r = await api.get("/delegations")
    body = r.json()
    ids = [d["task_id"] for d in body["delegations"]]
    assert ids == ["task:2"] and plain.task_id not in ids
    item = body["delegations"][0]
    assert item["state"] == "running" and item["session_id"] == "ses_fake1"
    assert item["pending_decision_ids"] == ["decision:1abc"]
    assert item["budget"]["tokens_limit"] == 5000
    one = await api.get("/delegations/task:2")
    assert one.status_code == 200 and one.json()["delegation"]["task_id"] == "task:2"
    assert (await api.get(f"/delegations/{plain.task_id}")).status_code == 404
    await _finish(client)


def test_blocker_serialised_in_workbench_shape():
    from aura.api.routes.delegations import _blocker
    from aura.models.task import BlockerInfo
    t = Task(task_id="task:b", goal="g", session_id="ses_b", delegated=True)
    assert _blocker(t) is None
    t.blocker = "stuck"
    assert _blocker(t) == "stuck"
    t.blocker_info = BlockerInfo(type="repeated_failure", last_reasoning="3 failed tool calls",
                                 suggested_action="Try the other test runner.")
    assert _blocker(t) == {"kind": "repeated_failure", "reason": "3 failed tool calls",
                           "suggestion": "Try the other test runner."}
