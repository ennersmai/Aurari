"""Delegation Runner — manages delegated OpenCode sessions.

This module implements the background monitoring of delegated tasks,
including event folding, permission handling, budget enforcement,
and task lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from aura.clock import get_clock
from aura.config import settings
from aura.connections.opencode_client import OpenCodeClient, OpenCodeUnavailable
from aura.connections.opencode_process import OpenCodeProcess
from aura.executor.decisions import get_decision_service
from aura.executor.policy import decide, risk_for_action
from aura.executor.task_queue import get_task_queue
from aura.models.task import Task, TaskStatus, TaskStepRecord
from aura.models.work import WorkEvent

logger = logging.getLogger(__name__)


@dataclass
class DelegationConfig:
    """Configuration for a delegation run."""

    goal: str
    workspace: str
    agent: str
    success_criteria: str
    tokens: int
    minutes: int
    skill: Optional[str] = None


class DelegationRunner:
    """Runs and monitors a single delegated OpenCode session.

    - Builds the brief from the goal, success criteria, and Recall Engine packet (agent mode)
    - Creates a task record via TaskQueueService
    - Ensures OpenCode is running, creates a session, sends the brief
    - Monitors events in a background task:
      * Folds events into task steps (persist_step)
      * Handles permission.asked via risk_for_action + decide (role=owner)
      * Tracks token usage and elapsed time, aborts on budget exceeded
      * Marks task for review on success, fails on failure/interruption
      * Handles OpenCodeUnavailable by marking task interrupted
    """

    def __init__(self, config: DelegationConfig) -> None:
        self.config = config
        self._task: Optional[Task] = None
        self._session_id: Optional[str] = None
        self._client: Optional[OpenCodeClient] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._tokens_used = 0
        self._start_time: Optional[datetime] = None

    async def run(self) -> str:
        """Start the delegation and return the task ID."""
        # 1. Build the brief
        brief = await self._build_brief()

        # 2. Create task record
        task_queue = get_task_queue()
        self._task = await task_queue.create_task(
            goal=self.config.goal,
            workspace_path=self.config.workspace,
            session_id="main",  # delegation tasks use main session for now
        )
        task_id = self._task.task_id

        # 3. Ensure OpenCode is running and create session
        self._client = await self._get_client()
        workspace_path = self._resolve_workspace_path()
        if workspace_path is None:
            await task_queue.fail_task(task_id, reason=f"Workspace '{self.config.workspace}' not registered or invalid")
            raise ValueError(f"Workspace '{self.config.workspace}' not registered or invalid")

        session_title = f"Delegation: {self.config.goal[:60]}"
        self._session_id = await self._client.create_session(
            workspace=workspace_path,
            agent=self.config.agent,
            title=session_title,
        )

        # Update task with session ID
        await task_queue.db.merge(task_id, {
            "session_id": self._session_id,
            "status": TaskStatus.RUNNING.value,
            "updated_at": get_clock().now().isoformat(),
        })

        # 4. Send the brief to start the session
        await self._client.send(self._session_id, brief)

        # 5. Start background monitoring
        self._start_time = get_clock().now()
        self._monitor_task = asyncio.create_task(self._monitor())

        return task_id

    async def _get_client(self) -> OpenCodeClient:
        """Get or create the OpenCode client."""
        if self._client is None:
            # Use managed process
            process = OpenCodeProcess()
            self._client = OpenCodeClient(process)
            # Configure decision service with this client
            decision_service = get_decision_service()
            decision_service._client = self._client
        return self._client

    def _resolve_workspace_path(self) -> Optional[Path]:
        """Resolve workspace name to absolute path."""
        workspaces = settings.workspaces
        if not workspaces:
            return None
        path_str = workspaces.get(self.config.workspace)
        if not path_str:
            return None
        try:
            return Path(path_str).resolve(strict=True)
        except (OSError, ValueError):
            return None

    async def _build_brief(self) -> str:
        """Build the brief for the delegated agent.

        Contains:
        - Goal
        - Success criteria
        - Recall Engine packet in 'agent' mode for the goal
        """
        from aura.engines.recall.engine import get_recall_engine
        from aura.engines.recall.models import RecallRequest

        # Get recall packet in agent mode
        recall_engine = get_recall_engine()
        request = RecallRequest(
            user_id="owner",
            user_input=self.config.goal,
            mode="agent",
            token_budget=self.config.tokens,
            include_cold_start=False,
            include_latent=False,
        )
        packet = await recall_engine.recall(request)
        recall_text = packet.all_text()

        # Build brief as plain text sections
        sections = [
            "=== GOAL ===",
            self.config.goal,
            "",
            "=== SUCCESS CRITERIA ===",
            self.config.success_criteria,
            "",
            "=== CONTEXT (from Recall Engine, agent mode) ===",
            recall_text if recall_text else "(no context retrieved)",
        ]

        if self.config.skill:
            sections.extend(["", "=== SKILL ===", self.config.skill])

        return "\n".join(sections)

    async def _monitor(self) -> None:
        """Monitor the OpenCode event stream and manage the task lifecycle."""
        if not self._client or not self._session_id or not self._task:
            return

        task_id = self._task.task_id
        task_queue = get_task_queue()
        decision_service = get_decision_service()

        try:
            async for event in self._client.events(self._session_id):
                # Track elapsed time
                if self._start_time:
                    elapsed = get_clock().now() - self._start_time
                    if elapsed.total_seconds() > self.config.minutes * 60:
                        await self._handle_budget_exceeded(task_queue, task_id, "time")
                        return

                # Handle specific event kinds first
                if event.kind == "permission":
                    await self._handle_permission_event(
                        task_queue, task_id, decision_service, event
                    )
                elif event.kind == "tool":
                    # Track token usage from tool events
                    usage = event.data.get("usage", {})
                    if usage:
                        self._tokens_used += usage.get("total_tokens", 0)
                        if self._tokens_used > self.config.tokens:
                            await self._handle_budget_exceeded(task_queue, task_id, "tokens")
                            return

                elif event.kind == "succeeded":
                    # Mark task for review (W3-33 will handle the review)
                    await task_queue.db.merge(task_id, {
                        "status": TaskStatus.COMPLETE.value,
                        "updated_at": get_clock().now().isoformat(),
                    })
                    logger.info(f"Delegation succeeded: {task_id}")
                    return

                elif event.kind in ("failed", "interrupted"):
                    reason = event.data.get("error", "Session ended unexpectedly")
                    await task_queue.fail_task(task_id, reason=f"Session {event.kind}: {reason}")
                    logger.info(f"Delegation {event.kind}: {task_id} — {reason}")
                    return

                # Fold event into task step (only for step and tool events, per card)
                if event.kind in ("step", "tool"):
                    await self._persist_step_from_event(task_queue, task_id, event)

        except OpenCodeUnavailable:
            await task_queue.fail_task(task_id, reason="OpenCode unavailable — task interrupted")
            logger.warning(f"OpenCode unavailable during delegation {task_id}")
        except asyncio.CancelledError:
            logger.info(f"Delegation monitor cancelled: {task_id}")
        except Exception as e:
            logger.error(f"Delegation monitor error for {task_id}: {e}")
            await task_queue.fail_task(task_id, reason=f"Monitor error: {e}")

    async def _persist_step_from_event(
        self, task_queue: Any, task_id: str, event: WorkEvent
    ) -> None:
        """Create a task step from an event."""
        step_number = len(self._task.steps) + 1 if self._task else 1

        # Build a one-line summary from event data
        summary = self._summarize_event(event)

        step = TaskStepRecord(
            step_number=step_number,
            step_type=event.kind,
            title=summary,
            detail=f"Event: {event.type}",
            tool_name=event.data.get("tool") if event.kind == "tool" else None,
            tool_args=event.data.get("arguments") if event.kind == "tool" else None,
            result=event.data.get("result") if event.kind == "tool" else None,
            success=event.kind not in ("failed", "interrupted"),
            duration_ms=0,  # Not available from event stream
        )

        await task_queue.persist_step(task_id, step)

        # Update local task steps for step numbering
        if self._task:
            self._task.steps.append(step)

    def _summarize_event(self, event: WorkEvent) -> str:
        """Create a one-line summary from an event."""
        if event.kind == "step":
            step_data = event.data.get("step", {})
            label = step_data.get("description") or step_data.get("action", "unknown")
            return f"Step: {label}"
        elif event.kind == "tool":
            tool = event.data.get("tool", "unknown")
            return f"Tool: {tool}"
        elif event.kind == "permission":
            action = event.data.get("action", "unknown")
            resources = event.data.get("resources", [])
            res_str = ", ".join(resources[:2])
            if len(resources) > 2:
                res_str += f" (+{len(resources) - 2} more)"
            return f"Permission: {action} on {res_str}"
        elif event.kind == "started":
            return "Session started"
        elif event.kind == "succeeded":
            return "Session succeeded"
        elif event.kind == "failed":
            return f"Session failed: {event.data.get('error', 'unknown')}"
        elif event.kind == "interrupted":
            return "Session interrupted"
        else:
            return f"Event: {event.type}"

    async def _handle_permission_event(
        self,
        task_queue: Any,
        task_id: str,
        decision_service: Any,
        event: WorkEvent,
    ) -> None:
        """Handle a permission.asked event."""
        data = event.data
        request_id = data.get("id", "")
        action = data.get("action", "")
        resources = data.get("resources", [])
        message = data.get("message", "")

        if not request_id or not action:
            logger.warning(f"Permission event missing request_id or action: {data}")
            return

        # Compute risk for the action
        risk = risk_for_action(action)

        # Decide with role=owner (only owner can call delegate_work)
        decision = decide(
            risk=risk,
            workspace=self.config.workspace,
            role="owner",
            resources=resources,
        )

        if decision == "allow":
            # Answer immediately through client
            await self._client.answer_permission(self._session_id, request_id, True)
        elif decision == "deny":
            await self._client.answer_permission(self._session_id, request_id, False)
        else:  # "ask"
            # Create a pending decision and set task to waiting_approval
            await decision_service.create(
                kind="permission",
                session_id=self._session_id,
                request_id=request_id,
                action=action,
                resources=resources,
                risk=risk,
                workspace=self.config.workspace,
                message=message,
                task_id=task_id,
            )
            await task_queue.set_waiting_approval(
                task_id,
                blocker=f"Permission required: {action} on {', '.join(resources[:3])}",
            )

    async def _handle_budget_exceeded(
        self, task_queue: Any, task_id: str, budget_type: str
    ) -> None:
        """Handle budget exceeded by aborting session and failing task."""
        if self._client and self._session_id:
            try:
                await self._client.abort(self._session_id)
            except Exception as e:
                logger.error(f"Failed to abort session {self._session_id}: {e}")

        reason = f"budget exceeded: {budget_type} ({self._tokens_used} tokens used, {self.config.tokens} limit)" if budget_type == "tokens" else f"budget exceeded: time ({self.config.minutes} minutes limit)"
        await task_queue.fail_task(task_id, reason=reason)
        logger.info(f"Delegation budget exceeded: {task_id} — {reason}")


async def start_delegation(
    goal: str,
    workspace: str,
    agent: str,
    success_criteria: str,
    tokens: int,
    minutes: int,
    skill: Optional[str] = None,
) -> str:
    """Start a delegation in the background and return the task ID."""
    config = DelegationConfig(
        goal=goal,
        workspace=workspace,
        agent=agent,
        success_criteria=success_criteria,
        tokens=tokens,
        minutes=minutes,
        skill=skill,
    )
    runner = DelegationRunner(config)
    task_id = await runner.run()
    return task_id