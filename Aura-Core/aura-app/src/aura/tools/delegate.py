"""delegate_work tool — delegate a task to an OpenCode agent.

This tool allows the owner to delegate work to one of three OpenCode agents:
- aura-explore: read-only exploration agent
- aura-build: build agent with edit and shell access
- aura-review: code review agent with read access and test command permission
"""

import logging
from typing import Any, Dict

from aura.config import settings

logger = logging.getLogger(__name__)

# Agent enum - must match the three agents in opencode_agents.py
VALID_AGENTS = ("aura-explore", "aura-build", "aura-review")


TOOL_DEFINITION = {
    "name": "delegate_work",
    "description": (
        "Delegate a task to an OpenCode agent. The task runs in the background; "
        "this tool returns immediately with the task ID."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "goal": {
                "type": "string",
                "description": "Natural-language description of the goal for the delegated agent.",
            },
            "workspace": {
                "type": "string",
                "description": "Workspace name (must be registered in settings.workspaces).",
            },
            "agent": {
                "type": "string",
                "enum": list(VALID_AGENTS),
                "description": "The OpenCode agent to use: aura-explore (read-only), aura-build (edit+shell), or aura-review (read+test).",
            },
            "success_criteria": {
                "type": "string",
                "description": "How to judge whether the delegation succeeded.",
            },
            "budget": {
                "type": "object",
                "description": "Optional resource budget. Both fields are optional and default to config values.",
                "properties": {
                    "tokens": {
                        "type": "integer",
                        "description": "Maximum tokens the delegated session may use.",
                        "minimum": 1000,
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Maximum wall-clock minutes for the delegated session.",
                        "minimum": 1,
                        "maximum": 1440,
                    },
                },
                "additionalProperties": False,
            },
            "skill": {
                "type": "string",
                "description": "Optional skill name to record (skills are G5; this is recorded only).",
            },
        },
        "required": ["goal", "workspace", "agent", "success_criteria"],
    },
}


def _overlay_text(session: Any) -> str | None:
    """The session's identity overlay as short text for the brief, or None."""
    overlay = getattr(session, "identity_overlay", None)
    if overlay is None:
        return None
    lines: list[str] = []
    if overlay.narrative_suffix:
        lines.append(overlay.narrative_suffix)
    if overlay.core_values:
        lines.append("Values: " + ", ".join(f"{k} {v}" for k, v in overlay.core_values.items()))
    if overlay.capabilities:
        lines.append("Capabilities: " + ", ".join(overlay.capabilities))
    if overlay.relevant_preferences:
        lines.append("Preferences: " + ", ".join(f"{k}={v}" for k, v in overlay.relevant_preferences.items()))
    return "\n".join(lines) or None


async def run(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Delegate work to an OpenCode agent.

    Returns immediately with the task ID and "started" status.
    The actual delegation runs in the background.
    """
    # Check if delegation is enabled
    if not settings.delegation_enabled:
        logger.info("delegate_work called but delegation is disabled")
        return {
            "status": "DISABLED",
            "message": "Delegation is turned off. Set AURA_DELEGATION_ENABLED=true to enable.",
            "success": False,
        }

    # Session scope (G4-04a). The executor sets `_session` and strips any
    # model-supplied one, so the model cannot forge it.
    session = arguments.get("_session")
    if session is not None:
        allowed, reason = session.is_tool_allowed("delegate_work")
        if not allowed:
            return {"status": "ERROR", "message": reason, "success": False}

    # Pause-all (G4-01): refuse new delegations; running sessions continue
    from aura.executor.delegation import delegations_paused

    if delegations_paused():
        return {
            "status": "ERROR",
            "message": "Delegations are paused. No new delegation was started.",
            "paused": True,
            "success": False,
        }

    # Validate arguments
    goal = arguments.get("goal", "").strip()
    workspace = arguments.get("workspace", "").strip()
    agent = arguments.get("agent", "").strip()
    success_criteria = arguments.get("success_criteria", "").strip()
    budget = arguments.get("budget") or {}
    skill = arguments.get("skill", "").strip() or None

    if not goal:
        return {
            "status": "ERROR",
            "message": "Goal is required and cannot be empty.",
            "success": False,
        }
    if not workspace:
        return {
            "status": "ERROR",
            "message": "Workspace is required and cannot be empty.",
            "success": False,
        }
    if agent not in VALID_AGENTS:
        return {
            "status": "ERROR",
            "message": f"Invalid agent '{agent}'. Must be one of: {', '.join(VALID_AGENTS)}",
            "success": False,
        }
    if not success_criteria:
        return {
            "status": "ERROR",
            "message": "Success criteria is required and cannot be empty.",
            "success": False,
        }

    # Apply config defaults for budget
    tokens = budget.get("tokens") if isinstance(budget.get("tokens"), int) else None
    minutes = budget.get("minutes") if isinstance(budget.get("minutes"), int) else None

    if tokens is None:
        tokens = settings.delegation_default_tokens
    if minutes is None:
        minutes = settings.delegation_default_minutes

    # Validate budget values
    if tokens < 1000:
        return {
            "status": "ERROR",
            "message": "Token budget must be at least 1000.",
            "success": False,
        }
    if minutes < 1 or minutes > 1440:
        return {
            "status": "ERROR",
            "message": "Minute budget must be between 1 and 1440.",
            "success": False,
        }

    # G5-04: with skills on, a skill name resolves to a live version whose body goes
    # in the brief. Flags off: the name stays a recorded text blob, as before.
    skill_ref = None
    if skill and settings.skills_v2_enabled and settings.skill_attribution_enabled:
        from aura.engines.learning.skill_stats import resolve_live_skill

        live = await resolve_live_skill(skill)
        if live is None:
            return {
                "status": "ERROR",
                "message": f"Skill '{skill}' has no live version.",
                "success": False,
            }
        skill_ref, skill = (live[0], live[1]), live[2]

    # Import here to avoid circular imports
    from aura.executor.delegation import start_delegation

    # Start the delegation in the background
    task_id = await start_delegation(
        goal=goal,
        workspace=workspace,
        agent=agent,
        success_criteria=success_criteria,
        tokens=tokens,
        minutes=minutes,
        skill=skill,
        identity_overlay=_overlay_text(session),
        skill_ref=skill_ref,
        requester_role=arguments.get("_requester_role") or "guest",
    )

    logger.info(f"Delegation started: task={task_id}, agent={agent}, workspace={workspace}")

    return {
        "status": "STARTED",
        "message": f"Delegation started. Task ID: {task_id}",
        "task_id": task_id,
        "success": True,
    }