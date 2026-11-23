"""P2-08: task graph persistence on the real schema (embedded SurrealDB)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from surrealdb import RecordID

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.executor.task_graph import TaskGraphStore
from aura.models.task_graph import GraphStatus, NodeStatus, TaskNode
from aura.tools import plan_task
from aura.tiers import reset_tier_cache
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _nodes() -> list[TaskNode]:
    return [
        TaskNode(id="r1", kind="research", brief="look", success_criteria="found", budget_share=0.25),
        TaskNode(id="t1", kind="think", brief="decide", success_criteria="chosen",
                 depends_on=["r1"], budget_share=0.25),
        TaskNode(id="c1", kind="code", brief="build", success_criteria="tests pass",
                 depends_on=["t1"], budget_share=0.5),
    ]


@pytest.fixture
async def db():
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    yield d
    set_clock(Clock())
    await d.close()


async def test_graph_nodes_blackboard_round_trip(db):
    store = TaskGraphStore(db)
    graph = await store.create_graph("ship it", _nodes(), 1.5, 60, created_by_turn=None)
    assert graph.id.startswith("task_graph:")
    assert graph.status == GraphStatus.PLANNED.value
    assert graph.budget_usd == 1.5 and graph.budget_minutes == 60 and graph.spent_usd == 0
    assert graph.created_by_turn is None and graph.created_at == _START

    got = await store.get_graph(graph.id)
    assert got is not None and got.goal == "ship it" and got.id == graph.id

    nodes = await store.list_nodes(graph.id)
    assert {n.id for n in nodes} == {"r1", "t1", "c1"}
    by_id = {n.id: n for n in nodes}
    assert by_id["t1"].depends_on == ["r1"] and by_id["c1"].kind == "code"
    assert by_id["c1"].budget_share == 0.5 and by_id["r1"].status == "pending"
    assert by_id["r1"].graph == graph.id and by_id["r1"].report is None

    await store.update_node_status(graph.id, "r1", NodeStatus.DONE, report="found 3", artifacts=["a.md"])
    r1 = {n.id: n for n in await store.list_nodes(graph.id)}["r1"]
    assert r1.status == "done" and r1.report == "found 3" and r1.artifacts == ["a.md"]

    entry = await store.write_blackboard(graph.id, "report", "found 3", node_id="r1", refs=["http://x"])
    await store.write_blackboard(graph.id, "note", "graph level")
    board = await store.list_blackboard(graph.id)
    assert [e.kind for e in board] == ["report", "note"]
    assert board[0].node == "task_node:" + graph.id.split(":")[1] + "_r1" == entry.node
    assert board[0].refs == ["http://x"] and board[1].node is None


async def test_record_links_are_real_links(db):
    store = TaskGraphStore(db)
    graph = await store.create_graph("g", _nodes(), 1.0, 30)
    await store.write_blackboard(graph.id, "report", "x", node_id="t1")
    rows = await db.query("SELECT graph, node FROM blackboard_entry")
    assert isinstance(rows[0]["graph"], RecordID) and isinstance(rows[0]["node"], RecordID)
    rows = await db.query("SELECT graph FROM task_node")
    assert all(isinstance(r["graph"], RecordID) for r in rows) and len(rows) == 3


async def test_graphs_do_not_mix(db):
    store = TaskGraphStore(db)
    a = await store.create_graph("a", _nodes()[:1], 1.0, 30)
    b = await store.create_graph("b", _nodes(), 1.0, 30)
    assert len(await store.list_nodes(a.id)) == 1 and len(await store.list_nodes(b.id)) == 3


async def test_schema_rejects_bad_status(db):
    store = TaskGraphStore(db)
    graph = await store.create_graph("g", _nodes(), 1.0, 30)
    with pytest.raises(Exception):
        await db.query("UPDATE $rid SET status = 'bogus'", {"rid": RecordID("task_graph", graph.id.split(":")[1])})


async def test_plan_task_end_to_end_on_real_schema(db, monkeypatch, tmp_path):
    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "o.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 2)
    store = TaskGraphStore(db)
    from aura.executor import task_graph as tg

    monkeypatch.setattr(tg, "get_task_graph_store", lambda: store)
    result = await plan_task.run({
        "goal": "g", "_requester_role": "owner",
        "nodes": [
            {"id": "a", "kind": "research", "brief": "b", "success_criteria": "c"},
            {"id": "b", "kind": "think", "brief": "b", "success_criteria": "c", "depends_on": ["a"]},
        ],
    })
    assert result["success"], result
    graph = await store.get_graph(result["graph_id"])
    assert graph.status == "planned" and graph.budget_usd == 2.0 and graph.budget_minutes == 120
    nodes = await store.list_nodes(result["graph_id"])
    assert [n.budget_share for n in nodes] == [0.5, 0.5]
    board = await store.list_blackboard(result["graph_id"])
    assert [e.kind for e in board] == ["plan"] and '"goal": "g"' in board[0].content
    reset_tier_cache()
