"""P2-11: task graph reports into the chat. Fake LLM, in-memory store, in-memory message db."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

import pytest

from aura.api.routes import chat as chat_routes
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.executor import task_graph as task_graph_module
from aura.executor import task_reports
from aura.executor import task_scheduler as ts
from aura.executor.task_graph import TaskGraphStore
from aura.executor.task_reports import TaskReporter
from aura.executor.tool_executor import ToolExecutor
from aura.models.task_graph import BlackboardEntry, GraphStatus, NodeStatus, TaskGraph, TaskNode
from aura.tiers import reset_tier_cache
from aura.tools import plan_task

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
CONV = "conversation:1"


class MemStore(TaskGraphStore):
    def __init__(self) -> None:
        self.graphs: dict[str, TaskGraph] = {}
        self.nodes: dict[str, dict[str, TaskNode]] = {}
        self.board: list[BlackboardEntry] = []

    async def create_graph(self, goal, nodes, budget_usd, budget_minutes, created_by_turn=None,
                           conversation_id=None):
        gid = f"task_graph:g{len(self.graphs) + 1}"
        self.graphs[gid] = TaskGraph(id=gid, goal=goal, budget_usd=budget_usd, budget_minutes=budget_minutes,
                                     conversation_id=conversation_id, created_at=_START)
        self.nodes[gid] = {n.id: n.model_copy(update={"graph": gid}) for n in nodes}
        return self.graphs[gid]

    async def get_graph(self, graph_id):
        g = self.graphs.get(graph_id)
        return g.model_copy() if g else None

    async def list_nodes(self, graph_id):
        return [n.model_copy() for n in self.nodes[graph_id].values()]

    async def update_node_status(self, graph_id, node_id, status, report=None, artifacts=None, transcript=None):
        n = self.nodes[graph_id][node_id]
        n.status = NodeStatus(status).value
        if report is not None:
            n.report = report

    async def update_graph(self, graph_id, status=None, spent_usd=None):
        g = self.graphs[graph_id]
        if status is not None:
            g.status = GraphStatus(status).value
        if spent_usd is not None:
            g.spent_usd = spent_usd

    async def claim_final_report(self, graph_id):
        g = self.graphs[graph_id]
        if g.final_reported_at is not None:
            return False
        g.final_reported_at = datetime.now(timezone.utc)
        return True

    async def write_blackboard(self, graph_id, kind, content, node_id=None, refs=None):
        e = BlackboardEntry(graph=graph_id, node=node_id, kind=kind, content=content, refs=list(refs or []))
        self.board.append(e)
        return e

    async def list_blackboard(self, graph_id):
        return [e for e in self.board if e.graph == graph_id]


class MemDB:
    """Just what TaskReporter.post uses: query(CREATE), select, merge."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.conv = {"message_count": 0}

    async def query(self, sql, params=None):
        assert sql.startswith("CREATE $rid CONTENT $data")
        self.messages.append(params["data"])
        return []

    async def select(self, thing):
        return [self.conv]

    async def merge(self, thing, data):
        self.conv.update(data)


class FakeLLM:
    def __init__(self) -> None:
        self.final_calls: list[dict] = []
        self.fail_final = False

    async def complete(self, messages, model, temperature=0.7, max_tokens=2000, **kw):
        system = messages[0]["content"]
        prompt = messages[-1]["content"]
        if "final report" in system:
            self.final_calls.append({"model": model, "prompt": prompt, "kw": kw})
            if self.fail_final:
                raise RuntimeError("l3 down")
            return "Result: all good.\nWhat was checked: everything."
        return "node report"


def N(id, kind="think", deps=()):
    return TaskNode(id=id, kind=kind, brief=f"do {id}\nsecond line", success_criteria="ok",
                    depends_on=list(deps), budget_share=0.3)


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(ts, "_POLL_SECONDS", 0.05)
    store, llm, db = MemStore(), FakeLLM(), MemDB()
    sched = ts.TaskGraphScheduler(store=store, llm_client=llm, executor=object())
    sched._reporter_obj = TaskReporter(store, llm_provider=lambda: llm, db=db)
    set_clock(FakeClock(_START))
    yield sched, store, llm, db
    set_clock(Clock())


async def _run(sched, store, nodes, conversation_id=CONV):
    graph = await store.create_graph("find the thing", nodes, 2.0, 30, conversation_id=conversation_id)
    sched.start(graph.id)
    await asyncio.wait_for(sched.wait(graph.id), 10)
    return graph.id


def kinds(db):
    return [m["meta"]["kind"] for m in db.messages]


