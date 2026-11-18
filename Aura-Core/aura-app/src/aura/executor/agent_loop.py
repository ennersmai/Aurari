"""
Agent Loop - Free-running autonomous execution with human-readable context.

Allows Aura to chain tool calls autonomously in a loop:
1. L3 generates a plan/response with tool calls
2. Tool calls are extracted and executed
3. Results are fed back to L3 for next iteration
4. Human-readable status is streamed via SSE at each step
5. Loop continues until: task complete, max iterations, or human intervention needed

Each step streams a structured status event so the frontend can display
a live, human-readable log of what Aura is doing.

Extended with:
- Blocker detection (repeated tool failures, reasoning loops, step limit)
- Emotional state snapshots on every step
- Heartbeat emission for long-running tasks
- Escalation SSE events with L2-suggested actions
- File version snapshots keyed by task_id:path:step_number
"""

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncGenerator, Callable, TYPE_CHECKING

from aura.config import settings
from aura.models.session import SessionContext

if TYPE_CHECKING:
    from aura.executor.task_queue import TaskQueueService
    from aura.engines.emotion.engine import EmotionEngine

logger = logging.getLogger(__name__)

# Blocker detection thresholds
_CONSECUTIVE_FAIL_LIMIT = 3
_REASONING_LOOP_WINDOW = 3
_REASONING_LOOP_SIMILARITY = 0.92
_STEP_LIMIT_WARNING_RATIO = 0.8


def _cosine_similarity_strings(a: str, b: str) -> float:
    """Quick bag-of-words cosine similarity for reasoning loop detection."""
    if not a or not b:
        return 0.0
    words_a = a.lower().split()
    words_b = b.lower().split()
    if not words_a or not words_b:
        return 0.0
    vocab = set(words_a) | set(words_b)
    vec_a = {w: words_a.count(w) for w in vocab}
    vec_b = {w: words_b.count(w) for w in vocab}
    dot = sum(vec_a[w] * vec_b[w] for w in vocab)
    mag_a = math.sqrt(sum(v * v for v in vec_a.values())) or 1.0
    mag_b = math.sqrt(sum(v * v for v in vec_b.values())) or 1.0
    return dot / (mag_a * mag_b)


class AgentStepType(str, Enum):
    """Types of steps in an agent loop."""
    THINKING = "thinking"       # L3 is reasoning about the next action
    TOOL_CALL = "tool_call"     # Executing a tool
    TOOL_RESULT = "tool_result" # Tool returned a result
    RESPONSE = "response"       # Final or intermediate response text
    ERROR = "error"             # Something went wrong
    WAITING = "waiting"         # Waiting for human approval
    COMPLETE = "complete"       # Loop finished successfully
    ABORTED = "aborted"        # Loop was stopped
    ESCALATION = "escalation"  # Blocker detected — needs user help
    HEARTBEAT = "heartbeat"    # Alive signal for long-running tasks
    WARNING = "warning"        # Non-fatal warning (e.g. approaching step limit)


@dataclass
class AgentStep:
    """A single step in the agent loop, designed for human-readable display."""
    step_number: int
    step_type: AgentStepType
    title: str                          # Short human-readable title
    detail: str = ""                    # Longer description
    tool_name: str | None = None        # If tool_call/tool_result
    tool_args: dict[str, Any] | None = None
    result: str | None = None           # Tool result or response text
    success: bool = True
    timestamp: float = field(default_factory=time.time)
    duration_ms: int = 0
    emotional_state_snapshot: dict[str, Any] | None = None
    active_file: str | None = None

    def to_sse_event(self) -> str:
        """Serialize to SSE event format."""
        data = {
            "step": self.step_number,
            "type": self.step_type.value,
            "title": self.title,
            "detail": self.detail,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "result": self.result[:2000] if self.result else None,  # Truncate large results
            "success": self.success,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "emotional_state_snapshot": self.emotional_state_snapshot,
            "active_file": self.active_file,
        }
        return f"data: {json.dumps(data)}\n\n"

    def to_task_step_record(self) -> dict[str, Any]:
        """Convert to TaskStepRecord-compatible dict for SurrealDB persistence."""
        return {
            "step_number": self.step_number,
            "step_type": self.step_type.value,
            "title": self.title,
            "detail": self.detail,
            "tool_name": self.tool_name,
            "tool_args": self.tool_args,
            "result": self.result[:5000] if self.result else None,
            "success": self.success,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "emotional_state_snapshot": self.emotional_state_snapshot,
            "active_file": self.active_file,
        }


