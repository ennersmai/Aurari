"""Delegation Runner — manages delegated OpenCode sessions.

This module implements the background monitoring of delegated tasks,
including event folding, permission handling, budget enforcement,
and task lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from aura.clock import get_clock
from aura.config import settings
from aura.connections.opencode_client import OpenCodeClient, OpenCodeUnavailable, WorkResult
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
                    # Session succeeded - now handle review and close task
                    await self._handle_session_success(task_queue, task_id)
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

    async def _handle_session_success(self, task_queue: Any, task_id: str) -> None:
        """Handle a successful session completion with optional review."""
        if not self._client or not self._session_id:
            return

        # Get the result from the completed session
        try:
            result: WorkResult = await self._client.result(self._session_id)
        except Exception as e:
            logger.error(f"Failed to get result for session {self._session_id}: {e}")
            await task_queue.fail_task(task_id, reason=f"Failed to get session result: {e}")
            return

        files_changed = result.files_changed or []
        additions = result.additions or 0
        deletions = result.deletions or 0

        # No changed files: close as succeeded without review
        if not files_changed:
            await task_queue.db.merge(task_id, {
                "status": TaskStatus.COMPLETE.value,
                "updated_at": get_clock().now().isoformat(),
            })
            logger.info(f"Delegation succeeded (no files changed): {task_id}")
            await self._finalize_task(task_queue, task_id, "succeeded", "No files changed")
            return

        # There are changed files - start a review session with aura-review agent
        logger.info(f"Delegation succeeded with {len(files_changed)} files changed, starting review: {task_id}")
        verdict, reason = await self._run_review(task_queue, task_id, result)

        # Close the task based on verdict
        if verdict == "PASS":
            await self._finalize_task(task_queue, task_id, "succeeded", "Review passed")
        elif verdict == "FAIL":
            await self._finalize_task(task_queue, task_id, "failed", f"Review failed: {reason}")
        else:  # needs_owner (no verdict or expired)
            await self._finalize_task(task_queue, task_id, "needs_owner", f"Review needs owner: {reason}")

    async def _run_review(self, task_queue: Any, task_id: str, result: WorkResult) -> tuple[str, str]:
        """Run an aura-review session and return (verdict, reason).

        Verdict is one of: "PASS", "FAIL", "needs_owner"
        """
        if not self._client:
            return "needs_owner", "No client available for review"

        workspace_path = self._resolve_workspace_path()
        if workspace_path is None:
            return "needs_owner", "Workspace not available for review"

        # Build review brief
        files_list = "\n".join(f"  - {f}" for f in result.files_changed)
        diff_stats = f"{len(result.files_changed)} files changed, +{result.additions} -{result.deletions} lines"

        review_brief = "\n".join([
            "=== REVIEW REQUEST ===",
            "You are reviewing a completed delegated task. Your job is to evaluate whether the work meets the success criteria.",
            "",
            "=== ORIGINAL GOAL ===",
            self.config.goal,
            "",
            "=== SUCCESS CRITERIA ===",
            self.config.success_criteria,
            "",
            "=== DIFF STATISTICS ===",
            diff_stats,
            "",
            "=== FILES CHANGED ===",
            files_list,
            "",
            "=== DELEGATE'S SUMMARY ===",
            result.summary or "(no summary provided)",
            "",
            "=== YOUR TASK ===",
            "Review the work against the success criteria. At the end of your response, you MUST include exactly one verdict line:",
            "  VERDICT: PASS",
            "or",
            "  VERDICT: FAIL: <reason>",
            "A missing verdict will be treated as NEEDS_OWNER.",
        ])

        try:
            # Create review session with aura-review agent
            review_session_id = await self._client.create_session(
                workspace=workspace_path,
                agent="aura-review",
                title=f"Review: {self.config.goal[:50]}",
            )

            # Send the review brief
            await self._client.send(review_session_id, review_brief)

            # Collect events until review session completes
            review_summary = ""
            async for event in self._client.events(review_session_id):
                if event.kind == "succeeded":
                    # Get the review result
                    review_result = await self._client.result(review_session_id)
                    review_summary = review_result.summary or ""
                    break
                elif event.kind in ("failed", "interrupted"):
                    logger.warning(f"Review session {event.kind}: {event.data.get('error', 'unknown')}")
                    return "needs_owner", f"Review session {event.kind}"

            # Parse verdict from review summary
            verdict, reason = self._parse_verdict(review_summary)
            return verdict, reason

        except Exception as e:
            logger.error(f"Review session error for task {task_id}: {e}")
            return "needs_owner", f"Review error: {e}"

    def _parse_verdict(self, summary: str) -> tuple[str, str]:
        """Parse verdict from review summary.

        Returns (verdict, reason) where verdict is "PASS", "FAIL", or "needs_owner".
        """
        if not summary:
            return "needs_owner", "Empty review summary"

        # Look for VERDICT: PASS or VERDICT: FAIL: <reason> anywhere in the summary
        import re
        # Match VERDICT: PASS or VERDICT: FAIL: <reason>
        pass_match = re.search(r"VERDICT:\s*PASS\b", summary)
        if pass_match:
            return "PASS", ""

        fail_match = re.search(r"VERDICT:\s*FAIL:\s*(.*)", summary)
        if fail_match:
            reason = fail_match.group(1).strip()
            return "FAIL", reason if reason else "No reason provided"

        # No verdict found
        return "needs_owner", "No verdict in review summary"

    async def _finalize_task(self, task_queue: Any, task_id: str, outcome: str, reason: str) -> None:
        """Finalize the task with outcome and write memory/appraisal if enabled."""
        # Update task status
        if outcome == "succeeded":
            await task_queue.db.merge(task_id, {
                "status": TaskStatus.COMPLETE.value,
                "updated_at": get_clock().now().isoformat(),
            })
        elif outcome == "failed":
            await task_queue.fail_task(task_id, reason=reason)
        elif outcome == "needs_owner":
            await task_queue.db.merge(task_id, {
                "status": TaskStatus.NEEDS_OWNER.value,
                "updated_at": get_clock().now().isoformat(),
                "blocker": reason,
            })
            logger.info(f"Task {task_id} marked as needs_owner: {reason}")

        # Memory v2 write (4.8): store episode and fact when enabled
        if settings.memory_v2_write_enabled:
            await self._write_delegation_memory(task_queue, task_id, outcome, reason)

        # Emit appraisal event (E2) when emotion_appraisal_enabled
        if settings.emotion_appraisal_enabled:
            await self._emit_appraisal(outcome)

        logger.info(f"Delegation {outcome}: {task_id} — {reason}")

    async def _write_delegation_memory(self, task_queue: Any, task_id: str, outcome: str, reason: str) -> None:
        """Write episode and fact for the completed delegation."""
        try:
            from aura.engines.memory.v2.episodes import store_episode

            db = task_queue.db
            # Get embeddings client
            from aura.llm.embeddings import get_embeddings_client
            embeddings = get_embeddings_client()

            # Build aura_text (outcome summary)
            aura_text = f"Delegation {outcome}: {self.config.goal}. {reason}"

            # Store episode
            episode_id = await store_episode(
                db=db,
                embeddings=embeddings,
                user_text=self.config.goal,
                aura_text=aura_text,
                speaker="owner",
                venue="app",
                conversation_id=None,
                emotional_signature={},  # Empty for now
                salience=0.5,
                display_name="owner",
            )

            # One fact with provenance "external" (agency PRD 4.8). It is written
            # directly rather than through write_facts, whose provenance rules
            # (observed / hearsay / inferred) are for things people said.
            fact_content = f"Aura delegated: {self.config.goal} in {self.config.workspace}: {outcome}"
            now = get_clock().now()
            rows = await db.query(
                "CREATE fact CONTENT $data",
                {
                    "data": {
                        "content": fact_content,
                        "kind": "event",
                        "subject": "Aura",
                        "predicate": "delegated",
                        "object": self.config.goal,
                        "provenance": "external",
                        "visibility": "owner",
                        "confidence": settings.memory_observed_confidence,
                        "valid_from": now,
                        "recorded_at": now,
                        "embedding": await embeddings.embed(fact_content),
                    }
                },
            )
            fact_id = rows[0]["id"]
            await db.query(
                "RELATE $fact->derived_from->$episode",
                {"fact": fact_id, "episode": episode_id},
            )

        except Exception as e:
            logger.warning(f"Failed to write delegation memory for {task_id}: {e}")

    async def _emit_appraisal(self, outcome: str) -> None:
        """Emit an appraisal event for the delegation outcome."""
        try:
            from aura.engines.emotion.system_events import tool_succeeded, tool_failed
            from aura.engines.emotion.engine import get_emotion_engine

            engine = get_emotion_engine()
            if outcome == "succeeded":
                event = tool_succeeded("delegation")
            else:
                event = tool_failed("delegation", retryable=False)
            await engine.appraise(event)
        except Exception as e:
            logger.warning(f"Failed to emit appraisal for delegation outcome: {e}")

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