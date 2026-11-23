"""Agenda delivery (B1-05, PRD 4.3). Event-driven, no model call.

``deliver_due`` runs when an item is created, when the earliest ``due_at``
arrives (one asyncio timer, re-armed on change), when controls change, and on
a slow fallback check that only catches stuck items. Venue is always ``app``.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any

from aura.autonomy import channel, trace
from aura.autonomy.agenda import AgendaItem, AgendaService, _rid, _to_item, effective_priority
from aura.autonomy.controls import may_initiate, quiet_hours_active
from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)


def interruptibility(now: datetime) -> float:
    """Stub returning 1.0 (always interruptible). B5-01 replaces this one name."""
    return 1.0


def item_to_dict(item: AgendaItem) -> dict[str, Any]:
    def iso(v: datetime | None) -> str | None:
        return v.isoformat() if v else None

    return {
        "id": item.id,
        "kind": item.kind,
        "content": item.content,
        "refs": list(item.refs),
        "priority": item.priority,
        "venue": item.venue,
        "state": item.state,
        "source": item.source,
        "created_at": iso(item.created_at),
        "due_at": iso(item.due_at),
        "expires_at": iso(item.expires_at),
        "delivered_at": iso(item.delivered_at),
        "resolved_at": iso(item.resolved_at),
    }


class AgendaDeliverer:
    def __init__(self, service: AgendaService | None = None) -> None:
        self.service = service or AgendaService()
        self._timer: asyncio.Task | None = None
        self._fallback: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._fallback = asyncio.create_task(self._fallback_loop())
        await self.rearm()

    async def stop(self) -> None:
        self._running = False
        tasks = [t for t in (self._timer, self._fallback) if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._timer = self._fallback = None

    async def notify(self) -> None:
        """Item created or controls changed: deliver what is due, re-arm."""
        await self.deliver_due()
        if self._running:
            await self.rearm()

    async def next_delay(self) -> float | None:
        """Seconds until the earliest future pending ``due_at``; None if none."""
        now = get_clock().now()
        rows = extract_rows(
            await self.service.db.query(
                "SELECT due_at FROM agenda_item WHERE state = 'pending' "
                "AND due_at != NONE AND due_at > $now ORDER BY due_at ASC LIMIT 1",
                {"now": now},
            )
        )
        if not rows:
            return None
        return max(0.0, (rows[0]["due_at"] - now).total_seconds())

    async def rearm(self) -> float | None:
        """Cancel the timer and set it for the earliest due_at. Returns the delay."""
        if self._timer is not None and self._timer is not asyncio.current_task():
            self._timer.cancel()
        self._timer = None
        delay = await self.next_delay()
        if delay is not None and self._running:
            self._timer = asyncio.create_task(self._wait_and_deliver(delay))
        return delay

    async def _wait_and_deliver(self, delay: float) -> None:
        await asyncio.sleep(delay)
        try:
            await self.deliver_due()
        except Exception as e:  # noqa: BLE001
            logger.warning("agenda delivery failed: %s", e)
        if self._running:
            self._timer = None  # this task is finishing; do not cancel itself
            try:
                await self.rearm()
            except Exception as e:  # noqa: BLE001
                logger.warning("agenda re-arm failed: %s", e)

    async def _fallback_loop(self) -> None:
        while self._running:
            await asyncio.sleep(settings.agenda_fallback_seconds)
            try:
                await self.deliver_due()
                await self.rearm()
            except Exception as e:  # noqa: BLE001
                logger.warning("agenda fallback failed: %s", e)

    async def deliver_due(self) -> list[AgendaItem]:
        """Deliver pending items whose due_at has passed. Returns those delivered."""
        db = self.service.db
        now = get_clock().now()
        if await self.service.expire_due(now):
            await channel.publish("agenda_update", {"reason": "expired"})
        rows = extract_rows(
            await db.query(
                "SELECT * FROM agenda_item WHERE state = 'pending' AND venue = 'app' "
                "AND (due_at = NONE OR due_at <= $now) ORDER BY created_at ASC",
                {"now": now},
            )
        )
        delivered: list[AgendaItem] = []
        for row in rows:
            item = _to_item(row)
            if quiet_hours_active(now) or interruptibility(now) <= 0:
                continue
            decision = await may_initiate(
                item.kind,
                now=now,
                owner_created=item.source == "owner",
                source="agenda_delivery",
                refs=[item.id],
                db=db,
            )
            if not decision.allowed:
                continue
            changed = extract_rows(
                await db.query(
                    "UPDATE $rid SET state = 'delivered', delivered_at = $now "
                    "WHERE state = 'pending' RETURN AFTER",
                    {"rid": _rid(item.id), "now": now},
                )
            )
            if not changed:
                continue
            item = _to_item(changed[0])
            delivered.append(item)
            payload = item_to_dict(item)
            if effective_priority(item, now) >= settings.agenda_message_priority:
                await channel.publish("aura_message", payload)
            await channel.publish("agenda_update", payload)
            await trace.record(
                "agenda_delivery", f"deliver:{item.kind}", "due and allowed", refs=[item.id], db=db
            )
        return delivered


_deliverer: AgendaDeliverer | None = None


def get_deliverer() -> AgendaDeliverer:
    global _deliverer
    if _deliverer is None:
        _deliverer = AgendaDeliverer()
    return _deliverer
