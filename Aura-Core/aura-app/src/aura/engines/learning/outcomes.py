"""Real per-turn outcome signal (G5-03, agency PRD 7 step 1, behavior PRD 11).

No model call anywhere in this module. A turn is ``negative`` when the owner
rephrases the previous message or opens with a correction, ``positive`` only on
explicit positive feedback or passing tests of a delegated task, and otherwise
``unknown``. Silence is never positive.

Turns are kept in a small in-memory ring per conversation (no persistence). When
the conversation id is unknown the caller keys the ring by user id.

B1-03 adds two more sources (``source`` values only; the signal vocabulary stays
``positive|negative|unknown``): ``explicit`` (owner thumbs through
``POST /chat/outcome``, applied by :func:`apply_explicit_outcome`) and ``task``
(a delegated task or code node finished with a passing review or an approved
merge, applied by :func:`record_task_evidence` to the turn that requested it).
An explicit signal beats everything and is never replaced by a task signal.

Consumers of the outcome: skill statistics (G5-04, through ``on_outcome``),
prediction settlement (B6) and dismissal learning (B5-03).
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aura.config import settings
from aura.engines.recall.feedback import _content_words

logger = logging.getLogger(__name__)

# Matched case-insensitively at the start of the stripped message.
CORRECTION_MARKERS: tuple[str, ...] = ("no,", "that's not", "that’s not", "i meant", "wrong")

_RING_CAP_KEYS = 256  # bound on the number of conversations kept

_rings: dict[str, deque["Turn"]] = {}


@dataclass
class _Logged:
    """One owner turn remembered for task evidence (B1-03)."""

    at: datetime
    experience_id: str
    source: str | None = None  # source of the last patch, if any


_TURN_LOG_CAP = 64
_turn_log: dict[str, deque[_Logged]] = {}
# The engine and hook of the last tracked turn; task evidence has no coordinator in hand.
_bound: dict[str, Any] = {"engine": None, "on_outcome": None}


def _now() -> datetime:
    from aura.clock import get_clock

    return _aware(get_clock().now())


def _aware(value: Any) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


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
    _turn_log.clear()
    _bound.update(engine=None, on_outcome=None)


def _mark(experience_id: str, source: str, *, resolve: bool = False) -> None:
    for log in _turn_log.values():
        for entry in log:
            if entry.experience_id == experience_id:
                entry.source = source
    if resolve:
        for ring in _rings.values():
            for turn in ring:
                if turn.experience_id == experience_id:
                    turn.resolved = True


async def apply_explicit_outcome(
    engine: Any, experience_id: str, signal: str, on_outcome: Any = None
) -> str:
    """Owner thumbs: ``signal`` is ``up`` or ``down``. Overrides any implicit outcome
    and calls the same downstream hook as G5-03. Returns the stored signal."""
    stored = {"up": "positive", "down": "negative"}[signal]
    _mark(experience_id, "explicit", resolve=True)
    await engine.set_experience_outcome(experience_id, _outcome_dict(stored, "explicit"))
    if on_outcome is not None:
        try:
            await on_outcome(experience_id, stored)
        except Exception as exc:
            logger.warning("Outcome hook failed (non-critical): %s", exc)
    return stored


async def record_task_evidence(conversation_id: str | None, requested_at: Any) -> str | None:
    """A task requested in ``conversation_id`` at ``requested_at`` finished with a passing
    review or an approved merge: mark the turn that requested it positive, source ``task``.

    The requesting turn is the first owner turn logged at or after ``requested_at`` (a turn
    is logged right after its reply, and a task is requested during that reply). Returns the
    experience id patched, or None (flag off, unknown turn, explicit signal present). Never raises.
    """
    try:
        if not settings.outcome_signals_enabled or not conversation_id or requested_at is None:
            return None
        engine = _bound["engine"]
        if engine is None:
            return None
        since = _aware(requested_at)
        entry = next((e for e in _turn_log.get(conversation_id, ()) if e.at >= since), None)
        if entry is None or entry.source in ("explicit", "task"):
            return None
        entry.source = "task"
        await engine.set_experience_outcome(
            entry.experience_id, _outcome_dict("positive", "task")
        )
        hook = _bound["on_outcome"]
        if hook is not None:
            await hook(entry.experience_id, "positive")
        return entry.experience_id
    except Exception as exc:
        logger.warning("Task evidence not recorded (non-critical): %s", exc)
        return None


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
    _bound.update(engine=engine, on_outcome=on_outcome)
    log = _turn_log.get(key)
    if log is None:
        if len(_turn_log) >= _RING_CAP_KEYS:
            _turn_log.pop(next(iter(_turn_log)))
        log = _turn_log[key] = deque(maxlen=_TURN_LOG_CAP)
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
            _mark(prev.experience_id, source)
            await engine.set_experience_outcome(
                prev.experience_id, _outcome_dict(signal, source)
            )
            await patched(prev.experience_id, signal)
            break
    ring.append(current)
    log.append(_Logged(at=_now(), experience_id=experience_id))

    if explicit_feedback in ("positive", "negative"):
        # Thumbs on this turn's own reply overrides.
        current.resolved = True
        _mark(experience_id, "explicit")
        await engine.set_experience_outcome(
            experience_id, _outcome_dict(explicit_feedback, "explicit")
        )
        await patched(experience_id, explicit_feedback)
