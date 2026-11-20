"""Work models for OpenCode client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class WorkEvent:
    """A work event from the OpenCode event stream."""

    kind: Literal[
        "started",
        "step",
        "tool",
        "permission",
        "succeeded",
        "failed",
        "interrupted",
        "idle",
        "other",
    ]
    session_id: str
    type: str
    data: dict


@dataclass(frozen=True)
class PermissionRequest:
    """A pending permission request from OpenCode."""

    id: str
    session_id: str
    action: str
    resources: list[str]
    message: str


@dataclass(frozen=True)
class WorkResult:
    """The result of a completed work session."""

    session_id: str
    summary: str
    files_changed: list[str]
    additions: int
    deletions: int