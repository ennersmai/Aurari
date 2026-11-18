"""Session models for Aura's multi-agent runtime.

A Session is the unit of *scope* for parallel agents. It owns:
- a memory namespace (so agents in different sessions don't pollute each other's recall),
- an optional identity overlay (so a session can be "Aura the Engineer" with weighted values),
- per-session model overrides and tool allow/deny lists.

What a session does NOT own: a private EmotionEngine. Aura's emotional
state is identity-defining and stays shared across every session by design
(see `feedback_emotion_consistency.md` in the agent's memory). The
`emotion_isolated` flag exists as an escape hatch for stress tests, never
as a default.

The MAIN session always exists and behaves identically to today's
singleton — backward compatibility for `/chat`, `/agent`, Mission Control
v1 is preserved by defaulting `session_id="main"` and
`memory_namespace="global"` everywhere.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from aura.models.base import BaseModel
from aura.models.task import EmotionalSnapshot

MAIN_SESSION_ID = "main"
GLOBAL_NAMESPACE = "global"


class SessionMode(str, Enum):
    """How the session relates to Aura's global state."""

    MAIN = "main"
    """The default session. Backed directly by global engines and `global` memory."""

    SCOPED = "scoped"
    """Independent memory namespace + optional identity overlay; persisted across restarts."""

    EPHEMERAL = "ephemeral"
    """Like SCOPED but discarded on session end. Use for one-off experiments."""


class SessionStatus(str, Enum):
    """Lifecycle states of a session."""

    QUEUED = "queued"
    ACTIVE = "active"
    PAUSED = "paused"
    ENDED = "ended"


class IdentityOverlay(BaseModel):
    """Patches applied to the base Identity when an agent in this session asks for context.

    Each field is optional. Present fields shadow the corresponding global identity
    field at *read* time only — the global Identity is never mutated.
    """

    core_values: dict[str, float] | None = Field(
        default=None,
        description="Override or weight core values, e.g. {'precision': 0.95, 'warmth': 0.4}",
    )
    relevant_preferences: dict[str, Any] | None = Field(
        default=None,
        description="Session-scoped preferences merged on top of global preferences",
    )
    capabilities: list[str] | None = Field(
        default=None,
        description="Restricted or augmented capability list",
    )
    narrative_suffix: str | None = Field(
        default=None,
        description="Extra context appended to the autobiographical narrative for this session",
    )


