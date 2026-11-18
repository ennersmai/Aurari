"""Recall Engine — one entry point over today's memory channels (M2).

This package implements the read-path Recall Engine from the memory PRD
section 6. Card W2-14 adds the package skeleton: the pure dataclasses in
:mod:`.models` and the pure assembly step in :mod:`.assembly`. Later cards
(W2-15 onwards) add the engine that wires today's stores into it.
"""

from .assembly import assemble, estimate_tokens, normalise_text
from .engine import RecallEngine, get_recall_engine
from .models import (
    BLOCK_ORDER,
    Block,
    BlockKind,
    Candidate,
    ContextPacket,
    RecallRequest,
    RecallTrace,
    TraceItem,
)

__all__ = [
    "BLOCK_ORDER",
    "Block",
    "BlockKind",
    "Candidate",
    "ContextPacket",
    "RecallEngine",
    "RecallRequest",
    "RecallTrace",
    "TraceItem",
    "assemble",
    "estimate_tokens",
    "get_recall_engine",
    "normalise_text",
]
