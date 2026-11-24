"""Curiosity daily budget (B4-03).

One row per local day (YYYY-MM-DD in app_timezone) tracking investigations,
tokens and USD spend. Ceilings come from config.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from surrealdb import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

_RID_PREFIX = "curiosity_budget"


async def _publish_budget_state(remaining: dict[str, Any]) -> None:
    """Publish the budget state to the autonomy_state channel (drive_state-style)."""
    try:
        from aura.autonomy import channel
        await channel.publish("autonomy_state", {"budget": remaining})
    except Exception:
        logger.warning("budget state publish failed", exc_info=True)


def _today_key(now: datetime | None = None) -> str:
    """Return the local-day key YYYY-MM-DD for the given time (or now)."""
    now = now or get_clock().now()
    try:
        tz = ZoneInfo(settings.app_timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    local = now.astimezone(tz)
    return local.date().isoformat()


def _make_rid(day: str) -> RecordID:
    return RecordID(_RID_PREFIX, day)


@dataclass
class Budget:
    """What curiosity can afford right now (remaining ceilings)."""

    investigations: int
    tokens: int
    spend_usd: float

    def exhausted(self) -> str | None:
        """Name of the first ceiling reached, or None."""
        if self.investigations <= 0:
            return "investigations"
        if self.tokens <= 0:
            return "tokens"
        if self.spend_usd <= 0.0:
            return "spend_usd"
        return None

    @property
    def any_exhausted(self) -> bool:
        return self.exhausted() is not None


async def _get_or_create_row(db: Any, day: str) -> dict[str, Any]:
    """Read or create the curiosity_budget row for ``day``."""
    rid = _make_rid(day)
    rows = extract_rows(await db.query("SELECT * FROM $rid", {"rid": rid}))
    if rows:
        return rows[0]
    # Create with defaults
    now = get_clock().now()
    data = {
        "day": day,
        "investigations": 0,
        "tokens": 0,
        "spend_usd": 0.0,
        "updated_at": now,
    }
    await db.query("CREATE $rid CONTENT $data", {"rid": rid, "data": data})
    return data


async def load_budget(db: Any = None, now: datetime | None = None) -> Budget:
    """Load today's budget (remaining ceilings)."""
    db = db if db is not None else get_db_client()
    day = _today_key(now)
    row = await _get_or_create_row(db, day)
    max_inv = settings.curiosity_daily_investigations
    max_tok = settings.curiosity_daily_tokens
    max_spend = settings.curiosity_daily_spend_usd
    # Ceiling 0 (PRD open item 2): free or zero-cost routes only. Tokens still count;
    # a zero provider cost spends nothing, but any recorded paid spend closes the day.
    spent = float(row.get("spend_usd") or 0.0)
    if max_spend > 0:
        spend_rem = max_spend - spent
    else:
        spend_rem = 0.0 if spent > 0 else float("inf")
    return Budget(
        investigations=max_inv - int(row.get("investigations") or 0),
        tokens=max_tok - int(row.get("tokens") or 0),
        spend_usd=spend_rem,
    )


async def record_spend(
    investigations: int = 0,
    tokens: int = 0,
    spend_usd: float = 0.0,
    *,
    db: Any = None,
    now: datetime | None = None,
) -> Budget:
    """Add to today's budget counters and return the updated remaining budget."""
    if investigations <= 0 and tokens <= 0 and spend_usd <= 0.0:
        return await load_budget(db=db, now=now)
    db = db if db is not None else get_db_client()
    day = _today_key(now)
    rid = _make_rid(day)
    now = now or get_clock().now()
    await _get_or_create_row(db, day)  # UPDATE does not create a missing record
    # Increment atomically
    await db.query(
        "UPDATE $rid SET investigations += $inv, tokens += $tok, spend_usd += $spend, updated_at = $now",
        {"rid": rid, "inv": investigations, "tok": tokens, "spend": spend_usd, "now": now},
    )
    budget = await load_budget(db=db, now=now)
    remaining = await get_remaining(db=db, now=now)
    await _publish_budget_state(remaining)
    return budget


async def get_remaining(db: Any = None, now: datetime | None = None) -> dict[str, Any]:
    """Return the remaining budget for the mind panel (B7)."""
    budget = await load_budget(db=db, now=now)
    max_inv = settings.curiosity_daily_investigations
    max_tok = settings.curiosity_daily_tokens
    max_spend = settings.curiosity_daily_spend_usd
    day = _today_key(now)
    row = await _get_or_create_row(db or get_db_client(), day)
    return {
        "day": day,
        "investigations_used": int(row.get("investigations") or 0),
        "investigations_remaining": max(0, budget.investigations),
        "investigations_ceiling": max_inv,
        "tokens_used": int(row.get("tokens") or 0),
        "tokens_remaining": max(0, budget.tokens),
        "tokens_ceiling": max_tok,
        "spend_usd_used": float(row.get("spend_usd") or 0.0),
        "spend_usd_remaining": max(0.0, budget.spend_usd) if max_spend > 0 else (0.0 if budget.spend_usd <= 0 else None),
        "spend_usd_ceiling": max_spend if max_spend > 0 else None,
        "any_exhausted": budget.any_exhausted,
    }