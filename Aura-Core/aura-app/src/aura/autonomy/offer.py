"""Working-set offer (B5-04, PRD 8.2 last bullet). No model call.

On an owner turn, pending agenda items that overlap the owner's message are
offered to the Recall Engine as a labelled block. The offer never interrupts:
items stay ``pending`` until the owner's next message touches the same topic,
which counts as acknowledging them (delivered and acknowledged through the
service, and fed to dismissal learning). Chat-path cost is one indexed query
under a hard time bound; matching is lexical and entity overlap only.
"""

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from aura.autonomy import channel
from aura.autonomy import learning as _learning
from aura.autonomy.agenda import AgendaItem, AgendaService, _rid, _to_item
from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import extract_rows

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9]{3,}")
_ENTITY = re.compile(r"\b[A-Z][A-Za-z0-9]{2,}\b")
_STOP = frozenset(
    "that this with have from your what when where which there their about would could "
    "should will just like been were they them then than into some more also very much "
    "the and for are was you but not can its has had our out how why who all any get got let may now one say see she him his her too use way yes does done make made want need know think here".split()
)

# owner user_id -> {item id: item} offered in the previous reply
_offered: dict[str, dict[str, AgendaItem]] = {}
_bg: set[asyncio.Task] = set()


def reset() -> None:
    _offered.clear()


def enabled() -> bool:
    return bool(settings.autonomy_enabled and settings.interruptibility_model_enabled)


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP}


def extract_entities(text: str) -> list[str]:
    """Capitalised words of the message; a cheap stand-in for entity linking."""
    return [m.lower() for m in _ENTITY.findall(text or "")]


def _score(item: AgendaItem, tokens: set[str], entities: set[str]) -> int:
    ref_hits = 0
    for ref in item.refs:
        low = str(ref).lower()
        if low in entities or low in tokens or any(e in low for e in entities):
            ref_hits += 1
    return 2 * ref_hits + len(tokens & _tokens(item.content))


async def relevant_items(
    user_text: str,
    entities: list[str] | None,
    now: datetime,
    limit: int,
    service: AgendaService | None = None,
) -> list[AgendaItem]:
    """Pending, undelivered app items whose refs or content overlap the message.

    One indexed query (state), bounded by ``agenda_offer_timeout_ms``; scoring
    is in memory. Any failure or timeout returns no items.
    """
    tokens = _tokens(user_text)
    ents = {e.lower() for e in (entities or [])}
    if not tokens and not ents:
        return []
    svc = service or AgendaService()
    try:
        rows = extract_rows(
            await asyncio.wait_for(
                svc.db.query(
                    "SELECT * FROM agenda_item WHERE state = 'pending' AND venue = 'app' "
                    "AND (expires_at = NONE OR expires_at > $now) "
                    "AND (due_at = NONE OR due_at <= $now) "
                    "ORDER BY created_at DESC LIMIT $scan",
                    {"now": now, "scan": settings.agenda_offer_scan},
                ),
                timeout=settings.agenda_offer_timeout_ms / 1000,
            )
        )
    except Exception as e:  # noqa: BLE001 - includes timeout; the reply goes on without it
        logger.debug("agenda offer skipped: %s", e)
        return []
    scored = []
    for row in rows:
        item = _to_item(row)
        s = _score(item, tokens, ents)
        if s >= 1:
            scored.append((s, item.priority, item))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [t[2] for t in scored[: max(0, limit)]]


async def acknowledge_offered(
    previous: dict[str, AgendaItem], user_text: str, service: AgendaService | None = None
) -> list[str]:
    """The owner's next message touches an item offered earlier: mark it delivered
    and acknowledged. Items it does not touch stay pending. Returns the ids moved."""
    if not previous:
        return []
    svc = service or AgendaService()
    tokens = _tokens(user_text)
    ents = {e.lower() for e in extract_entities(user_text)}
    now = get_clock().now()
    moved: list[str] = []
    for item_id, item in previous.items():
        if _score(item, tokens, ents) < 1:
            continue
        rows = extract_rows(
            await svc.db.query(
                "UPDATE $rid SET state = 'acknowledged', "
                "delivered_at = delivered_at ?? $now, resolved_at = $now "
                "WHERE state = 'pending' RETURN AFTER",
                {"rid": _rid(item_id), "now": now},
            )
        )
        if not rows:
            continue
        moved.append(item_id)
        await _learning.record_delivered(item.kind, svc.db)
        await _learning.record_outcome(item.kind, "acknowledged", item_id=item_id, db=svc.db)
        await channel.publish("agenda_update", {"id": item_id, "state": "acknowledged"})
    return moved


def _settle_in_background(previous: dict[str, AgendaItem], user_text: str) -> None:
    async def _go() -> None:
        try:
            await acknowledge_offered(previous, user_text)
        except Exception as e:  # noqa: BLE001
            logger.warning("agenda offer acknowledgement failed: %s", e)

    task = asyncio.get_running_loop().create_task(_go())
    _bg.add(task)
    task.add_done_callback(_bg.discard)


async def working_set_for_turn(
    user_id: str, user_text: str, requester_role: str, venue: str = "app"
) -> list[tuple[str, str]]:
    """The offer for one turn as ``(item id, text)`` pairs; ``[]`` when off, for a
    guest, or off the app venue. Remembers what was offered for the next turn."""
    if not enabled() or requester_role != "owner" or venue != "app":
        return []
    previous = _offered.pop(user_id, None)
    if previous:
        _settle_in_background(previous, user_text)  # owner replied; off the hot path
    items = await relevant_items(
        user_text, extract_entities(user_text), get_clock().now(), settings.agenda_offer_limit
    )
    if items:
        _offered[user_id] = {i.id: i for i in items}
    return [(i.id, f"[{i.kind}] {i.content}") for i in items]
