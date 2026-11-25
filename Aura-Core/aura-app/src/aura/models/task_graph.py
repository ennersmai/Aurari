"""Task graph models (P2-08): a plan of research / think / code nodes.

A TaskGraph is what ``plan_task`` creates; its TaskNodes run later (P2-09/10)
and write compact reports to the blackboard.
"""

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator

from aura.models.base import BaseModel

NodeKind = Literal["research", "think", "code"]
NODE_KINDS: tuple[str, ...] = ("research", "think", "code")


class GraphStatus(str, Enum):
    PLANNED = "planned"
    RUNNING = "running"
    DONE = "done"
    PARTIAL = "partial"
    FAILED = "failed"
    OVER_BUDGET = "over_budget"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"
    READY_TO_MERGE = "ready_to_merge"


class TaskNode(BaseModel):
    """One unit of work. ``id`` is the planner's local id, unique in its graph."""

    id: str = Field(min_length=1)
    graph: str = ""  # task_graph record id, set when stored
    kind: NodeKind
    brief: str = Field(min_length=1)
    success_criteria: str = Field(min_length=1)
    depends_on: list[str] = Field(default_factory=list)
    budget_share: float = Field(default=1.0, gt=0.0, le=1.0)
    status: NodeStatus = NodeStatus.PENDING
    report: str | None = None
    transcript: str | None = None  # full node transcript; never fed to other nodes or L3
    artifacts: list[str] = Field(default_factory=list)

    @field_validator("success_criteria", "brief")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class TaskGraph(BaseModel):
    id: str = ""
    goal: str = Field(min_length=1)
    status: GraphStatus = GraphStatus.PLANNED
    budget_usd: float = Field(default=0.0, ge=0.0)
    budget_minutes: int = Field(default=0, ge=0)
    spent_usd: float = Field(default=0.0, ge=0.0)
    created_by_turn: str | None = None
    conversation_id: str | None = None  # where this graph reports (P2-11)
    origin: str | None = None  # "autonomous" when Aura started it herself (P2-33)
    final_reported_at: datetime | None = None  # guard: the final summary is posted once
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BlackboardEntry(BaseModel):
    graph: str
    node: str | None = None  # task_node record id, or None for graph-level entries
    kind: str = Field(min_length=1)
    content: str
    refs: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
