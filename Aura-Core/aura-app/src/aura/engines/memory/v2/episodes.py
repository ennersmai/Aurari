"""Episode storage for memory v2 (W3-12).

An episode is one conversational turn, verbatim: what the user said, what Aura
said, who said it and where. Every turn that goes through the orchestrator can
be appended after the response has been logged, when
``settings.memory_v2_write_enabled`` is on.

Episodes are chained per ``(venue, conversation_id)`` with the ``next``
relation, so a conversation can be replayed in order even when several venues
share one process. A turn that does not need recall (a greeting or an
acknowledgement, per the W3-06 gate) is stored with ``ephemeral = True``.
"""

from __future__ import annotations

from typing import Any

from surrealdb.types import RecordID

from aura.clock import get_clock
from aura.db.query_utils import to_record_id
from aura.engines.recall.gate import needs_recall


async def ensure_person(db: Any, key: str, display_name: str | None) -> RecordID:
    """Upsert the ``entity:<key>`` person record and return its id.

    ``key`` is ``"owner"`` or ``"discord_<id>"``. The record id is built with
    :func:`to_record_id` and bound as a query parameter, never formatted into
    the query itself. An existing record keeps its id; its name and alias are
    refreshed from ``display_name`` (or ``key`` when there is no display name).
    """
    name = display_name or key
    record_id = to_record_id(f"entity:{key}")
    data = {
        "name": name,
        "type": "person",
        "aliases": [name.lower()],
    }

    # ``UPSERT ... CONTENT`` replaces the whole record, which would reset
    # ``created_at`` (and any later summary or embedding) on every turn. Merge
    # into an existing person instead, and only supply ``created_at`` when the
    # record is new, since the schema requires it.
    existing = await db.query(
        "SELECT id FROM $rid",
        {"rid": record_id},
    )
    if existing:
        rows = await db.query(
            "UPSERT $rid MERGE $data",
            {"rid": record_id, "data": data},
        )
    else:
        data["created_at"] = get_clock().now()
        rows = await db.query(
            "UPSERT $rid CONTENT $data",
            {"rid": record_id, "data": data},
        )
    return rows[0]["id"]


async def store_episode(
    db: Any,
    embeddings: Any,
    *,
    user_text: str,
    aura_text: str,
    speaker: str,
    venue: str,
    conversation_id: str | None,
    emotional_signature: dict[str, float],
    salience: float,
) -> RecordID:
    """Store one turn as an episode and return its id.

    The episode embeds ``user_text + "\\n" + aura_text[:200]``, is stamped with
    the clock provider's current time, and is marked ephemeral when the W3-06
    recall gate says this turn does not need retrieval. If an episode already
    exists for the same ``venue`` and ``conversation_id``, the new episode is
    linked from the most recent one with a ``next`` relation.

    Every value is bound as a query parameter.
    """
    embedding = await embeddings.embed(user_text + "\n" + aura_text[:200])
    speaker_id = await ensure_person(db, speaker, None)

    previous = await db.query(
        "SELECT id FROM episode "
        "WHERE venue = $venue AND conversation_id = $conversation_id "
        "ORDER BY recorded_at DESC LIMIT 1",
        {"venue": venue, "conversation_id": conversation_id},
    )

    data = {
        "user_text": user_text,
        "aura_text": aura_text,
        "speaker": speaker_id,
        "venue": venue,
        "conversation_id": conversation_id,
        "embedding": embedding,
        "emotional_signature": emotional_signature,
        "salience": salience,
        "ephemeral": not needs_recall(user_text),
        "recorded_at": get_clock().now(),
    }
    rows = await db.query("CREATE episode CONTENT $data", {"data": data})
    episode_id = rows[0]["id"]

    if previous:
        await db.query(
            "RELATE $prev->next->$episode",
            {"prev": previous[0]["id"], "episode": episode_id},
        )

    return episode_id