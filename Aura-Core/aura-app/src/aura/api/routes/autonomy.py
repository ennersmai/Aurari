"""Owner controls and kill switch (B1-06). Owner-only by posture: the API is unauthenticated."""

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from aura.autonomy import channel, controls, registry, trace
from aura.autonomy.delivery import get_deliverer
from aura.config import settings

router = APIRouter()


class LevelBody(BaseModel):
    level: Literal["silent", "important", "open"]


class KindBody(BaseModel):
    kind: str


def _state(c: controls.Controls) -> dict[str, Any]:
    return {
        "level": c.level,
        "muted_kinds": list(c.muted_kinds),
        "killed": c.killed,
        "killed_at": c.killed_at.isoformat() if c.killed_at else None,
        "quiet_hours": {
            "start": settings.quiet_hours_start,
            "end": settings.quiet_hours_end,
            "active": controls.quiet_hours_active(),
        },
        "autonomy_enabled": settings.autonomy_enabled,
        "workspace_enabled": settings.workspace_enabled,
    }


async def _changed(c: controls.Controls, action: str, why: str) -> dict[str, Any]:
    state = _state(c)
    await trace.record("owner", f"controls:{action}", why)
    await channel.publish("autonomy_state", state)
    await get_deliverer().notify()
    return state


@router.get("/autonomy")
async def get_autonomy() -> dict[str, Any]:
    return _state(await controls.get_controls())


@router.put("/autonomy/level")
async def put_level(body: LevelBody) -> dict[str, Any]:
    return await _changed(await controls.set_level(body.level), "level", f"level set to {body.level}")


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
