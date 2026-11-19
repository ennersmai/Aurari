"""Entity resolution for memory v2 (W3-14).

Extraction names things (a person, a project, a place, ...). Resolution maps
each surface form to one ``entity`` record so facts about the same thing point
at the same id:

* ``"I"``, ``"me"`` and ``"myself"`` are the speaker's person entity.
* An exact alias (the name lowercased with its whitespace collapsed) wins
  without an embedding call, preferring an entity of the same type.
* Otherwise the nearest entities by embedding are considered with a k=3 KNN
  query over ``entity.embedding``. The closest one at or above
  ``settings.memory_entity_match_threshold`` wins, and the new surface form is
  added to its aliases.
* When the two closest are both above the threshold and within
  ``settings.memory_entity_close_margin`` of each other, the closer one is
  taken and the pair is logged at INFO. The PRD's model call for close cases
  is deliberately left for a later card; this module never calls a model.
* With no match, a new entity is created with the name, type, lowercased alias
  and embedding.

Every value is bound as a query parameter.
"""

from __future__ import annotations

import logging
from typing import Any

from surrealdb.types import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import ensure_person

logger = logging.getLogger(__name__)

# Surface forms that mean the speaker themselves.
_SELF_NAMES = {"i", "me", "myself"}


def _normalise(name: str) -> str:
    """Lowercase ``name`` and collapse runs of whitespace to single spaces."""
    return " ".join(name.split()).lower()


async def _create_entity(
    db: Any,
    name: str,
    entity_type: str,
    alias: str,
    embedding: list[float] | None,
) -> RecordID:
    """Create one entity with its lowercase alias and embedding."""
    data = {
        "name": name,
        "type": entity_type,
        "aliases": [alias],
        "embedding": embedding,
        "created_at": get_clock().now(),
    }
    rows = await db.query("CREATE entity CONTENT $data", {"data": data})
    return rows[0]["id"]


async def _add_alias(
    db: Any,
    record_id: RecordID,
    aliases: list[str] | None,
    alias: str,
) -> None:
    """Add ``alias`` to an entity's alias list unless it is already there."""
    current = list(aliases or [])
    if alias in current:
        return
    await db.query(
        "UPDATE $rid MERGE $data",
        {"rid": record_id, "data": {"aliases": [*current, alias]}},
    )


async def resolve_entity(
    db: Any,
    embeddings: Any,
    name: str,
    type: str,
    speaker: str,
) -> RecordID:
    """Resolve one surface form to an ``entity`` record and return its id.

    ``speaker`` is the turn's speaker key (``"owner"`` or ``"discord_<id>"``).
    See the module docstring for the resolution order. The close-case tie is
    only logged: the PRD's model call is left for later, so no model is
    called here.
    """
    alias = _normalise(name)
    if alias in _SELF_NAMES:
        return await ensure_person(db, speaker, None)

    exact = await db.query(
        "SELECT * FROM entity WHERE aliases CONTAINS $alias",
        {"alias": alias},
    )
    if exact:
        same_type = next((row for row in exact if row.get("type") == type), None)
        return (same_type or exact[0])["id"]

    embedding = await embeddings.embed(name)
    if not embedding:
        return await _create_entity(db, name, type, alias, None)

    rows = await db.query(
        "SELECT id, name, type, aliases, vector::distance::knn() AS distance "
        "FROM entity WHERE embedding <|3,COSINE|> $vec ORDER BY distance",
        {"vec": embedding},
    )
    if not rows:
        return await _create_entity(db, name, type, alias, embedding)

    # ``vector::distance::knn()`` with COSINE is a distance: similarity is
    # one minus it, as in the recall engine's dense channel.
    best = rows[0]
    best_similarity = 1.0 - float(best["distance"])
    if best_similarity < settings.memory_entity_match_threshold:
        return await _create_entity(db, name, type, alias, embedding)

    if len(rows) > 1:
        second_similarity = 1.0 - float(rows[1]["distance"])
        if (
            second_similarity >= settings.memory_entity_match_threshold
            and best_similarity - second_similarity
            <= settings.memory_entity_close_margin
        ):
            logger.info(
                "Entity %r is close to both %r (%s, %.4f) and %r (%s, %.4f); "
                "taking the closer one. The PRD's model call for close cases "
                "is not implemented yet.",
                name,
                best.get("name"),
                best["id"],
                best_similarity,
                rows[1].get("name"),
                rows[1]["id"],
                second_similarity,
            )

    await _add_alias(db, best["id"], best.get("aliases"), alias)
    return best["id"]