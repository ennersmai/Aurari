"""Recall gate — a rule-only check for turns that need retrieval (M3).

Card W3-06 (PRD memory 6.3 step 1). A turn whose whole input is a greeting or
an acknowledgement does not need the memories channel to run again: the engine
reuses the memories block from the previous packet for the same user and
session. This module decides only whether retrieval is needed; it uses no
classifier and no model call.

The configured phrases live in ``settings.recall_gate_phrases``. Both the input
and the phrases are compared after lowercasing, removing punctuation and
stripping surrounding whitespace.
"""

from __future__ import annotations

import re

from aura.config import settings

_PUNCTUATION_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalise(text: str) -> str:
    """Lowercase ``text``, remove punctuation and strip surrounding space."""
    return _PUNCTUATION_RE.sub("", text.casefold()).strip()


def needs_recall(user_input: str) -> bool:
    """Return ``False`` for empty or acknowledgement-only input.

    The input is lowercased, stripped of punctuation and surrounding
    whitespace. If the result is empty or equals one of the configured
    ``recall_gate_phrases`` (compared the same way), this returns ``False``;
    every other input returns ``True``.
    """
    if not user_input:
        return False
    normalised = _normalise(user_input)
    if not normalised:
        return False
    phrases = {_normalise(phrase) for phrase in settings.recall_gate_phrases}
    return normalised not in phrases