"""Task API routes for Aura's persistent task engine.

Provides CRUD endpoints for tasks, designed for future multi-Aura
federation — another Aura instance could query your task queue.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aura.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Global references (set during startup)
_task_queue: Any = None
_agent_loop_runner: Any = None


def set_dependencies(task_queue: Any, agent_loop_runner: Any = None) -> None:
    """Set dependencies from main.py lifespan."""
    global _task_queue, _agent_loop_runner
    _task_queue = task_queue
    _agent_loop_runner = agent_loop_runner


def _get_tq() -> Any:
    if _task_queue is None:
        raise HTTPException(status_code=503, detail="Task queue not initialized")
    return _task_queue


# ============================================================================
# SCHEMAS
# ============================================================================

class CreateTaskRequest(BaseModel):
    goal: str = Field(..., description="Natural-language goal for Aura")
    workspace_path: str = Field(default="", description="Override workspace path")


class TaskResponse(BaseModel):
    success: bool = True
    task: dict[str, Any] | None = None
    tasks: list[dict[str, Any]] | None = None
    message: str = ""


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("")
async def list_tasks(
    status: str | None = None,
    limit: int = 50,
) -> TaskResponse:
    """List all tasks with optional status filter."""
    tq = _get_tq()
    tasks = await tq.get_tasks(status_filter=status, limit=limit)
    return TaskResponse(
        tasks=[t.model_dump(mode="json") for t in tasks],
    )


@router.post("")
async def create_task(request: CreateTaskRequest) -> TaskResponse:
    """Create a new task for Aura to execute."""
    tq = _get_tq()
    workspace = request.workspace_path or settings.aura_workspace_path or ""
    task = await tq.create_task(goal=request.goal, workspace_path=workspace)
    return TaskResponse(
        task=task.model_dump(mode="json"),
        message=f"Task created: {task.task_id}",
    )


@router.get("/active")
async def get_active_task() -> TaskResponse:
    """Get the currently running task."""
    tq = _get_tq()
    task = await tq.get_active_task()
    if not task:
        return TaskResponse(task=None, message="No active task")
    return TaskResponse(task=task.model_dump(mode="json"))


@router.get("/history")
async def get_task_history(limit: int = 20) -> TaskResponse:
    """Get completed/failed tasks."""
    tq = _get_tq()
    tasks = await tq.get_task_history(limit=limit)
    return TaskResponse(
        tasks=[t.model_dump(mode="json") for t in tasks],
    )


@router.get("/{task_id}")
async def get_task(task_id: str) -> TaskResponse:
    """Get a specific task by ID."""
    tq = _get_tq()
    # Normalize: accept both "task:abc" and "abc"
    if not task_id.startswith("task:"):
        task_id = f"task:{task_id}"
    task = await tq.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return TaskResponse(task=task.model_dump(mode="json"))


@router.post("/{task_id}/pause")
async def pause_task(task_id: str) -> TaskResponse:
    """Pause a running task."""
    tq = _get_tq()
    if not task_id.startswith("task:"):
        task_id = f"task:{task_id}"
    task = await tq.pause_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return TaskResponse(
        task=task.model_dump(mode="json"),
        message="Task paused",
    )


@router.post("/{task_id}/resume")
async def resume_task(task_id: str) -> TaskResponse:
    """Resume a paused task."""
    tq = _get_tq()
    if not task_id.startswith("task:"):
        task_id = f"task:{task_id}"
    task = await tq.resume_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return TaskResponse(
        task=task.model_dump(mode="json"),
        message="Task resumed",
    )


@router.delete("/{task_id}")
async def delete_task(task_id: str) -> TaskResponse:
    """Delete a task."""
    tq = _get_tq()
    if not task_id.startswith("task:"):
        task_id = f"task:{task_id}"
    success = await tq.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return TaskResponse(message=f"Task deleted: {task_id}")
