"""Feedback on recalled facts (W4-06, memory PRD 6.5).

After a turn, compare the reply with the facts the packet injected. A fact the
reply used (enough of its content words, or a close embedding) gets its usage
fields refreshed and a ``co_used`` edge to the other used facts; an injected
fact the reply did not use gets its ``unused_streak`` raised, which the rerank
turns into a small penalty. The reply is only compared with facts; nothing
from it is stored.
"""

import logging
import math
import re
from itertools import combinations
from typing import Any

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.recall.query import _STOP_WORDS

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[a-z0-9']+")


def _content_words(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOP_WORDS}


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


async def record_feedback(db: Any, embeddings: Any, packet: Any, reply: str) -> list[str]:
    """Update the facts of ``packet`` from what ``reply`` used. Logs failures only.

    Returns the ids of the facts the reply used (``"fact:<id>"``); empty on failure.
    """
    try:
        return await _record_feedback(db, embeddings, packet, reply)
    except Exception as exc:
        logger.warning("Recall feedback failed (non-critical): %s", exc)
        return []


def _id_text(value: Any) -> str:
    table = getattr(value, "table_name", None)
    return f"{table}:{value.id}" if table else str(value)


async def _record_feedback(db: Any, embeddings: Any, packet: Any, reply: str) -> list[str]:
    ids = [
        item.key
        for item in packet.trace.items
        if item.block == "memories"
        and item.fate == "kept"
        and item.key.startswith("fact:")
    ]
    if not ids or not reply:
        return []
    rows = await db.query(
        "SELECT id, content, embedding FROM fact WHERE id IN $ids",
        {
            "ids": [
                to_record_id(i.replace("⟨", "").replace("⟩", "")) for i in ids
            ]
        },
    )
    if not rows:
        return []

    reply_words = _content_words(reply)
    reply_vector = await embeddings.embed(reply)
    used: list[Any] = []
    unused: list[Any] = []
    for row in rows:
        words = _content_words(row.get("content") or "")
        overlap = len(words & reply_words) / len(words) if words else 0.0
        embedding = row.get("embedding")
        similar = bool(embedding) and (
            _cosine(reply_vector, embedding) >= settings.recall_feedback_min_similarity
        )
        is_used = overlap >= settings.recall_feedback_min_overlap or similar
        (used if is_used else unused).append(row["id"])

    params: dict[str, Any] = {
        "used": used,
        "unused": unused,
        "now": get_clock().now(),
    }
    statements = [
        "UPDATE fact SET use_count += 1, last_used_at = $now, unused_streak = 0 "
        "WHERE id IN $used",
        "UPDATE fact SET unused_streak += 1 WHERE id IN $unused",
    ]
    if len(used) > 1:
        edges = await db.query(
            "SELECT id, in, out FROM co_used WHERE in IN $used AND out IN $used",
            {"used": used},
        )
        existing = {(str(e["in"]), str(e["out"])): e["id"] for e in edges or []}
        for n, (a, b) in enumerate(
            combinations(sorted(used, key=str), 2)
        ):
            edge = existing.get((str(a), str(b))) or existing.get((str(b), str(a)))
            if edge is not None:
                params[f"e{n}"] = edge
                statements.append(f"UPDATE $e{n} SET weight += 1")
            else:
                params[f"a{n}"], params[f"b{n}"] = a, b
                statements.append(f"RELATE $a{n}->co_used->$b{n} SET weight = 1")
    await db.query(
        "BEGIN TRANSACTION; " + "; ".join(statements) + "; COMMIT TRANSACTION;",
        params,
    )
    return [_id_text(i) for i in used]
