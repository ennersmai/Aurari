"""Delegation Runner — manages delegated OpenCode sessions.

This module implements the background monitoring of delegated tasks,
including event folding, permission handling, budget enforcement,
and task lifecycle management.
"""

from __future__ import annotations

import asyncio
import json
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

# ---------------------------------------------------------------------------
# Controls (G4-01): registry of running runners and the pause-all flag
# ---------------------------------------------------------------------------

# task_id -> runner, for runners whose session is live. An entry is added once
# the task exists and removed when the monitor ends, on abort, or when run()
# fails before the monitor starts, so it holds only running delegations.
_RUNNERS: dict[str, "DelegationRunner"] = {}

# "Pause all" blocks NEW delegations only. OpenCode has no session pause, so
# running sessions carry on; this flag is checked at the delegate_work entry.
_paused = False


def _norm_id(task_id: Any) -> str:
    """A record id without the angle brackets SurrealDB adds to digit-led keys."""
    return str(task_id).replace("⟨", "").replace("⟩", "")


def running_runners() -> list["DelegationRunner"]:
    """A snapshot list of the runners that are registered (running)."""
    return list(_RUNNERS.values())


def get_runner(task_id: str) -> Optional["DelegationRunner"]:
    """The registered runner for a task id, if any."""
    return _RUNNERS.get(_norm_id(task_id))


def delegations_paused() -> bool:
    """True when new delegations are refused (running ones are unaffected)."""
    return _paused


def pause_all() -> None:
    """Refuse new delegations. Running sessions continue (no OpenCode pause)."""
    global _paused
    _paused = True


def resume_all() -> None:
    """Allow new delegations again."""
    global _paused
    _paused = False


def guidance_step(step_number: int, text: str) -> TaskStepRecord:
    """The task step recording owner guidance sent into a session."""
    return TaskStepRecord(
        step_number=step_number,
        step_type="guidance",
        title="Owner guidance",
        detail=text,
    )


