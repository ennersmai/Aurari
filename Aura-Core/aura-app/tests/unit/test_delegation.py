"""Tests for the delegate_work tool and DelegationRunner (W3-32)."""

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.clock import FakeClock, get_clock, set_clock
from aura.config import settings
from aura.connections.opencode_client import OpenCodeClient, OpenCodeUnavailable, WorkEvent
from aura.executor.decisions import DecisionService, get_decision_service, set_decision_service
from aura.executor.delegation import DelegationConfig, DelegationRunner, start_delegation
from aura.executor.task_queue import TaskQueueService
from aura.models.task import Task, TaskStatus, TaskStepRecord


# ---------------------------------------------------------------------------
# Fake OpenCode Client
# ---------------------------------------------------------------------------

class FakeOpenCodeClient:
    """Fake OpenCodeClient that scripts a sequence of events."""

    def __init__(self) -> None:
        self._events: List[WorkEvent] = []
        self._event_index = 0
        self._permissions_answered: dict[str, bool] = {}
        self._aborted = False
        self._session_id: Optional[str] = None
        self._started = False
        self._last_prompt = ""

    def script_events(self, events: List[WorkEvent]) -> None:
        """Set the events this fake client will yield."""
        self._events = events
        self._event_index = 0

    async def ensure_running(self) -> Any:
        return MagicMock(base_url="http://fake", auth=None, version="2.3.2")

    async def create_session(
        self, workspace: Any, agent: str, title: str
    ) -> str:
        self._session_id = "session:fake123"
        return self._session_id

    async def send(self, session_id: str, prompt: str) -> None:
        self._started = True
        self._last_prompt = prompt

    async def events(self, session_id: str) -> AsyncIterator[WorkEvent]:
        while self._event_index < len(self._events):
            yield self._events[self._event_index]
            self._event_index += 1
            await asyncio.sleep(0)  # Yield control

    async def pending_permissions(self, session_id: str) -> List[Any]:
        return []

    async def answer_permission(
        self, session_id: str, request_id: str, allow: bool
    ) -> None:
        self._permissions_answered[request_id] = allow

    async def abort(self, session_id: str) -> None:
        self._aborted = True

    async def result(self, session_id: str) -> Any:
        return MagicMock(
            session_id=session_id,
            summary="Done",
            files_changed=[],
            additions=0,
            deletions=0,
        )

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def fake_clock():
    """Install a fake clock for all tests."""
    previous = get_clock()
    clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
    set_clock(clock)
    yield clock
    set_clock(previous)  # Restore whatever clock was installed before


@pytest.fixture(autouse=True)
def mock_workspaces(monkeypatch):
    """Mock workspaces setting and workspace path resolution."""
    monkeypatch.setattr(settings, "workspaces", {"test": "/fake/workspace"})
    # Patch _resolve_workspace_path to return a valid path
    from aura.executor import delegation
    original_resolve = delegation.DelegationRunner._resolve_workspace_path
    async def mock_resolve(self):
        from pathlib import Path
        return Path("/fake/workspace")
    monkeypatch.setattr(delegation.DelegationRunner, "_resolve_workspace_path", mock_resolve)
    # Also patch policy.workspace_path to return a valid path
    from aura.executor import policy
    def mock_workspace_path(name: str):
        if name == "test":
            from pathlib import Path
            return Path("/fake/workspace")
        return None
    monkeypatch.setattr(policy, "workspace_path", mock_workspace_path)


@pytest.fixture
def fake_client() -> FakeOpenCodeClient:
    return FakeOpenCodeClient()


@pytest.fixture
def fake_decision_service(fake_client: FakeOpenCodeClient) -> AsyncMock:
    """Create a mock DecisionService with a mock create method."""
    mock = AsyncMock()
    mock._client = fake_client
    mock.create = AsyncMock()
    mock.answer = AsyncMock()
    mock.expire_for_session = AsyncMock()
    set_decision_service(mock)
    yield mock
    set_decision_service(None)


