"""Agenda service (B1-02): things Aura wants to raise with the owner.

Principle 1: an item without refs cannot exist. Content is drafted by the
caller; this module never calls a model. Delivery is not done here.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from surrealdb import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

KINDS = ("finding", "task_done", "needs_decision", "question_for_you", "reminder", "observation")
STATES = ("pending", "delivered", "acknowledged", "dismissed", "expired")
_OPEN = ["pending", "delivered"]


@dataclass
class AgendaItem:
    id: str
    kind: str
    content: str
    refs: list[str] = field(default_factory=list)
    priority: float = 0.5
    venue: str = "app"
    created_at: datetime | None = None
    expires_at: datetime | None = None
    state: str = "pending"
    delivered_at: datetime | None = None
    resolved_at: datetime | None = None
    source: str = ""
    due_at: datetime | None = None


def _rid(value: Any) -> RecordID:
    if isinstance(value, RecordID):
        return value
    table, _, ident = str(value).partition(":")
    if not ident:
        table, ident = "agenda_item", str(value)
    return RecordID(table, ident)


def _to_item(row: dict[str, Any]) -> AgendaItem:
    rid = row["id"]
    return AgendaItem(
        id=f"{rid.table_name}:{rid.id}" if isinstance(rid, RecordID) else str(rid),
        kind=row["kind"],
        content=row["content"],
        refs=list(row.get("refs") or []),
        priority=float(row.get("priority") or 0.0),
        venue=row.get("venue") or "app",
        created_at=row.get("created_at"),
        expires_at=row.get("expires_at"),
        state=row.get("state") or "pending",
        delivered_at=row.get("delivered_at"),
        resolved_at=row.get("resolved_at"),
        source=row.get("source") or "",
        due_at=row.get("due_at"),
    )


def effective_priority(item: AgendaItem, now: datetime) -> float:
    """Stored priority decayed exponentially by the per-kind hourly rate. Pure."""
    rate = float(getattr(settings, f"agenda_decay_per_hour_{item.kind}", 0.0) or 0.0)
    if item.created_at is None or rate <= 0:
        return item.priority
    hours = max(0.0, (now - item.created_at).total_seconds() / 3600.0)
    return item.priority * math.exp(-rate * hours)


class AgendaService:
    def __init__(self, db: Any = None) -> None:
        self._db = db

    @property
    def db(self) -> Any:
        return self._db if self._db is not None else get_db_client()

    async def create(
        self,
        kind: str,
        content: str,
        refs: list[Any],
        priority: float = 0.5,
        venue: str = "app",
        expires_at: datetime | None = None,
        due_at: datetime | None = None,
        source: str = "",
    ) -> AgendaItem:
        if kind not in KINDS:
            raise ValueError(f"unknown agenda kind: {kind}")
        clean_refs = [str(r) for r in (refs or []) if str(r).strip()]
        if not clean_refs:
            raise ValueError("agenda item needs refs")
        data: dict[str, Any] = {
            "kind": kind,
            "content": content,
            "refs": clean_refs,
            "priority": min(1.0, max(0.0, float(priority))),
            "venue": venue,
            "created_at": get_clock().now(),
            "state": "pending",
            "source": source,
        }
        if expires_at is not None:
            data["expires_at"] = expires_at
        if due_at is not None:
            data["due_at"] = due_at
        rid = RecordID("agenda_item", uuid4().hex[:12])
        rows = extract_rows(await self.db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data}))
        return _to_item(rows[0])

    async def list(self, states: list[str] | None = None) -> list[AgendaItem]:
        if states:
            rows = extract_rows(
                await self.db.query(
                    "SELECT * FROM agenda_item WHERE state IN $states ORDER BY created_at ASC",
                    {"states": list(states)},
                )
            )
        else:
            rows = extract_rows(await self.db.query("SELECT * FROM agenda_item ORDER BY created_at ASC"))
        return [_to_item(r) for r in rows]

    async def get(self, item_id: str) -> AgendaItem | None:
        rows = extract_rows(await self.db.query("SELECT * FROM $rid", {"rid": _rid(item_id)}))
        return _to_item(rows[0]) if rows else None

    async def _resolve(self, item_id: str, state: str) -> bool:
        """Move a pending/delivered item to ``state``; False if it was not open."""
        rows = extract_rows(
            await self.db.query(
                "UPDATE $rid SET state = $state, resolved_at = $now WHERE state IN $open RETURN AFTER",
                {"rid": _rid(item_id), "state": state, "now": get_clock().now(), "open": _OPEN},
            )
        )
        return bool(rows)

    async def acknowledge(self, item_id: str) -> bool:
        return await self._resolve(item_id, "acknowledged")

    async def dismiss(self, item_id: str) -> bool:
        return await self._resolve(item_id, "dismissed")

    async def expire_due(self, now: datetime | None = None) -> int:
        """Silently expire open items past ``expires_at``. Returns how many."""
        now = now or get_clock().now()
        rows = extract_rows(
            await self.db.query(
                "UPDATE agenda_item SET state = 'expired', resolved_at = $now "
                "WHERE state IN $open AND expires_at != NONE AND expires_at <= $now RETURN AFTER",
                {"now": now, "open": _OPEN},
            )
        )
        return len(rows)
