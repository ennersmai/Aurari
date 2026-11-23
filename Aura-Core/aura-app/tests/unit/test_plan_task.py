"""P2-08: plan_task validation, gating and the ablation. Offline: a fake store."""

import logging
from typing import Any

import pytest

from aura.config import settings
from aura.executor import task_graph as task_graph_module
from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import ToolRegistry, reset_tool_registry
from aura.models.task_graph import TaskNode
from aura.tiers import reset_tier_cache
from aura.tools import plan_task


class FakeStore:
    def __init__(self) -> None:
        self.graphs: list[dict[str, Any]] = []
        self.board: list[tuple] = []

    async def create_graph(self, goal, nodes, budget_usd, budget_minutes, created_by_turn=None):
        self.graphs.append(
            {"goal": goal, "nodes": nodes, "usd": budget_usd, "min": budget_minutes, "turn": created_by_turn}
        )

        class G:
            id = f"task_graph:t{len(self.graphs)}"

        return G()

    async def write_blackboard(self, graph_id, kind, content, node_id=None, refs=None):
        self.board.append((graph_id, kind, content))


@pytest.fixture(autouse=True)
def _on(monkeypatch, tmp_path):
    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 2)
    yield
    reset_tier_cache()
    reset_tool_registry()


@pytest.fixture
def store(monkeypatch):
    s = FakeStore()
    monkeypatch.setattr(task_graph_module, "get_task_graph_store", lambda: s)
    from aura.executor import task_scheduler

    started: list[str] = []
    monkeypatch.setattr(task_scheduler, "get_task_scheduler",
                        lambda: type("S", (), {"start": staticmethod(started.append)})())
    s.started = started
    return s


def N(id, kind="research", deps=(), **kw):
    return {"id": id, "kind": kind, "brief": f"do {id}", "success_criteria": f"{id} done",
            "depends_on": list(deps), **kw}


def args(nodes, **kw):
    return {"goal": "g", "nodes": nodes, "_requester_role": "owner", "_venue": "app", **kw}


async def call(a):
    return await plan_task.run(a)


async def test_valid_graph_returns_id_and_writes_plan_event(store):
    r = await call(args([N("a"), N("b", "think", ["a"]), N("c", "code", ["b"])]))
    assert r["success"] and r["graph_id"] == "task_graph:t1" and r["status"] == "PLANNED"
    g = store.graphs[0]
    assert [n.id for n in g["nodes"]] == ["a", "b", "c"]
    assert g["usd"] == 2.0 and g["min"] == 120 and g["turn"] is None
    assert sum(n.budget_share for n in g["nodes"]) == pytest.approx(1.0)
    assert store.board[0][1] == "plan" and '"nodes"' in store.board[0][2]


async def test_budget_share_rest_split_evenly(store):
    await call(args([N("a", budget_share=0.5), N("b"), N("c")]))
    shares = {n.id: n.budget_share for n in store.graphs[0]["nodes"]}
    assert shares == {"a": 0.5, "b": pytest.approx(0.25), "c": pytest.approx(0.25)}


async def _fails(a, store, *needles):
    r = await call(a)
    assert r["success"] is False and r["status"] == "ERROR"
    for needle in needles:
        assert needle in r["message"], r["message"]
    assert store.graphs == []
    return r


async def test_cycle(store):
    await _fails(args([N("a", deps=["b"]), N("b", deps=["a"])]), store, "cycle", "a, b", "Remove")


async def test_self_dependency(store):
    await _fails(args([N("a", deps=["a"])]), store, "depends on itself")


async def test_unknown_dependency(store):
    await _fails(args([N("a", deps=["zzz"])]), store, "unknown node 'zzz'", "Known ids: a")


async def test_too_many_nodes(store):
    await _fails(args([N(f"n{i}") for i in range(9)]), store, "Too many nodes", "9", "limit is 8")


async def test_empty_nodes(store):
    await _fails(args([]), store, "nodes is required", "1 to 8")


async def test_two_code_nodes(store):
    await _fails(args([N("a", "code"), N("b", "code")]), store, "Only one code node", "a, b", "Merge")


async def test_unknown_kind(store):
    await _fails(args([N("a", "magic")]), store, "unknown kind 'magic'", "research, think, code")


