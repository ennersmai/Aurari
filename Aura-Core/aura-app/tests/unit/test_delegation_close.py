"""Tests for delegation close/review logic (W3-33)."""

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.clock import FakeClock, get_clock, set_clock
from aura.config import settings
from aura.connections.opencode_client import OpenCodeClient, OpenCodeUnavailable, WorkEvent, WorkResult
from aura.executor.decisions import DecisionService, get_decision_service, set_decision_service
from aura.executor.delegation import DelegationConfig, DelegationRunner
from aura.executor.task_queue import TaskQueueService
from aura.models.task import Task, TaskStatus, TaskStepRecord


# ---------------------------------------------------------------------------
# Fake OpenCode Client for Review Tests
# ---------------------------------------------------------------------------

class FakeOpenCodeClientWithReview:
    """Fake OpenCodeClient that scripts events for both delegation and review sessions."""

    def __init__(self) -> None:
        self._delegation_events: List[WorkEvent] = []
        self._review_events: List[WorkEvent] = []
        self._delegation_index = 0
        self._review_index = 0
        self._permissions_answered: dict[str, bool] = {}
        self._aborted = False
        self._session_id: Optional[str] = None
        self._started = False
        self._last_prompt = ""
        self._review_session_created = False
        self._review_session_id: Optional[str] = None

    def script_delegation_events(self, events: List[WorkEvent]) -> None:
        """Set the events for the delegation session."""
        self._delegation_events = events
        self._delegation_index = 0

    def script_review_events(self, events: List[WorkEvent]) -> None:
        """Set the events for the review session."""
        self._review_events = events
        self._review_index = 0

    async def ensure_running(self) -> Any:
        return MagicMock(base_url="http://fake", auth=None, version="2.3.2")

    async def create_session(
        self, workspace: Any, agent: str, title: str
    ) -> str:
        self._session_id = "session:fake123"
        if agent == "aura-review":
            self._review_session_created = True
            self._review_session_id = "session:review456"
            return self._review_session_id
        return self._session_id

    async def send(self, session_id: str, prompt: str) -> None:
        self._started = True
        self._last_prompt = prompt

    async def events(self, session_id: str) -> AsyncIterator[WorkEvent]:
        # Determine which event list to use based on session
        if session_id == "session:review456" or (self._review_session_created and session_id != "session:fake123"):
            # Review session events
            while self._review_index < len(self._review_events):
                yield self._review_events[self._review_index]
                self._review_index += 1
                await asyncio.sleep(0)
        else:
            # Delegation session events
            while self._delegation_index < len(self._delegation_events):
                yield self._delegation_events[self._delegation_index]
                self._delegation_index += 1
                await asyncio.sleep(0)

    async def pending_permissions(self, session_id: str) -> List[Any]:
        return []

    async def answer_permission(
        self, session_id: str, request_id: str, allow: bool
    ) -> None:
        self._permissions_answered[request_id] = allow

    async def abort(self, session_id: str) -> None:
        self._aborted = True

    async def result(self, session_id: str) -> Any:
        if session_id == "session:review456" or (self._review_session_created and session_id != "session:fake123"):
            # Review session result - return summary with verdict
            return MagicMock(
                session_id=session_id,
                summary=getattr(self, '_review_summary', "VERDICT: PASS"),
                files_changed=[],
                additions=0,
                deletions=0,
            )
        else:
            # Delegation session result
            return MagicMock(
                session_id=session_id,
                summary=getattr(self, '_delegation_summary', "Done"),
                files_changed=getattr(self, '_files_changed', ["file1.py", "file2.py"]),
                additions=getattr(self, '_additions', 10),
                deletions=getattr(self, '_deletions', 5),
            )

    def set_delegation_result(self, summary: str, files_changed: List[str], additions: int, deletions: int) -> None:
        """Set the delegation session result."""
        self._delegation_summary = summary
        self._files_changed = files_changed
        self._additions = additions
        self._deletions = deletions

    def set_review_summary(self, summary: str) -> None:
        """Set the review session summary (with verdict)."""
        self._review_summary = summary

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
    set_clock(previous)


