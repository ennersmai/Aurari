"""Task models for Aura's persistent task engine.

A Task is a long-running job that survives Docker restarts, browser closes,
and sleep cycles.  Every step is persisted to SurrealDB immediately so that
if Docker crashes mid-step the task can resume cleanly.

Tasks carry their own memory namespace so Aura's internal reasoning
("I tried FastAPI and hit a circular import, switched to Flask") stays
scoped to the task and doesn't pollute global memory.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from aura.models.base import BaseModel


class TaskStatus(str, Enum):
    """Lifecycle states of a task."""
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETE = "complete"
    FAILED = "failed"


class EmotionalSnapshot(BaseModel):
    """Frozen emotional state at a single point in time."""

    dominant_emotion: str = "neutral"
    valence: float = 0.0
    arousal: float = 0.0
    top_emotions: dict[str, float] = Field(default_factory=dict)


class BlockerInfo(BaseModel):
    """Structured escalation data when Aura gets stuck."""

    type: Literal["repeated_failure", "reasoning_loop", "step_limit", "manual"] = "manual"
    tool: str | None = None
    attempts: int = 0
    last_error: str = ""
    last_reasoning: str = ""
    suggested_action: str = ""


class TaskStepRecord(BaseModel):
    """A single persisted step inside a task's execution history."""

    step_number: int
    step_type: str                          # mirrors AgentStepType values
    title: str
    detail: str = ""
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    result: str | None = None
    success: bool = True
    duration_ms: int = 0
    timestamp: float = Field(default_factory=lambda: datetime.utcnow().timestamp())
    emotional_state_snapshot: EmotionalSnapshot | None = Field(
        default=None,
        description="Emotional state frozen at step creation time",
    )
    active_file: str | None = Field(
        default=None,
        description="File path that was active/written at this step",
    )


class Task(BaseModel):
    """Persistent task record stored in SurrealDB."""

    task_id: str = Field(..., description="Unique task identifier (e.g. task:abc123)")
    goal: str = Field(..., description="Natural-language goal description")
    status: TaskStatus = Field(default=TaskStatus.QUEUED)

    # Execution progress
    current_step_index: int = Field(default=0)
    steps: list[TaskStepRecord] = Field(default_factory=list)

    # Workspace
    workspace_path: str = Field(default="", description="Working directory for this task")

    # Session scope (V1PRD §4). Defaults to "main" for backward compatibility.
    session_id: str = Field(
        default="main",
        description="Session this task is scoped to. 'main' for the default session.",
    )

    # Memory isolation
    task_memory_namespace: str = Field(
        default="",
        description="Namespace tag so task memories are scoped separately from global",
    )

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    # Emotional tracking
    resonance_scores: list[float] = Field(
        default_factory=list,
        description="Resonance score snapshots across the task lifetime",
    )

    # Approval gate
    blocker: str | None = Field(
        default=None,
        description="Human-readable description of what Aura is waiting on",
    )
    blocker_info: BlockerInfo | None = Field(
        default=None,
        description="Structured escalation data for frontend rendering",
    )

    # File annotations: path -> list of memory-backed notes
    file_annotations: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="Per-file annotations from Aura's reasoning (stored in task memory)",
    )

    # File version history: path -> list of content snapshots
    file_versions: dict[str, list[dict[str, Any]]] = Field(
        default_factory=dict,
        description="Previous versions of files for diff view",
    )
