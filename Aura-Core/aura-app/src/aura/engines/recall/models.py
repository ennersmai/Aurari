"""Recall Engine — models.

Pure standard-library dataclasses only. Nothing here imports from the
synthesis or orchestration layers (PRD section 6.1, card W2-14); the Recall
Engine must not depend on them.

The dataclasses describe the contract between the engine and its callers:

* :class:`RecallRequest` — what a turn asks the engine to assemble.
* :class:`Candidate` — one item pulled from a store, before assembly.
* :class:`TraceItem` — the per-candidate fate record inside a trace.
* :class:`RecallTrace` — the full trace for a turn.
* :class:`Block` — one rendered block of the assembled packet.
* :class:`ContextPacket` — the engine's return value, split into stable and
  dynamic blocks plus the trace.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal


# The four context blocks the L3 prompt renders today, in the order they appear
# in the prompt and in which deduplication and the budget run (PRD 6.3 step 6).
BlockKind = Literal["insights", "latent", "cold_start", "memories"]
BLOCK_ORDER: tuple[BlockKind, ...] = ("insights", "latent", "cold_start", "memories")


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


@dataclass
class RecallRequest:
    """A turn's request to the Recall Engine (PRD 6.1).

    The PRD 6.1 fields describe the user, the input and the budgets. The
    ``M2: wraps today's channel`` fields below carry the knobs today's
    individual stores expose, so M2 can wrap them unchanged; later milestones
    replace them.
    """

    user_id: str
    user_input: str
    session_id: str | None = None
    recent_turns: list[dict[str, str]] = field(default_factory=list)
    emotional_state: Any = None
    mode: Literal["chat", "task", "agent"] = "chat"
    token_budget: int | None = None  # None means use config
    latency_budget_ms: int | None = None

    # M2: wraps today's channel
    learning_context: Any = None
    # M2: wraps today's channel
    depth: int = 1
    # M2: wraps today's channel
    limit: int = 5
    # M2: wraps today's channel
    namespace: str | None = None
    # M2: wraps today's channel
    include_cold_start: bool = False
    # M2: wraps today's channel
    include_latent: bool = True


# ---------------------------------------------------------------------------
# Candidates and trace
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One item pulled from a store, before assembly.

    ``source`` names the store, for example ``"memory.retrieve_for_l3"``.
    ``dedup_keys`` are the normalised keys the deduplication step compares; a
    candidate is a duplicate if any of its keys was already registered by an
    earlier candidate (in ``BLOCK_ORDER``). ``rank`` orders candidates within a
    block (ascending; lower is better).
    """

    block: BlockKind
    key: str
    dedup_keys: tuple[str, ...]
    payload: Any
    rank: int
    source: str


@dataclass
class TraceItem:
    """One candidate's fate inside a trace."""

    block: BlockKind
    key: str
    source: str
    rank: int
    tokens: int
    fate: Literal["kept", "duplicate", "over_budget"]
    duplicate_of: str | None = None


@dataclass
class RecallTrace:
    """The full trace for one turn (PRD 6.6)."""

    turn_id: str
    user_id: str
    query: str
    created_at: datetime
    budget_tokens: int
    tokens_before: int
    tokens_after: int
    items: list[TraceItem]
    channel_errors: dict[str, str]


# ---------------------------------------------------------------------------
# Packet
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """One rendered block of the assembled packet.

    ``cold_start`` is stable (it changes slowly and benefits from prompt
    caching); the other three are dynamic.
    """

    kind: BlockKind
    text: str
    tokens: int
    stable: bool


@dataclass
class ContextPacket:
    """The Recall Engine's return value (PRD 6.1).

    ``abstain`` is always ``False`` in M2; M3 adds abstention.
    """

    stable_blocks: list[Block]
    dynamic_blocks: list[Block]
    abstain: bool
    trace: RecallTrace

    def block_text(self, kind: BlockKind) -> str | None:
        """Return the text of the block of ``kind``, or ``None`` if there is no
        such block or its text is empty."""
        for block in self.stable_blocks + self.dynamic_blocks:
            if block.kind == kind:
                if block.text:
                    return block.text
                return None
        return None

    def all_text(self) -> str:
        """Join the non-empty block texts in ``BLOCK_ORDER`` with ``"\\n"``."""
        texts: list[str] = []
        blocks_by_kind = {b.kind: b for b in self.stable_blocks + self.dynamic_blocks}
        for kind in BLOCK_ORDER:
            block = blocks_by_kind.get(kind)
            if block is not None and block.text:
                texts.append(block.text)
        return "\n".join(texts)
