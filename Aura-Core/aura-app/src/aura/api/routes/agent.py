"""
Agent Loop API Routes

Provides endpoints for free-running agent execution with
real-time human-readable status streaming via SSE.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from aura.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])

# Global references (set during startup)
_llm_layers = None
_tool_executor = None
_task_queue = None
_emotion_engine = None
_active_loops: dict[str, Any] = {}  # task_id -> AgentLoop instance


def set_dependencies(
    llm_layers: Any,
    tool_executor: Any,
    task_queue: Any = None,
    emotion_engine: Any = None,
) -> None:
    """Set dependencies from main.py lifespan."""
    global _llm_layers, _tool_executor, _task_queue, _emotion_engine
    _llm_layers = llm_layers
    _tool_executor = tool_executor
    _task_queue = task_queue
    _emotion_engine = emotion_engine


class AgentTaskRequest(BaseModel):
    """Request to start an agent loop."""
    task: str = Field(description="The task for Aura to execute autonomously")
    conversation_history: list[dict[str, str]] = Field(
        default=[],
        description="Prior conversation context"
    )
    max_iterations: int | None = Field(
        default=None,
        description="Override max iterations (default from config)"
    )
    system_context: str = Field(
        default="",
        description="Additional system context (e.g., emotional state)"
    )
    session_id: str = Field(
        default="main",
        description=(
            "Session this agent runs under (V1PRD §4). Defaults to the MAIN "
            "session — backward-compatible with pre-Sessions clients."
        ),
    )


class AgentApprovalRequest(BaseModel):
    """Request to approve/deny a pending agent action."""
    task_id: str = Field(description="ID of the agent task")
    approved: bool = Field(description="Whether to approve the pending action")


@router.post("/run")
async def run_agent_task(request: AgentTaskRequest) -> StreamingResponse:
    """
    Start a free-running agent loop that streams human-readable steps.
    
    Returns SSE stream with step-by-step progress:
    - thinking: L3 is reasoning
    - tool_call: Executing a tool
    - tool_result: Tool returned result
    - response: Text response
    - waiting: Needs human approval
    - complete: Task finished
    - error: Something failed
    """
    if not _llm_layers or not _tool_executor:
        raise HTTPException(
            status_code=503,
            detail="Agent loop dependencies not initialized"
        )

    from aura.executor.agent_loop import AgentLoop
    from aura.orchestrator.session_runtime import (
        ConcurrencyLimitError,
        SessionRuntimeError,
        get_session_runtime,
    )

    # Validate / resolve session and reserve an agent slot
    session_runtime = get_session_runtime()
    try:
        session_ctx = await session_runtime.context_for(request.session_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"invalid session: {e}") from e

    # Create persistent task if task queue is available
    persistent_task_id: str | None = None
    if _task_queue:
        try:
            task_obj = await _task_queue.create_task(
                goal=request.task,
                workspace_path=settings.aura_workspace_path or "",
                session_id=session_ctx.session_id,
            )
            persistent_task_id = task_obj.task_id
            await _task_queue.start_task(persistent_task_id)
        except Exception as e:
            logger.error(f"Failed to create persistent task: {e}")

    # Reserve a concurrency slot in the session (best-effort; release on stream close)
    if persistent_task_id:
        try:
            await session_runtime.attach_agent(session_ctx.session_id, persistent_task_id)
        except ConcurrencyLimitError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        except SessionRuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    task_id = persistent_task_id or f"agent-{id(request)}"
    loop = AgentLoop(
        llm_layers=_llm_layers,
        tool_executor=_tool_executor,
        max_iterations=request.max_iterations,
        task_id=persistent_task_id,
        task_queue=_task_queue,
        emotion_engine=_emotion_engine,
        session_ctx=session_ctx,
    )
    _active_loops[task_id] = loop

    async def event_stream():
        """Generate SSE events from agent loop steps."""
        try:
            # Send task_id as first event
            yield f"data: {json.dumps({'type': 'started', 'task_id': task_id})}\n\n"

            async for step in loop.run(
                task=request.task,
                conversation_history=request.conversation_history,
                system_context=request.system_context,
            ):
                yield step.to_sse_event()
                # Small delay to prevent overwhelming the client
                await asyncio.sleep(0.05)

            # Mark persistent task as complete
            if persistent_task_id and _task_queue:
                await _task_queue.complete_task(persistent_task_id)

            yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
        except Exception as e:
            logger.error(f"Agent loop error: {e}", exc_info=True)
            # Mark persistent task as failed
            if persistent_task_id and _task_queue:
                await _task_queue.fail_task(persistent_task_id, str(e))
            yield f"data: {json.dumps({'type': 'error', 'detail': str(e)})}\n\n"
        finally:
            _active_loops.pop(task_id, None)
            # Release the session agent slot (no-op for non-persistent tasks)
            if persistent_task_id:
                try:
                    await session_runtime.detach_agent(
                        session_ctx.session_id, persistent_task_id
                    )
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"detach_agent failed: {e}")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Task-Id": task_id,
        },
    )


@router.post("/approve")
async def approve_agent_action(request: AgentApprovalRequest) -> dict[str, Any]:
    """Approve or deny a pending agent action."""
    loop = _active_loops.get(request.task_id)
    if not loop:
        raise HTTPException(
            status_code=404,
            detail=f"No active agent loop with task_id: {request.task_id}"
        )

    if request.approved:
        loop.grant_approval()
        return {"success": True, "action": "approved"}
    else:
        loop.deny_approval()
        return {"success": True, "action": "denied"}


@router.post("/abort/{task_id}")
async def abort_agent_task(task_id: str) -> dict[str, Any]:
    """Abort a running agent loop."""
    loop = _active_loops.get(task_id)
    if not loop:
        raise HTTPException(
            status_code=404,
            detail=f"No active agent loop with task_id: {task_id}"
        )

    loop.abort()
    return {"success": True, "message": "Abort signal sent"}


@router.get("/active")
async def list_active_tasks() -> dict[str, Any]:
    """List currently active agent loops."""
    return {
        "active_tasks": list(_active_loops.keys()),
        "count": len(_active_loops),
    }


@router.post("/all/pause")
async def pause_all_agents() -> dict[str, Any]:
    """Pause all running agent loops (V1PRD §4.7)."""
    count = 0
    for task_id, loop in list(_active_loops.items()):
        try:
            loop.abort()
            count += 1
        except Exception as e:
            logger.warning(f"Failed to pause agent {task_id}: {e}")
    return {"success": True, "paused": count, "message": f"Pause signal sent to {count} agent(s)"}


@router.post("/all/abort")
async def abort_all_agents() -> dict[str, Any]:
    """Abort all running agent loops and clear tracking (V1PRD §4.7)."""
    count = len(_active_loops)
    for task_id, loop in list(_active_loops.items()):
        try:
            loop.abort()
        except Exception as e:
            logger.warning(f"Failed to abort agent {task_id}: {e}")
    _active_loops.clear()
    return {"success": True, "aborted": count, "message": f"Aborted {count} agent(s)"}


class GuidanceRequest(BaseModel):
    """User guidance to unblock a stuck agent."""
    task_id: str = Field(description="Task to inject guidance into")
    guidance: str = Field(description="User's guidance text")
    mode: str = Field(
        default="guidance",
        description="'guidance' to resume with hint, 'change_approach' to restart from last success",
    )


@router.post("/guidance")
async def inject_guidance(request: GuidanceRequest) -> dict[str, Any]:
    """Inject user guidance into a stuck agent loop and resume.

    This is the escalation recovery path: the user provides guidance,
    it goes into task memory with confidence 1.0, and the agent resumes.
    """
    loop = _active_loops.get(request.task_id)

    # Store guidance in task memory
    if _task_queue:
        try:
            await _task_queue.store_ide_chat_message(
                task_id=request.task_id,
                role="user",
                content=f"[GUIDANCE] {request.guidance}",
                file_context="escalation_response",
            )
            await _task_queue.clear_blocker(request.task_id)
        except Exception as e:
            logger.error(f"Failed to store guidance: {e}")

    if loop:
        # Active loop — inject guidance directly
        if request.mode == "change_approach":
            loop._tool_failure_counts.clear()
            loop._thinking_details.clear()
        loop.inject_guidance(request.guidance)
        loop.grant_approval()  # Unblock if waiting
        return {"success": True, "action": "guidance_injected", "mode": request.mode}

    # Loop not active — need to restart it
    # The frontend should re-trigger the agent run after this
    return {
        "success": True,
        "action": "guidance_stored",
        "mode": request.mode,
        "note": "Agent loop not active. Re-start the task to apply guidance.",
    }
