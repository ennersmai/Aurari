"""Rerank on features for the fact recall path (W4-04, PRD 6.3 step 5).

Pure maths, no I/O. Takes the fused fact candidates with the fields the score
needs, drops what must not be shown, rescales the fused score by provenance,
confidence, salience and age, adds an emotional resonance term, and orders the
result with maximal marginal relevance so near-duplicates do not fill the top.

Fused scores are first divided by the best fused score, so they lie in (0, 1]
and the resonance term (a cosine) and MMR's similarity are on the same scale.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from aura.config import settings

# Dimensions whose deviation counts as negative affect when deciding whether
# the current state is too dark to resonate with.
_NEGATIVE_DIMS = ("fear", "sadness", "anger", "shame", "disgust")


@dataclass
class RerankCandidate:
    """One fused fact with the fields the rerank needs.

    ``signature`` is the emotional signature stored with the fact (or with the
    episode it derives from); ``None`` or empty means no resonance.
    """

    id: str
    score: float
    provenance: str
    confidence: float
    salience: float
    recorded_at: datetime
    valid_to: datetime | None = None
    embedding: list[float] | None = None
    signature: dict[str, float] | None = None


def _cosine(a: list[float] | None, b: list[float] | None) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _dict_cosine(a: dict[str, float], b: dict[str, float]) -> float:
    dims = sorted(set(a) | set(b))
    return _cosine([a.get(d, 0.0) for d in dims], [b.get(d, 0.0) for d in dims])


def _resonance(
    signature: dict[str, float] | None,
    baseline: dict[str, float],
    deviation: dict[str, float] | None,
) -> float:
    """Cosine of (signature - baseline) with the current deviation, never above 0
    when the negative dimensions of the deviation dominate the positive ones."""
    if not signature or not deviation:
        return 0.0
    negative = sum(max(0.0, deviation.get(d, 0.0)) for d in _NEGATIVE_DIMS)
    positive = sum(
        max(0.0, v) for d, v in deviation.items() if d not in _NEGATIVE_DIMS
    )
    shifted = {d: v - baseline.get(d, 0.0) for d, v in signature.items()}
    cosine = _dict_cosine(shifted, deviation)
    if negative > positive:
        return min(cosine, 0.0)
    return cosine


def rerank(
    candidates: list[RerankCandidate],
    *,
    now: datetime,
    mode: str,
    has_time_range: bool,
    deviation: dict[str, float] | None = None,
    baseline: dict[str, float] | None = None,
    limit: int | None = None,
) -> list[RerankCandidate]:
    """Return ``candidates`` filtered, rescored and ordered by MMR.

    Superseded facts are dropped unless ``has_time_range``; imagined facts are
    dropped unless ``mode == "creative"``. At most ``limit`` are returned
    (all when ``None``). Each ``score`` on the returned
    candidates is the reranked score.
    """
    kept = [
        c
        for c in candidates
        if (has_time_range or c.valid_to is None)
        and (mode == "creative" or c.provenance != "imagined")
    ]
    if not kept:
        return []

    top = max(c.score for c in kept) or 1.0
    baseline = baseline or {}
    weights: dict[str, Any] = settings.recall_rerank_provenance_weights
    scored: list[RerankCandidate] = []
    for c in kept:
        age_days = max(0.0, (now - c.recorded_at).total_seconds() / 86400.0)
        score = (
            (c.score / top)
            * weights.get(c.provenance, 1.0)
            * (0.5 + 0.5 * c.confidence)
            * (1.0 + settings.recall_rerank_salience_boost * c.salience)
            * math.exp(-age_days / settings.recall_rerank_decay_days)
        )
        score += settings.recall_rerank_resonance_weight * _resonance(
            c.signature, baseline, deviation
        )
        scored.append(
            RerankCandidate(
                id=c.id,
                score=score,
                provenance=c.provenance,
                confidence=c.confidence,
                salience=c.salience,
                recorded_at=c.recorded_at,
                valid_to=c.valid_to,
                embedding=c.embedding,
                signature=c.signature,
            )
        )

    return _mmr(scored, limit)


def _mmr(scored: list[RerankCandidate], limit: int | None) -> list[RerankCandidate]:
    """Greedy maximal marginal relevance over the reranked scores.

    Picks up to ``limit`` candidates (all when ``None``). Each candidate's
    highest similarity to the already chosen ones is kept up to date after every
    pick, so the cost is one similarity row per pick, not per pair per pick.
    """
    lam = settings.recall_rerank_mmr_lambda
    top = max(c.score for c in scored)
    scale = top if top > 0 else 1.0
    pool = sorted(scored, key=lambda c: (-c.score, c.id))
    count = len(pool) if limit is None else min(limit, len(pool))

    dim = max((len(c.embedding) for c in pool if c.embedding), default=0)
    vectors = np.zeros((len(pool), max(dim, 1)))
    for row, c in enumerate(pool):
        if c.embedding and len(c.embedding) == dim:
            vectors[row] = c.embedding
    norms = np.linalg.norm(vectors, axis=1)
    norms[norms == 0] = 1.0
    unit = vectors / norms[:, None]

    relevance = np.array([lam * c.score / scale for c in pool])
    max_sim = np.zeros(len(pool))
    open_ = np.ones(len(pool), dtype=bool)
    chosen: list[RerankCandidate] = []
    for _ in range(count):
        value = np.where(open_, relevance - (1.0 - lam) * max_sim, -np.inf)
        pick = int(np.argmax(value))
        chosen.append(pool[pick])
        open_[pick] = False
        max_sim = np.maximum(max_sim, unit @ unit[pick])
    return chosen
