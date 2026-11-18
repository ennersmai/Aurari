"""Session API routes — V1PRD §4.7.

Surfaces SessionRuntime over HTTP. Default behaviour is unchanged for
existing clients: every legacy route still routes to the MAIN session
when `session_id` is absent, so this is purely additive.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aura.models.session import (
    MAIN_SESSION_ID,
    IdentityOverlay,
    Session,
    SessionMode,
    SessionStatus,
)
from aura.orchestrator.session_runtime import (
    ConcurrencyLimitError,
    SessionRuntime,
    SessionRuntimeError,
    get_session_runtime,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions", tags=["sessions"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class CreateSessionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    mode: SessionMode = Field(default=SessionMode.SCOPED)
    owner: str = Field(default="default")
    parent_session_id: str | None = None
    identity_overlay: IdentityOverlay | None = None
    model_overrides: dict[str, str] = Field(default_factory=dict)
    tool_allowlist: list[str] | None = None
    tool_denylist: list[str] = Field(default_factory=list)
    max_concurrent_agents: int = Field(default=3, ge=1, le=16)
    emotion_isolated: bool = Field(
        default=False,
        description=(
            "ESCAPE HATCH ONLY. Aura's emotion is shared by design — see "
            "`feedback_emotion_consistency.md`. Setting True here is a "
            "deliberate stress-test override."
        ),
    )


class UpdateSessionRequest(BaseModel):
    name: str | None = None
    model_overrides: dict[str, str] | None = None
    tool_allowlist: list[str] | None = None
    tool_denylist: list[str] | None = None
    max_concurrent_agents: int | None = Field(default=None, ge=1, le=16)
    identity_overlay: IdentityOverlay | None = None


class EndSessionRequest(BaseModel):
    merge_emotion: bool = False
    archive_memory: bool = True


class SessionResponse(BaseModel):
    success: bool = True
    session: dict[str, Any] | None = None
    sessions: list[dict[str, Any]] | None = None
    message: str = ""


class SessionStateResponse(BaseModel):
    session: dict[str, Any]
    attached_agent_ids: list[str]
    main: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalise(session_id: str) -> str:
    """Accept 'main', 'session:abc', or bare 'abc'; return canonical form."""
    if session_id == MAIN_SESSION_ID or session_id == "session:main":
        return MAIN_SESSION_ID
    if session_id.startswith("session:"):
        return session_id
    return f"session:{session_id}"


def _runtime() -> SessionRuntime:
    rt = get_session_runtime()
    return rt


def _serialize(session: Session) -> dict[str, Any]:
    return session.model_dump(mode="json")


def _to_4xx(exc: Exception) -> HTTPException:
    if isinstance(exc, ConcurrencyLimitError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, SessionRuntimeError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=SessionResponse)
async def create_session(request: CreateSessionRequest) -> SessionResponse:
    rt = _runtime()
    try:
        session = await rt.create_session(
            name=request.name,
            mode=request.mode,
            owner=request.owner,
            parent_session_id=request.parent_session_id,
            identity_overlay=request.identity_overlay,
            model_overrides=request.model_overrides,
            tool_allowlist=request.tool_allowlist,
            tool_denylist=request.tool_denylist,
            max_concurrent_agents=request.max_concurrent_agents,
            emotion_isolated=request.emotion_isolated,
        )
    except SessionRuntimeError as e:
        raise _to_4xx(e) from e
    return SessionResponse(
        session=_serialize(session),
        message=f"Session created: {session.session_id}",
    )


@router.get("", response_model=SessionResponse)
async def list_sessions(
    status: SessionStatus | None = None,
    owner: str | None = None,
    limit: int = 50,
) -> SessionResponse:
    rt = _runtime()
    sessions = await rt.list_sessions(status=status, owner=owner, limit=limit)
    return SessionResponse(sessions=[_serialize(s) for s in sessions])


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str) -> SessionResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    session = await rt.get_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session))


@router.patch("/{session_id}", response_model=SessionResponse)
async def update_session(session_id: str, request: UpdateSessionRequest) -> SessionResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    patch = request.model_dump(exclude_unset=True, mode="json")
    if not patch:
        raise HTTPException(status_code=400, detail="no fields to update")
    try:
        session = await rt.update_session(sid, patch)
    except SessionRuntimeError as e:
        raise _to_4xx(e) from e
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session), message="Updated")


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@router.post("/{session_id}/start", response_model=SessionResponse)
async def start_session(session_id: str) -> SessionResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    session = await rt.start_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session), message="Started")


@router.post("/{session_id}/pause", response_model=SessionResponse)
async def pause_session(session_id: str) -> SessionResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    try:
        session = await rt.pause_session(sid)
    except SessionRuntimeError as e:
        raise _to_4xx(e) from e
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session), message="Paused")


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session(session_id: str) -> SessionResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    session = await rt.resume_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session), message="Resumed")


@router.post("/{session_id}/end", response_model=SessionResponse)
async def end_session(session_id: str, request: EndSessionRequest) -> SessionResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    try:
        session = await rt.end_session(
            sid,
            merge_emotion=request.merge_emotion,
            archive_memory=request.archive_memory,
        )
    except SessionRuntimeError as e:
        raise _to_4xx(e) from e
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session), message="Ended")


@router.delete("/{session_id}", response_model=SessionResponse)
async def delete_session(session_id: str) -> SessionResponse:
    """Delete a session permanently (V1PRD §4.7).

    Ends the session first (stopping any attached agents), then removes
    the record from SurrealDB. The MAIN session cannot be deleted.
    """
    rt = _runtime()
    sid = _normalise(session_id)
    if sid == MAIN_SESSION_ID:
        raise HTTPException(status_code=400, detail="MAIN session cannot be deleted")
    try:
        session = await rt.delete_session(sid)
    except SessionRuntimeError as e:
        raise _to_4xx(e) from e
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    return SessionResponse(session=_serialize(session), message="Deleted")


# ---------------------------------------------------------------------------
# Live state
# ---------------------------------------------------------------------------


@router.get("/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(session_id: str) -> SessionStateResponse:
    rt = _runtime()
    sid = _normalise(session_id)
    session = await rt.get_session(sid)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {sid}")
    attached = await rt.list_attached_agents(sid)
    return SessionStateResponse(
        session=_serialize(session),
        attached_agent_ids=attached,
        main=(sid == MAIN_SESSION_ID),
    )


@router.get("/{session_id}/tasks", response_model=dict[str, Any])
async def get_session_tasks(session_id: str, limit: int = 50) -> dict[str, Any]:
    """Tasks scoped to this session. Reads via the task queue singleton."""
    from aura.executor.task_queue import get_task_queue

    sid = _normalise(session_id)
    tq = get_task_queue()
    tasks = await tq.get_tasks(session_id=sid, limit=limit)
    return {
        "session_id": sid,
        "tasks": [t.model_dump(mode="json") for t in tasks],
    }
