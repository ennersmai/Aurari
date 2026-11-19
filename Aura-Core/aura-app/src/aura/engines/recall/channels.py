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
"""

from dataclasses import dataclass
from typing import Any

from aura.config import settings


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