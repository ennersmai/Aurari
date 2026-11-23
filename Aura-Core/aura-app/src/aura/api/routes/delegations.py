"""Delegation controls API (G4-01).

GET  /delegations                    - running and recently closed delegated tasks
GET  /delegations/opencode-url       - the managed OpenCode server's base URL (no auth)
GET  /delegations/{task_id}          - one delegated task with all its steps
GET  /delegations/{task_id}/diff     - the session diff, from OpenCode (never local files)
POST /delegations/{task_id}/abort    - abort one running delegation
POST /delegations/{task_id}/guidance - send guidance into a running session
POST /delegations/abort-all | pause-all | resume-all

A delegated task is one whose ``session_id`` is an OpenCode session id (not the
Aura session "main"). Unauthenticated like the rest of the API (known FOR_MAI item).
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, HTTPException

from aura.config import settings
from aura.connections.opencode_client import OpenCodeError, OpenCodeUnavailable
from aura.executor import delegation
from aura.executor.decisions import get_decision_service
from aura.executor.task_queue import get_task_queue
from aura.models.task import Task, TaskStatus

router = APIRouter(prefix="/delegations", tags=["delegations"])
logger = logging.getLogger(__name__)


def _is_delegated(task: Task) -> bool:
    return bool(task.delegated) and bool(task.session_id) and task.session_id != "main"


def _blocker(task: Task) -> dict[str, Any] | str | None:
    """The blocker in the Workbench shape: {kind, reason, suggestion} from G4-02's
    BlockerInfo, else the plain blocker text."""
    info = task.blocker_info
    if info is not None:
        return {
            "kind": info.type,
            "reason": info.last_reasoning or info.last_error or (task.blocker or ""),
            "suggestion": info.suggested_action or None,
        }
    return task.blocker


def _summary(task: Task, pending_ids: list[str], steps: int | None) -> dict[str, Any]:
    runner = delegation.get_runner(task.task_id)
    shown = task.steps if steps is None else task.steps[-steps:]
    return {
        "task_id": task.task_id,
        "state": TaskStatus(task.status).value,
        "brief": task.goal,
        "session_id": task.session_id,
        "workspace": task.workspace_path,
        "budget": runner.budget_snapshot() if runner else None,
        "steps": [s.model_dump(mode="json") for s in shown],
        "step_count": len(task.steps),
        "blocker": _blocker(task),
        "pending_decision_ids": pending_ids,
        "created_at": task.created_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }


async def _pending_by_task() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for d in await get_decision_service().pending():
        tid = d.get("task_id")
        if tid:
            out.setdefault(delegation._norm_id(tid), []).append(delegation._norm_id(d.get("id", "")))
    return out


async def _load(task_id: str) -> Task:
    """The delegated task, or 404."""
    task = await get_task_queue().get_task(delegation._norm_id(task_id))
    if task is None or not _is_delegated(task):
        raise HTTPException(status_code=404, detail="Delegated task not found")
    return task


def _client_for(task: Task):
    """The OpenCode client for a task: its runner's, else the shared one."""
    runner = delegation.get_runner(task.task_id)
    client = runner.client if runner else None
    if client is None:
        client = getattr(get_decision_service(), "_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="OpenCode client not available")
    return client


@router.get("")
async def list_delegations() -> dict[str, Any]:
    tasks = await get_task_queue().get_delegated_tasks(settings.delegation_closed_list_limit)
    pending = await _pending_by_task()
    items = [
        _summary(t, pending.get(delegation._norm_id(t.task_id), []), settings.delegation_list_steps_limit)
        for t in tasks
        if _is_delegated(t)
    ]
    return {"success": True, "paused": delegation.delegations_paused(), "delegations": items, "count": len(items)}


@router.get("/opencode-url")
async def opencode_url() -> dict[str, Any]:
    """The managed server's base URL, or null when it is not running. No auth."""
    for runner in delegation.running_runners():
        url = runner.base_url()
        if url:
            return {"url": url}
    return {"url": None}


@router.post("/abort-all")
async def abort_all() -> dict[str, Any]:
    aborted: list[str] = []
    for runner in delegation.running_runners():
        try:
            await runner.abort()
            aborted.append(runner.task_id)
        except Exception as e:
            logger.error(f"abort-all: failed for {runner.task_id}: {e}")
    return {"success": True, "aborted": aborted, "count": len(aborted)}


@router.post("/pause-all")
async def pause_all() -> dict[str, Any]:
    delegation.pause_all()
    return {"success": True, "paused": True}


@router.post("/resume-all")
async def resume_all() -> dict[str, Any]:
    delegation.resume_all()
    return {"success": True, "paused": False}


@router.get("/{task_id}")
async def get_delegation(task_id: str) -> dict[str, Any]:
    task = await _load(task_id)
    pending = await _pending_by_task()
    return {"success": True, "delegation": _summary(task, pending.get(delegation._norm_id(task.task_id), []), None)}


@router.post("/{task_id}/abort")
async def abort_delegation(task_id: str) -> dict[str, Any]:
    task = await _load(task_id)
    runner = delegation.get_runner(task.task_id)
    if runner is not None:
        await runner.abort()
        return {"success": True, "task_id": task.task_id}
    if task.status not in (TaskStatus.RUNNING, TaskStatus.WAITING_APPROVAL, TaskStatus.QUEUED, TaskStatus.PAUSED):
        raise HTTPException(status_code=409, detail="Delegation is not running")
    # No runner (e.g. after a restart): ask OpenCode directly, fail the task regardless.
    try:
        await _client_for(task).abort(task.session_id)
    except HTTPException:
        logger.warning(f"No OpenCode client to abort {task.task_id}; failing the task only")
    except (OpenCodeUnavailable, OpenCodeError) as e:
        logger.error(f"Abort of session {task.session_id} failed: {e}")
    await get_task_queue().fail_task(task.task_id, reason="aborted by owner")
    return {"success": True, "task_id": task.task_id}


@router.post("/{task_id}/guidance")
async def send_guidance(task_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    text = body.get("text")
    if not isinstance(text, str) or not text.strip():
        raise HTTPException(status_code=422, detail="text is required")
    if len(text) > settings.delegation_guidance_max_chars:
        raise HTTPException(
            status_code=422,
            detail=f"text is limited to {settings.delegation_guidance_max_chars} characters",
        )
    task = await _load(task_id)
    if task.status != TaskStatus.RUNNING:
        raise HTTPException(status_code=409, detail="Guidance can only be sent to a running delegation")
    runner = delegation.get_runner(task.task_id)
    try:
        if runner is not None:
            await runner.send_guidance(text)
        else:
            await _client_for(task).send(task.session_id, text)
            await get_task_queue().persist_step(
                task.task_id, delegation.guidance_step(len(task.steps) + 1, text)
            )
    except OpenCodeUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OpenCodeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"success": True, "task_id": task.task_id}


@router.get("/{task_id}/diff")
async def get_diff(task_id: str) -> dict[str, Any]:
    task = await _load(task_id)
    try:
        result = await _client_for(task).result(task.session_id)
    except OpenCodeUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except OpenCodeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {
        "success": True,
        "task_id": task.task_id,
        "files_changed": list(result.files_changed or []),
        "additions": result.additions or 0,
        "deletions": result.deletions or 0,
        "summary": result.summary or "",
    }
