"""Reciprocal Rank Fusion for the Recall Engine (M3, W3-04).

Fuses the ranked candidate lists returned by the Recall Engine's channels
into one ranked list. The score of a memory is the sum, over the channels
that returned it, of ``1 / (k + rank + 1)`` with a 0-based ``rank``; ``k``
comes from ``settings.recall_rrf_k`` unless given. No per-channel weights
(PRD section 6.3 step 4).
"""

from dataclasses import dataclass

from aura.config import settings
from aura.engines.recall.channels import ChannelHit


@dataclass
class FusedHit:
    """One fused result.

    ``channel_ranks`` and ``channel_scores`` hold, per channel name, the
    rank and the raw score the channel gave this memory.
    """

    memory_id: str
    score: float
    channel_ranks: dict[str, int]
    channel_scores: dict[str, float]


def rrf(
    channels: dict[str, list[ChannelHit]], k: int | None = None
) -> list[FusedHit]:
    """Fuse ``channels`` into one list, best first.

    The order is deterministic: score descending, ties broken by the best
    (lowest) rank across channels, then by ``memory_id``.
    """
    rrf_k = settings.recall_rrf_k if k is None else k

    scores: dict[str, float] = {}
    ranks: dict[str, dict[str, int]] = {}
    raw_scores: dict[str, dict[str, float]] = {}

    for channel_name, hits in channels.items():
        for hit in hits:
            memory_id = hit.memory_id
            scores[memory_id] = scores.get(memory_id, 0.0) + 1.0 / (
                rrf_k + hit.rank + 1
            )
            ranks.setdefault(memory_id, {})[channel_name] = hit.rank
            raw_scores.setdefault(memory_id, {})[channel_name] = hit.score

    fused = [
        FusedHit(
            memory_id=memory_id,
            score=score,
            channel_ranks=ranks[memory_id],
            channel_scores=raw_scores[memory_id],
        )
        for memory_id, score in scores.items()
    ]
    fused.sort(
        key=lambda hit: (
            -hit.score,
            min(hit.channel_ranks.values()),
            hit.memory_id,
        )
    )
    return fused