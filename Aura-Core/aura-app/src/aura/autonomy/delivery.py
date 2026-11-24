"""Agenda delivery (B1-05, PRD 4.3). Event-driven, no model call.

``deliver_due`` runs when an item is created, when the earliest ``due_at``
arrives (one asyncio timer, re-armed on change), when controls change, and on
a slow fallback check that only catches stuck items. Venue is always ``app``.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any

from aura.autonomy import channel, trace
from aura.autonomy import interruptibility as _interrupt
from aura.autonomy import learning as _learning
from aura.autonomy.agenda import AgendaItem, AgendaService, _rid, _to_item, effective_priority
from aura.autonomy.controls import _parse_hhmm, may_initiate, quiet_hours_active
from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)


def interruptibility(now: datetime) -> float:
    """B5-01 model when ``interruptibility_model_enabled``, else the fixed-cooldown control."""
    signals = _interrupt.collect_signals(now)
    if settings.interruptibility_model_enabled:
        return _interrupt.interruptibility(signals, now)
    return _interrupt.fixed_cooldown(signals, now)


def threshold(kind: str) -> float:
    """Delivery threshold for a kind: config plus the learned delta (B5-03, zero when off)."""
    base = float(getattr(settings, f"delivery_threshold_{kind}", 0.3))
    return max(0.0, base + _learning.threshold_delta(kind))


def seconds_to_quiet_end(now: datetime) -> float:
    """Seconds from ``now`` to the next quiet-hours end boundary (one timer)."""
    try:
        tz = ZoneInfo(settings.app_timezone)
    except Exception:  # noqa: BLE001 - same fallback as quiet_hours_active
        tz = ZoneInfo("UTC")
    end = _parse_hhmm(settings.quiet_hours_end)
    local = now.astimezone(tz)
    target = local.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=1)
    return max(0.0, (target - local).total_seconds())


_reeval_tasks: set[asyncio.Task] = set()


def schedule_reevaluate() -> None:
    """Re-evaluate deferred items after an input changed (typing stopped, owner reply).

    No-op unless the model is on and an event loop is running. No polling.
    """
    if not settings.interruptibility_model_enabled:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _go() -> None:
        try:
            await get_deliverer().notify()
        except Exception as e:  # noqa: BLE001
            logger.warning("agenda re-evaluation failed: %s", e)

    task = loop.create_task(_go())
    _reeval_tasks.add(task)
    task.add_done_callback(_reeval_tasks.discard)


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
        self._wake: asyncio.Task | None = None
        self._next_wake: float | None = None  # seconds; set by deliver_due when items wait
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._fallback = asyncio.create_task(self._fallback_loop())
        await self.rearm()

    async def stop(self) -> None:
        self._running = False
        tasks = [t for t in (self._timer, self._fallback, self._wake) if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._timer = self._fallback = self._wake = None

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
        if self._wake is not None and self._wake is not asyncio.current_task():
            self._wake.cancel()
        self._wake = None
        if self._next_wake is not None and self._running:
            self._wake = asyncio.create_task(self._wake_and_deliver(self._next_wake))
        delay = await self.next_delay()
        if delay is not None and self._running:
            self._timer = asyncio.create_task(self._wait_and_deliver(delay))
        return delay

    async def _wake_and_deliver(self, delay: float) -> None:
        """Refractory end or quiet hours end: one timer, then re-evaluate."""
        await asyncio.sleep(delay)
        self._wake = None  # finishing; do not cancel itself in rearm
        try:
            await self.deliver_due()
            if self._running:
                await self.rearm()
        except Exception as e:  # noqa: BLE001
            logger.warning("agenda wake failed: %s", e)

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
        if settings.dismissal_learning_enabled:
            if await _learning.sweep_ignored(now, db):
                await channel.publish("agenda_update", {"reason": "ignored"})
            await _learning.refresh(db)
        rows = extract_rows(
            await db.query(
                "SELECT * FROM agenda_item WHERE state = 'pending' AND venue = 'app' "
                "AND (due_at = NONE OR due_at <= $now) ORDER BY created_at ASC",
                {"now": now},
            )
        )
        delivered: list[AgendaItem] = []
        model = settings.interruptibility_model_enabled
        self._next_wake = None
        last_delivery = await self._last_delivery() if model and rows else None
        for row in rows:
            item = _to_item(row)
            if quiet_hours_active(now):
                if model:
                    self._wake_in(seconds_to_quiet_end(now))
                continue
            level = interruptibility(now)
            if level <= 0:
                continue
            if model:
                product = effective_priority(item, now) * level
                limit = threshold(item.kind)
                cost = {"product": product, "threshold": limit, "interruptibility": level}
                if product < limit:
                    await trace.record(
                        "agenda_delivery",
                        f"defer:{item.kind}",
                        f"product {product:.3f} below threshold {limit:.3f}",
                        cost=cost,
                        refs=[item.id],
                        db=db,
                    )
                    continue
                if last_delivery is not None:
                    wait = settings.delivery_refractory_seconds - (now - last_delivery).total_seconds()
                    if wait > 0:
                        self._wake_in(wait)
                        await trace.record(
                            "agenda_delivery",
                            f"defer:{item.kind}",
                            f"refractory, {wait:.0f}s left; product {product:.3f}, threshold {limit:.3f}",
                            cost=cost,
                            refs=[item.id],
                            db=db,
                        )
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
            await _learning.record_delivered(item.kind, db)
            delivered.append(item)
            last_delivery = now
            payload = item_to_dict(item)
            if effective_priority(item, now) >= settings.agenda_message_priority:
                await channel.publish("aura_message", payload)
            await channel.publish("agenda_update", payload)
            if model:
                await trace.record(
                    "agenda_delivery",
                    f"deliver:{item.kind}",
                    f"product {product:.3f} met threshold {limit:.3f}",
                    cost=cost,
                    refs=[item.id],
                    db=db,
                )
            else:
                await trace.record(
                    "agenda_delivery", f"deliver:{item.kind}", "due and allowed", refs=[item.id], db=db
                )
        return delivered

    def _wake_in(self, seconds: float) -> None:
        if self._next_wake is None or seconds < self._next_wake:
            self._next_wake = max(0.0, seconds)

    async def _last_delivery(self) -> datetime | None:
        rows = extract_rows(
            await self.service.db.query(
                "SELECT delivered_at FROM agenda_item WHERE delivered_at != NONE "
                "ORDER BY delivered_at DESC LIMIT 1"
            )
        )
        return rows[0]["delivered_at"] if rows else None


_deliverer: AgendaDeliverer | None = None


def get_deliverer() -> AgendaDeliverer:
    global _deliverer
    if _deliverer is None:
        _deliverer = AgendaDeliverer()
    return _deliverer
