"""Tests for workspace and policy decisions (W3-29)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from aura.config import Settings, settings
from aura.executor.policy import (
    Risk,
    decide,
    inside_workspace,
    risk_for_action,
    workspace_path,
)


def test_workspace_path_registered_and_exists(tmp_path: Path):
    """workspace_path returns resolved Path for registered, existing workspace."""
    ws_dir = tmp_path / "my_workspace"
    ws_dir.mkdir()

    # Patch settings.workspaces
    original = settings.workspaces
    try:
        settings.workspaces = {"my_workspace": str(ws_dir)}
        result = workspace_path("my_workspace")
        assert result == ws_dir.resolve()
    finally:
        settings.workspaces = original


def test_workspace_path_unregistered_returns_none():
    """workspace_path returns None for unregistered workspace."""
    original = settings.workspaces
    try:
        settings.workspaces = {"other": "/tmp/other"}
        assert workspace_path("my_workspace") is None
    finally:
        settings.workspaces = original


def test_workspace_path_nonexistent_returns_none(tmp_path: Path):
    """workspace_path returns None for registered but non-existent path."""
    original = settings.workspaces
    try:
        settings.workspaces = {"ghost": str(tmp_path / "does_not_exist")}
        assert workspace_path("ghost") is None
    finally:
        settings.workspaces = original


def test_workspace_path_not_a_dir_returns_none(tmp_path: Path):
    """workspace_path returns None for registered path that is a file."""
    file_path = tmp_path / "not_a_dir.txt"
    file_path.write_text("hello")

    original = settings.workspaces
    try:
        settings.workspaces = {"bad": str(file_path)}
        assert workspace_path("bad") is None
    finally:
        settings.workspaces = original


def test_inside_workspace_true_for_same_path(tmp_path: Path):
    """inside_workspace returns True when path equals workspace root."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()

    original = settings.workspaces
    try:
        settings.workspaces = {"ws": str(ws_dir)}
        assert inside_workspace(ws_dir, "ws") is True
    finally:
        settings.workspaces = original


def test_inside_workspace_true_for_subdirectory(tmp_path: Path):
    """inside_workspace returns True for paths inside workspace."""
    ws_dir = tmp_path / "ws"
    subdir = ws_dir / "sub" / "deep"
    subdir.mkdir(parents=True)

    original = settings.workspaces
    try:
        settings.workspaces = {"ws": str(ws_dir)}
        assert inside_workspace(subdir, "ws") is True
    finally:
        settings.workspaces = original


def test_inside_workspace_false_for_outside(tmp_path: Path):
    """inside_workspace returns False for paths outside workspace."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    original = settings.workspaces
    try:
        settings.workspaces = {"ws": str(ws_dir)}
        assert inside_workspace(outside, "ws") is False
    finally:
        settings.workspaces = original


def test_inside_workspace_false_for_unregistered(tmp_path: Path):
    """inside_workspace returns False for unregistered workspace."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()

    original = settings.workspaces
    try:
        settings.workspaces = {}
        assert inside_workspace(ws_dir, "ws") is False
    finally:
        settings.workspaces = original


@pytest.mark.skipif(os.name == "nt", reason="Symlinks require admin on Windows")
def test_inside_workspace_resolves_symlinks(tmp_path: Path):
    """inside_workspace resolves symlinks before checking."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    # Create a symlink inside workspace pointing outside
    link = ws_dir / "link_outside"
    link.symlink_to(real_dir)

    original = settings.workspaces
    try:
        settings.workspaces = {"ws": str(ws_dir)}
        # The symlink target is outside, so should be False
        assert inside_workspace(link, "ws") is False
    finally:
        settings.workspaces = original


def test_inside_workspace_resolves_dotdot(tmp_path: Path):
    """inside_workspace resolves '..' before checking."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    # Path with .. that escapes the workspace
    escape_path = ws_dir / "sub" / ".." / ".." / "outside"
    escape_path.parent.mkdir(parents=True, exist_ok=True)

    original = settings.workspaces
    try:
        settings.workspaces = {"ws": str(ws_dir)}
        assert inside_workspace(escape_path, "ws") is False
    finally:
        settings.workspaces = original


# --- decide() tests ---