def parse_verdict(summary: str) -> tuple[str, str]:
    """Parse a review verdict: ("PASS" | "FAIL" | "needs_owner", reason).

    Shared by the delegation review and the code-node review (P2-10).
    """
    if not summary:
        return "needs_owner", "Empty review summary"

    # Look for VERDICT: PASS or VERDICT: FAIL: <reason> anywhere in the summary
    pass_match = re.search(r"VERDICT:\s*PASS\b", summary)
    if pass_match:
        return "PASS", ""

    fail_match = re.search(r"VERDICT:\s*FAIL:\s*(.*)", summary)
    if fail_match:
        reason = fail_match.group(1).strip()
        return "FAIL", reason if reason else "No reason provided"

    # No verdict found
    return "needs_owner", "No verdict in review summary"


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
    identity_overlay: Optional[str] = None
    # G5-04: the live skill version whose body is in ``skill`` and who asked for the task.
    skill_ref: Optional[tuple[str, int]] = None
    requester_role: str = "guest"
    # B1-03: the conversation that asked for the task and when, so a passing review can
    # mark the requesting turn positive. No experience id exists yet at request time.
    conversation_id: Optional[str] = None
    requested_at: Optional[Any] = None
    # FU-02: optional goal id to link the delegated task to a goal for test_pass evidence.
    goal_id: Optional[str] = None
    # P2-33: "autonomous" when Aura started the delegation herself; the B1-06 kill
    # switch stops those. Stored on the task so a re-attached runner keeps it.
    origin: Optional[str] = None

    @property
    def autonomous(self) -> bool:
        return self.origin == "autonomous"


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
        self._brief: str = ""
        # G4-02 monitor state
        self._fired: set[str] = set()  # blocker kinds already raised
        self._error_streak = 0
        self._repeat_counts: dict[tuple[str, str], int] = {}
        self._last_summary = ""
        self._last_beat: Optional[datetime] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._bg_tasks: set[asyncio.Task] = set()  # strong refs to suggestion calls
        self._blocker_data: Optional[dict[str, Any]] = None

    # -- controls (G4-01) ---------------------------------------------------

    @property
    def task_id(self) -> Optional[str]:
        return self._task.task_id if self._task else None

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def client(self) -> Optional[OpenCodeClient]:
        return self._client

    def base_url(self) -> Optional[str]:
        """The managed server's base URL, or None if it is not up. No auth."""
        process = getattr(self._client, "_process", None)
        conn = getattr(process, "connection", None)
        url = getattr(conn, "base_url", None)
        return url if isinstance(url, str) else None

    def budget_snapshot(self) -> dict[str, Any]:
        elapsed = None
        if self._start_time is not None:
            elapsed = (get_clock().now() - self._start_time).total_seconds()
        return {
            "tokens_used": self._tokens_used,
            "tokens_limit": self.config.tokens,
            "elapsed_seconds": elapsed,
            "minutes_limit": self.config.minutes,
        }

    def _unregister(self) -> None:
        if self._task is not None and _RUNNERS.get(self._task.task_id) is self:
            del _RUNNERS[self._task.task_id]

    async def abort(self) -> None:
        """Abort the session, stop monitoring, and fail the task."""
        task_id = self.task_id
        if task_id is None:
            return
        if self._client is not None and self._session_id:
            try:
                await self._client.abort(self._session_id)
            except Exception as e:
                logger.error(f"Failed to abort session {self._session_id}: {e}")
        monitor = self._monitor_task
        if monitor is not None and not monitor.done() and monitor is not asyncio.current_task():
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning(f"Monitor ended with error during abort of {task_id}: {e}")
        self._unregister()
        await get_task_queue().fail_task(task_id, reason="aborted by owner")

    async def send_guidance(self, text: str) -> None:
        """Send guidance into the running session and record it as a step."""
        if self._client is None or not self._session_id or self._task is None:
            raise RuntimeError("delegation is not running")
        await self._client.send(self._session_id, text)
        await self._record_step(guidance_step(len(self._task.steps) + 1, text))

    @classmethod
    def reattach(cls, task: Task, client: OpenCodeClient) -> "DelegationRunner":
        """Bind a runner to an existing delegated task and its live session.

        Used at startup when the OpenCode session outlived the app. The runner
        is registered and its monitor started. Time and token budgets count
        from the re-attach (the earlier usage is not recorded).
        """
        config = DelegationConfig(
            goal=task.goal,
            workspace=task.workspace_path,
            agent="",
            success_criteria="",
            tokens=settings.delegation_default_tokens,
            minutes=settings.delegation_default_minutes,
            origin=getattr(task, "origin", None),
        )
        runner = cls(config)
        runner._task = task
        runner._session_id = task.session_id
        runner._client = client
        runner._start_time = get_clock().now()
        _RUNNERS[task.task_id] = runner
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.delegation_running(True)
        except Exception:
            pass
        runner._monitor_task = asyncio.create_task(runner._monitor())
        return runner

    async def run(self) -> str:
        """Start the delegation and return the task ID."""
        # Emit delegation_running(true) event for avatar state machine
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.delegation_running(True)
        except Exception:
            pass

        # 1. Build the brief
        brief = await self._build_brief()
        self._brief = brief

        # 2. Create task record
        task_queue = get_task_queue()
        self._task = await task_queue.create_task(
            goal=self.config.goal,
            workspace_path=self.config.workspace,
            session_id="main",  # replaced by the OpenCode session id once started
            delegated=True,
        )
        task_id = self._task.task_id
        _RUNNERS[task_id] = self
        await self._record_skill_use(task_id)
        await self._merge_task_fields(task_queue, task_id, {"requested_by_role": self.config.requester_role})
        if self.config.origin:
            await self._merge_task_fields(task_queue, task_id, {"origin": self.config.origin})
        # FU-02: store goal_id on the task if provided
        if self.config.goal_id:
            from aura.db.query_utils import to_record_id
            await self._merge_task_fields(task_queue, task_id, {"goal_id": to_record_id(self.config.goal_id)})
        try:
            await self._start_session(task_queue, task_id, brief)
        except BaseException:
            self._unregister()
            raise
        return task_id

    async def _start_session(self, task_queue: Any, task_id: str, brief: str) -> None:
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
            "updated_at": get_clock().now(),
        })

        # 4. Send the brief to start the session
        await self._client.send(self._session_id, brief)

        # 5. Start background monitoring
        self._start_time = get_clock().now()
        self._monitor_task = asyncio.create_task(self._monitor())

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

        if self.config.identity_overlay:
            sections.extend(["", "=== SESSION CONTEXT ===", self.config.identity_overlay])

        return "\n".join(sections)

    async def _monitor(self) -> None:
        """Monitor the OpenCode event stream and manage the task lifecycle."""
        if not self._client or not self._session_id or not self._task:
            self._unregister()
            return

        task_id = self._task.task_id
        task_queue = get_task_queue()
        decision_service = get_decision_service()

        self._last_beat = get_clock().now()
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            async for event in self._client.events(self._session_id):
                # Track elapsed time
                if self._start_time:
                    elapsed = get_clock().now() - self._start_time
                    if elapsed.total_seconds() > self.config.minutes * 60:
                        await self._handle_budget_exceeded(task_queue, task_id, "time")
                        return
                    if elapsed.total_seconds() >= self.config.minutes * 60 * settings.delegation_budget_warn_fraction:
                        pct = int(settings.delegation_budget_warn_fraction * 100)
                        await self._raise_blocker(
                            "budget_time",
                            "step_limit",
                            f"{pct}% of the time budget used "
                            f"({int(elapsed.total_seconds() // 60)} of {self.config.minutes} minutes)",
                        )
                await self._maybe_heartbeat()

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
                        if self._tokens_used >= self.config.tokens * settings.delegation_budget_warn_fraction:
                            pct = int(settings.delegation_budget_warn_fraction * 100)
                            await self._raise_blocker(
                                "budget_tokens",
                                "step_limit",
                                f"{pct}% of the token budget used ({self._tokens_used} of {self.config.tokens})",
                            )
                    await self._observe_tool(event)

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
        finally:
            self._unregister()
            await self._stop_background()
            # Emit delegation_running(false) event for avatar state machine
            try:
                from aura.main import avatar_state_machine
                if avatar_state_machine is not None:
                    avatar_state_machine.delegation_running(False)
            except Exception:
                pass

    # -- blocker monitor, heartbeat, suggestion (G4-02) ---------------------

    async def _stop_background(self) -> None:
        """Cancel the heartbeat timer and any in-flight suggestion calls."""
        pending = [t for t in (self._heartbeat_task, *self._bg_tasks) if t is not None and not t.done()]
        for t in pending:
            t.cancel()
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        """Wake every heartbeat interval so a silent session still beats."""
        while True:
            await self._heartbeat_wait()
            try:
                await self._maybe_heartbeat()
            except Exception as e:
                logger.warning(f"Heartbeat failed for {self.task_id}: {e}")

    async def _heartbeat_wait(self) -> None:
        await asyncio.sleep(settings.delegation_heartbeat_seconds)

    async def _maybe_heartbeat(self) -> None:
        """Add a 'still working' status step if the interval has passed. No model call."""
        if self._task is None or self._last_beat is None or self._start_time is None:
            return
        now = get_clock().now()
        if (now - self._last_beat).total_seconds() < settings.delegation_heartbeat_seconds:
            return
        self._last_beat = now
        minutes = int((now - self._start_time).total_seconds() // 60)
        n_steps = len(self._task.steps)
        last = self._last_summary or "no steps yet"
        await self._record_step(TaskStepRecord(
            step_number=n_steps + 1,
            step_type="status",
            title=f"still working: {last}, {n_steps} steps, {minutes} min",
        ))

    async def _emotion_snapshot(self) -> Optional[dict[str, float]]:
        """Top 3 emotion dimensions now. Any failure gives None, never blocks a step."""
        try:
            engine = _get_emotion_engine()
            if engine is None:
                return None
            state = await engine.get_current_state()
            return {name: round(float(v), 4) for name, v in state.vector.get_top_n(3)}
        except Exception as e:
            logger.debug(f"Emotion snapshot unavailable: {e}")
            return None

    async def _record_step(self, step: TaskStepRecord) -> None:
        """Number, stamp with emotion, append locally and persist a step."""
        if self._task is None:
            return
        step.emotion = await self._emotion_snapshot()
        step.step_number = len(self._task.steps) + 1
        self._task.steps.append(step)
        await get_task_queue().persist_step(self._task.task_id, step)

    async def _observe_tool(self, event: WorkEvent) -> None:
        """Track failed-tool streaks and repeated identical calls."""
        data = event.data or {}
        # A tool event fails when its type is session.tool.failed (WorkEvent.type is
        # the raw OpenCode type, opencode_client.py:299-312; kind "tool" comes from the
        # "session.tool." prefix, opencode_client.py:320-321). That event's data carries
        # a required `error` (openapi-v2.3.2.json, schema session.tool.failed), so a
        # non-empty `error` counts too.
        failed = event.type.endswith(".failed") or bool(data.get("error"))
        if failed:
            self._error_streak += 1
            if self._error_streak >= settings.delegation_error_streak:
                await self._raise_blocker(
                    "error_streak",
                    "repeated_failure",
                    f"{self._error_streak} failed tool calls in a row",
                    attempts=self._error_streak,
                    last_error=str(data.get("error", ""))[:300],
                )
        elif event.type.endswith(".success"):
            self._error_streak = 0

        if event.type.endswith(".called"):
            name = str(data.get("tool") or data.get("name") or "")
            args = data.get("arguments", data.get("input"))
            key = (name, json.dumps(args, sort_keys=True, default=str))
            count = self._repeat_counts.get(key, 0) + 1
            self._repeat_counts[key] = count
            if count >= settings.delegation_repeat_limit:
                await self._raise_blocker(
                    "repeat_loop",
                    "reasoning_loop",
                    f"the same tool call ({name or 'unnamed'}) ran {count} times with the same arguments",
                    tool=name or None,
                    attempts=count,
                )

    async def _raise_blocker(
        self,
        kind: str,
        info_type: str,
        reason: str,
        tool: Optional[str] = None,
        attempts: int = 0,
        last_error: str = "",
    ) -> None:
        """Record a blocker once per kind: blocker info, a needs_decision item, a suggestion."""
        if self._task is None or kind in self._fired:
            return
        self._fired.add(kind)
        task_id = self._task.task_id
        recent = [s.title for s in self._task.steps[-settings.delegation_blocker_recent_steps:]]
        data: dict[str, Any] = {
            "type": info_type,
            "tool": tool,
            "attempts": attempts,
            "last_error": last_error or reason,
            "last_reasoning": reason,
            "suggested_action": "",
        }
        self._blocker_data = data
        await get_task_queue().set_blocker_info(task_id, data)
        message = f"{reason}. Last steps: " + ("; ".join(recent) if recent else "(none)")
        try:
            await get_decision_service().create(
                kind="needs_decision",
                session_id=self._session_id or "",
                request_id=f"blocker:{task_id}:{kind}",
                action=f"blocker_{kind}",
                resources=[],
                risk="blocker",
                workspace=self.config.workspace,
                message=message,
                task_id=task_id,
            )
        except Exception as e:
            logger.warning(f"Could not create blocker decision for {task_id}: {e}")
        logger.info(f"Delegation blocker ({kind}) on {task_id}: {reason}")
        bg = asyncio.create_task(self._suggest(task_id, data, reason, recent))
        self._bg_tasks.add(bg)
        bg.add_done_callback(self._bg_tasks.discard)

    async def _suggest(self, task_id: str, data: dict[str, Any], reason: str, recent: list[str]) -> None:
        """One L2 call drafting a next action; stored on the blocker info. Failures are logged."""
        try:
            client = _get_llm_client()
            prompt = (
                "A delegated coding agent is blocked.\n\n"
                f"Brief:\n{self._brief or self.config.goal}\n\n"
                f"Blocker: {reason}\n\n"
                "Last steps:\n" + "\n".join(f"- {t}" for t in recent) + "\n\n"
                "Suggest one next action for the owner in one paragraph."
            )
            reply = await client.complete(
                [{"role": "user", "content": prompt}],
                model=settings.active_l2_model,
                temperature=0.3,
                max_tokens=300,
            )
            text = (reply or "").strip()
            if not text:
                return
            data["suggested_action"] = text
            if self._blocker_data is data:  # a newer blocker owns the info otherwise
                await get_task_queue().set_blocker_info(task_id, data)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Blocker suggestion failed for {task_id}: {e}")

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
                "updated_at": get_clock().now(),
            })
            logger.info(f"Delegation succeeded (no files changed): {task_id}")
            await self._finalize_task(task_queue, task_id, "succeeded", "No files changed")
            return

        # There are changed files - start a review session with aura-review agent
        logger.info(f"Delegation succeeded with {len(files_changed)} files changed, starting review: {task_id}")
        verdict, reason = await self._run_review(task_queue, task_id, result)

        # Close the task based on verdict
        if verdict == "PASS":
            await self._finalize_task(task_queue, task_id, "succeeded", "Review passed", reviewed=True)
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
        return parse_verdict(summary)

    async def _record_skill_use(self, task_id: str) -> None:
        """G5-04: attribute the task to the skill version whose body is in the brief."""
        if not self.config.skill_ref:
            return
        try:
            from aura.engines.learning.skill_stats import record_skill_use
            from aura.engines.learning.skill_store import SkillStore

            skill, version = self.config.skill_ref
            await record_skill_use(
                SkillStore(), skill, version, turn_id=None, task_id=str(task_id),
                requester_role=self.config.requester_role,
            )
        except Exception as e:
            logger.warning(f"Skill use not recorded for {task_id}: {e}")

    async def _merge_task_fields(self, task_queue: Any, task_id: str, fields: dict[str, Any]) -> None:
        """G6-01: keep the requester role and review result on the task record."""
        try:
            await task_queue.db.merge(task_id, fields)
        except Exception as e:
            logger.warning(f"Task fields not stored for {task_id}: {e}")

    async def _count_skill_outcome(self, task_id: str, outcome: str, reviewed: bool) -> None:
        """G5-04: succeeded with a passing review counts positive, failed negative;
        needs_owner and anything else count nothing."""
        if not self.config.skill_ref:
            return
        try:
            from aura.engines.learning.outcomes import Turn, classify_outcome
            from aura.engines.learning.skill_stats import apply_outcome_for_task
            from aura.engines.learning.skill_store import SkillStore

            if outcome == "succeeded" and reviewed:
                signal, _ = await classify_outcome(
                    None, Turn(experience_id="", text=""), task_tests_passed=True
                )
            elif outcome == "failed":
                signal = "negative"
            else:
                return
            await apply_outcome_for_task(SkillStore(), str(task_id), signal)
        except Exception as e:
            logger.warning(f"Skill outcome not counted for {task_id}: {e}")

    async def _finalize_task(
        self, task_queue: Any, task_id: str, outcome: str, reason: str, reviewed: bool = False
    ) -> None:
        """Finalize the task with outcome and write memory/appraisal if enabled.

        ``reviewed`` is True when the review (tests) passed; only then does a
        ``succeeded`` task count as a positive skill outcome (G5-04).
        """
        # Update task status
        if outcome == "succeeded":
            await task_queue.db.merge(task_id, {
                "status": TaskStatus.COMPLETE.value,
                "updated_at": get_clock().now(),
            })
        elif outcome == "failed":
            await task_queue.fail_task(task_id, reason=reason)
        elif outcome == "needs_owner":
            await task_queue.db.merge(task_id, {
                "status": TaskStatus.NEEDS_OWNER.value,
                "updated_at": get_clock().now(),
                "blocker": reason,
            })
            logger.info(f"Task {task_id} marked as needs_owner: {reason}")

        # FU-02: store tests_passed based on review outcome (only when goal_id is set)
        if self.config.goal_id:
            if reviewed:
                await self._merge_task_fields(task_queue, task_id, {"reviewed": True, "tests_passed": True})
            elif outcome == "failed":
                # Review happened but failed
                await self._merge_task_fields(task_queue, task_id, {"tests_passed": False})
        elif reviewed:
            # Review passed but no goal_id: still mark reviewed but not tests_passed
            await self._merge_task_fields(task_queue, task_id, {"reviewed": True})
        await self._count_skill_outcome(task_id, outcome, reviewed)
        if outcome == "succeeded" and reviewed and self.config.requester_role == "owner":
            from aura.engines.learning.outcomes import record_task_evidence

            await record_task_evidence(self.config.conversation_id, self.config.requested_at)

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
        """Emit an appraisal event for the delegation outcome (E2/E3 flag only)."""
        if not settings.emotion_appraisal_enabled:
            return
        try:
            from aura.engines.emotion.system_events import tool_succeeded, tool_failed

            engine = _get_emotion_engine()
            if engine is None:
                return
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

        self._last_summary = summary
        await self._record_step(step)

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


