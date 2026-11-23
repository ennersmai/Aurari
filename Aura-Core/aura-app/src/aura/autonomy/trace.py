"""Autonomy trace (B1-01): one row per gate decision or autonomous action."""

import logging
from typing import Any

from aura.clock import get_clock
from aura.db.client import get_db_client

logger = logging.getLogger(__name__)


async def record(
    source: str,
    action: str,
    why: str,
    *,
    allowed: bool = True,
    cost: dict[str, Any] | None = None,
    refs: list[Any] | None = None,
    db: Any = None,
) -> bool:
    """Write an autonomy_trace row. Never raises; returns False on failure."""
    data = {
        "source": source,
        "action": action,
        "why": why,
        "cost": dict(cost or {}),
        "refs": [str(r) for r in (refs or [])],
        "at": get_clock().now(),
        "allowed": allowed,
    }
    try:
        db = db if db is not None else get_db_client()
        await db.query("CREATE autonomy_trace CONTENT $data", {"data": data})
        return True
    except Exception as e:  # noqa: BLE001 - tracing must not break callers
        logger.warning("autonomy trace write failed: %s", e)
        return False
