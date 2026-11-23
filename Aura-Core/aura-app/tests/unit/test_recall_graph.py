"""Unit tests for the graph channel's Personalised PageRank (card W4-03)."""

import pytest

from aura.config import settings
from aura.engines.recall.channels import _load_graph
from aura.engines.recall.graph import personalised_pagerank


def _ppr(edges, seeds, damping=0.5):
    return personalised_pagerank(edges, seeds, 0.15, 20, damping)


def test_strong_edges_outrank_weak_edges():
    edges = [
        ("seed", "s1", 1.0),
        ("s1", "strong", 1.0),
        ("seed", "w1", 0.2),
        ("w1", "weak", 0.2),
    ]
    scores = _ppr(edges, {"seed": 1.0})
    assert scores["strong"] > scores["weak"]


def test_hub_is_damped():
    edges = [("seed", "hub", 1.0)] + [("hub", f"leaf{i}", 1.0) for i in range(9)]
    damped = _ppr(edges, {"seed": 1.0}, damping=0.5)
    undamped = _ppr(edges, {"seed": 1.0}, damping=0.0)
    assert damped["leaf0"] < undamped["leaf0"]


class _FakeDB:
    def __init__(self):
        self.queries = []

    async def query(self, sql, params=None):
        self.queries.append(sql)
        return []


@pytest.mark.asyncio
async def test_loader_never_reads_supersedes(monkeypatch):
    db = _FakeDB()
    await _load_graph(db, ["fact:a"], "app")
    assert len(db.queries) == len(settings.recall_graph_weights)
    assert not any("supersedes" in sql for sql in db.queries)
