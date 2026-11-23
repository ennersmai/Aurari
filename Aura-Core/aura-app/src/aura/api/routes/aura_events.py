"""Polling fallback for the /ws/aura channel (B1-04)."""

from typing import Any

from fastapi import APIRouter

from aura.autonomy import channel

router = APIRouter()


@router.get("/aura/events")
async def get_aura_events(since_seq: int = 0) -> dict[str, Any]:
    """Buffered channel events after ``since_seq``, oldest first."""
    return {"events": channel.events_since(since_seq), "last_seq": channel.last_seq()}
