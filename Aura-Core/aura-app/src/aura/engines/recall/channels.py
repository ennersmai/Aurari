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
from datetime import datetime
from typing import Any

from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.memory.v2.identity import visibility_for_venue, visible_in_venue
from aura.engines.recall.graph import personalised_pagerank


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


async def fact_temporal_channel(
    db: Any,
    time_range: tuple[datetime, datetime],
    venue: str,
) -> list[ChannelHit]:
    """Return visible facts whose ``valid_from`` or ``recorded_at`` falls in the range.

    Includes superseded facts (``valid_to`` is not filtered out) because a question
    about a time is a question about the past. Results ordered by newest
    ``recorded_at`` first, capped by ``settings.recall_temporal_k``.

    Args:
        db: Database client.
        time_range: Tuple of (start, end) datetimes (inclusive).
        venue: The venue string for visibility filtering.

    Returns:
        List of ChannelHit with score 1.0, ranked by newest first.
    """
    if not time_range:
        return []

    start, end = time_range
    params: dict[str, Any] = {
        "start": start,
        "end": end,
        "visible": visible_in_venue(venue),
        "k": int(settings.recall_temporal_k),
    }

    # Filter: visibility IN $visible AND (valid_from BETWEEN $start AND $end OR recorded_at BETWEEN $start AND $end)
    # Note: superseded facts (valid_to set) are included intentionally.
    where = "visibility IN $visible AND ((valid_from IS NOT NONE AND valid_from >= $start AND valid_from <= $end) OR (recorded_at >= $start AND recorded_at <= $end))"

    rows = await db.query(
        f"""
        SELECT id, recorded_at
        FROM fact
        WHERE {where}
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


def _rid(thing: Any) -> Any:
    """A record id string, as ``str(row["id"])`` gives it, back to a RecordID."""
    return to_record_id(str(thing).replace("\u27e8", "").replace("\u27e9", ""))


def _episode_visibility(venue: str) -> str | None:
    """The visibility an episode's facts get: a DM's speaker is its user."""
    speaker = venue[len("dm:"):] if venue.startswith("dm:") else "owner"
    try:
        return visibility_for_venue(venue, speaker)
    except ValueError:
        return None


async def _load_graph(
    db: Any, seeds: list[str], venue: str
) -> list[tuple[str, str, float]]:
    """Expand breadth-first from ``seeds`` over the typed edges.

    One query per edge type per hop, plus one visibility check per hop: a fact
    the venue may not read is dropped with its edges, so it can neither be
    returned nor act as a bridge between visible facts. ``supersedes`` is not
    an edge type here, so it is never followed. Stops at
    ``recall_graph_max_nodes`` nodes.
    """
    cap = int(settings.recall_graph_max_nodes)
    seen: set[str] = set(seeds)
    frontier = list(seeds)
    known: set[tuple[str, str, str]] = set()
    weighted: list[tuple[str, str, float]] = []

    hidden: set[str] = set()
    visible = visible_in_venue(venue)

    while frontier and len(seen) < cap:
        ids = [_rid(node) for node in frontier]
        hop: list[tuple[str, str, float]] = []
        found: list[str] = []
        for relation, weight in settings.recall_graph_weights.items():
            rows = await db.query(
                f"SELECT in, out FROM {relation} WHERE in IN $ids OR out IN $ids",
                {"ids": ids},
            )
            for row in rows:
                a, b = str(row["in"]), str(row["out"])
                if a in hidden or b in hidden or (relation, a, b) in known:
                    continue
                known.add((relation, a, b))
                hop.append((a, b, float(weight)))
                for node in (a, b):
                    if node not in seen and len(seen) < cap:
                        seen.add(node)
                        found.append(node)

        new_facts = [node for node in found if node.startswith("fact:")]
        if new_facts:
            readable = await db.query(
                "SELECT VALUE id FROM fact WHERE id IN $ids AND visibility IN $visible",
                {"ids": [_rid(node) for node in new_facts], "visible": visible},
            )
            readable_ids = {str(rid) for rid in readable}
            hidden.update(node for node in new_facts if node not in readable_ids)
        new_episodes = [node for node in found if node.startswith("episode:")]
        if new_episodes:
            rows = await db.query(
                "SELECT id, venue FROM episode WHERE id IN $ids",
                {"ids": [_rid(node) for node in new_episodes]},
            )
            readable_ids = {
                str(row["id"])
                for row in rows
                if _episode_visibility(row["venue"]) in visible
            }
            hidden.update(node for node in new_episodes if node not in readable_ids)

        weighted.extend(
            (a, b, w) for a, b, w in hop if a not in hidden and b not in hidden
        )
        frontier = [node for node in found if node not in hidden]
    return weighted


async def fact_graph_channel(
    db: Any,
    seeds: dict[str, float],
    venue: str,
) -> list[ChannelHit]:
    """Return current, visible facts reached from ``seeds`` by Personalised PageRank.

    ``seeds`` maps the fact ids hit by the earlier channels to a weight. The
    seeds themselves are excluded; the rest are ranked by PPR score, capped by
    ``settings.recall_graph_k``.
    """
    if not seeds:
        return []

    edges = await _load_graph(db, list(seeds), venue)
    scores = personalised_pagerank(
        edges,
        seeds,
        settings.recall_graph_alpha,
        int(settings.recall_graph_iterations),
        settings.recall_graph_degree_damping,
    )
    candidates = [
        node for node in scores if node.startswith("fact:") and node not in seeds
    ]
    if not candidates:
        return []

    params: dict[str, Any] = {"ids": [_rid(node) for node in candidates]}
    where = _fact_filter_clause(venue, params)
    rows = await db.query(
        f"SELECT id FROM fact WHERE id IN $ids AND {where}", params
    )

    ranked = sorted((str(row["id"]) for row in rows), key=lambda node: -scores[node])
    return [
        ChannelHit(memory_id=node, rank=rank, score=scores[node])
        for rank, node in enumerate(ranked[: int(settings.recall_graph_k)])
    ]