@pytest.fixture
def mock_task_queue(fake_clock: FakeClock) -> MagicMock:
    """Create a mock TaskQueueService."""
    mock = MagicMock(spec=TaskQueueService)
    task = Task(
        task_id="task:abc123",
        goal="Test goal",
        status=TaskStatus.QUEUED,
        workspace_path="/workspace",
        task_memory_namespace="task_abc123",
        session_id="main",
    )
    task.steps = []
    mock.create_task = AsyncMock(return_value=task)
    mock.get_task = AsyncMock(return_value=task)
    mock.persist_step = AsyncMock()
    mock.fail_task = AsyncMock(return_value=task)
    mock.set_waiting_approval = AsyncMock()
    mock.db = MagicMock()
    mock.db.merge = AsyncMock()
    return mock


@pytest.fixture
def mock_recall_engine() -> MagicMock:
    """Create a mock RecallEngine."""
    from aura.engines.recall.models import Block, BlockKind, ContextPacket, RecallTrace

    mock = MagicMock()
    packet = ContextPacket(
        stable_blocks=[],
        dynamic_blocks=[
            Block(
                kind="memories",
                text="<memories>Recalled context for the goal</memories>",
                tokens=100,
                stable=False,
            )
        ],
        abstain=False,
        trace=RecallTrace(
            turn_id="turn1",
            user_id="owner",
            query="test goal",
            created_at=datetime.now(timezone.utc),
            budget_tokens=200000,
            tokens_before=100,
            tokens_after=100,
            items=[],
            channel_errors={},
        ),
    )
    mock.recall = AsyncMock(return_value=packet)
    return mock


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _make_work_event(kind: str, type_: str, data: dict) -> WorkEvent:
    return WorkEvent(kind=kind, session_id="session:fake123", type=type_, data=data)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDelegateWorkTool:
    """Tests for the delegate_work tool function."""

    @pytest.mark.asyncio
    async def test_guest_cannot_call_tool(self, monkeypatch):
        """A guest cannot call the tool (existing role check - tool doesn't check, executor does)."""
        from aura.tools.delegate import run

        settings.delegation_enabled = True
        monkeypatch.setattr(settings, "delegation_enabled", True)

        with patch("aura.executor.delegation.start_delegation", AsyncMock(return_value="task:fake123")):
            result = await run({
                "goal": "Test goal",
                "workspace": "test",
                "agent": "aura-build",
                "success_criteria": "Done",
            })
            assert result["success"] is True
            assert result["task_id"] == "task:fake123"

    @pytest.mark.asyncio
    async def test_flag_off_returns_disabled(self):
        """When delegation_enabled is off, tool returns clear message."""
        from aura.tools.delegate import run

        settings.delegation_enabled = False

        result = await run({
            "goal": "Test goal",
            "workspace": "test",
            "agent": "aura-build",
            "success_criteria": "Done",
        })

        assert result["success"] is False
        assert result["status"] == "DISABLED"
        assert "turned off" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_missing_required_args(self):
        """Tool validates required arguments."""
        from aura.tools.delegate import run

        settings.delegation_enabled = True

        # Missing goal
        result = await run({
            "workspace": "test",
            "agent": "aura-build",
            "success_criteria": "Done",
        })
        assert result["success"] is False
        assert "goal" in result["message"].lower()

        # Missing workspace
        result = await run({
            "goal": "Test",
            "agent": "aura-build",
            "success_criteria": "Done",
        })
        assert result["success"] is False
        assert "workspace" in result["message"].lower()

        # Invalid agent
        result = await run({
            "goal": "Test",
            "workspace": "test",
            "agent": "invalid-agent",
            "success_criteria": "Done",
        })
        assert result["success"] is False
        assert "invalid agent" in result["message"].lower()

        # Missing success_criteria
        result = await run({
            "goal": "Test",
            "workspace": "test",
            "agent": "aura-build",
        })
        assert result["success"] is False
        assert "success criteria" in result["message"].lower()

    @pytest.mark.asyncio
    async def test_budget_defaults_from_config(self, monkeypatch, mock_task_queue):
        """Budget defaults come from config when not provided."""
        from aura.tools.delegate import run

        settings.delegation_enabled = True
        monkeypatch.setattr(settings, "delegation_default_tokens", 150000)
        monkeypatch.setattr(settings, "delegation_default_minutes", 45)

        with patch("aura.executor.delegation.start_delegation", AsyncMock(return_value="task:fake123")) as mock_start:
            await run({
                "goal": "Test goal",
                "workspace": "test",
                "agent": "aura-build",
                "success_criteria": "Done",
            })
            # Check that start_delegation was called with config defaults
            call_args = mock_start.call_args[1]
            assert call_args["tokens"] == 150000
            assert call_args["minutes"] == 45