def test_decide_every_cell_of_default_table():
    """Test every cell of the default policy table for each role."""
    # Save and restore settings
    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        # Set up a valid workspace
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.workspaces = {"ws": tmpdir}
            settings.policy_table = {
                "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
                "trusted": {"read": "allow", "write": "deny", "execute": "deny", "send": "deny"},
                "guest": {"read": "deny", "write": "deny", "execute": "deny", "send": "deny"},
            }
            settings.delegation_enabled = True

            # Owner row
            assert decide("read", "ws", "owner") == "allow"
            assert decide("write", "ws", "owner") == "allow"
            assert decide("execute", "ws", "owner") == "ask"
            assert decide("send", "ws", "owner") == "ask"

            # Trusted row
            assert decide("read", "ws", "trusted") == "allow"
            assert decide("write", "ws", "trusted") == "deny"
            assert decide("execute", "ws", "trusted") == "deny"
            assert decide("send", "ws", "trusted") == "deny"

            # Guest row
            assert decide("read", "ws", "guest") == "deny"
            assert decide("write", "ws", "guest") == "deny"
            assert decide("execute", "ws", "guest") == "deny"
            assert decide("send", "ws", "guest") == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_guest_denied_everything():
    """A guest is denied everything regardless of risk."""
    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.workspaces = {"ws": tmpdir}
            settings.policy_table = {
                "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
                "trusted": {"read": "allow", "write": "deny", "execute": "deny", "send": "deny"},
                "guest": {"read": "deny", "write": "deny", "execute": "deny", "send": "deny"},
            }
            settings.delegation_enabled = True

            for risk in ("read", "write", "execute", "send"):
                assert decide(risk, "ws", "guest") == "deny", f"guest {risk} should be deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_unregistered_workspace_denied():
    """An unregistered workspace is denied."""
    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        settings.workspaces = {}
        settings.policy_table = {
            "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
        }
        settings.delegation_enabled = True

        assert decide("read", "unknown_ws", "owner") == "deny"
        assert decide("write", "unknown_ws", "owner") == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_none_workspace_denied():
    """A None workspace is denied."""
    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.workspaces = {"ws": tmpdir}
            settings.policy_table = {
                "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
            }
            settings.delegation_enabled = True

            assert decide("read", None, "owner") == "deny"
            assert decide("write", None, "owner") == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_write_resource_outside_workspace_denied(tmp_path: Path):
    """For write, any resource outside the workspace is denied."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        settings.workspaces = {"ws": str(ws_dir)}
        settings.policy_table = {
            "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
        }
        settings.delegation_enabled = True

        # Resource inside workspace -> allowed (per table)
        assert decide("write", "ws", "owner", resources=[str(ws_dir / "file.txt")]) == "allow"

        # Resource outside workspace -> denied
        assert decide("write", "ws", "owner", resources=[str(outside_dir / "file.txt")]) == "deny"

        # Mixed resources: one outside -> denied
        assert decide(
            "write", "ws", "owner",
            resources=[str(ws_dir / "file.txt"), str(outside_dir / "file.txt")]
        ) == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_write_dotdot_outside_denied(tmp_path: Path):
    """Write with '..' resource pointing outside workspace is denied."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        settings.workspaces = {"ws": str(ws_dir)}
        settings.policy_table = {
            "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
        }
        settings.delegation_enabled = True

        # Path with .. that escapes
        escape_path = ws_dir / "sub" / ".." / ".." / "outside" / "file.txt"
        assert decide("write", "ws", "owner", resources=[str(escape_path)]) == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


@pytest.mark.skipif(os.name == "nt", reason="Symlinks require admin on Windows")
def test_decide_write_symlink_outside_denied(tmp_path: Path):
    """Write with symlink pointing outside workspace is denied."""
    ws_dir = tmp_path / "ws"
    ws_dir.mkdir()
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()

    # Create symlink inside workspace pointing outside
    link = ws_dir / "link_outside"
    link.symlink_to(outside_dir)

    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        settings.workspaces = {"ws": str(ws_dir)}
        settings.policy_table = {
            "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
        }
        settings.delegation_enabled = True

        # The symlink resolves to outside, so write should be denied
        assert decide("write", "ws", "owner", resources=[str(link / "file.txt")]) == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_unknown_role_denied():
    """Unknown role is denied."""
    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.workspaces = {"ws": tmpdir}
            settings.policy_table = {
                "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
            }
            settings.delegation_enabled = True

            assert decide("read", "ws", "unknown_role") == "deny"
            assert decide("write", "ws", "unknown_role") == "deny"
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


def test_decide_unknown_risk_denied():
    """Unknown risk is denied."""
    original_workspaces = settings.workspaces
    original_policy = settings.policy_table
    original_delegation = settings.delegation_enabled

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            settings.workspaces = {"ws": tmpdir}
            settings.policy_table = {
                "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
            }
            settings.delegation_enabled = True

            # Use a risk not in the table
            assert decide("unknown_risk", "ws", "owner") == "deny"  # type: ignore[arg-type]
    finally:
        settings.workspaces = original_workspaces
        settings.policy_table = original_policy
        settings.delegation_enabled = original_delegation


# --- risk_for_action() tests ---

def test_risk_for_action_read_actions():
    """Read-style actions map to 'read' risk."""
    read_actions = ["read", "glob", "grep", "list", "ls", "stat", "cat", "head", "tail", "view", "search", "find"]
    for action in read_actions:
        assert risk_for_action(action) == "read", f"{action} should map to read"
        # Also test case insensitivity
        assert risk_for_action(action.upper()) == "read"
        assert risk_for_action(action.capitalize()) == "read"


def test_risk_for_action_write_actions():
    """Write-style actions map to 'write' risk."""
    write_actions = ["edit", "write", "patch", "create", "delete", "mkdir", "move", "rename", "remove", "touch", "append", "replace"]
    for action in write_actions:
        assert risk_for_action(action) == "write", f"{action} should map to write"
        assert risk_for_action(action.upper()) == "write"


def test_risk_for_action_execute_actions():
    """Execute-style actions map to 'execute' risk."""
    execute_actions = ["bash", "shell", "execute", "run", "command", "python", "node", "npm", "pip", "cargo", "go", "make", "script"]
    for action in execute_actions:
        assert risk_for_action(action) == "execute", f"{action} should map to execute"
        assert risk_for_action(action.upper()) == "execute"


def test_risk_for_action_send_actions():
    """Send/network-style actions map to 'send' risk."""
    send_actions = ["webfetch", "websearch", "fetch", "http", "network", "api", "request", "post", "get", "put", "websocket", "ws"]
    for action in send_actions:
        assert risk_for_action(action) == "send", f"{action} should map to send"
        assert risk_for_action(action.upper()) == "send"


def test_risk_for_action_unknown_maps_to_execute():
    """Unknown actions map to 'execute' (strictest approvable class)."""
    assert risk_for_action("completely_unknown_action") == "execute"
    assert risk_for_action("foobar") == "execute"
    assert risk_for_action("") == "execute"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])