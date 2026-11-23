"""Unit tests for the fact rerank maths (card W4-04)."""

import pytest

from datetime import datetime, timedelta, timezone

from aura.engines.recall.rerank import RerankCandidate, rerank

NOW = datetime(2026, 6, 1, tzinfo=timezone.utc)


def _c(id: str, score: float = 1.0, **kw) -> RerankCandidate:
    fields = dict(
        provenance="observed",
        confidence=1.0,
        salience=0.0,
        recorded_at=NOW,
        valid_to=None,
        embedding=None,
        signature=None,
    )
    fields.update(kw)
    return RerankCandidate(id=id, score=score, **fields)


def _ids(result):
    return [c.id for c in result]


def _run(cands, **kw):
    kw.setdefault("mode", "chat")
    kw.setdefault("has_time_range", False)
    return rerank(cands, now=NOW, **kw)


def test_superseded_dropped_unless_time_range():
    cands = [_c("a"), _c("b", valid_to=NOW)]
    assert _ids(_run(cands)) == ["a"]
    assert set(_ids(_run(cands, has_time_range=True))) == {"a", "b"}


def test_imagined_dropped_unless_creative():
    cands = [_c("a"), _c("b", provenance="imagined")]
    assert _ids(_run(cands)) == ["a"]
    assert set(_ids(_run(cands, mode="creative"))) == {"a", "b"}


def test_provenance_changes_order():
    cands = [_c("h", 1.0, provenance="hearsay"), _c("o", 0.9, provenance="observed")]
    assert _ids(_run(cands)) == ["o", "h"]


def test_confidence_changes_order():
    cands = [_c("low", 1.0, confidence=0.2), _c("high", 0.9, confidence=1.0)]
    assert _ids(_run(cands)) == ["high", "low"]


def test_salience_changes_order():
    cands = [_c("plain", 0.95), _c("salient", 0.9, salience=1.0)]
    assert _ids(_run(cands)) == ["salient", "plain"]


def test_decay_changes_order():
    old = NOW - timedelta(days=730)
    cands = [_c("old", 1.0, recorded_at=old), _c("new", 0.9)]
    assert _ids(_run(cands)) == ["new", "old"]


def test_resonance_adds_when_aligned():
    cands = [_c("plain", 1.0), _c("aligned", 0.95, signature={"joy": 0.8})]
    deviation = {"joy": 0.5}
    assert _ids(_run(cands, deviation=deviation, baseline={})) == ["aligned", "plain"]
    assert _ids(_run(cands)) == ["plain", "aligned"]


def test_resonance_zero_when_negative_dominates():
    cands = [_c("plain", 1.0), _c("aligned", 0.95, signature={"sadness": 0.8})]
    deviation = {"sadness": 0.6, "joy": 0.1}
    assert _ids(_run(cands, deviation=deviation, baseline={})) == ["plain", "aligned"]
    # Not negative-dominated: the same alignment does help.
    deviation = {"sadness": 0.1, "joy": 0.6, "interest": 0.3}
    cands = [_c("plain", 1.0), _c("aligned", 0.95, signature={"joy": 0.8})]
    assert _ids(_run(cands, deviation=deviation, baseline={})) == ["aligned", "plain"]


def test_resonance_subtracts_baseline():
    cands = [_c("plain", 1.0), _c("rest", 0.95, signature={"joy": 0.3})]
    # The signature equals the baseline, so there is no deviation to align with.
    result = _run(cands, deviation={"joy": 0.5}, baseline={"joy": 0.3})
    assert _ids(result) == ["plain", "rest"]


def test_mmr_keeps_one_of_five_near_identical_in_top_three():
    dup = [1.0, 0.0, 0.0]
    cands = [
        _c(f"d{i}", 1.0 - i * 0.001, embedding=dup) for i in range(5)
    ] + [
        _c("x", 0.8, embedding=[0.0, 1.0, 0.0]),
        _c("y", 0.75, embedding=[0.0, 0.0, 1.0]),
    ]
    top3 = _ids(_run(cands))[:3]
    assert sum(i.startswith("d") for i in top3) == 1
    assert {"x", "y"} <= set(top3)


def test_unused_streak_penalty_applies_from_threshold():
    from aura.config import settings

    after, factor = settings.recall_unused_penalty_after, settings.recall_unused_penalty
    below = _run([_c("a", unused_streak=after - 1)])[0].score
    at = _run([_c("a", unused_streak=after)])[0].score
    assert at == pytest.approx(below * factor)
