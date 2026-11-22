"""Dense and lexical candidate channels for the Recall Engine (M3, W3-02).

Each channel fetches a ranked candidate list from the ``memory`` table and
returns it as :class:`ChannelHit` rows.  The channels apply the same filters
as ``MemoryManager.retrieve_memories``: only non-deprecated, non-ephemeral
memories are candidates, the ``user_id`` filter applies when given, and a
non-global namespace sees its own memories plus global ones.

Dense retrieval uses the HNSW vector index (cosine distance); lexical
retrieval uses the BM25 full-text index on ``memory.content``.  Database
errors are deliberately left to propagate: the caller decides whether a
failing channel is fatal.

W3-17 adds the same two channels over the memory v2 ``fact`` table.  Their
candidates are filtered by the visibilities of the turn's venue
(``visible_in_venue``) and by ``valid_to IS NONE``; visibility replaces the
memory table's ``user_id`` filter.  Superseded facts are therefore never
candidates.
"""

from dataclasses import dataclass
from typing import Any

from aura.config import settings
from aura.engines.memory.v2.identity import visible_in_venue


@dataclass
class ChannelHit:
    """One ranked result from a candidate channel.

    ``rank`` is 0-based.  ``score`` is cosine similarity
    (``1 - distance``) for the dense channel and the BM25 score for the
    lexical channel.
    """

    memory_id: str
    rank: int
    score: float


def _filter_clause(user_id: str | None, namespace: str | None, params: dict[str, Any]) -> str:
    """Build the shared WHERE filter and populate its parameters."""
    conditions = ["deprecated = false", "ephemeral = false"]
    if user_id:
        conditions.append("user_id = $user_id")
        params["user_id"] = user_id
    # "global" / None / "" all mean "no scope filter — read everything".
    if namespace and namespace != "global":
        conditions.append('(namespace = $ns OR namespace = "global" OR namespace IS NONE)')
        params["ns"] = namespace
    return " AND ".join(conditions)


async def dense_channel(
    db: Any,
    embedding: list[float] | None,
    user_id: str | None,
    namespace: str | None,
) -> list[ChannelHit]:
    """Return the nearest memories by cosine similarity, nearest first.

    ``k`` and ``ef`` come from ``settings.recall_dense_k`` and
    ``settings.recall_dense_ef``; the KNN operator needs them inline, so
    they are coerced to ints.  Every other value is a query parameter.
    """
    if not embedding:
        return []

    params: dict[str, Any] = {"vec": embedding}
    where = _filter_clause(user_id, namespace, params)
    k = int(settings.recall_dense_k)
    ef = int(settings.recall_dense_ef)

    rows = await db.query(
        f"""
        SELECT id, vector::distance::knn() AS distance
        FROM memory
        WHERE embedding <|{k},{ef}|> $vec
          AND {where}
        ORDER BY distance
        """,
        params,
    )

    return [
        ChannelHit(
            memory_id=str(row["id"]),
            rank=rank,
            score=1.0 - float(row["distance"]),
        )
        for rank, row in enumerate(rows or [])
    ]


async def lexical_channel(
    db: Any,
    text: str,
    user_id: str | None,
    namespace: str | None,
) -> list[ChannelHit]:
    """Return memories matching ``text`` by BM25 full-text score, best first.

    The full-text index is referenced as ``@1`` and its score read with
    ``search::score(1)``.  The result limit comes from
    ``settings.recall_lexical_k``.
    """
    if not text or not text.strip():
        return []

    params: dict[str, Any] = {"text": text, "k": int(settings.recall_lexical_k)}
    where = _filter_clause(user_id, namespace, params)

    rows = await db.query(
        f"""
        SELECT id, search::score(1) AS score
        FROM memory
        WHERE content @1,OR@ $text
          AND {where}
        ORDER BY score DESC
        LIMIT $k
        """,
        params,
    )

    return [
        ChannelHit(
            memory_id=str(row["id"]),
            rank=rank,
            score=float(row["score"]),
        )
        for rank, row in enumerate(rows or [])
    ]


