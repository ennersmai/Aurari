"""Recall Engine — pure assembly step.

This module contains the budgeted-assembly step from PRD 6.3 step 6 (without
abstention) and the token estimate used by it and by the trace. It is pure: it
calls no store, no database and no model. The shares and the budget come from
callers (the engine passes the config values in), so the shares are never
inlined here (card W2-14 "Do not put the shares inline in ``assembly.py``").
"""

import math
import re
from typing import Any, Callable

from aura.config import settings

from .models import BLOCK_ORDER, Block, BlockKind, Candidate, TraceItem


def estimate_tokens(text: str) -> int:
    """Estimate the token count of ``text``.

    ``math.ceil(len(text) / settings.recall_chars_per_token)``, and ``0`` for
    an empty string.
    """
    if not text:
        return 0
    return math.ceil(len(text) / settings.recall_chars_per_token)


_WS_RE = re.compile(r"\s+")


def normalise_text(text: str) -> str:
    """Casefold, strip and collapse runs of whitespace to one space.

    Used to build dedup keys.
    """
    if not text:
        return ""
    return _WS_RE.sub(" ", text.casefold().strip())


def assemble(
    candidates: list[Candidate],
    renderers: dict[BlockKind, Callable[[list[Any]], str]],
    budget_tokens: int,
    shares: dict[BlockKind, float],
    dedup: bool,
    budget: bool,
) -> tuple[list[Block], list[TraceItem], int, int]:
    """Assemble candidates into budgeted blocks.

    Returns ``(blocks, trace_items, tokens_before, tokens_after)``.

    1. Group the candidates by block, in ``BLOCK_ORDER``. Within a block, sort
       by ``rank`` ascending.
    2. Deduplication (only if ``dedup``): walk the blocks in ``BLOCK_ORDER``
       and the candidates in rank order. Keep a map from dedup key to
       ``"<block>:<key>"``. If any of a candidate's ``dedup_keys`` is already
       in the map, its fate is ``duplicate``, and ``duplicate_of`` is the first
       holder. Otherwise, register all of its keys. The first occurrence in
       block order wins.
    3. Budget (only if ``budget``): ``carry = 0``. For each block in
       ``BLOCK_ORDER``: ``allowance = int(budget_tokens * shares[block]) +
       carry``; ``kept`` = the surviving candidates; while ``kept`` is
       non-empty and ``estimate_tokens(renderer(payloads))`` is more than
       ``allowance``, pop the last candidate and mark it ``over_budget``;
       ``carry = max(0, allowance - estimate_tokens(text))``.
    4. Render each block from its kept payloads. A block with no renderer is
       skipped. Keep a block only if its text is non-empty.
    5. Mark the remaining candidates ``kept``. ``TraceItem.tokens`` is
       ``estimate_tokens(renderer([payload]))``.
    6. ``tokens_before`` is the token sum of the blocks rendered from all
       candidates, with no dedup and no budget. ``tokens_after`` is the token
       sum of the returned blocks.
    """
    # Step 1: group by block in BLOCK_ORDER, sorted by rank ascending.
    grouped: dict[BlockKind, list[Candidate]] = {kind: [] for kind in BLOCK_ORDER}
    for cand in candidates:
        grouped[cand.block].append(cand)
    for kind in BLOCK_ORDER:
        grouped[kind].sort(key=lambda c: c.rank)

    # Step 2: deduplication (only if ``dedup``).
    # fate[block][key] and duplicate_of[block][key], for candidates in blocks
    # that have a renderer. We only trace candidates whose block has a
    # renderer (a block with no renderer is skipped — step 4).
    dedup_map: dict[str, str] = {}
    # Per-block surviving candidates (after dedup) and per-block dropped-by-
    # dedup candidates, for blocks that have a renderer.
    surviving: dict[BlockKind, list[Candidate]] = {kind: [] for kind in BLOCK_ORDER}
    duplicates: list[Candidate] = []
    duplicate_of: dict[str, str | None] = {}

    for kind in BLOCK_ORDER:
        renderer = renderers.get(kind)
        if renderer is None:
            # No renderer → block is skipped; its candidates are not traced.
            continue
        for cand in grouped[kind]:
            holder: str | None = None
            for key in cand.dedup_keys:
                existing = dedup_map.get(key)
                if existing is not None:
                    holder = existing
                    break
            if dedup and holder is not None:
                duplicates.append(cand)
                duplicate_of[cand.key] = holder
            else:
                if dedup:
                    for key in cand.dedup_keys:
                        dedup_map[key] = f"{cand.block}:{cand.key}"
                surviving[kind].append(cand)
                duplicate_of[cand.key] = None

    # Step 3: budget (only if ``budget``).
    over_budget: list[Candidate] = []
    if budget:
        carry = 0
        for kind in BLOCK_ORDER:
            renderer = renderers.get(kind)
            if renderer is None:
                continue
            kept = list(surviving[kind])
            allowance = int(budget_tokens * shares[kind]) + carry
            while kept and estimate_tokens(renderer([c.payload for c in kept])) > allowance:
                dropped = kept.pop()
                over_budget.append(dropped)
            surviving[kind] = kept
            text = renderer([c.payload for c in kept])
            carry = max(0, allowance - estimate_tokens(text))

    # Step 4: render each block from its kept payloads. A block with no
    # renderer is skipped. Keep a block only if its text is non-empty.
    blocks: list[Block] = []
    rendered_text: dict[BlockKind, str] = {}
    for kind in BLOCK_ORDER:
        renderer = renderers.get(kind)
        if renderer is None:
            continue
        text = renderer([c.payload for c in surviving[kind]])
        rendered_text[kind] = text
        if text:
            blocks.append(
                Block(
                    kind=kind,
                    text=text,
                    tokens=estimate_tokens(text),
                    stable=(kind == "cold_start"),
                )
            )

    # Step 5: mark the remaining candidates ``kept``. Build trace items for
    # every candidate in a rendered block (kept, duplicate or over_budget).
    trace_items: list[TraceItem] = []

    # Index the kept candidates by (block, key) for ordering. We emit trace
    # items grouped by block in BLOCK_ORDER; within a block, in rank order,
    # with kept first then duplicate/over_budget in the order they were
    # encountered (which is rank order, since dedup/budget walk rank order).
    def _tokens_for(cand: Candidate) -> int:
        renderer = renderers.get(cand.block)
        if renderer is None:
            return 0
        return estimate_tokens(renderer([cand.payload]))

    kept_keys: set[tuple[BlockKind, str]] = {
        (c.block, c.key) for c in (
            item for kind in BLOCK_ORDER for item in surviving[kind]
        )
    }
    dup_keys: set[tuple[BlockKind, str]] = {
        (c.block, c.key) for c in duplicates
    }
    ob_keys: set[tuple[BlockKind, str]] = {
        (c.block, c.key) for c in over_budget
    }

    for kind in BLOCK_ORDER:
        if renderers.get(kind) is None:
            continue
        for cand in grouped[kind]:
            ident = (cand.block, cand.key)
            if ident in kept_keys:
                fate = "kept"
                dup_of = None
            elif ident in dup_keys:
                fate = "duplicate"
                dup_of = duplicate_of.get(cand.key)
            elif ident in ob_keys:
                fate = "over_budget"
                dup_of = None
            else:
                # Should not happen: every candidate in a rendered block is
                # either kept, duplicate or over_budget.
                continue
            trace_items.append(
                TraceItem(
                    block=cand.block,
                    key=cand.key,
                    source=cand.source,
                    rank=cand.rank,
                    tokens=_tokens_for(cand),
                    fate=fate,
                    duplicate_of=dup_of,
                    channel_ranks=cand.channel_ranks,
                    fused_score=cand.fused_score,
                )
            )

    # Step 6: tokens_before (no dedup, no budget) and tokens_after.
    tokens_before = 0
    for kind in BLOCK_ORDER:
        renderer = renderers.get(kind)
        if renderer is None:
            continue
        text = renderer([c.payload for c in grouped[kind]])
        tokens_before += estimate_tokens(text)
    tokens_after = sum(b.tokens for b in blocks)

    return blocks, trace_items, tokens_before, tokens_after
