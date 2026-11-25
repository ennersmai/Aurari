"""FU-02: Delegated tasks record goal_id and tests_passed (test_pass evidence).

Tests that a delegation with goal_id whose review passes leaves a task with
goal_id and tests_passed = true, and _test_pass(db, goal_id, {}) returns that
task id; a failed review stores tests_passed = false and _test_pass returns None;
no goal_id given changes nothing (ablation).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.connections.opencode_client import OpenCodeClient, WorkEvent, WorkResult
from aura.db.query_utils import to_record_id
from aura.engines.goal import evidence
from aura.executor.delegation import DelegationConfig, DelegationRunner, _norm_id
from aura.executor.task_queue import TaskQueueService
from aura.models.task import Task, TaskStatus
from surrealdb import RecordID
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GID = "goal:g1"


async def _ensure_owner_entity(db: EmbeddedSurrealDB, embeddings: HashedBagOfWordsEmbeddings) -> None:
    """Ensure the owner entity exists for fact writing."""
    from aura.engines.memory.v2.episodes import ensure_person
    await ensure_person(db, "owner", "owner")


# ---------------------------------------------------------------------------
# Fake OpenCode Client for Review Tests (from test_delegation_close.py)
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
        self._delegation_summary = "Done"
        self._files_changed = ["file1.py"]
        self._additions = 10
        self._deletions = 5
        self._review_summary = "VERDICT: PASS"

    def script_delegation_events(self, events: List[WorkEvent]) -> None:
        """Set the events for the delegation session."""
        self._delegation_events = events
        self._delegation_index = 0

    def script_review_events(self, events: List[WorkEvent]) -> None:
        """Set the events for the review session."""
        self._review_events = events
        self._review_index = 0

    def set_delegation_result(self, summary: str, files_changed: List[str], additions: int, deletions: int) -> None:
        """Set the delegation session result."""
        self._delegation_summary = summary
        self._files_changed = files_changed
        self._additions = additions
        self._deletions = deletions

    def set_review_summary(self, summary: str) -> None:
        """Set the review session summary (with verdict)."""
        self._review_summary = summary

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

    async def close(self) -> None:
        pass


def _make_work_event(kind: str, type_: str, data: dict) -> WorkEvent:
    return WorkEvent(kind=kind, session_id="session:fake123", type=type_, data=data)


@pytest.fixture
async def db():
    """Provide an EmbeddedSurrealDB with real schema applied."""
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        yield d
    finally:
        set_clock(Clock())
        await d.close()


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
def mock_recall_engine() -> MagicMock:
    """Create a mock RecallEngine."""
    from aura.engines.recall.models import Block, ContextPacket, RecallTrace

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


@pytest.fixture
def fake_client() -> FakeOpenCodeClientWithReview:
    return FakeOpenCodeClientWithReview()


@pytest.fixture(autouse=True)
def mock_llm_client():
    """Mock the LLM client used for blocker suggestions."""
    with patch("aura.executor.delegation._get_llm_client", return_value=MagicMock()):
        yield


@pytest.mark.asyncio
async def test_delegation_with_goal_id_review_pass_sets_tests_passed_true(
    db, fake_client, mock_workspaces, mock_recall_engine, mock_llm_client
):
    """A delegation with goal_id whose review passes leaves a task with
    goal_id and tests_passed = true, and _test_pass returns that task id."""
    embeddings = HashedBagOfWordsEmbeddings()
    await _ensure_owner_entity(db, embeddings)

    # Create a goal record
    await db.query(
        "CREATE $rid CONTENT $row",
        {
            "rid": to_record_id(GID),
            "row": {
                "name": "Test Goal",
                "description": "A test goal",
                "goal_type": "creative",
                "origin": "test",
                "created": _START,
                "updated": _START,
                "criteria": [],
            },
        },
    )

    # Create a DelegationConfig with goal_id
    config = DelegationConfig(
        goal="Test delegation goal",
        workspace="test",
        agent="aura-build",
        success_criteria="Tests pass",
        tokens=10000,
        minutes=30,
        goal_id=GID,
    )

    # Create a runner
    runner = DelegationRunner(config)

    # Delegation succeeds with files changed
    success_event = _make_work_event(
        kind="succeeded",
        type_="session.execution.succeeded",
        data={},
    )
    fake_client.script_delegation_events([success_event])
    fake_client.set_delegation_result("Done", ["file1.py"], 10, 5)

    # Review session succeeds with PASS verdict
    review_success = _make_work_event(
        kind="succeeded",
        type_="session.execution.succeeded",
        data={},
    )
    fake_client.script_review_events([review_success])
    fake_client.set_review_summary("Review complete. VERDICT: PASS")

    # Use real TaskQueueService with embedded DB
    task_queue = TaskQueueService()
    task_queue.db = db

    with patch("aura.executor.delegation.get_task_queue", return_value=task_queue), \
         patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
         patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

        runner._record_skill_use = AsyncMock()
        task_id = await runner.run()
        await runner._monitor_task  # wait for monitor to finish

    # Fetch the task from the database
    rows = await db.query("SELECT * FROM task WHERE id = $id", {"id": to_record_id(task_id)})
    assert len(rows) == 1
    task_row = rows[0]

    # Check that goal_id is stored
    assert task_row.get("goal_id") is not None
    goal_id_stored = task_row["goal_id"]
    if isinstance(goal_id_stored, RecordID):
        goal_id_str = f"{goal_id_stored.table_name}:{goal_id_stored.id}"
    else:
        goal_id_str = str(goal_id_stored)
    assert goal_id_str == GID or goal_id_str == "goal:g1"

    # Check that tests_passed is true
    assert task_row.get("tests_passed") is True

    # Check that reviewed is true
    assert task_row.get("reviewed") is True

    # Now test _test_pass - it should return the task id
    ref = await evidence._test_pass(db, GID, {})
    assert ref is not None
    assert _norm_id(ref) == _norm_id(task_id)


@pytest.mark.asyncio
async def test_delegation_with_goal_id_review_failed_sets_tests_passed_false(
    db, fake_client, mock_workspaces, mock_recall_engine, mock_llm_client
):
    """A failed review stores tests_passed = false and _test_pass returns None."""
    embeddings = HashedBagOfWordsEmbeddings()
    await _ensure_owner_entity(db, embeddings)

    # Create a goal record
    await db.query(
        "CREATE $rid CONTENT $row",
        {
            "rid": to_record_id(GID),
            "row": {
                "name": "Test Goal",
                "description": "A test goal",
                "goal_type": "creative",
                "origin": "test",
                "created": _START,
                "updated": _START,
                "criteria": [],
            },
        },
    )

    # Create a DelegationConfig with goal_id
    config = DelegationConfig(
        goal="Test delegation goal",
        workspace="test",
        agent="aura-build",
        success_criteria="Tests pass",
        tokens=10000,
        minutes=30,
        goal_id=GID,
    )

    # Create a runner
    runner = DelegationRunner(config)

    # Delegation succeeds with files changed
    success_event = _make_work_event(
        kind="succeeded",
        type_="session.execution.succeeded",
        data={},
    )
    fake_client.script_delegation_events([success_event])
    fake_client.set_delegation_result("Done", ["file1.py"], 10, 5)

    # Review session succeeds with FAIL verdict
    review_success = _make_work_event(
        kind="succeeded",
        type_="session.execution.succeeded",
        data={},
    )
    fake_client.script_review_events([review_success])
    fake_client.set_review_summary("Work does not meet criteria. VERDICT: FAIL: Missing tests")

    # Use real TaskQueueService with embedded DB
    task_queue = TaskQueueService()
    task_queue.db = db

    with patch("aura.executor.delegation.get_task_queue", return_value=task_queue), \
         patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
         patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

        runner._record_skill_use = AsyncMock()
        task_id = await runner.run()
        await runner._monitor_task  # wait for monitor to finish

    # Fetch the task from the database
    rows = await db.query("SELECT * FROM task WHERE id = $id", {"id": to_record_id(task_id)})
    assert len(rows) == 1
    task_row = rows[0]

    # Check that goal_id is stored
    assert task_row.get("goal_id") is not None

    # Check that tests_passed is false
    assert task_row.get("tests_passed") is False

    # _test_pass should return None because tests_passed is false
    ref = await evidence._test_pass(db, GID, {})
    assert ref is None


@pytest.mark.asyncio
async def test_delegation_without_goal_id_changes_nothing(
    db, fake_client, mock_workspaces, mock_recall_engine, mock_llm_client
):
    """No goal_id given changes nothing (ablation)."""
    embeddings = HashedBagOfWordsEmbeddings()
    await _ensure_owner_entity(db, embeddings)

    # Create a DelegationConfig WITHOUT goal_id
    config = DelegationConfig(
        goal="Test delegation goal",
        workspace="test",
        agent="aura-build",
        success_criteria="Tests pass",
        tokens=10000,
        minutes=30,
        # No goal_id
    )

    # Create a runner
    runner = DelegationRunner(config)

    # Delegation succeeds with NO files changed (no review)
    success_event = _make_work_event(
        kind="succeeded",
        type_="session.execution.succeeded",
        data={},
    )
    fake_client.script_delegation_events([success_event])
    fake_client.set_delegation_result("Done", [], 0, 0)

    # Use real TaskQueueService with embedded DB
    task_queue = TaskQueueService()
    task_queue.db = db

    with patch("aura.executor.delegation.get_task_queue", return_value=task_queue), \
         patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
         patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

        runner._record_skill_use = AsyncMock()
        task_id = await runner.run()
        await runner._monitor_task  # wait for monitor to finish

    # Fetch the task from the database
    rows = await db.query("SELECT * FROM task WHERE id = $id", {"id": to_record_id(task_id)})
    assert len(rows) == 1
    task_row = rows[0]

    # Check that goal_id is NOT stored (should be None or missing)
    assert task_row.get("goal_id") is None

    # Check that tests_passed is NOT stored
    assert task_row.get("tests_passed") is None or task_row.get("tests_passed") is False
    # reviewed should still be set when no files changed - actually it won't be
    # because _finalize_task is called with reviewed=False when no files changed

    # _test_pass should return None because no task has goal_id = GID and tests_passed = true
    ref = await evidence._test_pass(db, GID, {})
    assert ref is None


@pytest.mark.asyncio
async def test_run_stores_goal_id_on_task_creation(
    db, fake_client, mock_workspaces, mock_recall_engine, mock_llm_client
):
    """Test that goal_id is stored on task creation via _merge_task_fields in run()."""
    embeddings = HashedBagOfWordsEmbeddings()
    await _ensure_owner_entity(db, embeddings)

    # Create a goal record
    await db.query(
        "CREATE $rid CONTENT $row",
        {
            "rid": to_record_id(GID),
            "row": {
                "name": "Test Goal",
                "description": "A test goal",
                "goal_type": "creative",
                "origin": "test",
                "created": _START,
                "updated": _START,
                "criteria": [],
            },
        },
    )

    # Create a DelegationConfig with goal_id
    config = DelegationConfig(
        goal="Test delegation goal",
        workspace="test",
        agent="aura-build",
        success_criteria="Tests pass",
        tokens=10000,
        minutes=30,
        goal_id=GID,
    )

    # Create a runner
    runner = DelegationRunner(config)

    # Delegation succeeds with NO files changed (no review)
    success_event = _make_work_event(
        kind="succeeded",
        type_="session.execution.succeeded",
        data={},
    )
    fake_client.script_delegation_events([success_event])
    fake_client.set_delegation_result("Done", [], 0, 0)

    # Use real TaskQueueService with embedded DB
    task_queue = TaskQueueService()
    task_queue.db = db

    with patch("aura.executor.delegation.get_task_queue", return_value=task_queue), \
         patch("aura.engines.recall.engine.get_recall_engine", return_value=mock_recall_engine), \
         patch("aura.executor.delegation.OpenCodeClient", return_value=fake_client):

        runner._record_skill_use = AsyncMock()
        task_id = await runner.run()
        await runner._monitor_task  # wait for monitor to finish

    # Fetch the task from the database
    rows = await db.query("SELECT * FROM task WHERE id = $id", {"id": to_record_id(task_id)})
    assert len(rows) == 1
    task_row = rows[0]

    # Check that goal_id is stored
    assert task_row.get("goal_id") is not None
    goal_id_stored = task_row["goal_id"]
    if isinstance(goal_id_stored, RecordID):
        goal_id_str = f"{goal_id_stored.table_name}:{goal_id_stored.id}"
    else:
        goal_id_str = str(goal_id_stored)
    assert goal_id_str == GID or goal_id_str == "goal:g1"