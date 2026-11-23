"""P2-09: task graph scheduler with a fake LLM, fake executor and in-memory store."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.executor import task_graph as task_graph_module
from aura.executor import task_scheduler as ts
from aura.executor.task_graph import TaskGraphStore
from aura.llm.tool_calls import ModelTurn
from aura.models.task_graph import BlackboardEntry, GraphStatus, NodeStatus, TaskGraph, TaskNode
from aura.tools import plan_task

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class MemStore(TaskGraphStore):
    """In-memory store with the TaskGraphStore interface."""

    def __init__(self) -> None:
        self.graphs: dict[str, TaskGraph] = {}
        self.nodes: dict[str, dict[str, TaskNode]] = {}
        self.board: list[BlackboardEntry] = []
        self.node_log: list[tuple[str, str]] = []

    async def create_graph(self, goal, nodes, budget_usd, budget_minutes, created_by_turn=None):
        gid = f"task_graph:g{len(self.graphs) + 1}"
        self.graphs[gid] = TaskGraph(id=gid, goal=goal, budget_usd=budget_usd, budget_minutes=budget_minutes)
        self.nodes[gid] = {n.id: n.model_copy(update={"graph": gid}) for n in nodes}
        return self.graphs[gid]

    async def get_graph(self, graph_id):
        return self.graphs.get(graph_id)

    async def list_nodes(self, graph_id):
        return [n.model_copy() for n in self.nodes[graph_id].values()]

    async def update_node_status(self, graph_id, node_id, status, report=None, artifacts=None, transcript=None):
        n = self.nodes[graph_id][node_id]
        n.status = NodeStatus(status).value
        self.node_log.append((node_id, n.status))
        if report is not None:
            n.report = report
        if transcript is not None:
            n.transcript = transcript

    async def update_graph(self, graph_id, status=None, spent_usd=None):
        g = self.graphs[graph_id]
        if status is not None:
            g.status = GraphStatus(status).value
        if spent_usd is not None:
            g.spent_usd = spent_usd

    async def list_graphs(self, status):
        return [g for g in self.graphs.values() if g.status == GraphStatus(status).value]

    async def write_blackboard(self, graph_id, kind, content, node_id=None, refs=None):
        e = BlackboardEntry(graph=graph_id, node=node_id, kind=kind, content=content, refs=list(refs or []))
        self.board.append(e)
        return e

    async def list_blackboard(self, graph_id):
        return list(self.board)


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def extract_tool_calls(self, text):
        try:
            data = json.loads(text.strip())
        except ValueError:
            return []
        return [data] if isinstance(data, dict) and "tool" in data else []

    async def execute_and_feedback(self, calls, **kwargs):
        self.calls.extend(calls)
        assert kwargs["requester_role"] == "owner" and kwargs["venue"] == "app"
        return "\n".join(
            f"OK Tool {c['tool']} succeeded\nResult:\nURL: https://ex.test/{c['arguments']['query']}"
            for c in calls
        )


class FakeLLM:
    """Research rounds: call web_search first, then report. Behaviour per brief via hooks."""

    def __init__(self) -> None:
        self.log: list[str] = []
        self.models: list[str] = []
        self.active = 0
        self.max_active = 0
        self.both_running = asyncio.Event()
        self.report_text = "short report"
        self.fail_briefs: set[str] = set()
        self.hang_briefs: set[str] = set()
        self.on_round = None  # async callable(brief)
        self.inputs: list[str] = []

    @staticmethod
    def _brief(prompt: str) -> str:
        return prompt.split("Task: ", 1)[1].split("\n", 1)[0]

    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kw):
        self.models.append(model)
        prompt = messages[-1]["content"]
        self.inputs.append(prompt)
        system = messages[0]["content"]
        brief = self._brief(prompt)
        if "analyst" in system:  # think node
            self.log.append(f"think:{brief}")
            if brief in self.fail_briefs:
                raise RuntimeError("think boom")
            return self.report_text
        # research node
        if "[Round 1]" not in prompt:
            self.log.append(f"research:{brief}")
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            if self.active >= 2:
                self.both_running.set()
            try:
                if brief in self.hang_briefs:
                    await asyncio.sleep(3600)
                if self.on_round is not None:
                    await self.on_round(brief)
                if brief in self.fail_briefs:
                    raise RuntimeError("research boom")
                if brief.startswith("par"):
                    await asyncio.wait_for(self.both_running.wait(), 5)
            finally:
                self.active -= 1
            return json.dumps({"tool": "web_search", "arguments": {"query": brief.replace(" ", "_")}})
        return self.report_text


def N(id, kind="research", deps=(), share=0.25):
    return TaskNode(id=id, kind=kind, brief=("par " if id in ("r1", "r2") else "") + f"do {id}",
                    success_criteria=f"{id} ok", depends_on=list(deps), budget_share=share)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "tool_loop_budgets_enabled", True)
    monkeypatch.setattr(settings, "l3_native_tools", False)
    monkeypatch.setattr(ts, "_POLL_SECONDS", 0.05)
    store, llm, execu = MemStore(), FakeLLM(), FakeExecutor()
    sched = ts.TaskGraphScheduler(store=store, llm_client=llm, executor=execu)
    set_clock(FakeClock(_START))
    yield sched, store, llm, execu
    set_clock(Clock())


async def _run(sched, store, nodes, budget_usd=10.0, budget_minutes=60):
    graph = await store.create_graph("goal", nodes, budget_usd, budget_minutes)
    sched.start(graph.id)
    await asyncio.wait_for(sched.wait(graph.id), 10)
    return graph.id


def _status(store, gid):
    return {i: n.status for i, n in store.nodes[gid].items()}


def FOUR():
    return [N("r1"), N("r2"), N("t1", "think", ["r1", "r2"]), N("t2", "think", ["t1"])]


async def test_four_node_graph_order_and_parallelism(env):
    sched, store, llm, _ = env
    gid = await _run(sched, store, FOUR())
    assert store.graphs[gid].status == "done"
    assert _status(store, gid) == {"r1": "done", "r2": "done", "t1": "done", "t2": "done"}
    # Both research nodes were inside their first round at the same time (the barrier needs both).
    assert llm.both_running.is_set() and llm.max_active == 2
    order = [e for e in llm.log if e.startswith("think")]
    assert order == ["think:do t1", "think:do t2"]
    log = store.node_log
    assert log.index(("t1", "running")) > max(log.index(("r1", "done")), log.index(("r2", "done")))
    assert log.index(("t2", "running")) > log.index(("t1", "done"))
    # Dependency reports reach the dependant's input, not the transcripts.
    t1_input = [i for i in llm.inputs if "Task: do t1" in i][0]
    assert "[r1]" in t1_input and "[r2]" in t1_input and "[Tool results]" not in t1_input


async def test_models_used(env, monkeypatch):
    sched, store, llm, _ = env
    monkeypatch.setattr(settings, "task_research_model", "")
    llm.both_running.set()
    await _run(sched, store, [N("r1"), N("t1", "think", ["r1"])])
    assert llm.models[0] == settings.active_l5_model and llm.models[-1] == settings.active_l2_model
    llm.models.clear()
    llm.both_running.set()
    monkeypatch.setattr(settings, "task_research_model", "my/research-model")
    await _run(sched, store, [N("r2")])
    assert set(llm.models) == {"my/research-model"}


async def test_parallel_limit(env, monkeypatch):
    sched, store, llm, _ = env
    monkeypatch.setattr(settings, "task_graph_parallel", 2)

    async def pause(brief):
        await asyncio.sleep(0.05)

    llm.on_round = pause
    nodes = [TaskNode(id=f"x{i}", kind="research", brief=f"x{i}", success_criteria="ok", budget_share=0.2)
             for i in range(5)]
    await _run(sched, store, nodes)
    assert llm.max_active == 2  # reached the limit, never above it


async def test_failing_node_skips_dependants_and_partial(env):
    sched, store, llm, _ = env
    llm.fail_briefs = {"do bad"}
    nodes = [N("bad"), N("after", "think", ["bad"]), N("after2", "think", ["after"]),
             N("good"), N("good2", "think", ["good"])]
    llm.both_running.set()
    gid = await _run(sched, store, nodes)
    st = _status(store, gid)
    assert st == {"bad": "failed", "after": "skipped", "after2": "skipped", "good": "done", "good2": "done"}
    assert store.graphs[gid].status == "partial"
    assert "research boom" in store.nodes[gid]["bad"].report
    assert "think:do after" not in llm.log


async def test_all_failed_is_failed(env):
    sched, store, llm, _ = env
    llm.fail_briefs = {"do a"}
    gid = await _run(sched, store, [N("a"), N("b", "think", ["a"])])
    assert store.graphs[gid].status == "failed"


async def test_code_node_placeholder_fails_and_skips_dependants(env):
    sched, store, llm, _ = env
    llm.both_running.set()
    nodes = [N("r1"), N("c1", "code", ["r1"]), N("t1", "think", ["c1"])]
    gid = await _run(sched, store, nodes)
    assert _status(store, gid) == {"r1": "done", "c1": "failed", "t1": "skipped"}
    assert store.nodes[gid]["c1"].report == f"failed: {ts.CODE_NODE_REASON}"
    assert store.graphs[gid].status == "partial"


async def test_code_node_limit_is_one(env, monkeypatch):
    sched, store, _, _ = env
    active = {"now": 0, "max": 0}

    async def fake_code(graph, node, deps):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.05)
        active["now"] -= 1
        return ts.NodeOutcome(ok=True, report="built")

    monkeypatch.setattr(sched, "_run_code_node", fake_code)
    # Two code nodes cannot come from plan_task (validation), so store them directly.
    nodes = [TaskNode(id=f"c{i}", kind="code", brief="b", success_criteria="s", budget_share=0.3)
             for i in range(2)]
    gid = await _run(sched, store, nodes)
    assert active["max"] == 1 and store.graphs[gid].status == "done"


async def test_cost_budget_stop_marks_running_interrupted(env, monkeypatch):
    sched, store, llm, _ = env
    monkeypatch.setattr(settings, "l3_native_tools", True)

    async def with_tools(messages, model, tools, **kw):
        if "Task: par do r1" in messages[-1]["content"]:
            return ModelTurn(text="costly report", tool_calls=[], cost=2.0)
        await asyncio.sleep(3600)

    llm.complete_with_tools = with_tools
    nodes = [N("r1"), N("r2"), N("t1", "think", ["r1", "r2"])]
    gid = await _run(sched, store, nodes, budget_usd=1.0)
    assert store.graphs[gid].status == "over_budget"
    assert _status(store, gid) == {"r1": "done", "r2": "interrupted", "t1": "pending"}
    assert store.graphs[gid].spent_usd == pytest.approx(2.0)


async def test_time_budget_stop(env):
    sched, store, llm, _ = env

    async def slow(brief):
        get_clock().advance(61 * 60)
        await asyncio.sleep(3600)

    llm.on_round = slow
    gid = await _run(sched, store, [N("a"), N("b", "think", ["a"])], budget_minutes=60)
    assert store.graphs[gid].status == "over_budget"
    assert _status(store, gid) == {"a": "interrupted", "b": "pending"}


async def test_restart_then_resume_completes(env):
    sched, store, llm, _ = env
    llm.hang_briefs = {"do a"}
    graph = await store.create_graph("goal", [N("a"), N("b", "think", ["a"])], 10.0, 60)
    sched.start(graph.id)
    for _ in range(200):
        if store.nodes[graph.id]["a"].status == "running":
            break
        await asyncio.sleep(0.01)
    assert store.graphs[graph.id].status == "running"
    # "Crash": the graph is left in running with a running node. Recovery marks both interrupted.
    await sched.shutdown()
    store.graphs[graph.id].status = "running"
    store.nodes[graph.id]["a"].status = "running"
    recovered = await store.recover_interrupted_graphs()
    assert [g.id for g in recovered] == [graph.id]
    assert store.graphs[graph.id].status == "interrupted"
    assert _status(store, graph.id) == {"a": "interrupted", "b": "pending"}

    assert await sched.resume_graph(graph.id, "trusted") is False
    assert await sched.resume_graph(graph.id, "guest") is False
    assert store.graphs[graph.id].status == "interrupted"

    llm.hang_briefs = set()
    assert await sched.resume_graph(graph.id, "owner") is True
    await asyncio.wait_for(sched.wait(graph.id), 10)
    assert store.graphs[graph.id].status == "done"
    assert _status(store, graph.id) == {"a": "done", "b": "done"}


async def test_resume_refuses_graph_that_is_not_interrupted(env):
    sched, store, _, _ = env
    gid = await _run(sched, store, [N("a")])
    assert await sched.resume_graph(gid, "owner") is False


async def test_report_cap_and_transcript(env, monkeypatch):
    sched, store, llm, _ = env
    monkeypatch.setattr(settings, "task_node_report_max_tokens", 10)
    llm.report_text = "word " * 200
    llm.both_running.set()
    gid = await _run(sched, store, [N("r1"), N("t1", "think", ["r1"])])
    r1, t1 = store.nodes[gid]["r1"], store.nodes[gid]["t1"]
    assert r1.report.endswith(ts.TRUNCATION_MARKER)
    assert ts.estimate_tokens(r1.report) <= 10 + ts.estimate_tokens(ts.TRUNCATION_MARKER)
    # The full transcript is stored on the node; the capped report is not the transcript.
    assert "word " * 100 in r1.transcript and "https://ex.test/par_do_r1" in r1.transcript
    assert len(r1.transcript) > len(r1.report) * 5
    assert t1.report.endswith(ts.TRUNCATION_MARKER) and "word " * 100 in t1.transcript
    # Blackboard: one entry per node, capped content, URLs as refs for research.
    by_node = {e.node: e for e in store.board}
    assert set(by_node) == {"r1", "t1"}
    assert by_node["r1"].kind == "research" and by_node["r1"].content == r1.report
    assert by_node["r1"].refs == ["https://ex.test/par_do_r1"]
    assert by_node["t1"].kind == "think" and by_node["t1"].refs == []
    # The dependant sees the capped report, never the transcript.
    t1_input = [i for i in llm.inputs if "Task: do t1" in i][0]
    assert "word " * 100 not in t1_input and ts.TRUNCATION_MARKER in t1_input


def test_cap_report_short_text_untouched():
    assert ts.cap_report("tiny", 800) == "tiny"


async def test_research_node_cannot_use_other_tools(env):
    _, _, _, execu = env
    wrapper = ts._ResearchExecutor(execu)
    out = await wrapper.execute_and_feedback(
        [{"tool": "terminal", "arguments": {"query": "x"}},
         {"tool": "web_search", "arguments": {"query": "x"}}],
        requester_role="owner", venue="app")
    assert [c["tool"] for c in execu.calls] == ["web_search"]
    assert "Tool terminal failed" in out and "not available to research nodes" in out


# --- plan_task integration ------------------------------------------------------

def _plan_env(monkeypatch, tmp_path, flag):
    from aura.tiers import reset_tier_cache

    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "o.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "task_graphs_enabled", flag)
    monkeypatch.setattr(settings, "model_stack_index", 2)
    monkeypatch.setattr(settings, "l3_native_tools", False)
    store = MemStore()
    monkeypatch.setattr(task_graph_module, "get_task_graph_store", lambda: store)
    llm = FakeLLM()
    sched = ts.TaskGraphScheduler(store=store, llm_client=llm, executor=FakeExecutor())
    monkeypatch.setattr(ts, "_scheduler", sched)
    return store, sched, llm


def _args():
    return {"goal": "g", "_requester_role": "owner", "_venue": "app",
            "nodes": [{"id": "r1", "kind": "research", "brief": "one", "success_criteria": "ok"}]}


async def test_plan_task_starts_scheduler_when_flag_on(monkeypatch, tmp_path):
    from aura.tiers import reset_tier_cache

    store, sched, _ = _plan_env(monkeypatch, tmp_path, True)
    result = await plan_task.run(_args())
    assert result["success"] is True
    gid = result["graph_id"]
    assert sched.is_running(gid)  # started, and plan_task did not wait for it
    await asyncio.wait_for(sched.wait(gid), 10)
    assert store.graphs[gid].status == "done"
    assert not sched._tasks
    reset_tier_cache()


async def test_plan_task_flag_off_starts_nothing(monkeypatch, tmp_path):
    from aura.tiers import reset_tier_cache

    store, sched, llm = _plan_env(monkeypatch, tmp_path, False)
    result = await plan_task.run(_args())
    assert result["success"] is False and not store.graphs
    assert not sched._tasks and llm.log == []
    reset_tier_cache()


async def test_recover_noop_with_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "task_graphs_enabled", False)
    assert await ts.recover_interrupted_graphs() == []


async def test_no_leaked_tasks(env):
    sched, store, _, _ = env
    before = set(asyncio.all_tasks())
    await _run(sched, store, FOUR())
    await asyncio.sleep(0)
    assert not sched._tasks
    assert {t for t in asyncio.all_tasks() if not t.done()} <= before