@pytest.fixture(autouse=True)
def mock_workspaces(monkeypatch):
    """Mock workspaces setting and workspace path resolution."""
    monkeypatch.setattr(settings, "workspaces", {"test": "/fake/workspace"})
    from aura.executor import delegation
    async def mock_resolve(self):
        from pathlib import Path
        return Path("/fake/workspace")
    monkeypatch.setattr(delegation.DelegationRunner, "_resolve_workspace_path", mock_resolve)
    from aura.executor import policy
    def mock_workspace_path(name: str):
        if name == "test":
            from pathlib import Path
            return Path("/fake/workspace")
        return None
    monkeypatch.setattr(policy, "workspace_path", mock_workspace_path)


@pytest.fixture
def fake_client() -> FakeOpenCodeClientWithReview:
    return FakeOpenCodeClientWithReview()


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
# Tests for W3-33: Review, closing, and memory
# ---------------------------------------------------------------------------

class TestDelegationClose:
    """Tests for the delegation close/review logic."""

    @pytest.mark.asyncio
    async def test_no_changed_files_skips_review_closes_succeeded(
        self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine
    ):
        """No changed files: skip review, close as succeeded."""
        # Delegation succeeds with no file changes
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_delegation_events([success_event])
        fake_client.set_delegation_result("Done", [], 0, 0)

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Test goal",
                workspace="test",
                agent="aura-build",
                success_criteria="Done",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.1)

            # Should NOT create a review session
            assert fake_client._review_session_created is False

            # Task should be marked COMPLETE
            mock_task_queue.db.merge.assert_called()
            # Find the merge call that sets status
            merge_calls = mock_task_queue.db.merge.call_args_list
            status_set = False
            for call in merge_calls:
                args, kwargs = call
                if len(args) > 1 and isinstance(args[1], dict) and args[1].get("status") == TaskStatus.COMPLETE.value:
                    status_set = True
                    break
            assert status_set, "Task status should be set to COMPLETE"

            # fail_task should NOT be called
            mock_task_queue.fail_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_changed_files_pass_verdict_closes_succeeded(
        self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine
    ):
        """Changed files + PASS verdict: close as succeeded."""
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_delegation_events([success_event])
        fake_client.set_delegation_result("Done", ["file1.py", "file2.py"], 10, 5)

        # Review session succeeds with PASS verdict
        review_success = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_review_events([review_success])
        fake_client.set_review_summary("Review complete. VERDICT: PASS")

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
            await runner.run()
            await asyncio.sleep(0.2)  # Allow time for review session

            # Should create a review session
            assert fake_client._review_session_created is True

            # Task should be marked COMPLETE
            merge_calls = mock_task_queue.db.merge.call_args_list
            status_set = False
            for call in merge_calls:
                args, kwargs = call
                if len(args) > 1 and isinstance(args[1], dict) and args[1].get("status") == TaskStatus.COMPLETE.value:
                    status_set = True
                    break
            assert status_set, "Task status should be set to COMPLETE"

    @pytest.mark.asyncio
    async def test_changed_files_fail_verdict_closes_failed_with_reason(
        self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine
    ):
        """Changed files + FAIL verdict: close as failed with reason."""
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_delegation_events([success_event])
        fake_client.set_delegation_result("Done", ["file1.py"], 5, 2)

        # Review session fails with FAIL verdict
        review_success = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_review_events([review_success])
        fake_client.set_review_summary("Work does not meet criteria. VERDICT: FAIL: Missing tests")

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
             patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

            config = DelegationConfig(
                goal="Build a login page",
                workspace="test",
                agent="aura-build",
                success_criteria="Login page works with tests",
                tokens=200000,
                minutes=30,
            )
            runner = DelegationRunner(config)
            await runner.run()
            await asyncio.sleep(0.2)

            # Should create a review session
            assert fake_client._review_session_created is True

            # Task should be failed with the reason
            mock_task_queue.fail_task.assert_called()
            call_args = mock_task_queue.fail_task.call_args
            assert "Missing tests" in call_args[1]["reason"]

    @pytest.mark.asyncio
    async def test_changed_files_no_verdict_closes_needs_owner(
        self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine
    ):
        """Changed files + no verdict: close as needs_owner."""
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_delegation_events([success_event])
        fake_client.set_delegation_result("Done", ["file1.py"], 5, 2)

        # Review session succeeds but no verdict in summary
        review_success = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_review_events([review_success])
        fake_client.set_review_summary("The work looks good overall.")

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
            await runner.run()
            await asyncio.sleep(0.2)

            # Task should be marked NEEDS_OWNER
            merge_calls = mock_task_queue.db.merge.call_args_list
            status_set = False
            for call in merge_calls:
                args, kwargs = call
                if len(args) > 1 and isinstance(args[1], dict) and args[1].get("status") == TaskStatus.NEEDS_OWNER.value:
                    status_set = True
                    break
            assert status_set, "Task status should be set to NEEDS_OWNER"

            # blocker should be set
            blocker_set = False
            for call in merge_calls:
                args, kwargs = call
                if len(args) > 1 and isinstance(args[1], dict) and "blocker" in args[1]:
                    blocker_set = True
                    break
            assert blocker_set, "Blocker should be set for NEEDS_OWNER"

    @pytest.mark.asyncio
    async def test_review_session_failed_closes_needs_owner(
        self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine
    ):
        """Review session fails: close as needs_owner."""
        success_event = _make_work_event(
            kind="succeeded",
            type_="session.execution.succeeded",
            data={},
        )
        fake_client.script_delegation_events([success_event])
        fake_client.set_delegation_result("Done", ["file1.py"], 5, 2)

        # Review session fails
        review_failed = _make_work_event(
            kind="failed",
            type_="session.execution.failed",
            data={"error": "Review agent crashed"},
        )
        fake_client.script_review_events([review_failed])

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
            await runner.run()
            await asyncio.sleep(0.2)

            # Task should be marked NEEDS_OWNER
            merge_calls = mock_task_queue.db.merge.call_args_list
            status_set = False
            for call in merge_calls:
                args, kwargs = call
                if len(args) > 1 and isinstance(args[1], dict) and args[1].get("status") == TaskStatus.NEEDS_OWNER.value:
                    status_set = True
                    break
            assert status_set, "Task status should be set to NEEDS_OWNER"

    @pytest.mark.asyncio
    async def test_parse_verdict_pass(self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine):
        """Test _parse_verdict correctly parses PASS."""
        runner = DelegationRunner(DelegationConfig(
            goal="Test", workspace="test", agent="aura-build", success_criteria="Done", tokens=1000, minutes=10
        ))
        verdict, reason = runner._parse_verdict("All good. VERDICT: PASS")
        assert verdict == "PASS"
        assert reason == ""

    @pytest.mark.asyncio
    async def test_parse_verdict_fail_with_reason(self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine):
        """Test _parse_verdict correctly parses FAIL with reason."""
        runner = DelegationRunner(DelegationConfig(
            goal="Test", workspace="test", agent="aura-build", success_criteria="Done", tokens=1000, minutes=10
        ))
        verdict, reason = runner._parse_verdict("Issues found. VERDICT: FAIL: Missing error handling")
        assert verdict == "FAIL"
        assert reason == "Missing error handling"

    @pytest.mark.asyncio
    async def test_parse_verdict_fail_no_reason(self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine):
        """Test _parse_verdict correctly parses FAIL without reason."""
        runner = DelegationRunner(DelegationConfig(
            goal="Test", workspace="test", agent="aura-build", success_criteria="Done", tokens=1000, minutes=10
        ))
        verdict, reason = runner._parse_verdict("Failed. VERDICT: FAIL:")
        assert verdict == "FAIL"
        assert reason == "No reason provided"

    @pytest.mark.asyncio
    async def test_parse_verdict_none(self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine):
        """Test _parse_verdict returns needs_owner when no verdict."""
        runner = DelegationRunner(DelegationConfig(
            goal="Test", workspace="test", agent="aura-build", success_criteria="Done", tokens=1000, minutes=10
        ))
        verdict, reason = runner._parse_verdict("Looks good but no verdict line.")
        assert verdict == "needs_owner"
        assert "No verdict" in reason

    @pytest.mark.asyncio
    async def test_parse_verdict_empty(self, fake_client: FakeOpenCodeClientWithReview, mock_task_queue, mock_recall_engine):
        """Test _parse_verdict returns needs_owner for empty summary."""
        runner = DelegationRunner(DelegationConfig(
            goal="Test", workspace="test", agent="aura-build", success_criteria="Done", tokens=1000, minutes=10
        ))
        verdict, reason = runner._parse_verdict("")
        assert verdict == "needs_owner"
        assert "Empty" in reason