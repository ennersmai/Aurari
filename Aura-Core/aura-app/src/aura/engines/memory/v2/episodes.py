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

import asyncio
from typing import Any

from surrealdb.types import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.memory.v2.extraction import run_extraction
from aura.engines.recall.gate import needs_recall

# Strong references to in-flight extraction tasks: asyncio only keeps a weak
# reference to a task, so without this set a task could be garbage collected
# before it completes.
_extraction_tasks: set[asyncio.Task[Any]] = set()


def schedule_extraction(db: Any, client: Any, episode_id: Any) -> asyncio.Task[Any] | None:
    """Run :func:`run_extraction` in the background when the flag is on.

    Returns the task (also kept in a module-level set until it finishes), or
    ``None`` when memory v2 writes are disabled.
    """
    if not settings.memory_v2_write_enabled:
        return None
    task = asyncio.create_task(run_extraction(db, client, episode_id))
    _extraction_tasks.add(task)
    task.add_done_callback(_extraction_tasks.discard)
    return task


async def ensure_person(db: Any, key: str, display_name: str | None) -> RecordID:
    """Upsert the ``entity:<key>`` person record and return its id.

    ``key`` is ``"owner"`` or ``"discord_<id>"``. The record id is built with
    :func:`to_record_id` and bound as a query parameter, never formatted into
    the query itself. An existing record keeps its id; its name and aliases are
    merged (union) with the new values, lowercased and whitespace-collapsed.
    """
    record_id = to_record_id(f"entity:{key}")

    # Read existing record to get current aliases (if any)
    existing = await db.query(
        "SELECT aliases FROM $rid",
        {"rid": record_id},
    )

    existing_aliases: list[str] = []
    if existing and existing[0].get("aliases"):
        existing_aliases = existing[0]["aliases"]

    # Determine the name: owner_display_name takes precedence, else "owner".
    # The passed display_name is NOT used for the owner's canonical name.
    if key == "owner":
        name = settings.owner_display_name or "owner"
    else:
        name = display_name or key

    # Build new aliases: lowercased and whitespace-collapsed
    def normalize_alias(a: str) -> str:
        return " ".join(a.lower().split())

    new_aliases = [normalize_alias(name)]

    if key == "owner":
        # Owner always has "owner" alias, plus owner_aliases from config
        new_aliases.append("owner")
        for alias in settings.owner_aliases:
            norm = normalize_alias(alias)
            if norm:
                new_aliases.append(norm)
        # When owner_display_name is not configured, the passed display_name
        # (e.g., the user_id from an app turn) is added as an alias so the
        # owner's entity accumulates the names they use.
        if not settings.owner_display_name and display_name:
            new_aliases.append(normalize_alias(display_name))
    else:
        # For non-owner, also add the display_name if different from name
        if display_name and normalize_alias(display_name) != normalize_alias(name):
            new_aliases.append(normalize_alias(display_name))

    # Merge: union of existing and new, deduplicated
    merged_aliases = list(dict.fromkeys(existing_aliases + new_aliases))

    data = {
        "name": name,
        "type": "person",
        "aliases": merged_aliases,
    }

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
    display_name: str | None = None,
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
    speaker_id = await ensure_person(db, speaker, display_name)

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