"""Real per-turn outcome signal (G5-03, agency PRD 7 step 1, behavior PRD 11).

No model call anywhere in this module. A turn is ``negative`` when the owner
rephrases the previous message or opens with a correction, ``positive`` only on
explicit positive feedback or passing tests of a delegated task, and otherwise
``unknown``. Silence is never positive.

Turns are kept in a small in-memory ring per conversation (no persistence). When
the conversation id is unknown the caller keys the ring by user id.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import Any

from aura.config import settings
from aura.engines.recall.feedback import _content_words

logger = logging.getLogger(__name__)

# Matched case-insensitively at the start of the stripped message.
CORRECTION_MARKERS: tuple[str, ...] = ("no,", "that's not", "that’s not", "i meant", "wrong")

_RING_CAP_KEYS = 256  # bound on the number of conversations kept

_rings: dict[str, deque["Turn"]] = {}


@dataclass
class Turn:
    experience_id: str
    text: str
    embedding: list[float] | None = None
    resolved: bool = False  # already patched; never patched twice


def _cosine(a: list[float], b: list[float]) -> float:
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / norm if norm else 0.0


def starts_with_correction(text: str) -> bool:
    return (text or "").strip().lower().startswith(CORRECTION_MARKERS)


async def classify_outcome(
    previous_turn: Turn | None,
    current_turn: Turn,
    embeddings: Any = None,
    *,
    explicit_feedback: str | None = None,
    task_tests_passed: bool | None = None,
) -> tuple[str, str]:
    """Return ``(signal, source)`` for ``previous_turn`` given ``current_turn``.

    ``explicit_feedback`` ("positive" or "negative", from a thumbs control) overrides
    everything. ``task_tests_passed`` is for G5-04 (True is positive).
    """
    if explicit_feedback in ("positive", "negative"):
        return explicit_feedback, "explicit"
    if task_tests_passed is True:
        return "positive", "task_tests"
    if previous_turn is None:
        return "unknown", "none"
    if starts_with_correction(current_turn.text):
        return "negative", "correction_marker"

    prev_words = _content_words(previous_turn.text)
    cur_words = _content_words(current_turn.text)
    smaller = min(len(prev_words), len(cur_words))
    if smaller and len(prev_words & cur_words) / smaller >= settings.outcome_rephrase_overlap:
        return "negative", "rephrase"
    if current_turn.embedding and previous_turn.embedding:
        if (
            _cosine(current_turn.embedding, previous_turn.embedding)
            >= settings.outcome_rephrase_similarity
        ):
            return "negative", "rephrase"
    return "unknown", "none"


def _outcome_dict(signal: str, source: str) -> dict[str, Any]:
    success = {"positive": True, "negative": False}.get(signal)
    return {"signal": signal, "success": success, "source": source}


def reset_rings() -> None:
    _rings.clear()


async def track_turn_outcome(
    engine: Any,
    embeddings: Any,
    *,
    key: str,
    speaker: str,
    text: str,
    experience_id: str | None,
    explicit_feedback: str | None = None,
    on_outcome: Any = None,
) -> None:
    """Classify the earlier owner turns against this one and patch them. Never raises.

    ``on_outcome(experience_id, signal)`` (async, optional) runs after each patch; G5-04
    uses it to count skill uses. Its failures are logged and never reach the turn.
    """
    try:
        await _track(
            engine, embeddings, key, speaker, text, experience_id, explicit_feedback, on_outcome
        )
    except Exception as exc:
        logger.warning("Turn outcome tracking failed (non-critical): %s", exc)


async def _track(
    engine: Any,
    embeddings: Any,
    key: str,
    speaker: str,
    text: str,
    experience_id: str | None,
    explicit_feedback: str | None,
    on_outcome: Any = None,
) -> None:
    async def patched(eid: str, signal: str) -> None:
        if on_outcome is None:
            return
        try:
            await on_outcome(eid, signal)
        except Exception as exc:
            logger.warning("Outcome hook failed (non-critical): %s", exc)

    # Guest turns neither classify nor get classified.
    if speaker != "owner" or not experience_id or not (text or "").strip():
        return
    ring = _rings.get(key)
    if ring is None:
        if len(_rings) >= _RING_CAP_KEYS:
            _rings.pop(next(iter(_rings)))
        ring = _rings[key] = deque(maxlen=settings.outcome_rephrase_turns)

    current = Turn(experience_id=experience_id, text=text)
    candidates = [t for t in reversed(ring) if not t.resolved]
    # One embeddings call (never an LLM); kept so later turns can compare with it.
    try:
        vector = await embeddings.embed(text)
        current.embedding = list(vector) if vector else None
    except Exception as exc:
        logger.debug("Outcome embedding failed: %s", exc)

    # A correction marker refers to the turn just before it; a rephrase to any of
    # the last few.
    if starts_with_correction(text):
        candidates = candidates[:1] if ring and not ring[-1].resolved else []
    for prev in candidates:
        signal, source = await classify_outcome(prev, current, embeddings)
        if signal == "negative":
            prev.resolved = True
            await engine.set_experience_outcome(
                prev.experience_id, _outcome_dict(signal, source)
            )
            await patched(prev.experience_id, signal)
            break
    ring.append(current)

    if explicit_feedback in ("positive", "negative"):
        # Thumbs on this turn's own reply overrides.
        current.resolved = True
        await engine.set_experience_outcome(
            experience_id, _outcome_dict(explicit_feedback, "explicit")
        )
        await patched(experience_id, explicit_feedback)
