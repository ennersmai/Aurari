"""Proposal and Cost models for the behaviour workspace (B2-02, PRD 4.1)."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from aura.clock import get_clock


class ProposalKind(str, Enum):
    """The seven proposal kinds per PRD 4.1."""

    INVESTIGATE = "investigate"
    PURSUE_GOAL = "pursue_goal"
    PRACTICE = "practice"
    SHARE = "share"
    ASK_USER = "ask_user"
    CONSOLIDATE = "consolidate"
    RESPOND = "respond"


class RiskLevel(str, Enum):
    """Risk levels for proposals."""

    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEND = "send"


@dataclass
class Cost:
    """Cost of executing a proposal."""

    tokens: int = 0
    seconds: float = 0.0
    risk: RiskLevel = RiskLevel.READ

    def __post_init__(self) -> None:
        if isinstance(self.risk, str):
            self.risk = RiskLevel(self.risk)


class Proposal(BaseModel):
    """
    A proposal for autonomous work.
    
    Per PRD 4.1: source, kind (seven kinds), summary, refs, urgency, value,
    cost (tokens, seconds, risk in read|write|execute|send), expires_at, created_at, id.
    A proposal needs non-empty refs (same rule as the agenda) and a summary of one line.
    """

    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    source: str = Field(..., description="Which engine or system created this proposal")
    kind: ProposalKind = Field(..., description="Type of proposal")
    summary: str = Field(..., description="One-line summary of the proposal")
    refs: list[str] = Field(..., description="References to memories, goals, questions, etc.")
    urgency: float = Field(default=0.5, ge=0.0, le=1.0, description="Urgency score 0..1")
    value: float = Field(default=0.5, ge=0.0, le=1.0, description="Expected value score 0..1")
    cost: Cost = Field(default_factory=Cost, description="Cost of executing this proposal")
    expires_at: datetime | None = Field(default=None, description="When this proposal expires")
    created_at: datetime = Field(default_factory=lambda: get_clock().now(), description="When this proposal was created")

    @field_validator("refs", mode="before")
    @classmethod
    def _clean_refs(cls, v: list[Any]) -> list[str]:
        """Clean and validate refs - same rule as agenda: non-empty required."""
        if v is None:
            return []
        cleaned = [str(r).strip() for r in v if str(r).strip()]
        return cleaned

    @field_validator("summary")
    @classmethod
    def _validate_summary(cls, v: str) -> str:
        """Validate summary is a single line."""
        if "\n" in v or "\r" in v:
            raise ValueError("summary must be a single line")
        return v.strip()

    @field_validator("refs")
    @classmethod
    def _validate_refs_not_empty(cls, v: list[str]) -> list[str]:
        """Refs must not be empty (same rule as agenda)."""
        if not v:
            raise ValueError("proposal needs refs")
        return v

    def duplicate_key(self) -> tuple:
        """Key for duplicate detection: (source, kind, sorted refs)."""
        return (self.source, self.kind.value, tuple(sorted(self.refs)))

    def is_expired(self, now: datetime) -> bool:
        """Check if the proposal has expired."""
        if self.expires_at is None:
            return False
        return now >= self.expires_at