class AgentLoop:
    """
    Free-running agent loop with streaming status updates.

    Orchestrates autonomous tool execution chains where L3 decides
    the next action, tools are executed, and results feed back in.

    Extended with blocker detection, emotional snapshots, heartbeat,
    and escalation for production-grade long-running task support.
    """

    def __init__(
        self,
        llm_layers: Any,
        tool_executor: Any,
        max_iterations: int | None = None,
        require_approval_for: set[str] | None = None,
        task_id: str | None = None,
        task_queue: "TaskQueueService | None" = None,
        emotion_engine: "EmotionEngine | None" = None,
        session_ctx: SessionContext | None = None,
    ):
        """
        Initialize the agent loop.

        Args:
            llm_layers: LLMLayers instance for L3 synthesis
            tool_executor: ToolExecutor instance for running tools
            max_iterations: Max loop iterations (default from config)
            require_approval_for: Tool names requiring human approval
            task_id: Optional persistent task ID for crash-safe step tracking
            task_queue: Optional TaskQueueService for SurrealDB persistence
            emotion_engine: Optional EmotionEngine for emotional snapshots
            session_ctx: Optional SessionContext for tool allow/deny,
                memory namespace, model overrides, and identity overlay
        """
        self.llm = llm_layers
        self.executor = tool_executor
        self.max_iterations = max_iterations or settings.agent_loop_max_iterations
        self.require_approval = require_approval_for or {
            "delete_file", "write_file", "edit_file",
        }
        self._abort_flag = False
        self._waiting_for_approval = False
        self._approval_granted = False
        # Task persistence
        self.task_id = task_id
        self.task_queue = task_queue
        # Emotional state
        self.emotion_engine = emotion_engine
        # Session context (V1PRD §4) — defaults to MAIN for backward compat
        self.session_ctx = session_ctx or SessionContext.main()
        # Blocker detection state
        self._tool_failure_counts: dict[str, int] = {}
        self._thinking_details: list[str] = []
        self._completed_steps = 0
        # Heartbeat
        self._start_time = time.time()
        self._last_heartbeat = 0.0
        # Guidance injection
        self._injected_guidance: str | None = None

    def abort(self) -> None:
        """Signal the loop to stop at the next safe point."""
        self._abort_flag = True

    def grant_approval(self) -> None:
        """Grant approval for a pending destructive action."""
        self._approval_granted = True

    def deny_approval(self) -> None:
        """Deny approval for a pending destructive action."""
        self._approval_granted = False
        self._waiting_for_approval = False

    def inject_guidance(self, guidance: str) -> None:
        """Inject user guidance into the next iteration context."""
        self._injected_guidance = guidance

    async def _capture_emotional_snapshot(self) -> dict[str, Any] | None:
        """Capture current emotional state as a serializable snapshot."""
        if not self.emotion_engine:
            return None
        try:
            state = await self.emotion_engine.get_current_state()
            vector_dict = state.vector.model_dump()
            dominant_name, dominant_val = state.dominant
            valence = self.emotion_engine._compute_valence(vector_dict)
            top_3 = state.vector.get_top_n(n=3)
            return {
                "dominant_emotion": dominant_name,
                "valence": round(valence, 3),
                "arousal": round(state.volatility, 3),
                "top_emotions": {name: round(val, 3) for name, val in top_3},
            }
        except Exception as e:
            logger.debug(f"Failed to capture emotional snapshot: {e}")
            return None

    def _check_reasoning_loop(self) -> bool:
        """Detect if the last N thinking steps are near-identical (reasoning loop)."""
        if len(self._thinking_details) < _REASONING_LOOP_WINDOW:
            return False
        recent = self._thinking_details[-_REASONING_LOOP_WINDOW:]
        # All pairwise similarities must exceed threshold
        for i in range(len(recent)):
            for j in range(i + 1, len(recent)):
                if _cosine_similarity_strings(recent[i], recent[j]) < _REASONING_LOOP_SIMILARITY:
                    return False
        return True

    def _record_tool_result(self, tool_name: str, success: bool) -> bool:
        """Track consecutive failures per tool. Returns True if limit hit."""
        if success:
            self._tool_failure_counts[tool_name] = 0
            self._completed_steps += 1
            return False
        self._tool_failure_counts[tool_name] = self._tool_failure_counts.get(tool_name, 0) + 1
        return self._tool_failure_counts[tool_name] >= _CONSECUTIVE_FAIL_LIMIT

    async def _generate_suggested_action(self, blocker_context: str) -> str:
        """Use L2 to generate a suggested user action for an escalation."""
        try:
            result = await self.llm.l2_reasoning({
                "user_input": f"[ESCALATION CONTEXT]\n{blocker_context}",
                "aura_response": "I am stuck and need user guidance.",
            })
            analysis = result.get("analysis", "")
            if analysis:
                return analysis[:500]
            return "Review the error details and provide guidance or a different approach."
        except Exception as e:
            logger.error(f"Failed to generate suggested action: {e}")
            return "Review the error details and provide guidance or a different approach."

    def _should_emit_heartbeat(self) -> bool:
        """Check if 30 seconds have passed since last heartbeat."""
        now = time.time()
        if now - self._last_heartbeat >= 30.0:
            self._last_heartbeat = now
            return True
        return False

    def _make_heartbeat(self, step_num: int) -> AgentStep:
        """Create a heartbeat SSE event."""
        import psutil
        try:
            mem_mb = psutil.Process().memory_info().rss / (1024 * 1024)
        except Exception:
            mem_mb = 0.0
        uptime_s = int(time.time() - self._start_time)
        return AgentStep(
            step_number=step_num,
            step_type=AgentStepType.HEARTBEAT,
            title="heartbeat",
            detail=json.dumps({
                "task_id": self.task_id,
                "step": step_num,
                "uptime_s": uptime_s,
                "memory_used_mb": round(mem_mb, 1),
            }),
            success=True,
        )

    async def run(
        self,
        task: str,
        conversation_history: list[dict[str, str]] | None = None,
        system_context: str = "",
    ) -> AsyncGenerator[AgentStep, None]:
        """
        Run the agent loop, yielding human-readable steps.

        Args:
            task: The user's task/request
            conversation_history: Prior conversation for context
            system_context: Additional system context (e.g., emotion state)

        Yields:
            AgentStep objects for each action taken
        """
        self._abort_flag = False
        self._start_time = time.time()
        self._last_heartbeat = time.time()
        history = list(conversation_history or [])
        step_num = 0
        accumulated_context: list[str] = []

        # Build the agent system prompt
        agent_system = self._build_agent_system_prompt(system_context)

        for iteration in range(self.max_iterations):
            if self._abort_flag:
                yield AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.ABORTED,
                    title="Loop aborted by user",
                )
                return

            # === HEARTBEAT ===
            if self._should_emit_heartbeat():
                yield self._make_heartbeat(step_num)

            # === STEP LIMIT WARNING ===
            if (
                iteration >= int(self.max_iterations * _STEP_LIMIT_WARNING_RATIO)
                and self._completed_steps == 0
            ):
                warning_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.WARNING,
                    title="Approaching step limit with no completed steps",
                    detail=f"Iteration {iteration + 1}/{self.max_iterations} — no successful tool results yet.",
                    success=False,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                )
                yield warning_step

            # === STEP: THINKING ===
            step_num += 1
            emo_snap = await self._capture_emotional_snapshot()
            thinking_step = AgentStep(
                step_number=step_num,
                step_type=AgentStepType.THINKING,
                title=f"Thinking... (iteration {iteration + 1}/{self.max_iterations})",
                detail="Analyzing task and deciding next action",
                emotional_state_snapshot=emo_snap,
            )
            await self._persist_step(thinking_step)
            yield thinking_step

            # Build messages for L3
            messages = [{"role": "system", "content": agent_system}]
            messages.extend(history)

            # Add accumulated tool results as context
            context_text = ""
            if accumulated_context:
                context_text = "\n\n".join(accumulated_context)
                messages.append({
                    "role": "system",
                    "content": f"[TOOL RESULTS FROM PREVIOUS STEPS]\n{context_text}",
                })

            # Inject user guidance if provided
            if self._injected_guidance:
                messages.append({
                    "role": "user",
                    "content": f"[DIRECT USER GUIDANCE — follow this precisely]\n{self._injected_guidance}",
                })
                self._injected_guidance = None

            # Add the current task
            if iteration == 0:
                messages.append({"role": "user", "content": task})
            else:
                messages.append({
                    "role": "user",
                    "content": (
                        f"Continue working on the task. Here's what has happened so far:\n"
                        f"{context_text if accumulated_context else 'No results yet.'}\n\n"
                        f"If the task is complete, respond with [TASK_COMPLETE] at the start. "
                        f"Otherwise, continue with the next tool call or action."
                    ),
                })

            # === L3 SYNTHESIS ===
            t0 = time.time()
            try:
                response = await self.llm.client.complete(
                    messages=messages,
                    model=self.llm.l3_model,
                    temperature=0.7,
                    max_tokens=4000,
                )
                duration = int((time.time() - t0) * 1000)
            except Exception as e:
                error_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.ERROR,
                    title="L3 synthesis failed",
                    detail=str(e),
                    success=False,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                )
                await self._persist_step(error_step)
                yield error_step
                return

            # Track thinking content for reasoning loop detection
            self._thinking_details.append(response[:500])

            # === REASONING LOOP DETECTION ===
            if self._check_reasoning_loop():
                blocker_context = (
                    f"Aura's last {_REASONING_LOOP_WINDOW} thinking steps are nearly identical. "
                    f"She appears stuck in a reasoning loop.\n"
                    f"Last reasoning: {response[:300]}"
                )
                suggested = await self._generate_suggested_action(blocker_context)
                blocker_data = {
                    "type": "reasoning_loop",
                    "tool": None,
                    "attempts": _REASONING_LOOP_WINDOW,
                    "last_error": "Identical reasoning detected",
                    "last_reasoning": response[:300],
                    "suggested_action": suggested,
                }
                # Auto-pause task
                if self.task_id and self.task_queue:
                    await self.task_queue.set_waiting_approval(
                        self.task_id, json.dumps(blocker_data)
                    )
                    await self.task_queue.set_blocker_info(self.task_id, blocker_data)
                escalation_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.ESCALATION,
                    title="Reasoning loop detected",
                    detail=json.dumps(blocker_data),
                    success=False,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                )
                yield escalation_step
                return

            # === CHECK: TASK COMPLETE? ===
            if "[TASK_COMPLETE]" in response[:100]:
                clean_response = response.replace("[TASK_COMPLETE]", "").strip()
                step_num += 1
                complete_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.COMPLETE,
                    title="Task completed",
                    detail=clean_response[:500],
                    result=clean_response,
                    duration_ms=duration,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                )
                await self._persist_step(complete_step)
                yield complete_step
                return

            # === EXTRACT TOOL CALLS ===
            tool_calls = self.executor.extract_tool_calls(response)

            if not tool_calls:
                # No tool calls — this is a text response
                step_num += 1
                resp_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.RESPONSE,
                    title="Aura responded",
                    detail=response[:200],
                    result=response,
                    duration_ms=duration,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                )
                await self._persist_step(resp_step)
                yield resp_step
                # If no tool calls and this isn't the first iteration, task is likely done
                if iteration > 0:
                    step_num += 1
                    done_step = AgentStep(
                        step_number=step_num,
                        step_type=AgentStepType.COMPLETE,
                        title="Task completed (no more actions needed)",
                        result=response,
                        emotional_state_snapshot=await self._capture_emotional_snapshot(),
                    )
                    await self._persist_step(done_step)
                    yield done_step
                    return
                # First iteration with no tools — just a normal response
                return

            # === EXECUTE TOOL CALLS ===
            for tc in tool_calls:
                tool_name = tc.get("tool", "unknown")
                tool_args = tc.get("arguments", {})

                # --- SESSION TOOL ALLOW/DENY CHECK (V1PRD §4) ---
                allowed, reason = self.session_ctx.is_tool_allowed(tool_name)
                if not allowed:
                    step_num += 1
                    deny_step = AgentStep(
                        step_number=step_num,
                        step_type=AgentStepType.ERROR,
                        title=f"Tool blocked by session policy: {tool_name}",
                        detail=reason,
                        tool_name=tool_name,
                        success=False,
                        emotional_state_snapshot=await self._capture_emotional_snapshot(),
                    )
                    await self._persist_step(deny_step)
                    yield deny_step
                    accumulated_context.append(
                        f"[BLOCKED] Tool '{tool_name}' blocked by session policy: {reason}"
                    )
                    continue

                # Check if approval is needed
                if (
                    settings.agent_loop_require_approval
                    and tool_name in self.require_approval
                ):
                    step_num += 1
                    yield AgentStep(
                        step_number=step_num,
                        step_type=AgentStepType.WAITING,
                        title=f"Approval needed: {tool_name}",
                        detail=f"Aura wants to execute '{tool_name}' with args: {json.dumps(tool_args)[:300]}",
                        tool_name=tool_name,
                        tool_args=tool_args,
                        emotional_state_snapshot=await self._capture_emotional_snapshot(),
                    )

                    # Wait for approval (with timeout)
                    self._waiting_for_approval = True
                    self._approval_granted = False
                    wait_start = time.time()
                    while self._waiting_for_approval and (time.time() - wait_start) < 120:
                        await asyncio.sleep(0.5)
                        if self._approval_granted:
                            break
                        if self._abort_flag:
                            yield AgentStep(
                                step_number=step_num,
                                step_type=AgentStepType.ABORTED,
                                title="Loop aborted while waiting for approval",
                            )
                            return

                    self._waiting_for_approval = False
                    if not self._approval_granted:
                        step_num += 1
                        yield AgentStep(
                            step_number=step_num,
                            step_type=AgentStepType.ABORTED,
                            title=f"Action denied: {tool_name}",
                            detail="User did not approve the action",
                            success=False,
                        )
                        accumulated_context.append(
                            f"[DENIED] Tool '{tool_name}' was denied by the user."
                        )
                        continue

                # Execute the tool
                step_num += 1
                call_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.TOOL_CALL,
                    title=f"Executing: {tool_name}",
                    detail=f"Arguments: {json.dumps(tool_args)[:300]}",
                    tool_name=tool_name,
                    tool_args=tool_args,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                )
                await self._persist_step(call_step)
                yield call_step

                t0 = time.time()
                try:
                    result = await self.executor.execute_tool_call(tc, requester_role="owner")
                    exec_duration = int((time.time() - t0) * 1000)
                except Exception as e:
                    exec_duration = int((time.time() - t0) * 1000)
                    step_num += 1
                    err_step = AgentStep(
                        step_number=step_num,
                        step_type=AgentStepType.ERROR,
                        title=f"Tool failed: {tool_name}",
                        detail=str(e),
                        tool_name=tool_name,
                        success=False,
                        duration_ms=exec_duration,
                        emotional_state_snapshot=await self._capture_emotional_snapshot(),
                    )
                    await self._persist_step(err_step)
                    yield err_step

                    # Track failure for blocker detection
                    if self._record_tool_result(tool_name, False):
                        blocker_context = (
                            f"Tool '{tool_name}' has failed {_CONSECUTIVE_FAIL_LIMIT} times consecutively.\n"
                            f"Last error: {str(e)[:300]}\n"
                            f"Last reasoning: {response[:300]}"
                        )
                        suggested = await self._generate_suggested_action(blocker_context)
                        blocker_data = {
                            "type": "repeated_failure",
                            "tool": tool_name,
                            "attempts": _CONSECUTIVE_FAIL_LIMIT,
                            "last_error": str(e)[:300],
                            "last_reasoning": response[:300],
                            "suggested_action": suggested,
                        }
                        if self.task_id and self.task_queue:
                            await self.task_queue.set_waiting_approval(
                                self.task_id, json.dumps(blocker_data)
                            )
                            await self.task_queue.set_blocker_info(self.task_id, blocker_data)
                        esc_step = AgentStep(
                            step_number=step_num,
                            step_type=AgentStepType.ESCALATION,
                            title=f"Repeated failure: {tool_name}",
                            detail=json.dumps(blocker_data),
                            success=False,
                            emotional_state_snapshot=await self._capture_emotional_snapshot(),
                        )
                        yield esc_step
                        return

                    accumulated_context.append(
                        f"[ERROR] Tool '{tool_name}' failed: {str(e)}"
                    )
                    continue

                # --- WAITING_APPROVAL: tool-level HITL gate ---
                if isinstance(result, dict) and result.get("status") == "WAITING_APPROVAL":
                    pending_command = result.get("pending_command", tool_args.get("command", ""))
                    pending_file = result.get("pending_file", tool_args.get("path", ""))
                    is_filesystem = bool(pending_file and not pending_command)

                    if is_filesystem:
                        detail_msg = (
                            f"Aura wants to modify a core file:\n"
                            f"**File:** `{pending_file}`\n"
                            f"{result.get('message', 'User approval required.')}"
                        )
                        approval_type = "filesystem_approval"
                        pending_data = {
                            "type": "filesystem_approval",
                            "tool": tool_name,
                            "pending_file": pending_file,
                            "message": result.get("message", ""),
                        }
                    else:
                        detail_msg = (
                            f"Aura wants to execute a mutative command:\n"
                            f"```\n{pending_command}\n```\n"
                            f"{result.get('message', 'User approval required.')}"
                        )
                        approval_type = "terminal_approval"
                        pending_data = {
                            "type": "terminal_approval",
                            "tool": tool_name,
                            "pending_command": pending_command,
                            "message": result.get("message", ""),
                        }

                    step_num += 1
                    yield AgentStep(
                        step_number=step_num,
                        step_type=AgentStepType.WAITING,
                        title=f"Approval needed: {tool_name}",
                        detail=detail_msg,
                        tool_name=tool_name,
                        tool_args=tool_args,
                        emotional_state_snapshot=await self._capture_emotional_snapshot(),
                    )

                    # Pause the task in SurrealDB
                    if self.task_id and self.task_queue:
                        await self.task_queue.set_waiting_approval(
                            self.task_id,
                            json.dumps(pending_data),
                        )

                    # Wait for approval (with timeout)
                    self._waiting_for_approval = True
                    self._approval_granted = False
                    wait_start = time.time()
                    while self._waiting_for_approval and (time.time() - wait_start) < 120:
                        await asyncio.sleep(0.5)
                        if self._approval_granted:
                            break
                        if self._abort_flag:
                            yield AgentStep(
                                step_number=step_num,
                                step_type=AgentStepType.ABORTED,
                                title="Loop aborted while waiting for approval",
                            )
                            return

                    self._waiting_for_approval = False

                    if not self._approval_granted:
                        step_num += 1
                        if is_filesystem:
                            deny_title = f"File edit denied: {tool_name}"
                            deny_detail = f"User did not approve edit to: {pending_file}"
                            deny_context = f"[DENIED] File edit '{pending_file}' was denied by the user."
                        else:
                            deny_title = f"Terminal command denied: {tool_name}"
                            deny_detail = f"User did not approve: {pending_command[:200]}"
                            deny_context = f"[DENIED] Terminal command '{pending_command[:200]}' was denied by the user."
                        yield AgentStep(
                            step_number=step_num,
                            step_type=AgentStepType.ABORTED,
                            title=deny_title,
                            detail=deny_detail,
                            success=False,
                        )
                        accumulated_context.append(deny_context)
                        continue

                    # Re-execute with runtime approval (W1-02, agency S2).
                    # Approval no longer travels in the model-supplied args; the
                    # executor sets the reserved ``_runtime_approved`` flag
                    # itself when ``approved=True``.
                    approved_args = dict(tool_args)
                    approved_tc = {"tool": tool_name, "arguments": approved_args}

                    t0 = time.time()
                    try:
                        result = await self.executor.execute_tool_call(approved_tc, requester_role="owner", approved=True)
                        exec_duration = int((time.time() - t0) * 1000)
                    except Exception as e:
                        exec_duration = int((time.time() - t0) * 1000)
                        step_num += 1
                        err_step = AgentStep(
                            step_number=step_num,
                            step_type=AgentStepType.ERROR,
                            title=f"Approved action failed: {tool_name}",
                            detail=str(e),
                            tool_name=tool_name,
                            success=False,
                            duration_ms=exec_duration,
                            emotional_state_snapshot=await self._capture_emotional_snapshot(),
                        )
                        await self._persist_step(err_step)
                        yield err_step
                        accumulated_context.append(
                            f"[ERROR] Approved action '{tool_name}' failed: {str(e)}"
                        )
                        continue

                # Report tool result
                result_text = result.get("result", "")
                is_success = result.get("success", False)
                self._record_tool_result(tool_name, is_success)

                # Determine active file for this step
                step_active_file = None
                if tool_name in ("write_file", "edit_file", "read_file") and tool_args.get("path"):
                    step_active_file = tool_args["path"]

                step_num += 1
                result_step = AgentStep(
                    step_number=step_num,
                    step_type=AgentStepType.TOOL_RESULT,
                    title=f"{'✓' if is_success else '✗'} {tool_name} {'succeeded' if is_success else 'failed'}",
                    detail=result_text[:300] if result_text else (result.get("error", "No output")),
                    tool_name=tool_name,
                    result=result_text,
                    success=is_success,
                    duration_ms=exec_duration,
                    emotional_state_snapshot=await self._capture_emotional_snapshot(),
                    active_file=step_active_file,
                )
                await self._persist_step(result_step)
                yield result_step

                # Emit file_write SSE event for Monaco live updates + save version
                if tool_name == "write_file" and is_success and tool_args.get("path"):
                    file_event = AgentStep(
                        step_number=step_num,
                        step_type=AgentStepType.RESPONSE,
                        title="file_written",
                        detail=tool_args["path"],
                        tool_name="write_file",
                        tool_args={"path": tool_args["path"]},
                        result=tool_args.get("content", "")[:10000],
                    )
                    yield file_event

                    # Save file version keyed by task_id:path:step_number
                    if self.task_id and self.task_queue:
                        try:
                            await self.task_queue.save_file_version(
                                task_id=self.task_id,
                                file_path=tool_args["path"],
                                content=tool_args.get("content", "")[:50000],
                                step_number=step_num,
                            )
                        except Exception as e:
                            logger.error(f"Failed to save file version: {e}")

                    # Notify WebSocket watchers
                    try:
                        from aura.api.routes.workspace import notify_file_change
                        await notify_file_change("modified", tool_args["path"], aura_written=True)
                    except Exception:
                        pass

                # Add to accumulated context for next iteration
                accumulated_context.append(
                    f"[TOOL: {tool_name}] {'SUCCESS' if is_success else 'FAILED'}: "
                    f"{result_text[:1000] if result_text else result.get('error', 'No output')}"
                )

            # === HEARTBEAT after tool batch ===
            if self._should_emit_heartbeat():
                yield self._make_heartbeat(step_num)

        # Max iterations reached
        step_num += 1
        final_step = AgentStep(
            step_number=step_num,
            step_type=AgentStepType.COMPLETE,
            title=f"Max iterations reached ({self.max_iterations})",
            detail="The agent loop reached its iteration limit. Review results above.",
            emotional_state_snapshot=await self._capture_emotional_snapshot(),
        )
        await self._persist_step(final_step)
        yield final_step

    def _build_agent_system_prompt(self, extra_context: str = "") -> str:
        """Build the system prompt for agent loop mode."""
        # Inject identity overlay if present (V1PRD §4)
        overlay = self.session_ctx.identity_overlay
        identity_block = ""
        if overlay:
            parts = []
            if overlay.narrative_suffix:
                parts.append(overlay.narrative_suffix)
            if overlay.core_values:
                vals = ", ".join(
                    f"{k}={v:.2f}" for k, v in sorted(overlay.core_values.items())
                )
                parts.append(f"Core-value weights: {vals}")
            if parts:
                identity_block = "\n\nIDENTITY CONTEXT (session overlay):\n" + "\n".join(parts)

        return f"""You are Aura, an autonomous AI agent executing a multi-step task.{identity_block}

CAPABILITIES:
You have access to these tools (use JSON format to call them):
- read_file: Read file contents
- write_file: Write/create files
- edit_file: Edit files (find-and-replace)
- list_directory: List directory contents
- directory_tree: Get directory structure
- search_files: Search for files by pattern
- create_directory: Create directories
- delete_file: Delete files/empty dirs
- web_search: Search the web
- execute_code: Run code in a sandbox (if enabled)
- terminal: Execute shell commands (safe commands auto-run; mutative commands require approval)
- generate_chart: Create interactive Chart.js charts (doughnut, bar, line, pie, etc.) — renders as a popup in chat

TOOL CALL FORMAT:
```json
{{"tool": "tool_name", "arguments": {{"arg1": "value1"}}}}
```

RULES:
1. Think step-by-step about what needs to be done
2. Execute one tool at a time, review the result, then decide next action
3. When the task is fully complete, start your response with [TASK_COMPLETE]
4. Be efficient — minimize unnecessary tool calls
5. If you encounter an error, try to recover or explain what went wrong
6. Always explain what you're doing and why in natural language BEFORE the tool call

{extra_context}"""

    async def _persist_step(self, step: AgentStep) -> None:
        """Persist a step to SurrealDB via the task queue (crash safety)."""
        if not self.task_id or not self.task_queue:
            return
        try:
            from aura.models.task import TaskStepRecord, EmotionalSnapshot
            record_data = step.to_task_step_record()
            # Convert emotional snapshot dict to model
            if record_data.get("emotional_state_snapshot"):
                record_data["emotional_state_snapshot"] = EmotionalSnapshot(
                    **record_data["emotional_state_snapshot"]
                )
            record = TaskStepRecord(**record_data)
            await self.task_queue.persist_step(self.task_id, record)
        except Exception as e:
            logger.error(f"Failed to persist step {step.step_number}: {e}")
