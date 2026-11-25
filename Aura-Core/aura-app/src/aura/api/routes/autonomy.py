"""Owner controls and kill switch (B1-06), autonomy slider (P2-33).
Owner-only by posture: the API is unauthenticated."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aura.autonomy import budget as curiosity_budget
from aura.autonomy import (
    command,
    controls,
    initiative,  # noqa: F401 - registers the proposal answer hooks
    learning,
    registry,
)
from aura.config import settings

router = APIRouter()


class LevelBody(BaseModel):
    # P2-33: 0..3; the B1-01 names are still accepted (silent 0, important 1, open 3).
    level: int | Literal["silent", "important", "open"] = Field(...)


class KindBody(BaseModel):
    kind: str


async def _changed(c: controls.Controls, action: str, why: str) -> dict[str, Any]:
    return await command.announce(c, action, why)


@router.get("/autonomy")
async def get_autonomy() -> dict[str, Any]:
    return await command.state_for(await controls.get_controls())


@router.put("/autonomy/level")
async def put_level(body: LevelBody) -> dict[str, Any]:
    try:
        return await command.change_level(body.level, "dashboard")
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None


@router.post("/autonomy/mute")
async def mute(body: KindBody) -> dict[str, Any]:
    if not body.kind.strip():
        raise HTTPException(status_code=400, detail="kind is required")
    return await _changed(await controls.mute_kind(body.kind), "mute", f"muted {body.kind}")


@router.post("/autonomy/unmute")
async def unmute(body: KindBody) -> dict[str, Any]:
    return await _changed(await controls.unmute_kind(body.kind), "unmute", f"unmuted {body.kind}")


@router.post("/autonomy/kill")
async def kill() -> dict[str, Any]:
    result = await registry.kill()
    state = await _changed(await controls.get_controls(), "kill", "kill switch")
    return {**result, "state": state}


@router.post("/autonomy/resume")
async def resume() -> dict[str, Any]:
    """Clear the kill flag. Nothing that was cancelled is restarted."""
    return await _changed(await controls.set_killed(False), "resume", "kill cleared")


@router.get("/autonomy/stats")
async def autonomy_stats() -> dict[str, Any]:
    """Per-kind delivery counters and reply rate (acknowledged over delivered)."""
    return {"enabled": settings.dismissal_learning_enabled, "kinds": await learning.stats_report()}


@router.get("/autonomy/budget")
async def get_autonomy_budget() -> dict[str, Any]:
    """Remaining curiosity daily budget for the mind panel (B4-03, B7)."""
    if not settings.curiosity_enabled:
        return {"enabled": False}
    remaining = await curiosity_budget.get_remaining()
    remaining["enabled"] = True
    return remaining