async def test_duplicate_id(store):
    await _fails(args([N("a"), N("a")]), store, "Duplicate node id 'a'", "unique")


async def test_missing_success_criteria(store):
    node = N("a")
    node["success_criteria"] = "  "
    await _fails(args([node]), store, "Node 'a' has no success_criteria")


async def test_budget_over_limit(store):
    await _fails(args([N("a")], budget_usd=5.0), store, "budget_usd 5.0", "limit of 2.0")
    await _fails(args([N("a")], budget_minutes=500), store, "budget_minutes 500", "limit of 120")


async def test_budget_shares_over_one(store):
    await _fails(args([N("a", budget_share=0.7), N("b", budget_share=0.6)]), store, "add up to 1.30", "at most 1.0")


async def test_bad_share_value(store):
    await _fails(args([N("a", budget_share=0)]), store, "budget_share must be a number above 0")


async def test_guest_refused(store):
    a = args([N("a")])
    a["_requester_role"] = "guest"
    await _fails(a, store, "only available to the owner")


async def test_forged_role_absent_refused(store):
    a = args([N("a")])
    del a["_requester_role"]
    await _fails(a, store, "owner")


@pytest.mark.parametrize("index", [0, 1])
async def test_wrong_tier(store, monkeypatch, index):
    monkeypatch.setattr(settings, "model_stack_index", index)
    await _fails(args([N("a")]), store, "Titan")


async def test_flags_off_refuse(store, monkeypatch):
    monkeypatch.setattr(settings, "task_graphs_enabled", False)
    await _fails(args([N("a")]), store, "turned off")
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    await _fails(args([N("a")]), store, "turned off")


class _EmptyDB:
    async def query(self, *a, **k):
        return []


async def _registry() -> ToolRegistry:
    reset_tool_registry()
    from aura.executor.tool_registry import get_tool_registry

    reg = get_tool_registry()
    await reg.refresh(_EmptyDB())
    return reg


@pytest.mark.parametrize(
    "graphs,tiers,index,offered",
    [
        (True, True, 2, True),
        (False, True, 2, False),
        (True, False, 2, False),
        (True, True, 1, False),
        (True, True, 0, False),
    ],
)
async def test_offered_only_under_the_three_flags(monkeypatch, graphs, tiers, index, offered):
    monkeypatch.setattr(settings, "task_graphs_enabled", graphs)
    monkeypatch.setattr(settings, "tier_profiles_enabled", tiers)
    monkeypatch.setattr(settings, "model_stack_index", index)
    monkeypatch.setattr(settings, "tool_selection_threshold", 100)
    reg = await _registry()
    assert ("plan_task" in [r.name for r in reg.all()]) is offered
    selected = await reg.select_tools("plan a job", requester_role="owner")
    assert ("plan_task" in [r.name for r in selected]) is offered


async def test_ablation_tool_list_is_as_before(monkeypatch):
    monkeypatch.setattr(settings, "task_graphs_enabled", False)
    reg = await _registry()
    off = [r.name for r in reg.all()]
    assert "plan_task" not in off and len(off) == 21
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    assert [r.name for r in reg.all()] == sorted(off + ["plan_task"])


async def test_executor_refuses_plan_task_for_guest_and_lean(monkeypatch):
    ex = ToolExecutor.__new__(ToolExecutor)
    ex.logger = logging.getLogger("t")
    r = await ex.execute_tool_call({"tool": "plan_task", "arguments": {}}, requester_role="guest")
    assert r["success"] is False and "not available to this user" in r["error"]
    monkeypatch.setattr(settings, "model_stack_index", 1)
    r = await ex.execute_tool_call({"tool": "plan_task", "arguments": {}}, requester_role="owner")
    assert r["success"] is False and "not available on this tier" in r["error"]


def test_node_model_requires_success_criteria():
    with pytest.raises(ValueError):
        TaskNode(id="a", kind="think", brief="b", success_criteria="")
    with pytest.raises(ValueError):
        TaskNode(id="a", kind="think", brief="b", success_criteria="x", budget_share=0)
    with pytest.raises(ValueError):
        TaskNode(id="a", kind="oops", brief="b", success_criteria="x")
