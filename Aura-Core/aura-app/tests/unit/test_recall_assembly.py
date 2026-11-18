"""W2-14: Recall Engine — models, config and the pure assembly step.

Tests for ``aura.engines.recall.assembly.assemble`` and
``ContextPacket.block_text`` using string payloads and a ``"\\n".join``
renderer (card W2-14).
"""

import math

import pytest

from aura.config import settings
from aura.engines.recall.assembly import assemble, estimate_tokens
from aura.engines.recall.models import (
    Block,
    BLOCK_ORDER,
    Candidate,
    ContextPacket,
    RecallTrace,
    TraceItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _join_renderer(payloads):
    """The card's ``"\\n".join`` renderer over string payloads."""
    return "\n".join(payloads)


def _cand(block, key, dedup_keys, payload, rank, source="test"):
    return Candidate(
        block=block,
        key=key,
        dedup_keys=tuple(dedup_keys),
        payload=payload,
        rank=rank,
        source=source,
    )


def _shares(**overrides):
    base = {
        "insights": 0.15,
        "latent": 0.10,
        "cold_start": 0.30,
        "memories": 0.45,
    }
    base.update(overrides)
    return base


def _fates(trace_items):
    return {item.key: item.fate for item in trace_items}


def _dup_of(trace_items):
    return {item.key: item.duplicate_of for item in trace_items}


# ---------------------------------------------------------------------------
# (a) Two candidates in different blocks that share a dedup key: the later
#     block's candidate is duplicate, and duplicate_of names the earlier one.
# ---------------------------------------------------------------------------


def test_a_shared_dedup_key_makes_later_block_duplicate():
    c1 = _cand("insights", "i1", ("k1",), "insight text", rank=0, source="test.insights")
    c2 = _cand("memories", "m1", ("k1",), "memory text", rank=0, source="test.memories")
    renderers = {"insights": _join_renderer, "memories": _join_renderer}

    blocks, trace_items, _, _ = assemble(
        candidates=[c1, c2],
        renderers=renderers,
        budget_tokens=settings.recall_token_budget,
        shares=_shares(),
        dedup=True,
        budget=False,
    )

    assert _fates(trace_items) == {"i1": "kept", "m1": "duplicate"}
    assert _dup_of(trace_items)["m1"] == "insights:i1"
    # The duplicate is dropped from the packet.
    block_kinds = {b.kind for b in blocks}
    assert "insights" in block_kinds
    assert "memories" not in block_kinds


# ---------------------------------------------------------------------------
# (b) With dedup=False, both are kept.
# ---------------------------------------------------------------------------


def test_b_no_dedup_keeps_both():
    c1 = _cand("insights", "i1", ("k1",), "insight text", rank=0)
    c2 = _cand("memories", "m1", ("k1",), "memory text", rank=0)
    renderers = {"insights": _join_renderer, "memories": _join_renderer}

    blocks, trace_items, _, _ = assemble(
        candidates=[c1, c2],
        renderers=renderers,
        budget_tokens=settings.recall_token_budget,
        shares=_shares(),
        dedup=False,
        budget=False,
    )

    assert _fates(trace_items) == {"i1": "kept", "m1": "kept"}
    block_kinds = {b.kind for b in blocks}
    assert block_kinds == {"insights", "memories"}


# ---------------------------------------------------------------------------
# (c) A block over its allowance drops candidates from the end until it fits,
#     and the dropped ones are over_budget.
# ---------------------------------------------------------------------------


def test_c_budget_drops_from_end_until_it_fits():
    # Four memory candidates; the budget only fits the first two.
    cands = [
        _cand("memories", f"m{i}", (), f"line {i}", rank=i)
        for i in range(4)
    ]
    renderers = {"memories": _join_renderer}

    full_text = _join_renderer([c.payload for c in cands])
    full_tokens = estimate_tokens(full_text)
    two_text = _join_renderer([cands[0].payload, cands[1].payload])
    two_tokens = estimate_tokens(two_text)

    # Give the memories block the full budget (share 1.0) and set the budget
    # so the allowance equals two_tokens exactly. The loop drops lines 3 and
    # 2 (from the end) and stops, leaving lines 0 and 1.
    shares = _shares(memories=1.0)
    budget_tokens = two_tokens
    allowance = int(budget_tokens * shares["memories"])
    assert allowance == two_tokens  # sanity for the test setup
    assert full_tokens > allowance  # the full block is over budget

    blocks, trace_items, _, _ = assemble(
        candidates=cands,
        renderers=renderers,
        budget_tokens=budget_tokens,
        shares=shares,
        dedup=False,
        budget=True,
    )

    assert _fates(trace_items) == {
        "m0": "kept",
        "m1": "kept",
        "m2": "over_budget",
        "m3": "over_budget",
    }
    # The block fits within the allowance.
    mem_block = [b for b in blocks if b.kind == "memories"][0]
    assert mem_block.tokens <= allowance
    assert mem_block.text == two_text


# ---------------------------------------------------------------------------
# (d) The unused allowance of an earlier block carries into the next one.
#     Build a case where the second block fits only because of the carry.
# ---------------------------------------------------------------------------


def test_d_unused_allowance_carries_into_next_block():
    # insights uses far less than its allowance; memories needs the carry.
    c_insight = _cand("insights", "i1", (), "short", rank=0)
    c_memory = _cand("memories", "m1", (), "x" * 44, rank=0)
    renderers = {"insights": _join_renderer, "memories": _join_renderer}

    insight_tokens = estimate_tokens(_join_renderer([c_insight.payload]))
    memory_tokens = estimate_tokens(_join_renderer([c_memory.payload]))

    # memories allowance alone would not fit the memory:
    budget_tokens = 100
    shares = _shares(insights=0.50, memories=0.10)
    mem_allowance = int(budget_tokens * shares["memories"])
    assert mem_allowance < memory_tokens
    # But with the carry from the (mostly unused) insights allowance it fits:
    ins_allowance = int(budget_tokens * shares["insights"])
    expected_carry = max(0, ins_allowance - insight_tokens)
    assert mem_allowance + expected_carry >= memory_tokens

    blocks, trace_items, _, _ = assemble(
        candidates=[c_insight, c_memory],
        renderers=renderers,
        budget_tokens=budget_tokens,
        shares=shares,
        dedup=False,
        budget=True,
    )

    assert _fates(trace_items) == {"i1": "kept", "m1": "kept"}
    block_kinds = {b.kind for b in blocks}
    assert block_kinds == {"insights", "memories"}

    # Prove the carry is what made it fit: with no earlier block (so no
    # carry), the same memory is over budget. Use only the memories renderer
    # so the insights block is skipped entirely (no allowance, no carry).
    blocks2, trace_items2, _, _ = assemble(
        candidates=[c_memory],
        renderers={"memories": _join_renderer},
        budget_tokens=budget_tokens,
        shares=shares,
        dedup=False,
        budget=True,
    )
    assert _fates(trace_items2) == {"m1": "over_budget"}
    assert [b.kind for b in blocks2] == []


# ---------------------------------------------------------------------------
# (e) With budget=False, nothing is over_budget.
# ---------------------------------------------------------------------------


def test_e_no_budget_nothing_is_over_budget():
    cands = [
        _cand("memories", f"m{i}", (), f"line {i}", rank=i)
        for i in range(10)
    ]
    renderers = {"memories": _join_renderer}

    blocks, trace_items, _, _ = assemble(
        candidates=cands,
        renderers=renderers,
        budget_tokens=1,  # tiny; irrelevant because budget is off
        shares=_shares(),
        dedup=False,
        budget=False,
    )

    fates = set(_fates(trace_items).values())
    assert fates == {"kept"}
    assert "over_budget" not in fates
    # All ten candidates survive into the block.
    mem_block = [b for b in blocks if b.kind == "memories"][0]
    assert mem_block.text == _join_renderer([c.payload for c in cands])


# ---------------------------------------------------------------------------
# (f) tokens_before >= tokens_after, and both are exact for a hand-computed
#     case.
# ---------------------------------------------------------------------------


def test_f_tokens_before_and_after_exact_and_ordered():
    # One block ("memories") with three candidates. One dedup duplicate and
    # one over_budget, hand-computed.
    #
    #   m1: "aaa", rank 0, dedup_keys=("k",)
    #   m2: "bbb", rank 1, dedup_keys=("k",)   -> duplicate of m1
    #   m3: "ccc", rank 2, no dedup
    #
    # dedup=True keeps m1 and m3; budget then drops m3 from the end. With
    # recall_chars_per_token=4:
    #   "aaa"           -> ceil(3/4) = 1 token
    #   "aaa\nbbb\nccc" -> ceil(11/4) = 3 tokens   (tokens_before)
    #   "aaa"           -> 1 token                 (tokens_after)
    c_m1 = _cand("memories", "m1", ("k",), "aaa", rank=0)
    c_m2 = _cand("memories", "m2", ("k",), "bbb", rank=1)
    c_m3 = _cand("memories", "m3", (), "ccc", rank=2)
    renderers = {"memories": _join_renderer}

    all_text = _join_renderer([c_m1.payload, c_m2.payload, c_m3.payload])
    expected_before = estimate_tokens(all_text)
    expected_after = estimate_tokens(_join_renderer([c_m1.payload]))

    # memories gets the full budget (share 1.0) and the budget equals one
    # token, so the kept survivors (m1, m3 -> "aaa\nccc" = 2 tokens) are
    # reduced to "aaa" (1 token) by popping m3.
    shares = _shares(memories=1.0)
    budget_tokens = expected_after
    allowance = int(budget_tokens * shares["memories"])
    assert allowance == expected_after

    blocks, trace_items, tokens_before, tokens_after = assemble(
        candidates=[c_m1, c_m2, c_m3],
        renderers=renderers,
        budget_tokens=budget_tokens,
        shares=shares,
        dedup=True,
        budget=True,
    )

    assert tokens_before == expected_before == 3
    assert tokens_after == expected_after == 1
    assert tokens_before >= tokens_after

    assert _fates(trace_items) == {
        "m1": "kept",
        "m2": "duplicate",
        "m3": "over_budget",
    }
    assert _dup_of(trace_items)["m2"] == "memories:m1"
    block_kinds = {b.kind for b in blocks}
    assert block_kinds == {"memories"}
    mem_block = [b for b in blocks if b.kind == "memories"][0]
    assert mem_block.text == "aaa"


# ---------------------------------------------------------------------------
# (g) ContextPacket.block_text returns None for a missing kind and for empty
#     text.
# ---------------------------------------------------------------------------


def _trace():
    return RecallTrace(
        turn_id="t",
        user_id="u",
        query="q",
        created_at=__import__("datetime").datetime(2026, 1, 1, 12, 0, 0),
        budget_tokens=3000,
        tokens_before=0,
        tokens_after=0,
        items=[],
        channel_errors={},
    )


def test_g_block_text_none_for_missing_kind_and_empty_text():
    # A non-empty insights block and an empty-text cold_start block.
    insights_block = Block(kind="insights", text="hello", tokens=1, stable=False)
    cold_block = Block(kind="cold_start", text="", tokens=0, stable=True)
    packet = ContextPacket(
        stable_blocks=[cold_block],
        dynamic_blocks=[insights_block],
        abstain=False,
        trace=_trace(),
    )

    # Missing kind → None.
    assert packet.block_text("memories") is None
    # Empty text → None.
    assert packet.block_text("cold_start") is None
    # Present, non-empty → the text.
    assert packet.block_text("insights") == "hello"

    # all_text joins non-empty block texts in BLOCK_ORDER with "\n".
    assert packet.all_text() == "hello"
