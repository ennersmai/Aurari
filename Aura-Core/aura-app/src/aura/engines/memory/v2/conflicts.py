"""The conflict check for memory v2 (W3-16).

Before a new fact is stored, it is compared with the current facts
(``valid_to IS NONE``) that are about any of the same entities and have the
same visibility. One of four relations is returned:

* ``duplicate``: an existing fact has an embedding cosine similarity at or
  above ``settings.memory_duplicate_similarity``. Nothing new is stored; the
  existing fact's confidence is raised instead (``facts.write_facts``).
* ``update``: an existing fact has the same resolved subject and the same
  predicate (lowercased, whitespace-collapsed) but a different object, and
  its provenance is not stronger than the new fact's
  (``observed`` > ``inferred`` > ``hearsay``).
* ``contradiction``: the new fact negates an existing fact at or above
  ``settings.memory_contradiction_similarity``, or an update was blocked
  only by the provenance rule (a guest's hearsay never updates an observed
  fact).
* ``new``: none of the above.

The classification is a pure read; ``facts.write_facts`` applies it. Every
value is bound as a query parameter, and no model is called.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

from surrealdb.types import RecordID

from aura.config import settings

# Provenance strength: a fact may only be updated by a statement whose
# provenance is at least as strong. Hearsay therefore never updates an
# observed fact.
_PROVENANCE_RANK = {"hearsay": 1, "inferred": 2, "observed": 3}


def _normalise(value: Any) -> str:
    """Lowercase ``value`` and collapse runs of whitespace to single spaces."""
    return " ".join(str(value or "").split()).lower()


def _cosine(left: Any, right: Any) -> float:
    """Return the cosine similarity of two embeddings, or 0.0 if unusable."""
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = 0.0
    left_norm = 0.0
    right_norm = 0.0
    for a, b in zip(left, right):
        dot += float(a) * float(b)
        left_norm += float(a) * float(a)
        right_norm += float(b) * float(b)
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return dot / math.sqrt(left_norm * right_norm)


async def _candidates(
    db: Any,
    new_fact: Mapping[str, Any],
    about_ids: list[RecordID],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Return current facts about the same entities and the subject matches.

    The second value holds the string ids of the facts whose ``about`` edges
    point at the new fact's resolved subject, so an ``I`` statement and a
    ``Mai`` statement about the same person compare as the same subject.
    """
    if not about_ids:
        return [], set()

    edges = await db.query(
        "SELECT * FROM about WHERE out IN $about_ids",
        {"about_ids": list(about_ids)},
    )

    fact_ids: list[RecordID] = []
    subject_facts: set[str] = set()
    seen: set[str] = set()
    subject_id = new_fact.get("subject_id")
    for edge in edges:
        fact_id = edge.get("in")
        if fact_id is None:
            continue
        key = str(fact_id)
        if subject_id is not None and str(edge.get("out")) == str(subject_id):
            subject_facts.add(key)
        if key in seen:
            continue
        seen.add(key)
        fact_ids.append(fact_id)

    if not fact_ids:
        return [], set()

    rows = await db.query(
        "SELECT * FROM fact "
        "WHERE id IN $fact_ids AND valid_to IS NONE AND visibility = $visibility",
        {"fact_ids": fact_ids, "visibility": new_fact.get("visibility")},
    )
    return rows, subject_facts


async def classify(
    db: Any,
    new_fact: Mapping[str, Any],
    about_ids: list[RecordID],
) -> tuple[str, RecordID | None]:
    """Classify the relation of ``new_fact`` to the current facts.

    ``new_fact`` carries the fields the conflict check needs: ``content``,
    ``subject``, ``subject_id`` (the resolved subject entity), ``predicate``,
    ``object``, ``provenance``, ``visibility``, ``embedding`` and ``negates``.
    ``about_ids`` are the resolved entities the new fact is about. Returns
    ``(classification, existing_fact_id)``; the id is ``None`` for ``new``.
    """
    rows, subject_facts = await _candidates(db, new_fact, about_ids)
    if not rows:
        return "new", None

    new_embedding = new_fact.get("embedding")
    new_subject = _normalise(new_fact.get("subject"))
    new_subject_id = new_fact.get("subject_id")
    new_predicate = _normalise(new_fact.get("predicate"))
    new_object = _normalise(new_fact.get("object"))
    new_rank = _PROVENANCE_RANK.get(str(new_fact.get("provenance")), 0)

    scored: list[tuple[dict[str, Any], float, bool]] = []
    for row in rows:
        similarity = _cosine(new_embedding, row.get("embedding"))
        if new_subject_id is not None:
            subject_match = str(row.get("id")) in subject_facts
        else:
            subject_match = bool(new_subject) and _normalise(
                row.get("subject")
            ) == new_subject
        scored.append((row, similarity, subject_match))

    # A negation against a sufficiently similar fact is a contradiction even
    # when the wording is identical (which would otherwise look duplicate).
    if new_fact.get("negates"):
        negated = [
            (row, similarity)
            for row, similarity, _ in scored
            if similarity >= settings.memory_contradiction_similarity
        ]
        if negated:
            row, _ = max(negated, key=lambda item: item[1])
            return "contradiction", row["id"]

    duplicates = [
        (row, similarity)
        for row, similarity, _ in scored
        if similarity >= settings.memory_duplicate_similarity
    ]
    if duplicates:
        row, _ = max(duplicates, key=lambda item: item[1])
        return "duplicate", row["id"]

    updates: list[tuple[dict[str, Any], float]] = []
    for row, similarity, subject_match in scored:
        if not subject_match:
            continue
        if _normalise(row.get("predicate")) != new_predicate:
            continue
        if _normalise(row.get("object")) == new_object:
            continue
        updates.append((row, similarity))

    if updates:
        row, _ = max(updates, key=lambda item: item[1])
        old_rank = _PROVENANCE_RANK.get(str(row.get("provenance")), 0)
        if old_rank <= new_rank:
            return "update", row["id"]
        # The update is blocked only by provenance: surface the conflict.
        return "contradiction", row["id"]

    return "new", None