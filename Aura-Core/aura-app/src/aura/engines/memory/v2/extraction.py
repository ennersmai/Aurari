"""Structured extraction from one episode (W3-13).

Extraction is the memory v2 write after the turn: one model call reads the
current episode together with the two previous episodes in the same venue and
returns a single JSON object with entities, facts, questions and predictions.
The result is stored on the episode itself; writing facts and entities is the
job of later cards.

The call runs in a background task scheduled by :mod:`aura.engines.memory.v2.
episodes`, never on the reply path. A failed call increments the episode's
attempt count, stores the error, and leaves the episode ``pending`` until the
configured maximum is reached, when it becomes ``failed``. The episode is never
deleted.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from aura.config import settings
from aura.db.query_utils import to_record_id

logger = logging.getLogger(__name__)

ENTITY_TYPES = ("person", "project", "place", "tool", "concept", "other")
FACT_KINDS = ("fact", "preference", "pattern", "decision", "event")


class ExtractedEntity(BaseModel):
    """One entity mentioned by the turn."""

    name: str
    type: str
    surface: str

    @field_validator("type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        if value not in ENTITY_TYPES:
            logger.warning(
                "Unknown extracted entity type %r; coerced to 'other'", value
            )
            return "other"
        return value


class ExtractedFact(BaseModel):
    """One atomic statement extracted from the turn."""

    content: str
    kind: str
    subject: str | None = None
    predicate: str | None = None
    object: str | None = None
    about: list[str] = Field(default_factory=list)
    asserted_by: Literal["user", "aura"]
    implied: bool = False
    negates: bool = False

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        if value not in FACT_KINDS:
            logger.warning("Unknown extracted fact kind %r; coerced to 'fact'", value)
            return "fact"
        return value


class Extraction(BaseModel):
    """The validated result of one extraction call."""

    entities: list[ExtractedEntity]
    facts: list[ExtractedFact]
    questions: list[str]
    predictions: list[str]


_SYSTEM_PROMPT = """\
You extract structured memory from one conversational turn.

Reply with a single JSON object in exactly this shape:
{"entities": [{"name": "Miso", "type": "other", "surface": "my cat"}], \
"facts": [{"content": "The speaker has a cat named Miso.", "kind": "fact", \
"subject": "I", "predicate": "has", "object": "a cat named Miso", \
"about": ["Miso"], "asserted_by": "user", "implied": false, "negates": false}], \
"questions": [], "predictions": []}

Entity types are person, project, place, tool, concept or other. Fact kinds \
are fact, preference, pattern, decision or event.

Rules:
- Each fact is one self-contained sentence.
- `asserted_by` is `aura` for anything only Aura said.
- `subject` is `I` when the speaker talks about themselves.
- `negates` is true when the statement denies something said before.
"""


def _episode_block(episode: dict[str, Any]) -> str:
    """Render one episode as the card's ``speaker`` / ``Aura`` transcript."""
    return (
        f"speaker: {episode.get('user_text', '')}\n"
        f"Aura: {episode.get('aura_text', '')}"
    )


def build_prompt(episode: dict[str, Any], previous: list[dict[str, Any]]) -> list[dict]:
    """Build the messages for the extraction call.

    ``previous`` is rendered oldest first and limited to the two most recent
    episodes, matching what :func:`run_extraction` loads. Each episode is a
    ``speaker: user_text`` / ``Aura: aura_text`` pair.
    """
    blocks = ["Previous episodes:"]
    for row in previous[-2:]:
        blocks.append(_episode_block(row))
    blocks.append("Current episode:")
    blocks.append(_episode_block(episode))

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": "\n\n".join(blocks)},
    ]


def _first_json_object(text: str) -> dict[str, Any]:
    """Return the first JSON object in ``text``.

    The object may be bare or inside a Markdown code fence; scanning for each
    opening brace and using ``raw_decode`` accepts both without trusting the
    fence markers.
    """
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("No JSON object found in the extraction reply")


async def extract(
    client: Any,
    episode: dict[str, Any],
    previous: list[dict[str, Any]],
) -> Extraction:
    """Run one extraction call and validate its reply."""
    model = settings.memory_extraction_model or settings.l2_model
    reply = await client.complete(
        build_prompt(episode, previous),
        model=model,
        temperature=0,
    )
    data = _first_json_object(reply)
    return Extraction.model_validate(data)


async def run_extraction(db: Any, client: Any, episode_id: Any) -> Extraction | None:
    """Extract from one stored episode and record the outcome.

    On success the ``Extraction`` is stored as JSON in the episode's
    ``extraction`` field and the status becomes ``done``. On any failure the
    attempt count is incremented and the error stored; the status stays
    ``pending`` until the configured maximum attempts is reached, then becomes
    ``failed``. Returns the extraction, or ``None`` when it failed.
    """
    record_id = to_record_id(episode_id)
    rows = await db.query("SELECT * FROM $episode_id", {"episode_id": record_id})
    if not rows:
        logger.warning("Extraction skipped: episode %s does not exist", episode_id)
        return None
    episode = rows[0]

    try:
        previous_rows = await db.query(
            "SELECT * FROM episode "
            "WHERE venue = $venue AND id != $episode_id "
            "AND recorded_at <= $recorded_at "
            "ORDER BY recorded_at DESC LIMIT 2",
            {
                "venue": episode.get("venue"),
                "episode_id": record_id,
                "recorded_at": episode.get("recorded_at"),
            },
        )
        extraction = await extract(client, episode, list(reversed(previous_rows)))
    except Exception as exc:  # noqa: BLE001 - any failure is recorded on the episode
        attempts = int(episode.get("extraction_attempts") or 0) + 1
        status = (
            "failed"
            if attempts >= settings.memory_extraction_max_attempts
            else "pending"
        )
        await db.query(
            "UPDATE $episode_id MERGE $data",
            {
                "episode_id": record_id,
                "data": {
                    "extraction_attempts": attempts,
                    "extraction_error": str(exc),
                    "extraction_status": status,
                },
            },
        )
        logger.warning(
            "Memory extraction failed for episode %s (attempt %s/%s): %s",
            episode_id,
            attempts,
            settings.memory_extraction_max_attempts,
            exc,
        )
        return None

    await db.query(
        "UPDATE $episode_id MERGE $data",
        {
            "episode_id": record_id,
            "data": {
                "extraction": extraction.model_dump(),
                "extraction_status": "done",
            },
        },
    )

    # Writing facts is a separate step after a successful extraction. It must
    # not turn a stored extraction into a failure, so an error is logged and
    # the episode stays ``done``.
    try:
        from aura.engines.memory.v2.facts import write_facts
        from aura.llm.embeddings import get_embeddings_client

        await write_facts(db, get_embeddings_client(), episode, extraction)
    except Exception:  # noqa: BLE001 - extraction already succeeded
        logger.exception("Writing facts failed for episode %s", episode_id)
    return extraction