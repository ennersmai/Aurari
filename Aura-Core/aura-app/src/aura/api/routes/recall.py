"""Recall Engine trace API routes.

Provides access to the in-memory recall traces stored by the RecallEngine
(PRD section 6.6, milestone M2). Traces are kept in memory only and are
not persisted to the database.
"""

import dataclasses
from datetime import datetime

from fastapi import APIRouter, HTTPException

from aura.engines.recall.engine import get_recall_engine

router = APIRouter()


@router.get("/trace/{turn_id}")
async def get_recall_trace(turn_id: str) -> dict:
    """Get a single recall trace by turn ID.

    Args:
        turn_id: The turn identifier (hex string from uuid.uuid4().hex)

    Returns:
        The trace as a dictionary with created_at as ISO format string.

    Raises:
        HTTPException: 404 if the trace is not found (evicted or never stored).
    """
    recall_engine = get_recall_engine()
    trace = recall_engine.get_trace(turn_id)

    if trace is None:
        raise HTTPException(
            status_code=404,
            detail="trace not found",
        )

    # Convert to dict with created_at as ISO string
    trace_dict = dataclasses.asdict(trace)
    if isinstance(trace_dict.get("created_at"), datetime):
        trace_dict["created_at"] = trace_dict["created_at"].isoformat()
    # TraceItem objects in items list also need conversion if they have datetime fields
    # (they don't currently, but handle generically)
    return trace_dict


@router.get("/traces")
async def list_recall_traces() -> dict[str, list[str]]:
    """List all stored recall trace turn IDs, newest first.

    Returns:
        Dictionary with "turn_ids" key containing list of turn IDs.
    """
    recall_engine = get_recall_engine()
    # OrderedDict is ordered by insertion (oldest first), so reverse for newest first
    turn_ids = list(recall_engine._traces.keys())[::-1]
    return {"turn_ids": turn_ids}