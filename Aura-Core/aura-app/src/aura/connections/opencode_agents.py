"""
OpenCode agent definitions for Aura's managed server.

Provides the three agents (aura-explore, aura-build, aura-review) in the
Config.AgentEncoded shape as defined by the OpenCode v2.3.2 spec.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from aura.config import settings


def write_config(config_dir: Path) -> Path:
    """
    Write the OpenCode config file to <config_dir>/opencode/opencode.jsonc.

    The config contains exactly two top-level keys:
    - "provider": the sluice provider with baseURL from settings.opencode_router_base_url
    - "agents": the three Aura agent definitions from agent_definitions()

    Writes atomically (temp file then replace) and creates directories as needed.
    Returns the path to the written config file.
    """
    # Build the provider configuration
    provider_config = {
        "npm": "@ai-sdk/openai-compatible",
        "name": "Sluice",
        "options": {"baseURL": settings.opencode_router_base_url},
        "models": {
            "coder": {"name": "coder"},
            "chat": {"name": "chat"},
        },
    }

    # Get agent definitions and replace model placeholder
    definitions = agent_definitions()
    model = settings.opencode_agent_model
    for agent in definitions.values():
        if agent.get("model") == "{{opencode_agent_model}}":
            agent["model"] = model

    # Build the full config
    config = {
        "provider": provider_config,
        "agents": definitions,
    }

    # Create the config directory
    opencode_dir = config_dir / "opencode"
    opencode_dir.mkdir(parents=True, exist_ok=True)

    # Write atomically: temp file then replace
    config_path = opencode_dir / "opencode.jsonc"
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=opencode_dir,
        prefix=".opencode.jsonc.tmp.",
        suffix="",
        delete=False,
        encoding="utf-8",
    ) as f:
        json.dump(config, f, indent=2)
        temp_path = Path(f.name)

    # Atomic replace
    temp_path.replace(config_path)

    return config_path


def agent_definitions() -> dict[str, dict[str, Any]]:
    """
    Return the three Aura agents in Config.AgentEncoded format.

    Each agent has:
    - model: the model to use (from settings.opencode_agent_model)
    - system: a short prompt describing the agent's purpose
    - description: brief description for the UI
    - mode: "subagent" or "primary" as appropriate
    - permissions: Permission.Ruleset with allow/deny/ask rules
    """
    # The model will be injected from settings at runtime
    model_placeholder = "{{opencode_agent_model}}"

    return {
        "aura-explore": {
            "model": model_placeholder,
            "system": (
                "You are aura-explore, a read-only exploration agent for Aura. "
                "Your purpose is to search, read, and understand codebases without making changes. "
                "The brief is the source of truth for your task."
            ),
            "description": "Read-only exploration agent for searching and understanding code",
            "mode": "subagent",
            "permissions": [
                {"action": "read", "resource": "*", "effect": "allow"},
                {"action": "glob", "resource": "*", "effect": "allow"},
                {"action": "grep", "resource": "*", "effect": "allow"},
                {"action": "list", "resource": "*", "effect": "allow"},
                {"action": "edit", "resource": "*", "effect": "deny"},
                {"action": "write", "resource": "*", "effect": "deny"},
                {"action": "patch", "resource": "*", "effect": "deny"},
                {"action": "bash", "resource": "*", "effect": "deny"},
                {"action": "shell", "resource": "*", "effect": "deny"},
                {"action": "execute", "resource": "*", "effect": "deny"},
            ],
        },
        "aura-build": {
            "model": model_placeholder,
            "system": (
                "You are aura-build, a build and edit agent for Aura. "
                "Your purpose is to implement changes, write code, and modify files as directed. "
                "The brief is the source of truth for your task."
            ),
            "description": "Build agent with edit and shell access for implementing changes",
            "mode": "primary",
            "permissions": [
                {"action": "read", "resource": "*", "effect": "allow"},
                {"action": "glob", "resource": "*", "effect": "allow"},
                {"action": "grep", "resource": "*", "effect": "allow"},
                {"action": "list", "resource": "*", "effect": "allow"},
                {"action": "edit", "resource": "*", "effect": "allow"},
                {"action": "write", "resource": "*", "effect": "allow"},
                {"action": "patch", "resource": "*", "effect": "allow"},
                {"action": "bash", "resource": "*", "effect": "ask"},
                {"action": "shell", "resource": "*", "effect": "ask"},
                {"action": "execute", "resource": "*", "effect": "ask"},
            ],
        },
        "aura-review": {
            "model": model_placeholder,
            "system": (
                "You are aura-review, a code review agent for Aura. "
                "Your purpose is to review changes, run tests, and verify correctness. "
                "The brief is the source of truth for your task."
            ),
            "description": "Review agent with read access and test command permission",
            "mode": "subagent",
            "permissions": [
                {"action": "read", "resource": "*", "effect": "allow"},
                {"action": "glob", "resource": "*", "effect": "allow"},
                {"action": "grep", "resource": "*", "effect": "allow"},
                {"action": "list", "resource": "*", "effect": "allow"},
                {"action": "edit", "resource": "*", "effect": "deny"},
                {"action": "write", "resource": "*", "effect": "deny"},
                {"action": "patch", "resource": "*", "effect": "deny"},
                {"action": "bash", "resource": "*", "effect": "ask"},
                {"action": "shell", "resource": "*", "effect": "ask"},
                {"action": "execute", "resource": "*", "effect": "ask"},
            ],
        },
    }


def validate_agent_definitions(definitions: dict[str, dict[str, Any]]) -> list[str]:
    """
    Validate agent definitions against Config.AgentEncoded and Permission.Ruleset schemas.

    Returns a list of validation errors (empty if valid).
    """
    errors = []

    required_agent_fields = {"model", "system", "description", "mode", "permissions"}
    valid_modes = {"subagent", "primary", "all"}
    valid_effects = {"allow", "deny", "ask"}

    for agent_id, agent in definitions.items():
        # Check required fields
        missing = required_agent_fields - set(agent.keys())
        if missing:
            errors.append(f"{agent_id}: missing required fields: {missing}")

        # Check mode enum
        if "mode" in agent and agent["mode"] not in valid_modes:
            errors.append(f"{agent_id}: invalid mode '{agent['mode']}', must be one of {valid_modes}")

        # Check permissions structure
        if "permissions" in agent:
            perms = agent["permissions"]
            if not isinstance(perms, list):
                errors.append(f"{agent_id}: permissions must be a list")
            else:
                for i, rule in enumerate(perms):
                    if not isinstance(rule, dict):
                        errors.append(f"{agent_id}: permission rule {i} must be an object")
                        continue
                    rule_missing = {"action", "resource", "effect"} - set(rule.keys())
                    if rule_missing:
                        errors.append(f"{agent_id}: permission rule {i} missing fields: {rule_missing}")
                    if "effect" in rule and rule["effect"] not in valid_effects:
                        errors.append(f"{agent_id}: permission rule {i} invalid effect '{rule['effect']}', must be one of {valid_effects}")

    return errors