class Session(BaseModel):
    """A scoped runtime for parallel agents. See module docstring."""

    session_id: str = Field(..., description="Unique session ID (e.g. 'session:abc123' or 'main')")
    name: str = Field(..., description="Human-readable name, e.g. 'Research: emotion physics'")
    mode: SessionMode = Field(default=SessionMode.SCOPED)
    owner: str = Field(default="default", description="User who owns this session (single-user for v1)")
    parent_session_id: str | None = Field(
        default=None,
        description="If this session was forked/cloned from another, the parent's ID",
    )

    # Lifecycle
    status: SessionStatus = Field(default=SessionStatus.QUEUED)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    ended_at: datetime | None = None

    # Scope
    memory_namespace: str = Field(
        default=GLOBAL_NAMESPACE,
        description="Memory namespace tag. 'global' for MAIN; 'session_<short>' for SCOPED.",
    )
    emotion_isolated: bool = Field(
        default=False,
        description=(
            "If True, this session uses a snapshot-isolated EmotionEngine. "
            "**Default False — emotion is identity, kept shared across sessions.** "
            "Set True only for explicit stress tests of divergent emotional state."
        ),
    )
    identity_overlay: IdentityOverlay | None = Field(
        default=None,
        description="Optional identity patches applied at read-time only (no global mutation)",
    )

    # Routing
    model_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Per-layer model overrides, e.g. {'l3': 'anthropic/claude-3.5-sonnet'}",
    )
    tool_allowlist: list[str] | None = Field(
        default=None,
        description="If set, only these tools may be called from agents in this session",
    )
    tool_denylist: list[str] = Field(
        default_factory=list,
        description="Tools that may never be called from agents in this session",
    )
    max_concurrent_agents: int = Field(default=3, ge=1, le=16)

    # Live telemetry (rebuilt on read; not authoritative across restarts)
    active_agent_ids: list[str] = Field(default_factory=list)
    completed_task_ids: list[str] = Field(default_factory=list)
    emotion_snapshot: EmotionalSnapshot | None = Field(
        default=None,
        description="Last observed emotional snapshot from the session's perspective",
    )

    # ------------------------------------------------------------------
    # Convenience constructors
    # ------------------------------------------------------------------

    @classmethod
    def main(cls) -> "Session":
        """Construct the canonical MAIN session (singleton-equivalent)."""
        return cls(
            session_id=MAIN_SESSION_ID,
            name="Main",
            mode=SessionMode.MAIN,
            status=SessionStatus.ACTIVE,
            memory_namespace=GLOBAL_NAMESPACE,
            emotion_isolated=False,
            started_at=datetime.utcnow(),
        )

    @classmethod
    def new_scoped(
        cls,
        name: str,
        *,
        mode: SessionMode = SessionMode.SCOPED,
        owner: str = "default",
        parent_session_id: str | None = None,
        identity_overlay: IdentityOverlay | None = None,
        model_overrides: dict[str, str] | None = None,
        tool_allowlist: list[str] | None = None,
        tool_denylist: list[str] | None = None,
        max_concurrent_agents: int = 3,
    ) -> "Session":
        """Construct a new SCOPED or EPHEMERAL session with a fresh memory namespace."""
        if mode is SessionMode.MAIN:
            raise ValueError("Use Session.main() to construct the main session")
        short = uuid4().hex[:12]
        return cls(
            session_id=f"session:{short}",
            name=name,
            mode=mode,
            owner=owner,
            parent_session_id=parent_session_id,
            status=SessionStatus.QUEUED,
            memory_namespace=f"session_{short}",
            emotion_isolated=False,  # See module docstring; deliberate default.
            identity_overlay=identity_overlay,
            model_overrides=model_overrides or {},
            tool_allowlist=tool_allowlist,
            tool_denylist=tool_denylist or [],
            max_concurrent_agents=max_concurrent_agents,
        )


class SessionContext(BaseModel):
    """Lightweight runtime context passed to ToolExecutor and AgentLoop.

    Carries only what the executor needs to enforce session scope. Built
    by SessionRuntime when an agent is attached to a session.
    """

    session_id: str = Field(default=MAIN_SESSION_ID)
    memory_namespace: str = Field(default=GLOBAL_NAMESPACE)
    tool_allowlist: list[str] | None = None
    tool_denylist: list[str] = Field(default_factory=list)
    model_overrides: dict[str, str] = Field(default_factory=dict)
    identity_overlay: IdentityOverlay | None = None

    @classmethod
    def main(cls) -> "SessionContext":
        return cls()  # all defaults

    @classmethod
    def from_session(cls, session: Session) -> "SessionContext":
        return cls(
            session_id=session.session_id,
            memory_namespace=session.memory_namespace,
            tool_allowlist=session.tool_allowlist,
            tool_denylist=list(session.tool_denylist),
            model_overrides=dict(session.model_overrides),
            identity_overlay=session.identity_overlay,
        )

    def is_tool_allowed(self, tool_name: str) -> tuple[bool, str]:
        """Return (allowed, reason). Reason is empty when allowed."""
        if tool_name in self.tool_denylist:
            return False, f"tool '{tool_name}' is denylisted in session {self.session_id}"
        if self.tool_allowlist is not None and tool_name not in self.tool_allowlist:
            return False, (
                f"tool '{tool_name}' is not on the allowlist for session {self.session_id}"
            )
        return True, ""


# Re-exports for convenience
__all__ = [
    "MAIN_SESSION_ID",
    "GLOBAL_NAMESPACE",
    "IdentityOverlay",
    "Session",
    "SessionContext",
    "SessionMode",
    "SessionStatus",
]


# Type aliases used elsewhere
SessionId = str
Namespace = Literal["global"] | str
