"""Goal models (Goal Engine)."""

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import Field

from aura.models.base import BaseModel


# Criterion kinds deliberately match the P2-32 evidence kinds (test_pass, file_exists,
# task_node_done); P2-32's ``mai_confirms`` maps to ``owner_confirms`` here. P2-31 and
# P2-32 add milestones on top of criteria without renaming anything.
CriterionKind = Literal[
    "test_pass", "file_exists", "question_resolved", "owner_confirms", "task_node_done"
]


class Criterion(BaseModel):
    """One checkable completion criterion of a goal."""

    id: str
    name: str
    kind: CriterionKind
    spec: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "met"] = "open"
    met_at: datetime | None = None
    evidence_ref: str | None = None


GoalStage = Literal["seed", "forming", "crystal", "active", "closed"]
STAGE_ORDER: dict[str, int] = {"seed": 0, "forming": 1, "crystal": 2, "active": 3, "closed": 4}
GoalOwner = Literal["mai", "aura", "shared"]
OriginKind = Literal["mai_said", "aura_curiosity", "aura_drive", "parent", "extraction"]
# The five items a goal needs before it can crystallize.
CHECKLIST_FIELDS = ("outcome", "done_criteria", "owner", "horizon", "first_action")


class Milestone(BaseModel):
    """One milestone of an active goal (P2-32 fills these). ``evidence_spec`` reuses the
    criterion kinds and spec shapes of B3 (see ``Criterion``)."""

    name: str
    evidence_spec: dict[str, Any] = Field(default_factory=dict)
    status: Literal["open", "done"] = "open"
    evidence_refs: list[str] = Field(default_factory=list)


class Goal(BaseModel):
    """
    Goal node with hierarchical structure.

    Based on PRD Section 5.1.
    """

    goal_id: str
    name: str
    description: str
    goal_type: Literal[
        "curiosity_driven",
        "user_requested",
        "maintenance",
        "learning_gap",
        "creative",
        "self_improvement",  # P2-33: graphs only on Mai's registered Aura workspace (D16)
    ]
    status: Literal["active", "completed", "cancelled", "paused", "abandoned"] = "active"
    priority: float = Field(default=0.5, ge=0.0, le=1.0)

    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed: datetime | None = None

    # Hierarchy
    parent_goal_id: str | None = None
    sub_goal_ids: list[str] = Field(default_factory=list)

    # Progress
    progress: float = Field(default=0.0, ge=0.0, le=1.0)

    # Emotional alignment
    emotional_alignment: dict[str, float] = Field(
        default_factory=dict, description="Which emotions drive this goal"
    )

    # Origin
    origin: str = Field(..., description="How this goal was formed")

    # Metadata
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Goals v2 (B3-01). All optional: legacy rows read as None and behave as before.
    criteria: list[dict[str, Any]] | None = None  # Criterion dumps
    abandon_reason: str | None = None
    last_evidence_at: datetime | None = None
    evidence: list[dict[str, Any]] | None = None

    # Goals v3 (P2-31). The legacy ``origin`` string stays; ``origin_link`` is the typed
    # {kind, ref} lineage. All optional so legacy rows load; ``stage`` is stored.
    stage: GoalStage = "seed"
    stage_changed: datetime | None = None
    outcome: str | None = None
    done_criteria: list[str] | None = None
    owner: GoalOwner | None = None
    horizon: str | None = None
    first_action: str | None = None
    origin_link: dict[str, Any] | None = None
    milestones: list[dict[str, Any]] | None = None
    close_reason: str | None = None
    # P2-32 (all stored, so they survive a restart)
    proposed: dict[str, Any] | None = None  # outcome / done_criteria L3 proposed on Mai's goal
    outcome_changed_at: datetime | None = None  # Mai changed a crystal outcome: only an explicit refine re-crystallizes
    plan_requested_at: datetime | None = None  # last Sage milestone-plan call
    swift_checked_at: datetime | None = None  # last Swift call about this goal
    orphan_flagged_at: datetime | None = None  # orphan flag raised (once)
    conflict_flags: list[str] | None = None  # goal ids this goal was flagged against (once)
    conflict_checked: list[str] | None = None  # goal ids already compared by Swift

    def crystallization(self) -> dict[str, Any]:
        """The crystal checklist: per item whether it is filled, and what is missing.

        ``done_criteria`` also counts as filled when the goal has B3 ``criteria``
        (those are checkable by construction).
        """
        filled = {
            "outcome": bool(self.outcome and self.outcome.strip()),
            "done_criteria": bool(
                [d for d in (self.done_criteria or []) if d and d.strip()] or self.criteria
            ),
            "owner": self.owner is not None,
            "horizon": bool(self.horizon and self.horizon.strip()),
            "first_action": bool(self.first_action and self.first_action.strip()),
        }
        missing = [f for f in CHECKLIST_FIELDS if not filled[f]]
        return {"stage": self.stage, "items": filled, "missing": missing, "complete": not missing}

    def progress_from_criteria(self) -> float | None:
        """Met criteria over total, or None when the goal has no criteria."""
        if not self.criteria:
            return None
        met = sum(1 for c in self.criteria if c.get("status") == "met")
        return met / len(self.criteria)


class Task(BaseModel):
    """Concrete action for a goal."""

    task_id: str
    goal_id: str
    description: str
    status: Literal["pending", "in_progress", "completed", "failed"] = "pending"
    created: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed: datetime | None = None
    result: str | None = None


class GoalContext(BaseModel):
    """Goal context for LLM injection."""

    active_goals: list[Goal] = Field(default_factory=list)
    current_focus: Goal | None = None
    pending_proposals: list[dict[str, Any]] = Field(default_factory=list)
    pursuit_suggestions: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Goals that would benefit from autonomous pursuit"
    )