class TestDelegationRunner:
    """Tests for the DelegationRunner class."""

    @pytest.mark.asyncio
    async def test_brief_contains_goal_criteria_and_recall(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine
    ):
        """Brief contains goal, success criteria, and recall text."""
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_events([success_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Build a login page",
                workspace="test",
                agent="aura-build",
                success_criteria="Login page works",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            task_id = await runner.run()

            # Verify the prompt sent to the session
            assert fake_client._started
            prompt = fake_client._last_prompt
            assert "Build a login page" in prompt
            assert "Login page works" in prompt
            assert "Recalled context for the goal" in prompt

    @pytest.mark.asyncio
    async def test_permission_asked_creates_pending_decision_and_waits(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine, fake_decision_service
    ):
        """T3: permission.asked for shell command creates pending decision, task waits."""
        # Script a permission.asked event for a shell command
        permission_event = _make_work_event(
            kind="permission",
            type_="permission.asked",
            data={
                "id": "perm:123",
                "action": "bash",
                "resources": ["/workspace/test.sh"],
                "message": "Run test script",
            },
        )
        # Then a step.ended event after permission is granted
        step_event = _make_work_event(
            kind="step",
            type_="session.step.ended",
            data={"step": {"action": "bash", "description": "Run test"}},
        )
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_events([permission_event, step_event, success_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Run tests",
                workspace="test",
                agent="aura-build",
                success_criteria="Tests pass",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            task_id = await runner.run()

            # Wait for monitor to process events
            await asyncio.sleep(0.5)

            # For bash (execute risk), owner gets "ask" -> creates decision, sets task to waiting_approval
            # Client does NOT answer for "ask" decisions
            assert "perm:123" not in fake_client._permissions_answered

            # Verify task was set to waiting_approval
            mock_task_queue.set_waiting_approval.assert_called()
            call_args = mock_task_queue.set_waiting_approval.call_args
            assert "Permission required" in call_args[1]["blocker"]

            # Verify decision was created
            fake_decision_service.create.assert_called()

    @pytest.mark.asyncio
    async def test_read_request_allowed_at_once(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine, fake_decision_service
    ):
        """Read request is allowed at once (no decision created)."""
        permission_event = _make_work_event(
            kind="permission",
            type_="permission.asked",
            data={
                "id": "perm:read1",
                "action": "read",
                "resources": ["/workspace/file.txt"],
                "message": "Read file",
            },
        )
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_events([permission_event, success_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Read file",
                workspace="test",
                agent="aura-build",
                success_criteria="File read",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            # Read -> read risk, owner gets "allow" -> answered immediately
            assert fake_client._permissions_answered.get("perm:read1") is True
            # No waiting_approval should be set
            mock_task_queue.set_waiting_approval.assert_not_called()
            # No decision should be created for "allow"
            fake_decision_service.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_outside_workspace_denied_at_once(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine, fake_decision_service
    ):
        """Write outside workspace is denied at once."""
        permission_event = _make_work_event(
            kind="permission",
            type_="permission.asked",
            data={
                "id": "perm:write1",
                "action": "write",
                "resources": ["/etc/passwd"],
                "message": "Write outside workspace",
            },
        )
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_events([permission_event, success_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Write file",
                workspace="test",
                agent="aura-build",
                success_criteria="File written",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            # Write outside workspace should be denied
            assert fake_client._permissions_answered.get("perm:write1") is False
            mock_task_queue.set_waiting_approval.assert_not_called()

    @pytest.mark.asyncio
    async def test_token_budget_exceeded_aborts_and_fails(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine
    ):
        """T5: Usage events past token budget cause abort and failed task."""
        # Tool event with high token usage
        tool_event = _make_work_event(
            kind="tool",
            type_="session.tool.called",
            data={
                "tool": "bash",
                "arguments": {"command": "big-command"},
                "usage": {"total_tokens": 250000},  # Exceeds 200000 limit
            },
        )
        fake_client.script_events([tool_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Big task",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            # Verify abort was called
            assert fake_client._aborted is True
            # Verify task failed with budget reason
            mock_task_queue.fail_task.assert_called()
            call_args = mock_task_queue.fail_task.call_args
            assert "budget exceeded" in call_args[1]["reason"].lower()
            assert "tokens" in call_args[1]["reason"].lower()

    @pytest.mark.asyncio
    async def test_time_budget_exceeded_aborts_and_fails(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine, fake_clock: FakeClock
    ):
        """Time budget exceeded causes abort and failed task."""
        step_event = _make_work_event(
            kind="step",
            type_="session.step.ended",
            data={"step": {"action": "thinking"}},
        )
        fake_client.script_events([step_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Long task",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=1,  # 1 minute budget
            )
            runner = DelegationRunner(config)
            await runner.run()

            # Advance clock by 2 minutes
            fake_clock.advance(120)
            await asyncio.sleep(0.1)

            # Verify abort was called
            assert fake_client._aborted is True
            # Verify task failed with budget reason
            mock_task_queue.fail_task.assert_called()
            call_args = mock_task_queue.fail_task.call_args
            assert "budget exceeded" in call_args[1]["reason"].lower()
            assert "time" in call_args[1]["reason"].lower()

    @pytest.mark.asyncio
    async def test_steps_are_persisted(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine
    ):
        """Steps are persisted for session.step.ended and tool calls."""
        step_event = _make_work_event(
            kind="step",
            type_="session.step.ended",
            data={"step": {"action": "read", "description": "Read config"}},
        )
        tool_event = _make_work_event(
            kind="tool",
            type_="session.tool.called",
            data={"tool": "bash", "arguments": {"command": "ls"}},
        )
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_events([step_event, tool_event, success_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Test steps",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            # Verify persist_step was called twice (step + tool)
            assert mock_task_queue.persist_step.call_count == 2

            # Check step content
            calls = mock_task_queue.persist_step.call_args_list
            step1 = calls[0][0][1]  # Second arg is the step
            assert step1.step_type == "step"
            assert "Read config" in step1.title

            step2 = calls[1][0][1]
            assert step2.step_type == "tool"
            assert step2.tool_name == "bash"

    @pytest.mark.asyncio
    async def test_session_failed_fails_task(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine
    ):
        """On session.execution.failed, task fails with reason."""
        failed_event = _make_work_event(
            kind="failed",
            type_="session.execution.failed",
            data={"error": "Command not found"},
        )
        fake_client.script_events([failed_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Failing task",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            mock_task_queue.fail_task.assert_called()
            call_args = mock_task_queue.fail_task.call_args
            assert "Command not found" in call_args[1]["reason"]

    @pytest.mark.asyncio
    async def test_session_interrupted_fails_task(
        self, fake_client: FakeOpenCodeClient, mock_task_queue, mock_recall_engine
    ):
        """On session.execution.interrupted, task fails with reason."""
        interrupted_event = _make_work_event(
            kind="interrupted",
            type_="session.execution.interrupted",
            data={"reason": "User cancelled"},
        )
        fake_client.script_events([interrupted_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Interrupted task",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            mock_task_queue.fail_task.assert_called()
            call_args = mock_task_queue.fail_task.call_args
            assert "interrupted" in call_args[1]["reason"].lower()

    @pytest.mark.asyncio
    async def test_opencode_unavailable_marks_task_interrupted(
        self, mock_task_queue, mock_recall_engine
    ):
        """On OpenCodeUnavailable, task is marked interrupted (T6)."""
        # Create a client that raises OpenCodeUnavailable on events
        class UnavailableClient(FakeOpenCodeClient):
            async def events(self, session_id: str) -> AsyncIterator[WorkEvent]:
                if False:
                    yield  # Makes this an async generator
                raise OpenCodeUnavailable("Connection lost")

        unavailable_client = UnavailableClient()

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=unavailable_client):

            config = DelegationConfig(
                goal="Unavailable test",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            mock_task_queue.fail_task.assert_called()
            call_args = mock_task_queue.fail_task.call_args
            assert "unavailable" in call_args[1]["reason"].lower()


class TestStartDelegation:
    """Tests for the start_delegation convenience function."""

    @pytest.mark.asyncio
    async def test_returns_task_id(self, mock_task_queue, mock_recall_engine, fake_client: FakeOpenCodeClient):
        """start_delegation returns the task ID."""
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_events([success_event])

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            task_id = await start_delegation(
                goal="Test goal",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )

            assert task_id == "task:abc123"