async def test_event_order_and_meta(env):
    sched, store, llm, db = env
    gid = await _run(sched, store, [N("a"), N("b", deps=["a"]), N("c", deps=["b"])])
    assert kinds(db) == ["plan", "progress", "progress", "progress", "final"]
    for m in db.messages:
        assert m["role"] == "assistant" and m["conversation_id"] == CONV
        assert m["meta"]["task_graph"] == gid
        assert isinstance(m["timestamp"], str)
    plan = db.messages[0]["content"]
    assert "find the thing" in plan and "a [think]" in plan and "do b" in plan and "second line" not in plan
    assert "$2.00" in plan and "30 minutes" in plan
    assert [m["content"] for m in db.messages[1:4]] == [
        "think 'a' done", "think 'b' done", "think 'c' done"]
    assert "Result: all good." in db.messages[-1]["content"]
    assert db.conv["message_count"] == 5
    # One L3 call on the active L3 model, no tools, with the node reports.
    assert len(llm.final_calls) == 1
    assert llm.final_calls[0]["model"] == settings.active_l3_model
    assert "tools" not in llm.final_calls[0]["kw"]
    assert "[a] kind=think status=done" in llm.final_calls[0]["prompt"]


async def test_failed_node_progress_line_and_skipped_in_final(env):
    sched, store, llm, db = env

    async def boom(*a, **k):
        raise RuntimeError("think boom")

    llm_complete = llm.complete

    async def complete(messages, model, **kw):
        if "do a" in messages[-1]["content"] and "analyst" in messages[0]["content"]:
            raise RuntimeError("think boom")
        return await llm_complete(messages, model, **kw)

    llm.complete = complete
    await _run(sched, store, [N("a"), N("b", deps=["a"])])
    texts = [m["content"] for m in db.messages if m["meta"]["kind"] == "progress"]
    assert texts == ["think 'a' failed: think boom"]
    assert kinds(db)[-1] == "final"
    assert "skipped" in llm.final_calls[0]["prompt"]


async def test_final_generated_once_also_after_restart(env):
    sched, store, llm, db = env
    gid = await _run(sched, store, [N("a")])
    assert kinds(db).count("final") == 1
    # A restart builds a new reporter over the same stored guard field.
    fresh = TaskReporter(store, llm_provider=lambda: llm, db=db)
    await fresh.final(gid)
    await fresh.final(gid)
    assert kinds(db).count("final") == 1 and len(llm.final_calls) == 1
    assert store.graphs[gid].final_reported_at is not None


async def test_final_l3_failure_posts_template(env):
    sched, store, llm, db = env
    llm.fail_final = True
    await _run(sched, store, [N("a"), N("b", deps=["a"])])
    final = db.messages[-1]
    assert final["meta"]["kind"] == "final"
    assert "Task graph done" in final["content"] and "Cost and time" in final["content"]
    assert "node report" in final["content"]


async def test_over_budget_graph_gets_a_final(env, monkeypatch):
    sched, store, llm, db = env
    graph = await store.create_graph("g", [N("a")], 2.0, 30, conversation_id=CONV)
    await store.update_graph(graph.id, status=GraphStatus.OVER_BUDGET, spent_usd=2.5)
    await sched.reporter.final(graph.id)
    assert kinds(db) == ["final"]
    assert "over_budget" in llm.final_calls[0]["prompt"] and "$2.5000" in llm.final_calls[0]["prompt"]


async def test_no_final_for_a_running_graph(env):
    sched, store, llm, db = env
    graph = await store.create_graph("g", [N("a")], 2.0, 30, conversation_id=CONV)
    await store.update_graph(graph.id, status=GraphStatus.RUNNING)
    await sched.reporter.final(graph.id)
    assert db.messages == [] and store.graphs[graph.id].final_reported_at is None


async def test_graph_without_conversation_reports_nowhere_and_logs_once(env, caplog):
    sched, store, llm, db = env
    with caplog.at_level(logging.INFO, logger="aura.executor.task_reports"):
        await _run(sched, store, [N("a"), N("b", deps=["a"])], conversation_id=None)
    assert db.messages == [] and llm.final_calls == []
    assert sum("reports nowhere" in r.message for r in caplog.records) == 1


async def test_escalation_carries_decision_id(env):
    sched, store, llm, db = env
    graph = await store.create_graph("g", [N("a", "code")], 2.0, 30, conversation_id=CONV)
    await sched.reporter.escalation(graph.id, "Ready to merge branch x.", "decision:abc")
    m = db.messages[0]
    assert m["meta"] == {"task_graph": graph.id, "kind": "escalation", "decision_id": "decision:abc"}
    assert "decision:abc" in m["content"]


async def test_plan_not_repeated_on_resume(env):
    sched, store, llm, db = env
    gid = await _run(sched, store, [N("a")])
    await sched.reporter.plan(gid)
    assert kinds(db).count("plan") == 1


async def test_report_failure_never_reaches_the_scheduler(env):
    sched, store, llm, db = env

    async def broken(*a, **k):
        raise RuntimeError("db down")

    db.query = broken
    gid = await _run(sched, store, [N("a")])
    assert store.graphs[gid].status == "done"


# -- _conversation_id -----------------------------------------------------------


@pytest.fixture
def titan(monkeypatch, tmp_path):
    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 2)
    yield
    reset_tier_cache()


