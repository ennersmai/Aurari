"""Fact writing for memory v2 (W3-15).

An episode is what was said; a fact is one atomic statement learned from it.
This module turns one validated extraction into ``fact`` records:

* every extracted entity is resolved to an ``entity`` (W3-14) and linked from
  the episode with a ``mentions`` edge;
* Aura's own statements (``asserted_by == "aura"``) are never stored as facts
  about the world (PRD rule 5);
* provenance follows who spoke and what the subject is: ``implied`` facts are
  ``inferred``, the speaker's own world is ``observed``, and another person's
  words about a person are ``hearsay``;
* confidence comes from the three configured provenance settings, and
  visibility from the venue (W3-10);
* a guest can never create an ``observed`` or ``inferred`` fact about the
  owner: anything a guest says whose subject is the owner is ``hearsay``
  (PRD rule 6).

Each stored fact gets ``derived_from`` to its episode and ``about`` to the
entities it concerns. Before a fact is stored it goes through the conflict
check (W3-16): a duplicate raises the existing fact's confidence and stores
nothing new, an update closes the old fact with ``valid_to`` and links
``supersedes``, and a contradiction links ``contradicts`` and opens a
``question``. Facts are never deleted.

Every value is bound as a query parameter.
"""

from __future__ import annotations

import logging
from typing import Any

from surrealdb.types import RecordID

from aura.clock import get_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.memory.v2.conflicts import classify
from aura.engines.memory.v2.entities import resolve_entity
from aura.engines.memory.v2.extraction import (
    ExtractedEntity,
    ExtractedFact,
    Extraction,
)
from aura.engines.memory.v2.identity import visibility_for_venue

logger = logging.getLogger(__name__)

# Confidence for each provenance this module can produce. Read from settings
# at call time so tests (and the deployment) can change them.
_CONFIDENCE_SETTINGS = {
    "observed": "memory_observed_confidence",
    "hearsay": "memory_hearsay_confidence",
    "inferred": "memory_inferred_confidence",
    "external": "memory_external_confidence",
}


def _normalise(name: str) -> str:
    """Match the normalisation used by entity resolution."""
    return " ".join(name.split()).lower()


def _speaker_key(episode: dict[str, Any]) -> str:
    """Return the episode speaker's key, e.g. ``"owner"`` or ``"discord_42"``."""
    speaker = episode.get("speaker")
    text = str(speaker) if speaker is not None else "owner"
    if text.startswith("entity:"):
        return text[len("entity:") :]
    return text


def _extraction_parts(
    extraction: Extraction | dict[str, Any],
) -> tuple[list[ExtractedEntity], list[ExtractedFact]]:
    """Return the entities and facts of a model or a stored extraction dict."""
    if isinstance(extraction, dict):
        entities = [
            ExtractedEntity.model_validate(item)
            for item in extraction.get("entities", [])
        ]
        facts = [
            ExtractedFact.model_validate(item) for item in extraction.get("facts", [])
        ]
        return entities, facts
    return list(extraction.entities), list(extraction.facts)


async def _entity_row(db: Any, entity_id: RecordID | str) -> dict[str, Any]:
    """Return one entity record, or an empty dict when it is missing."""
    rows = await db.query("SELECT * FROM $rid", {"rid": entity_id})
    return rows[0] if rows else {}


async def _resolve(
    db: Any,
    embeddings: Any,
    cache: dict[str, RecordID],
    name: str | None,
    type: str,
    speaker: str,
) -> RecordID | None:
    """Resolve ``name`` once per extraction, reusing the result."""
    if not name:
        return None
    key = _normalise(name)
    if key not in cache:
        cache[key] = await resolve_entity(db, embeddings, name, type, speaker)
    return cache[key]