# ---------------------------------------------------------------------------
# Memory v2 fact channels (W3-17)
# ---------------------------------------------------------------------------


def _fact_filter_clause(venue: str, params: dict[str, Any]) -> str:
    """Build the fact WHERE filter and populate its parameters.

    A fact is visible when its stored visibility is one the venue may read,
    and a superseded fact (``valid_to`` set) is never a candidate.  There is
    no ``user_id`` filter: visibility replaces it.
    """
    params["visible"] = visible_in_venue(venue)
    return "visibility IN $visible AND valid_to IS NONE"


async def fact_dense_channel(
    db: Any,
    embedding: list[float] | None,
    venue: str,
) -> list[ChannelHit]:
    """Return the nearest visible facts by cosine similarity, nearest first.

    ``k`` and ``ef`` come from ``settings.recall_dense_k`` and
    ``settings.recall_dense_ef``; the KNN operator needs them inline, so they
    are coerced to ints.  Every other value is a query parameter.
    """
    if not embedding:
        return []

    params: dict[str, Any] = {"vec": embedding}
    where = _fact_filter_clause(venue, params)
    k = int(settings.recall_dense_k)
    ef = int(settings.recall_dense_ef)

    rows = await db.query(
        f"""
        SELECT id, vector::distance::knn() AS distance
        FROM fact
        WHERE embedding <|{k},{ef}|> $vec
          AND {where}
        ORDER BY distance
        """,
        params,
    )

    return [
        ChannelHit(
            memory_id=str(row["id"]),
            rank=rank,
            score=1.0 - float(row["distance"]),
        )
        for rank, row in enumerate(rows or [])
    ]


async def fact_lexical_channel(
    db: Any,
    text: str,
    venue: str,
) -> list[ChannelHit]:
    """Return visible facts matching ``text`` by BM25, best first.

    The full-text index is referenced as ``@1`` and its score read with
    ``search::score(1)``.  The result limit comes from
    ``settings.recall_lexical_k``.
    """
    if not text or not text.strip():
        return []

    params: dict[str, Any] = {"text": text, "k": int(settings.recall_lexical_k)}
    where = _fact_filter_clause(venue, params)

    rows = await db.query(
        f"""
        SELECT id, search::score(1) AS score
        FROM fact
        WHERE content @1,OR@ $text
          AND {where}
        ORDER BY score DESC
        LIMIT $k
        """,
        params,
    )

    return [
        ChannelHit(
            memory_id=str(row["id"]),
            rank=rank,
            score=float(row["score"]),
        )
        for rank, row in enumerate(rows or [])
    ]


async def fact_entity_channel(
    db: Any,
    aliases: list[str],
    venue: str,
) -> list[ChannelHit]:
    """Return current, visible facts about entities matching any of ``aliases``.

    Finds entities whose ``aliases`` array contains any of the candidate aliases
    (``aliases CONTAINSANY $aliases``), then retrieves current facts linked to
    those entities via the ``about`` edge, filtered by the venue's visibility
    and ``valid_to IS NONE``. Results are ordered by newest ``recorded_at``
    first, up to ``recall_entity_k``. Every hit gets a score of 1.0; rank
    carries the order.
    """
    if not aliases:
        return []

    params: dict[str, Any] = {
        "aliases": aliases,
        "k": int(settings.recall_entity_k),
    }
    where = _fact_filter_clause(venue, params)

    # ``about`` runs fact -> entity, so the matching facts are the ``in`` side
    # of edges whose ``out`` entity carries one of the aliases. Selecting from
    # ``fact`` keeps each fact once even when it is about several matches.
    rows = await db.query(
        f"""
        SELECT id, recorded_at
        FROM fact
        WHERE id IN (
            SELECT VALUE in FROM about
            WHERE out IN (SELECT VALUE id FROM entity WHERE aliases CONTAINSANY $aliases)
        )
          AND {where}
        ORDER BY recorded_at DESC
        LIMIT $k
        """,
        params,
    )

    return [
        ChannelHit(
            memory_id=str(row["id"]),
            rank=rank,
            score=1.0,
        )
        for rank, row in enumerate(rows or [])
    ]