async def _exec_plan_task(monkeypatch, model_args, **kw):
    ex = ToolExecutor.__new__(ToolExecutor)
    ex.logger = logging.getLogger("t")
    seen: dict = {}

    async def no_skill(name):
        return None

    async def local(tool_name, arguments, *a, **k):
        seen.update(arguments)
        return {"success": True, "result": "ok", "tool_name": tool_name}

    monkeypatch.setattr(ex, "_get_skill_by_name", no_skill)
    monkeypatch.setattr(ex, "_builtin_skill", lambda n: {"skill_type": "local_function", "id": n})
    monkeypatch.setattr(ex, "_execute_local_tool", local)
    await ex.execute_tool_call({"tool": "plan_task", "arguments": model_args},
                               requester_role="owner", **kw)
    return seen


async def test_conversation_id_injected_and_model_value_stripped(titan, monkeypatch):
    seen = await _exec_plan_task(monkeypatch, {"goal": "g", "_conversation_id": "conversation:evil"},
                                 conversation_id="conversation:real")
    assert seen["_conversation_id"] == "conversation:real"
    seen = await _exec_plan_task(monkeypatch, {"goal": "g", "_conversation_id": "conversation:evil"})
    assert "_conversation_id" not in seen


async def test_conversation_id_only_reaches_plan_task(titan, monkeypatch):
    ex = ToolExecutor.__new__(ToolExecutor)
    ex.logger = logging.getLogger("t")
    seen: dict = {}

    async def no_skill(name):
        return None

    async def local(tool_name, arguments, *a, **k):
        seen.update(arguments)
        return {"success": True, "result": "ok", "tool_name": tool_name}

    monkeypatch.setattr(ex, "_get_skill_by_name", no_skill)
    monkeypatch.setattr(ex, "_builtin_skill", lambda n: {"skill_type": "local_function", "id": n})
    monkeypatch.setattr(ex, "_execute_local_tool", local)
    await ex.execute_tool_call({"tool": "recall", "arguments": {"query": "x"}},
                               requester_role="owner", conversation_id="conversation:real")
    assert "_conversation_id" not in seen


def test_schema_has_no_conversation_id_field():
    assert "_conversation_id" not in json.dumps(plan_task.TOOL_DEFINITION)


async def test_plan_task_stores_conversation_id(titan, monkeypatch):
    got: dict = {}

    class S:
        async def create_graph(self, goal, nodes, usd, minutes, turn=None, **kw):
            got.update(kw)

            class G:
                id = "task_graph:x"

            return G()

        async def write_blackboard(self, *a, **k):
            pass

    monkeypatch.setattr(task_graph_module, "get_task_graph_store", lambda: S())
    monkeypatch.setattr(ts, "get_task_scheduler", lambda: type("X", (), {"start": staticmethod(lambda g: None)})())
    nodes = [{"id": "a", "kind": "think", "brief": "b", "success_criteria": "c"}]
    base = {"goal": "g", "nodes": nodes, "_requester_role": "owner", "_venue": "app"}
    await plan_task.run({**base, "_conversation_id": "conversation:7"})
    assert got == {"conversation_id": "conversation:7"}
    got.clear()
    await plan_task.run(base)
    assert got == {}


# -- endpoint -------------------------------------------------------------------


class EndpointDB:
    def __init__(self, rows, graphs):
        self.rows, self.graphs, self.calls = rows, graphs, []

    async def query(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM task_graph" in sql:
            return [g for g in self.graphs if g["status"] in params["live"]]
        rows = [r for r in self.rows if r["conversation_id"] == params["conv"] and r.get("meta")]
        if "since" in params:
            rows = [r for r in rows if r["timestamp"] > params["since"]]
        return sorted(rows, key=lambda r: r["timestamp"])


async def test_endpoint_since_filter_and_running(monkeypatch):
    rows = [
        {"id": "message:1", "conversation_id": CONV, "content": "plan", "role": "assistant",
         "timestamp": "2026-01-01T12:00:01", "meta": {"task_graph": "g", "kind": "plan"}},
        {"id": "message:2", "conversation_id": CONV, "content": "line", "role": "assistant",
         "timestamp": "2026-01-01T12:00:02", "meta": {"task_graph": "g", "kind": "progress"}},
        {"id": "message:3", "conversation_id": CONV, "content": "plain", "role": "assistant",
         "timestamp": "2026-01-01T12:00:03", "meta": None},
        {"id": "message:4", "conversation_id": "conversation:2", "content": "other", "role": "assistant",
         "timestamp": "2026-01-01T12:00:04", "meta": {"task_graph": "h", "kind": "plan"}},
    ]
    db = EndpointDB(rows, [{"id": "task_graph:g", "status": "running"}])
    monkeypatch.setattr(chat_routes, "get_db_client", lambda: db)
    out = await chat_routes.get_task_reports(conversation_id=CONV)
    assert [m["content"] for m in out["messages"]] == ["plan", "line"]
    assert out["running"] is True and out["messages"][0]["meta"]["kind"] == "plan"
    assert out["messages"][0]["conversationId"] == CONV
    out = await chat_routes.get_task_reports(conversation_id=CONV, since="2026-01-01T12:00:01")
    assert [m["content"] for m in out["messages"]] == ["line"]
    db.graphs.clear()
    out = await chat_routes.get_task_reports(conversation_id=CONV, since="2026-01-01T12:00:02")
    assert out == {"messages": [], "running": False}
    assert all("$conv" in sql for sql, _ in db.calls)
