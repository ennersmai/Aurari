"""Agenda endpoints (B1-05). Owner-only by posture: the API is unauthenticated."""

from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aura.autonomy import channel
from aura.autonomy.agenda import STATES, AgendaService
from aura.autonomy.delivery import get_deliverer, item_to_dict

router = APIRouter()


class AgendaCreate(BaseModel):
    kind: Literal["reminder", "observation"] = "reminder"
    content: str = Field(min_length=1)
    refs: list[str] = Field(default_factory=lambda: ["owner:manual"])
    due_at: datetime | None = None
    expires_at: datetime | None = None
    priority: float = 0.5


@router.get("/agenda")
async def list_agenda(state: str | None = None) -> dict[str, Any]:
    states = [s.strip() for s in state.split(",") if s.strip()] if state else ["pending", "delivered"]
    bad = [s for s in states if s not in STATES]
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown state: {bad[0]}")
    items = await AgendaService().list(states)
    return {"items": [item_to_dict(i) for i in items]}


@router.post("/agenda")
async def create_agenda_item(body: AgendaCreate) -> dict[str, Any]:
    svc = AgendaService()
    try:
        item = await svc.create(
            body.kind,
            body.content,
            body.refs or ["owner:manual"],
            body.priority,
            expires_at=body.expires_at,
            due_at=body.due_at,
            source="owner",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await channel.publish("agenda_update", item_to_dict(item))
    await get_deliverer().notify()
    current = await svc.get(item.id)
    return item_to_dict(current or item)


async def _resolve(item_id: str, action: str) -> dict[str, Any]:
    svc = AgendaService()
    if await svc.get(item_id) is None:
        raise HTTPException(status_code=404, detail="agenda item not found")
    ok = await (svc.acknowledge(item_id) if action == "ack" else svc.dismiss(item_id))
    if not ok:
        raise HTTPException(status_code=409, detail="agenda item is not open")
    item = await svc.get(item_id)
    assert item is not None
    await channel.publish("agenda_update", item_to_dict(item))
    return item_to_dict(item)


@router.post("/agenda/{item_id}/ack")
async def ack_agenda_item(item_id: str) -> dict[str, Any]:
    return await _resolve(item_id, "ack")


@router.post("/agenda/{item_id}/dismiss")
async def dismiss_agenda_item(item_id: str) -> dict[str, Any]:
    return await _resolve(item_id, "dismiss")