async def write_facts(
    db: Any,
    embeddings: Any,
    episode: dict[str, Any],
    extraction: Extraction | dict[str, Any],
    *,
    provenance: str | None = None,
    sources: list[str] | None = None,
) -> list[RecordID]:
    """Store the facts of one successful extraction and link them.

    ``provenance`` (only ``"external"``, B4-02) replaces the derived provenance
    for every fact and ``sources`` (URLs) is stored on each fact; both are
    unused for conversation extractions.

    ``episode`` is the stored episode row (with ``speaker`` and ``venue``) and
    ``extraction`` is the validated result of the extraction call. Returns the
    ids of the facts created.
    """
    speaker = _speaker_key(episode)
    speaker_id = str(to_record_id(f"entity:{speaker}"))
    venue = episode.get("venue")
    entities, facts = _extraction_parts(extraction)

    # Resolve every extracted entity and remember its id by normalised name so
    # the facts below do not repeat the work or the embedding calls.
    resolved: dict[str, RecordID] = {}
    extracted_types: dict[str, str] = {}
    mentioned: list[RecordID] = []
    seen_mentions: set[str] = set()
    for entity in entities:
        key = _normalise(entity.name)
        entity_id = await _resolve(
            db, embeddings, resolved, entity.name, entity.type, speaker
        )
        if entity_id is None:  # pragma: no cover - names are required by the model
            continue
        extracted_types[key] = entity.type
        if str(entity_id) in seen_mentions:
            continue
        seen_mentions.add(str(entity_id))
        mentioned.append(entity_id)
        await db.query(
            "RELATE $episode->mentions->$entity",
            {"episode": episode["id"], "entity": entity_id},
        )

    created: list[RecordID] = []
    for fact in facts:
        # Rule 5: Aura's own words are not facts about the world.
        if fact.asserted_by == "aura":
            continue

        about_ids: list[RecordID] = []
        seen_about: set[str] = set()
        for name in fact.about:
            type_ = extracted_types.get(_normalise(name), "other")
            entity_id = await _resolve(db, embeddings, resolved, name, type_, speaker)
            if entity_id is not None and str(entity_id) not in seen_about:
                seen_about.add(str(entity_id))
                about_ids.append(entity_id)

        subject_id = await _resolve(
            db,
            embeddings,
            resolved,
            fact.subject,
            extracted_types.get(_normalise(fact.subject or ""), "other"),
            speaker,
        )
        if subject_id is not None and str(subject_id) not in seen_about:
            seen_about.add(str(subject_id))
            about_ids.append(subject_id)

        fact_provenance = await _provenance(db, fact, subject_id, speaker_id)
        if provenance == "external":
            fact_provenance = "external"
        # Rule 6: nothing a guest says changes what the owner said about
        # themselves. A guest's statement about the owner is always hearsay,
        # even when it was marked implied.
        if speaker != "owner" and subject_id is not None:
            if str(subject_id) == "entity:owner":
                fact_provenance = "hearsay"

        now = get_clock().now()
        data = {
            "content": fact.content,
            "kind": fact.kind,
            "subject": fact.subject,
            "predicate": fact.predicate,
            "object": fact.object,
            "provenance": fact_provenance,
            "visibility": visibility_for_venue(venue, speaker),
            "confidence": getattr(settings, _CONFIDENCE_SETTINGS[fact_provenance]),
            "valid_from": now,
            "recorded_at": now,
            "embedding": await embeddings.embed(fact.content),
        }
        if sources:
            data["sources"] = list(sources)
        classification, existing_id = await classify(
            db,
            {**data, "subject_id": subject_id, "negates": fact.negates},
            about_ids,
        )

        if classification == "duplicate":
            # The same statement was heard again: raise the existing fact's
            # confidence and link it to this episode, but store nothing new.
            await db.query(
                "UPDATE $fact SET confidence = math::min([1.0, confidence + $step])",
                {
                    "fact": existing_id,
                    "step": settings.memory_duplicate_confidence_step,
                },
            )
            await db.query(
                "RELATE $fact->derived_from->$episode",
                {"fact": existing_id, "episode": episode["id"]},
            )
            continue

        rows = await db.query("CREATE fact CONTENT $data", {"data": data})
        fact_id = rows[0]["id"]
        created.append(fact_id)

        await db.query(
            "RELATE $fact->derived_from->$episode",
            {"fact": fact_id, "episode": episode["id"]},
        )
        for entity_id in about_ids:
            await db.query(
                "RELATE $fact->about->$entity",
                {"fact": fact_id, "entity": entity_id},
            )

        if classification == "update":
            await db.query(
                "UPDATE $fact SET valid_to = $now",
                {"fact": existing_id, "now": now},
            )
            await db.query(
                "RELATE $fact->supersedes->$old",
                {"fact": fact_id, "old": existing_id},
            )
        elif classification == "contradiction":
            await db.query(
                "RELATE $fact->contradicts->$old",
                {"fact": fact_id, "old": existing_id},
            )
            old_rows = await db.query(
                "SELECT content FROM $fact",
                {"fact": existing_id},
            )
            old_content = old_rows[0].get("content") if old_rows else ""
            await db.query(
                "CREATE question CONTENT $data",
                {
                    "data": {
                        "content": (
                            f"Which is true: {old_content} or {fact.content}?"
                        ),
                        "visibility": data["visibility"],
                        "recorded_at": now,
                    }
                },
            )

    logger.info(
        "Wrote %s fact(s) and linked %s entit(ies) from episode %s",
        len(created),
        len(mentioned),
        episode.get("id"),
    )
    return created


async def _provenance(
    db: Any,
    fact: ExtractedFact,
    subject_id: RecordID | None,
    speaker_id: str,
) -> str:
    """Return the provenance of ``fact`` from its subject and the speaker."""
    if fact.implied:
        return "inferred"
    if subject_id is None:
        # No subject to attribute: the statement is Aura's interpretation.
        return "inferred"
    if str(subject_id) == speaker_id:
        return "observed"
    row = await _entity_row(db, subject_id)
    if row.get("type") != "person":
        return "observed"
    return "hearsay"