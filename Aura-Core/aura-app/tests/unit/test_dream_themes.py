"""Pure tests for dreaming themes (W4-10): replay ordering, label propagation."""

from datetime import datetime, timedelta, timezone

from aura.engines.dreaming.themes import (
    communities,
    label_propagation,
    select_replay,
    trim_words,
)

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _fact(name, salience, days_ago):
    return {"id": name, "salience": salience, "recorded_at": _NOW - timedelta(days=days_ago)}


def test_replay_ranks_by_salience_and_recency():
    facts = [
        _fact("fact:old_strong", 1.0, 60),   # 1 * e^-4.3 = 0.014
        _fact("fact:new_weak", 0.2, 1),      # 0.2 * e^-0.07 = 0.186
        _fact("fact:mid", 0.5, 14),          # 0.5 * e^-1 = 0.184
    ]
    chosen = select_replay(facts, _NOW, 2, 14, _NOW)
    assert chosen == ["fact:mid", "fact:new_weak"]


def test_replay_adds_facts_recorded_since_last_cycle():
    facts = [_fact("fact:a", 1.0, 1), _fact("fact:b", 0.0, 0.5), _fact("fact:c", 0.0, 30)]
    since = _NOW - timedelta(days=1)
    assert select_replay(facts, _NOW, 1, 14, since) == ["fact:a", "fact:b"]
    # After a restart (no last cycle) only the top batch: one cycle stays bounded.
    assert select_replay(facts, _NOW, 1, 14, None) == ["fact:a"]


def test_replay_caps_the_facts_recorded_since_last_cycle():
    facts = [_fact("fact:a", 1.0, 1)] + [
        _fact(f"fact:n{i}", 0.0, 0.1 * (i + 1)) for i in range(5)
    ]
    since = _NOW - timedelta(days=1)
    assert select_replay(facts, _NOW, 2, 14, since) == ["fact:a", "fact:n0", "fact:n1"]


def _cluster(prefix, n):
    ids = [f"{prefix}{i}" for i in range(n)]
    return [(a, b, 1.0) for i, a in enumerate(ids) for b in ids[i + 1:]]


def test_two_clusters_with_a_weak_link_are_two_communities():
    edges = _cluster("fact:a", 5) + _cluster("fact:b", 5) + [("fact:a0", "fact:b0", 0.1)]
    labels = label_propagation(edges)
    found = communities(labels, lambda n: n.startswith("fact:"), 4)
    assert found == [
        [f"fact:a{i}" for i in range(5)],
        [f"fact:b{i}" for i in range(5)],
    ]
    assert label_propagation(list(reversed(edges))) == labels


def test_small_communities_are_dropped_and_entities_do_not_count():
    edges = _cluster("fact:a", 3) + [("fact:a0", "entity:x", 1.0)]
    labels = label_propagation(edges)
    assert communities(labels, lambda n: n.startswith("fact:"), 4) == []


def test_trim_words():
    assert trim_words("  one two\nthree four ", 3) == "one two three"