def _get_emotion_engine() -> Any:
    """The running emotion engine (aura.main), or None. Patched in tests."""
    from aura.main import emotion_engine
    return emotion_engine


def _get_llm_client() -> Any:
    """The LLM client behind the app's layers. Patched in tests."""
    from aura.api.routes.school import get_llm_layers
    return get_llm_layers().client


async def try_reattach(task: Task) -> bool:
    """At startup: attach a monitor to a delegated task whose session still runs.

    Returns True when re-attached. Any error or a session that is not running
    returns False, so the caller keeps its interrupted handling.
    """
    if not task.delegated or not task.session_id or task.session_id == "main":
        return False
    try:
        client = OpenCodeClient(OpenCodeProcess())
        if not await client.session_running(task.session_id):
            await client.close()
            return False
        get_decision_service()._client = client
        DelegationRunner.reattach(task, client)
        logger.info(f"Re-attached delegation monitor: {task.task_id} (session {task.session_id})")
        return True
    except Exception as e:
        logger.warning(f"Re-attach failed for {task.task_id}: {e}")
        return False


async def start_delegation(
    goal: str,
    workspace: str,
    agent: str,
    success_criteria: str,
    tokens: int,
    minutes: int,
    skill: Optional[str] = None,
    identity_overlay: Optional[str] = None,
    skill_ref: Optional[tuple[str, int]] = None,
    requester_role: str = "guest",
    conversation_id: Optional[str] = None,
    goal_id: Optional[str] = None,
    origin: Optional[str] = None,
) -> str:
    """Start a delegation in the background and return the task ID.

    ``origin="autonomous"`` (P2-33) marks a self-started delegation; the caller
    must have passed ``may_initiate("delegation")`` first.
    """
    config = DelegationConfig(
        goal=goal,
        workspace=workspace,
        agent=agent,
        success_criteria=success_criteria,
        tokens=tokens,
        minutes=minutes,
        skill=skill,
        identity_overlay=identity_overlay,
        skill_ref=skill_ref,
        requester_role=requester_role,
        conversation_id=conversation_id,
        requested_at=get_clock().now() if conversation_id else None,
        goal_id=goal_id,
        origin=origin,
    )
    runner = DelegationRunner(config)
    task_id = await runner.run()
    return task_id