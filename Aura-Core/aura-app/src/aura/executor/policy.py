"""Workspace and policy decisions for delegation (G3 / W3-29).

This module implements the single decision function that every delegated
permission decision goes through (PRD rule 4).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from aura.config import settings

logger = logging.getLogger(__name__)

# Risk classes matching the tool registry and PRD 11.3
Risk = Literal["read", "write", "execute", "send"]
Decision = Literal["allow", "ask", "deny"]


def workspace_path(name: str) -> Path | None:
    """Resolve a workspace name to an absolute Path.

    The workspace must be explicitly registered in settings.workspaces,
    must exist on disk, and must be a directory. Returns None otherwise.
    """
    workspaces = settings.workspaces
    if not workspaces:
        return None

    path_str = workspaces.get(name)
    if not path_str:
        return None

    try:
        path = Path(path_str).resolve(strict=True)
    except (OSError, ValueError):
        return None

    if not path.is_dir():
        return None

    return path


def inside_workspace(path: str | Path, workspace: str) -> bool:
    """Check if a resolved path is inside (or equal to) a workspace.

    Both the input path and the workspace root are resolved (symlinks and
    '..' components resolved) before the containment check.
    """
    ws_path = workspace_path(workspace)
    if ws_path is None:
        return False

    try:
        target = Path(path).resolve(strict=False)
    except (OSError, ValueError):
        return False

    try:
        # Check if target is the workspace or a subdirectory
        target.relative_to(ws_path)
        return True
    except ValueError:
        return False


def _default_policy_table() -> dict[str, dict[str, str]]:
    """Return the default policy table per PRD 11.3 recommendation."""
    return {
        "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
        "trusted": {"read": "allow", "write": "deny", "execute": "deny", "send": "deny"},
        "guest": {"read": "deny", "write": "deny", "execute": "deny", "send": "deny"},
    }


def decide(
    risk: Risk,
    workspace: str | None,
    role: str,
    resources: list[str] = [],
) -> Decision:
    """Decide a delegated permission request.

    This is the ONE function every delegated permission decision goes through
    (PRD rule 4).

    Args:
        risk: The risk class of the action (read, write, execute, send).
        workspace: The workspace name the action targets, or None.
        role: The requester role (owner, trusted, guest).
        resources: List of resource paths the action affects.

    Returns:
        "allow", "ask", or "deny".
    """
    # Unknown role or risk -> deny
    policy_table = settings.policy_table
    if not policy_table:
        policy_table = _default_policy_table()

    role_policy = policy_table.get(role)
    if role_policy is None:
        logger.debug("decide: unknown role %r -> deny", role)
        return "deny"

    decision = role_policy.get(risk)
    if decision is None:
        logger.debug("decide: unknown risk %r for role %r -> deny", risk, role)
        return "deny"

    # Unregistered workspace -> deny
    if workspace is None:
        logger.debug("decide: no workspace -> deny")
        return "deny"

    ws_path = workspace_path(workspace)
    if ws_path is None:
        logger.debug("decide: workspace %r not registered or invalid -> deny", workspace)
        return "deny"

    # For write actions, any resource outside the workspace -> deny
    if risk == "write":
        for resource in resources:
            if not inside_workspace(resource, workspace):
                logger.debug(
                    "decide: write resource %r outside workspace %r -> deny",
                    resource,
                    workspace,
                )
                return "deny"

    return decision  # type: ignore[return-value]


def risk_for_action(action: str) -> Risk:
    """Map an OpenCode permission action to a risk class.

    Action names are taken from the OpenCode v2.3.2 permission schemas
    and examples. Unknown actions map to 'execute' (the strictest class
    that can still be approved).

    Known actions:
      - read: read, glob, grep, list, ls, stat, cat, head, tail
      - write: edit, write, patch, create, mkdir, move, rename
      - execute: bash, shell, execute, run, command, python, node
      - send: webfetch, websearch, fetch, http, network, api
    """
    action_lower = action.lower()

    # Send/network-style actions (check first to catch http verbs like post, get, put)
    if action_lower in (
        "webfetch",
        "websearch",
        "fetch",
        "http",
        "network",
        "api",
        "request",
        "post",
        "get",
        "put",
        "websocket",
        "ws",
    ):
        return "send"

    # Read-style actions
    if action_lower in (
        "read",
        "glob",
        "grep",
        "list",
        "ls",
        "stat",
        "cat",
        "head",
        "tail",
        "view",
        "search",
        "find",
    ):
        return "read"

    # Write-style actions
    if action_lower in (
        "edit",
        "write",
        "patch",
        "create",
        "delete",
        "mkdir",
        "move",
        "rename",
        "remove",
        "touch",
        "append",
        "replace",
    ):
        return "write"

    # Execute-style actions
    if action_lower in (
        "bash",
        "shell",
        "execute",
        "run",
        "command",
        "python",
        "node",
        "npm",
        "pip",
        "cargo",
        "go",
        "make",
        "script",
    ):
        return "execute"

    # Unknown action -> execute (strictest class that can still be approved)
    logger.debug("risk_for_action: unknown action %r -> execute", action)
    return "execute"