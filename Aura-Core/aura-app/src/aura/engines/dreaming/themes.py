"""Dreaming v2 themes (W4-10): replay, communities, theme and entity summaries.

The pure parts (replay ordering, label propagation, word trimming) do no I/O.
The database parts read in batches (one query per relation) and never mix
visibilities: a community's facts all share one visibility and its theme gets
it. Entity summaries use owner facts only, because ``entity`` is shared.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime
from typing import Any
from uuid import uuid4

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import to_record_id

logger = logging.getLogger(__name__)

_PROMPT_FACTS = 40
_PROPAGATION_ROUNDS = 20


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def select_replay(
    facts: list[dict[str, Any]],
    now: datetime,
    batch: int,
    recency_days: float,
    since: datetime | None,
) -> list[str]:
    """Ids of the facts to consider: the top ``batch`` by
    ``salience * exp(-age_days / recency_days)`` plus the newest ``batch`` facts
    recorded after ``since`` (none extra when ``since`` is None, e.g. after a
    restart, so one cycle stays bounded). Ties: newer, then smaller id.
    """

    def score(fact: dict[str, Any]) -> float:
        age_days = max((now - fact["recorded_at"]).total_seconds(), 0.0) / 86400.0
        return float(fact["salience"] or 0.0) * math.exp(-age_days / recency_days)

    ranked = sorted(
        facts,
        key=lambda f: (-score(f), -f["recorded_at"].timestamp(), str(f["id"])),
    )
    chosen = {str(f["id"]) for f in ranked[:batch]}
    if since is not None:
        recent = sorted(
            (f for f in facts if f["recorded_at"] > since),
            key=lambda f: (-f["recorded_at"].timestamp(), str(f["id"])),
        )
        chosen.update(str(f["id"]) for f in recent[:batch])
    return sorted(chosen)


def label_propagation(
    edges: list[tuple[str, str, float]], rounds: int = _PROPAGATION_ROUNDS
) -> dict[str, str]:
    """Weighted label propagation over an undirected graph.

    Deterministic: nodes are visited in sorted order, each takes the label with
    the largest total edge weight among its neighbours, ties going to the
    smallest label, and it stops when a full pass changes nothing.
    """
    neighbours: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for a, b, weight in edges:
        if a != b:
            neighbours[a][b] += weight
            neighbours[b][a] += weight
    order = sorted(neighbours)
    labels = {node: node for node in order}
    for _ in range(rounds):
        changed = False
        for node in order:
            totals: dict[str, float] = defaultdict(float)
            for other, weight in neighbours[node].items():
                totals[labels[other]] += weight
            best = min(totals, key=lambda label: (-totals[label], label))
            if best != labels[node]:
                labels[node] = best
                changed = True
        if not changed:
            break
    return labels


def communities(
    labels: dict[str, str], is_member: Any, min_size: int
) -> list[list[str]]:
    """Groups of nodes sharing a label that pass ``is_member`` (the fact test),
    with at least ``min_size`` members. Largest first, then smallest id."""
    groups: dict[str, list[str]] = defaultdict(list)
    for node, label in labels.items():
        if is_member(node):
            groups[label].append(node)
    found = [sorted(members) for members in groups.values() if len(members) >= min_size]
    return sorted(found, key=lambda members: (-len(members), members[0]))


def trim_words(text: str, limit: int) -> str:
    return " ".join(text.split()[:limit])


# ---------------------------------------------------------------------------
# Database phases
# ---------------------------------------------------------------------------


async def _summarise(client: Any, instruction: str, contents: list[str]) -> str:
    """One model call; plain text trimmed to the word cap, "" on failure."""
    facts = "\n".join(f"- {c[:200]}" for c in contents[:_PROMPT_FACTS])
    limit = int(settings.dreaming_theme_summary_words)
    prompt = f"{instruction} Use at most {limit} words, plain text.\n\nFACTS:\n{facts}"
    try:
        reply = await client.complete(
            [{"role": "user", "content": prompt}],
            model=settings.memory_extraction_model or settings.active_l2_model,
            temperature=0,
        )
    except Exception as e:
        logger.warning(f"[DREAM-V2] Summary call failed: {e}")
        return ""
    return trim_words(str(reply or ""), limit)


async def _community_graph(
    db: Any, replay_ids: list[str], rids: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], list[tuple[str, str, float]]]:
    """Replayed facts, their one-hop neighbours through shared entities, and
    the edges among them: ``about`` (weight 1) and ``co_used`` (its weight).

    Returns ``(facts by id, edges)``; only current, unarchived facts are kept.
    """
    about = await db.query(
        "SELECT in, out FROM about WHERE in IN $ids", {"ids": [rids[i] for i in replay_ids]}
    )
    entities = {str(r["out"]): r["out"] for r in about}
    neighbours = await db.query(
        "SELECT in, out FROM about WHERE out IN $ids", {"ids": list(entities.values())}
    )
    for row in neighbours:
        rids.setdefault(str(row["in"]), row["in"])
    fact_ids = sorted({str(r["in"]) for r in about} | {str(r["in"]) for r in neighbours})
    rows = await db.query(
        "SELECT id, content, visibility FROM fact "
        "WHERE id IN $ids AND valid_to IS NONE AND archived != true",
        {"ids": [rids[i] for i in fact_ids]},
    )
    facts = {str(r["id"]): r for r in rows}
    edges = [
        (a, b, 1.0)
        for a, b in sorted({(str(r["in"]), str(r["out"])) for r in about + neighbours})
        if a in facts
    ]
    co_used = await db.query(
        "SELECT in, out, weight FROM co_used WHERE in IN $ids OR out IN $ids",
        {"ids": [rids[i] for i in facts]},
    )
    edges += [
        (str(r["in"]), str(r["out"]), float(r["weight"] or 1.0))
        for r in co_used
        if str(r["in"]) in facts and str(r["out"]) in facts
    ]
    return facts, edges


async def update_themes(
    db: Any, client: Any, embeddings: Any, since: datetime | None
) -> int:
    """Replay, find communities per visibility, create or update themes.

    Returns the number of model calls made. A theme whose members did not
    change is left alone; past ``dreaming_theme_max_per_cycle`` calls the rest
    wait for the next cycle (nothing about them was written).
    """
    now = get_clock().now()
    rows = await db.query(
        "SELECT id, salience, recorded_at FROM fact "
        "WHERE valid_to IS NONE AND archived != true"
    )
    rids = {str(r["id"]): r["id"] for r in rows}
    replay = select_replay(
        rows, now, int(settings.dreaming_replay_batch),
        float(settings.dreaming_replay_recency_days), since,
    )
    if not replay:
        return 0
    facts, edges = await _community_graph(db, replay, rids)

    found: list[tuple[str, list[str]]] = []
    for visibility in sorted({f["visibility"] for f in facts.values()}):
        # Entities are shared, so only this visibility's facts keep their edges.
        same = {i for i, f in facts.items() if f["visibility"] == visibility}
        subset = [
            e for e in edges
            if all(n in same or not n.startswith("fact:") for n in e[:2])
        ]
        labels = label_propagation(subset)
        found += [
            (visibility, members)
            for members in communities(
                labels, lambda n: n in same, int(settings.dreaming_theme_min_facts)
            )
        ]
    if not found:
        return 0

    all_ids = sorted({i for _, members in found for i in members})
    links = await db.query(
        "SELECT in, out FROM member_of WHERE in IN $ids", {"ids": [rids[i] for i in all_ids]}
    )
    theme_rids = {str(r["out"]): r["out"] for r in links}
    current: dict[str, set[str]] = defaultdict(set)
    if theme_rids:
        for r in await db.query(
            "SELECT in, out FROM member_of WHERE out IN $ids", {"ids": list(theme_rids.values())}
        ):
            current[str(r["out"])].add(str(r["in"]))
    overlap: dict[str, set[str]] = defaultdict(set)
    for r in links:
        overlap[str(r["out"])].add(str(r["in"]))

    calls = 0
    taken: set[str] = set()
    for visibility, members in found:
        member_set = set(members)
        matches = sorted(
            (t for t in overlap if t not in taken and len(overlap[t] & member_set) * 2 >= len(members)),
            key=lambda t: (-len(overlap[t] & member_set), t),
        )
        theme = matches[0] if matches else None
        if theme:
            taken.add(theme)
            # Members this cycle did not look at (outside the replay and its
            # neighbours) stay while they are current and unarchived; only
            # facts this cycle placed elsewhere leave the theme.
            member_set |= {i for i in current[theme] if i not in facts and i in rids}
            if current[theme] == member_set:
                continue
        if calls >= int(settings.dreaming_theme_max_per_cycle):
            continue
        calls += 1
        summary = await _summarise(
            client, "Summarise what these facts say about one topic.",
            [facts[i]["content"] for i in members],
        )
        if not summary:
            logger.info("[DREAM-V2] Empty theme summary; skipped this cycle")
            continue
        theme_rid = theme_rids[theme] if theme else to_record_id(f"theme:{uuid4().hex}")
        fields = {
            "content": summary,
            "visibility": visibility,
            "updated_at": now,
            "fact_count": len(member_set),
        }
        embedding = await embeddings.embed(summary)
        if embedding is not None:
            fields["embedding"] = embedding
        if theme:
            head = "UPDATE $t MERGE $fields; DELETE member_of WHERE out = $t;"
        else:
            fields["recorded_at"] = now
            head = "CREATE $t CONTENT $fields;"
        await db.query(
            f"BEGIN TRANSACTION; {head} "
            "INSERT RELATION INTO member_of $edges; COMMIT TRANSACTION;",
            {
                "t": theme_rid,
                "fields": fields,
                "edges": [{"in": rids[i], "out": theme_rid} for i in sorted(member_set)],
            },
        )
    return calls


async def update_entity_summaries(db: Any, client: Any) -> int:
    """Rewrite the summary of entities with owner facts newer than their
    ``summary_updated_at``. Only current, unarchived owner facts are used, so a
    guild or private fact never reaches the shared entity. Returns model calls.
    """
    now = get_clock().now()
    rows = await db.query(
        "SELECT id, content, recorded_at FROM fact "
        "WHERE visibility = 'owner' AND valid_to IS NONE AND archived != true"
    )
    if not rows:
        return 0
    facts = {str(r["id"]): r for r in rows}
    about = await db.query(
        "SELECT in, out FROM about WHERE in IN $ids", {"ids": [r["id"] for r in rows]}
    )
    by_entity: dict[str, list[dict[str, Any]]] = defaultdict(list)
    entity_rids: dict[str, Any] = {}
    for r in about:
        by_entity[str(r["out"])].append(facts[str(r["in"])])
        entity_rids[str(r["out"])] = r["out"]
    entities = await db.query(
        "SELECT id, summary_updated_at FROM entity WHERE id IN $ids",
        {"ids": list(entity_rids.values())},
    )
    stale = sorted(
        str(e["id"]) for e in entities
        if e.get("summary_updated_at") is None
        or any(f["recorded_at"] > e["summary_updated_at"] for f in by_entity[str(e["id"])])
    )
    calls = 0
    for entity in stale[: int(settings.dreaming_entity_summary_max_per_cycle)]:
        calls += 1
        newest = sorted(by_entity[entity], key=lambda f: f["recorded_at"], reverse=True)
        summary = await _summarise(
            client, "Summarise what is known about one entity.",
            [f["content"] for f in newest],
        )
        if not summary:
            logger.info("[DREAM-V2] Empty entity summary; skipped this cycle")
            continue
        await db.query(
            "UPDATE $e SET summary = $s, summary_updated_at = $now",
            {"e": entity_rids[entity], "s": summary, "now": now},
        )
    return calls
