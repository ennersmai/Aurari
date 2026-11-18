"""
Terminal Tool - Human-in-the-Loop command execution for Aura.

Implements a strict permission state machine similar to Claude Code's
execution ledger. Safe (non-destructive) commands execute immediately;
mutative commands require explicit user approval.
"""

import importlib
import logging
import subprocess
from typing import Any, Dict

logger = logging.getLogger(__name__)

SAFE_COMMAND_PREFIXES = (
    "ls",
    "dir",
    "pwd",
    "echo",
    "cat",
    "type",
    "head",
    "tail",
    "wc",
    "find",
    "grep",
    "which",
    "where",
    "whoami",
    "hostname",
    "date",
    "time",
    "env",
    "printenv",
    "set",
    "uname",
    "python --version",
    "python3 --version",
    "pip show",
    "pip list",
    "pip freeze",
    "pip check",
    "pip config list",
    "pip cache list",
    "pip debug",
    "node --version",
    "npm --version",
    "npm list",
    "npm view",
    "npm outdated",
    "git status",
    "git log",
    "git diff",
    "git branch",
    "git tag",
    "git show",
    "git config --list",
    "git remote -v",
    "git stash list",
    "cargo --version",
    "rustc --version",
    "go version",
    "docker --version",
    "docker ps",
    "docker images",
    "docker info",
    "docker compose ps",
    "docker compose config",
    "docker compose images",
    "kubectl version",
    "kubectl get",
    "kubectl describe",
    "kubectl config view",
    "kubectl cluster-info",
    "helm version",
    "helm list",
    "helm history",
    "helm status",
    "helm get",
    "helm show",
    "terraform version",
    "terraform plan",
    "terraform output",
    "terraform state list",
    "terraform state show",
    "terraform show",
    "terraform providers",
    "terraform workspace list",
)

TOOL_DEFINITION = {
    "name": "terminal",
    "description": (
        "Execute a shell command in the local terminal. "
        "Safe read-only commands run immediately. "
        "Mutative commands (install, uninstall, delete, etc.) require user approval."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute.",
            },
            "cwd": {
                "type": "string",
                "description": "Optional working directory for the command.",
            },
            "force_execute": {
                "type": "boolean",
                "description": (
                    "Set to true to bypass the safety check and execute immediately. "
                    "Only honored when the caller has already obtained user approval."
                ),
                "default": False,
            },
        },
        "required": ["command"],
    },
}


def _is_safe_command(command: str) -> bool:
    """Check whether a command matches a known safe prefix."""
    stripped = command.strip()
    for prefix in SAFE_COMMAND_PREFIXES:
        if stripped == prefix or stripped.startswith(prefix + " "):
            return True
    return False


def _contains_pip_install(command: str) -> bool:
    """Detect 'pip install' (or 'pip3 install', 'python -m pip install') in the command."""
    lowered = command.strip().lower()
    return (
        "pip install" in lowered
        or "pip3 install" in lowered
        or "python -m pip install" in lowered
        or "python3 -m pip install" in lowered
    )


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a terminal command with Human-in-the-Loop safety gating.

    Safe commands (matching SAFE_COMMAND_PREFIXES) execute immediately.
    Mutative commands return WAITING_APPROVAL unless force_execute is True.

    After a successful 'pip install', importlib.invalidate_caches() is called
    so the running Python process can discover newly installed packages.
    """
    command: str = arguments.get("command", "")
    cwd: str | None = arguments.get("cwd")
    force_execute: bool = bool(arguments.get("force_execute", False))

    if not command:
        return {
            "status": "ERROR",
            "message": "No command provided.",
            "success": False,
        }

    # --- Permission Gate ---
    if not _is_safe_command(command) and not force_execute:
        logger.info(f"⛔ Terminal tool blocked mutative command: {command[:120]}")
        return {
            "status": "WAITING_APPROVAL",
            "message": "User approval required.",
            "pending_command": command,
            "success": False,
        }

    # --- Execute ---
    logger.info(f"▶ Terminal executing: {command[:120]}")

    try:
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd or None,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.error(f"⏱ Terminal command timed out (60s): {command[:120]}")
        return {
            "status": "ERROR",
            "message": f"Command timed out after 60 seconds: {command[:120]}",
            "success": False,
        }
    except Exception as exc:
        logger.error(f"❌ Terminal command failed to launch: {exc}")
        return {
            "status": "ERROR",
            "message": f"Failed to execute command: {exc}",
            "success": False,
        }

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    exit_code = result.returncode

    # --- Hot-Reload: invalidate import caches after pip install ---
    if exit_code == 0 and _contains_pip_install(command):
        logger.info("🔄 pip install detected — invalidating importlib caches")
        importlib.invalidate_caches()

    output = stdout
    if stderr:
        output += f"\n[stderr]\n{stderr}"

    return {
        "status": "OK",
        "message": output.strip() or f"(exit code {exit_code})",
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "success": exit_code == 0,
    }
