"""W3-04: Reciprocal Rank Fusion.

Tests for ``aura.engines.recall.fusion.rrf``: the fused score, the
deterministic ordering, and the empty-input case.
"""

import pytest

from aura.config import settings
from aura.engines.recall.channels import ChannelHit
from aura.engines.recall.fusion import FusedHit, rrf


def _hits(*rows: tuple[str, int, float]) -> list[ChannelHit]:
    return [
        ChannelHit(memory_id=memory_id, rank=rank, score=score)
        for memory_id, rank, score in rows
    ]


def test_id_found_by_two_channels_outranks_ids_found_by_one():
    channels = {
        "dense": _hits(("both", 0, 0.9), ("dense_only", 1, 0.8)),
        "lexical": _hits(("both", 0, 5.0), ("lexical_only", 1, 4.0)),
    }

    fused = rrf(channels, k=60)

    assert [hit.memory_id for hit in fused] == ["both", "dense_only", "lexical_only"]
    assert fused[0].score > fused[1].score
    assert fused[0].score == pytest.approx(2.0 / 61.0)
    assert fused[1].score == pytest.approx(1.0 / 62.0)
    assert fused[2].score == pytest.approx(1.0 / 62.0)


def test_exact_score_of_a_hand_computed_example():
    channels = {
        "dense": _hits(("a", 0, 0.9), ("b", 1, 0.8)),
        "lexical": _hits(("b", 0, 5.0), ("c", 2, 3.0)),
    }

    fused = rrf(channels, k=60)

    assert [hit.memory_id for hit in fused] == ["b", "a", "c"]
    assert fused[0].score == pytest.approx(1.0 / 62.0 + 1.0 / 61.0)
    assert fused[1].score == pytest.approx(1.0 / 61.0)
    assert fused[2].score == pytest.approx(1.0 / 63.0)

    by_id = {hit.memory_id: hit for hit in fused}
    assert by_id["b"].channel_ranks == {"dense": 1, "lexical": 0}
    assert by_id["b"].channel_scores == {"dense": 0.8, "lexical": 5.0}
    assert by_id["a"].channel_ranks == {"dense": 0}
    assert by_id["a"].channel_scores == {"dense": 0.9}
    assert isinstance(by_id["b"], FusedHit)


def test_ties_break_by_best_rank_then_memory_id():
    # k=0: p scores 1/2 + 1/6 and q scores 1/3 + 1/3, both exactly 2/3.
    # p's best rank is 1, q's is 2, so p comes first.
    channels = {
        "alpha": _hits(("p", 1, 1.0), ("q", 2, 1.0)),
        "beta": _hits(("p", 5, 1.0), ("q", 2, 1.0)),
    }

    fused = rrf(channels, k=0)

    assert [hit.memory_id for hit in fused] == ["p", "q"]
    assert fused[0].score == pytest.approx(2.0 / 3.0)
    assert fused[1].score == pytest.approx(2.0 / 3.0)


def test_equal_scores_and_ranks_break_by_memory_id():
    channels = {
        "dense": _hits(("zeta", 0, 0.9)),
        "lexical": _hits(("alpha", 0, 5.0)),
    }

    fused = rrf(channels, k=60)

    assert [hit.memory_id for hit in fused] == ["alpha", "zeta"]


def test_order_is_deterministic_regardless_of_channel_order():
    channels = {
        "dense": _hits(("b", 0, 0.9), ("a", 1, 0.8)),
        "lexical": _hits(("a", 0, 5.0), ("c", 1, 4.0)),
    }

    forward = rrf(channels, k=60)
    backward = rrf(dict(reversed(list(channels.items()))), k=60)

    assert [hit.memory_id for hit in forward] == [hit.memory_id for hit in backward]
    assert [hit.score for hit in forward] == [hit.score for hit in backward]


def test_empty_input_gives_empty_list():
    assert rrf({}) == []
    assert rrf({"dense": [], "lexical": []}) == []


def test_none_k_uses_config():
    fused = rrf({"dense": _hits(("only", 0, 0.5))})

    assert fused[0].score == pytest.approx(1.0 / (settings.recall_rrf_k + 1.0))