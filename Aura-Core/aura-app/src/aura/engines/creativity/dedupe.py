"""Word-set Jaccard dedupe of ideas (P2-28). Pure code, no model call."""

from __future__ import annotations

import re

from aura.config import settings

_WORD = re.compile(r"\w+", re.UNICODE)


def word_set(text: str) -> frozenset[str]:
    return frozenset(_WORD.findall((text or "").lower()))


def jaccard(a: str, b: str) -> float:
    wa, wb = word_set(a), word_set(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def same_idea(a: str, b: str, threshold: float | None = None) -> bool:
    """Above the threshold (``diverge_jaccard``) means the same idea."""
    limit = settings.diverge_jaccard if threshold is None else threshold
    return jaccard(a, b) > limit


def dedupe(items: list[str], threshold: float | None = None) -> list[int | None]:
    """For each item, the index of the earlier kept item it duplicates, or None when it is new."""
    out: list[int | None] = []
    for i, text in enumerate(items):
        match = None
        for j in range(i):
            if out[j] is None and same_idea(text, items[j], threshold):
                match = j
                break
        out.append(match)
    return out
