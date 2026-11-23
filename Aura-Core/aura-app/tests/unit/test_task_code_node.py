"""P2-10: code nodes in a real temporary git repository, with a fake OpenCode client.

No OpenCode binary is used. Every git repository here lives in tmp_path; Aura's own
repository is never touched (the refusal test checks that no git command runs).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.executor import code_node
from aura.executor import task_scheduler as ts
from aura.executor.task_graph import TaskGraphStore
from aura.models.task_graph import BlackboardEntry, GraphStatus, NodeStatus, TaskGraph, TaskNode
from aura.models.work import WorkEvent

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not available")

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
BRANCH = "aura/task-g1-c1"


# -- helpers ------------------------------------------------------------------------


def git(cwd: Path, *args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=30, stdin=subprocess.DEVNULL)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {args} failed: {proc.stderr}")
    return proc.stdout.strip()


def head(ws: Path) -> str:
    return git(ws, "rev-parse", "HEAD")


def branch_exists(ws: Path, name: str = BRANCH) -> bool:
    return subprocess.run(["git", "show-ref", "--verify", "--quiet", f"refs/heads/{name}"],
                          cwd=str(ws), timeout=30).returncode == 0


def worktrees(ws: Path) -> list[str]:
    out = git(ws, "worktree", "list", "--porcelain")
    return [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")]


async def wait_until(cond, timeout: float = 15.0) -> None:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond():
        if loop.time() > end:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


class MemStore(TaskGraphStore):
    """In-memory store with the TaskGraphStore interface."""

    def __init__(self) -> None:
        self.graphs: dict[str, TaskGraph] = {}
        self.nodes: dict[str, dict[str, TaskNode]] = {}
        self.board: list[BlackboardEntry] = []

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


class FakeClient:
    """OpenCode stand-in: sessions, prompts, a succeeded event per prompt."""

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}
        self.prompts: list[tuple[str, str, str]] = []  # (sid, agent, prompt)
        self.texts: dict[str, str] = {}
        self.queues: dict[str, asyncio.Queue] = {}
        self.aborted: list[str] = []
        self.plan = [{"agent": "explore", "brief": "look around"},
                     {"agent": "build", "brief": "add feature.txt"},
                     {"agent": "review", "brief": "check it"}]
        self.review_text = "Ran pytest tests/test_feature.py: 1 passed.\nVERDICT: PASS"
        self.build_files = {"feature.txt": "feature\n"}

    async def create_session(self, workspace, agent, title, *, parent_id=None):
        sid = f"ses{len(self.sessions) + 1}"
        directory = Path(workspace) if parent_id is None else self.sessions[parent_id]["dir"]
        self.sessions[sid] = {"agent": agent, "parent": parent_id, "dir": directory, "rounds": 0}
        self.queues[sid] = asyncio.Queue()
        return sid

    async def send(self, sid, prompt):
        s = self.sessions[sid]
        s["rounds"] += 1
        self.prompts.append((sid, s["agent"], prompt))
        agent = s["agent"]
        if agent == "aura-lead":
            text = json.dumps({"subtasks": self.plan}) if s["rounds"] == 1 else \
                "FINAL REPORT\nchanged: feature.txt\ntests: pytest tests/test_feature.py\nresults: pass"
        elif agent == "aura-build":
            for name, content in self.build_files.items():
                (s["dir"] / name).write_text(content, encoding="utf-8")
            text = "built feature.txt"
        elif "REVIEW REQUEST" in prompt:
            text = self.review_text
        else:
            text = f"{agent} report"
        self.texts[sid] = text
        await self.queues[sid].put(WorkEvent(kind="succeeded", session_id=sid,
                                             type="session.execution.succeeded", data={}))

    async def events(self, sid):
        while True:
            yield await self.queues[sid].get()

    async def last_text(self, sid):
        return self.texts.get(sid, "")

    async def abort(self, sid):
        self.aborted.append(sid)

    async def answer_permission(self, sid, request_id, allow):
        pass

    def by_agent(self, agent):
        return [sid for sid, s in self.sessions.items() if s["agent"] == agent]


class FakeDecisions:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    async def create(self, **kw):
        did = f"decision:d{len(self.records) + 1}"
        self.records[did] = {**kw, "id": did, "status": "pending"}
        return dict(self.records[did])

    async def get(self, did):
        rec = self.records.get(did)
        return dict(rec) if rec else None

    async def reopen(self, did, message):
        self.records[did].update(status="pending", message=message)

    def merge_decision(self):
        found = [r for r in self.records.values() if r["kind"] == "needs_decision" and r["action"] == "merge"]
        return found[-1] if found else None

    def answer(self, allow: bool):
        rec = self.merge_decision()
        assert rec is not None and rec["status"] == "pending"
        rec["status"] = "allowed" if allow else "denied"


# -- fixtures -----------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path, monkeypatch):
    ws = tmp_path / "proj"
    ws.mkdir()
    git(ws, "init", "-q", "-b", "main")
    git(ws, "config", "user.name", "Test Owner")
    git(ws, "config", "user.email", "owner@example.test")
    git(ws, "config", "commit.gpgsign", "false")
    (ws / "README.md").write_text("hello\n", encoding="utf-8")
    git(ws, "add", "README.md")
    git(ws, "commit", "-q", "-m", "initial")
    monkeypatch.setattr(settings, "workspaces", {"proj": str(ws)})
    monkeypatch.setattr(settings, "task_worktree_root", "")
    yield ws
    # Never leak a worktree: remove any that a failing test left behind.
    for path in worktrees(ws):
        if Path(path).resolve() != ws.resolve():
            git(ws, "worktree", "remove", "--force", path, check=False)


@pytest.fixture
async def env(repo, monkeypatch):
    monkeypatch.setattr(settings, "task_graphs_enabled", True)
    monkeypatch.setattr(settings, "task_code_nodes_enabled", True)
    monkeypatch.setattr(settings, "task_merge_poll_seconds", 0.01)
    monkeypatch.setattr(ts, "_POLL_SECONDS", 0.02)
    store, client, decisions = MemStore(), FakeClient(), FakeDecisions()
    sched = ts.TaskGraphScheduler(store=store, opencode_client=client, decisions=decisions)
    set_clock(FakeClock(_START))
    try:
        yield sched, store, client, decisions, repo
    finally:
        await sched.shutdown()
        set_clock(Clock())


def code(brief="workspace: proj\nAdd feature.txt", criteria="pytest tests/test_feature.py passes", id="c1"):
    return TaskNode(id=id, kind="code", brief=brief, success_criteria=criteria)


async def start(sched, store, nodes, budget_minutes=60):
    graph = await store.create_graph("goal", nodes, 1.0, budget_minutes)
    sched.start(graph.id)
    return graph.id


def node(store, gid, nid="c1"):
    return store.nodes[gid][nid]


async def finish(sched, gid):
    await asyncio.wait_for(sched.wait(gid), 15)


# -- tests ----------------------------------------------------------------------------


async def test_full_flow_worktree_session_and_merge_after_approval(env, tmp_path):
    sched, store, client, decisions, ws = env
    before = head(ws)
    gid = await start(sched, store, [code()])
    await wait_until(lambda: node(store, gid).status == "ready_to_merge")
    await wait_until(lambda: decisions.merge_decision() is not None)

    # The worktree: right path (sibling of the workspace), right branch.
    wt = tmp_path / ".aura-worktrees" / "proj-task-g1-c1"
    assert wt.is_dir()
    assert git(wt, "rev-parse", "--abbrev-ref", "HEAD") == BRANCH
    assert any(Path(p).resolve() == wt.resolve() for p in worktrees(ws))
    # The lead session points at the worktree; children are its children.
    lead = client.by_agent("aura-lead")
    assert len(lead) == 1 and client.sessions[lead[0]]["dir"] == wt
    children = [s for s in client.sessions.values() if s["agent"] != "aura-lead"]
    assert [c["agent"] for c in children] == ["aura-explore", "aura-build", "aura-review", "aura-review"]
    assert all(c["parent"] == lead[0] and c["dir"] == wt for c in children)
    # The children's reports went back into the lead.
    lead_prompts = [p for sid, a, p in client.prompts if a == "aura-lead"]
    assert len(lead_prompts) == 2 and "built feature.txt" in lead_prompts[1]

    # Before approval the main tree is untouched.
    assert head(ws) == before
    assert git(ws, "status", "--porcelain") == ""
    assert not (ws / "feature.txt").exists()
    rec = decisions.merge_decision()
    assert rec["kind"] == "needs_decision" and rec["action"] == "merge"
    assert rec["resources"] == [BRANCH] and "1 file changed" in rec["message"]
    await asyncio.sleep(0.1)
    assert head(ws) == before and node(store, gid).status == "ready_to_merge"

    decisions.answer(True)
    await finish(sched, gid)
    assert node(store, gid).status == "done"
    assert store.graphs[gid].status == "done"
    # --no-ff: the merge commit has two parents.
    parents = git(ws, "rev-list", "--parents", "-n", "1", "HEAD").split()
    assert len(parents) == 3 and parents[1] == before
    assert (ws / "feature.txt").read_text(encoding="utf-8") == "feature\n"
    # Worktree removed, branch deleted after the merge.
    assert not wt.exists()
    assert [Path(p).resolve() for p in worktrees(ws)] == [ws.resolve()]
    assert not branch_exists(ws)


async def test_merge_wait_does_not_count_against_time_budget(env):
    sched, store, client, decisions, ws = env
    gid = await start(sched, store, [code()], budget_minutes=60)
    await wait_until(lambda: decisions.merge_decision() is not None)
    get_clock().advance(3 * 3600)  # Mai takes three hours to decide
    await asyncio.sleep(0.15)
    assert store.graphs[gid].status == "running"
    decisions.answer(True)
    await finish(sched, gid)
    assert store.graphs[gid].status == "done"


async def test_conflict_aborts_merge_and_keeps_branch(env, tmp_path):
    sched, store, client, decisions, ws = env
    gid = await start(sched, store, [code()])
    await wait_until(lambda: decisions.merge_decision() is not None)
    (ws / "feature.txt").write_text("something else\n", encoding="utf-8")
    git(ws, "add", "feature.txt")
    git(ws, "commit", "-q", "-m", "conflicting change")
    conflicting = head(ws)

    decisions.answer(True)
    await finish(sched, gid)
    n = node(store, gid)
    assert n.status == "failed" and "merge conflict" in n.report and "kept" in n.report
    assert head(ws) == conflicting
    assert git(ws, "status", "--porcelain") == ""
    assert not (ws / ".git" / "MERGE_HEAD").exists()
    assert branch_exists(ws)
    assert not (tmp_path / ".aura-worktrees" / "proj-task-g1-c1").exists()
    assert any(e.kind == "escalation" and "conflict" in e.content for e in store.board)


async def test_rejection_keeps_branch_and_removes_worktree(env, tmp_path):
    sched, store, client, decisions, ws = env
    before = head(ws)
    gid = await start(sched, store, [code()])
    await wait_until(lambda: decisions.merge_decision() is not None)
    decisions.answer(False)
    await finish(sched, gid)
    n = node(store, gid)
    assert n.status == "failed" and "merge rejected by owner" in n.report
    assert head(ws) == before and git(ws, "status", "--porcelain") == ""
    assert branch_exists(ws)
    assert not (tmp_path / ".aura-worktrees" / "proj-task-g1-c1").exists()
    assert [Path(p).resolve() for p in worktrees(ws)] == [ws.resolve()]


async def test_dirty_main_tree_blocks_merge_and_keeps_decision_pending(env):
    sched, store, client, decisions, ws = env
    before = head(ws)
    gid = await start(sched, store, [code()])
    await wait_until(lambda: decisions.merge_decision() is not None)
    (ws / "README.md").write_text("local edit\n", encoding="utf-8")

    decisions.answer(True)
    await wait_until(lambda: any(e.kind == "escalation" for e in store.board))
    await wait_until(lambda: decisions.merge_decision()["status"] == "pending")
    assert "uncommitted changes" in decisions.merge_decision()["message"]
    assert node(store, gid).status == "ready_to_merge"
    assert head(ws) == before and not (ws / "feature.txt").exists()

    git(ws, "checkout", "--", "README.md")
    decisions.answer(True)
    await finish(sched, gid)
    assert node(store, gid).status == "done"
    assert len(git(ws, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3


async def test_review_failure_fails_node_without_decision(env, tmp_path):
    sched, store, client, decisions, ws = env
    client.review_text = "Ran pytest: 1 failed.\nVERDICT: FAIL: tests/test_feature.py fails"
    before = head(ws)
    gid = await start(sched, store, [code()])
    await finish(sched, gid)
    n = node(store, gid)
    assert n.status == "failed" and "review failed: tests/test_feature.py fails" in n.report
    assert decisions.merge_decision() is None
    assert head(ws) == before and git(ws, "status", "--porcelain") == ""
    assert branch_exists(ws)  # the work is kept on the branch
    assert not (tmp_path / ".aura-worktrees" / "proj-task-g1-c1").exists()


async def test_one_code_node_at_a_time_across_graphs(env):
    sched, store, client, decisions, ws = env
    g1 = await start(sched, store, [code()])
    await wait_until(lambda: decisions.merge_decision() is not None)
    g2 = await start(sched, store, [code(id="c2")])
    await asyncio.sleep(0.2)
    assert node(store, g2, "c2").status == "pending"
    assert len(client.by_agent("aura-lead")) == 1
    decisions.answer(False)
    await finish(sched, g1)
    await wait_until(lambda: node(store, g2, "c2").status == "ready_to_merge")
    assert len(client.by_agent("aura-lead")) == 2
    decisions.answer(False)
    await finish(sched, g2)


async def test_unregistered_or_missing_workspace_is_refused(env, monkeypatch):
    sched, store, client, decisions, ws = env
    gid = await start(sched, store, [code(brief="workspace: other\nAdd it")])
    await finish(sched, gid)
    assert "workspace 'other' is not registered" in node(store, gid).report
    gid = await start(sched, store, [code(brief="Add it, no workspace named")])
    await finish(sched, gid)
    assert "names no workspace" in node(store, gid).report
    assert client.sessions == {}


async def test_aura_own_repo_is_refused_without_git(env, monkeypatch):
    sched, store, client, decisions, ws = env
    aura_root = Path(code_node.__file__).resolve().parents[3]  # .../aura-app
    assert code_node.is_aura_repo(aura_root)
    assert not code_node.is_aura_repo(ws)
    calls = []

    async def no_git(args, cwd, env_extra=None):
        calls.append((args, cwd))
        raise AssertionError("git must not run")

    monkeypatch.setattr(code_node, "run_git", no_git)
    gid = await start(sched, store, [code(brief=f"workspace: {aura_root.name}\nImprove yourself")])
    await finish(sched, gid)
    assert node(store, gid).status == "failed"
    assert "is not registered" in node(store, gid).report
    assert calls == [] and client.sessions == {}


async def test_worktree_root_inside_workspace_is_refused(env, monkeypatch):
    sched, store, client, decisions, ws = env
    monkeypatch.setattr(settings, "task_worktree_root", str(ws / "trees"))
    gid = await start(sched, store, [code()])
    await finish(sched, gid)
    assert "inside the main working tree" in node(store, gid).report
    assert not (ws / "trees").exists() and not branch_exists(ws)
    assert client.sessions == {}


async def test_flag_off_keeps_placeholder(env, monkeypatch):
    sched, store, client, decisions, ws = env
    monkeypatch.setattr(settings, "task_code_nodes_enabled", False)
    gid = await start(sched, store, [code()])
    await finish(sched, gid)
    assert node(store, gid).report == f"failed: {ts.CODE_NODE_REASON}"
    assert client.sessions == {} and not branch_exists(ws)


async def test_bad_plan_fails_and_cleans_up(env, tmp_path):
    sched, store, client, decisions, ws = env
    client.plan = [{"agent": "build", "brief": f"b{i}"} for i in range(4)]
    gid = await start(sched, store, [code()])
    await finish(sched, gid)
    assert "at most 3" in node(store, gid).report
    assert client.by_agent("aura-build") == []
    assert not branch_exists(ws)  # nothing was done, so the branch is gone too
    assert not (tmp_path / ".aura-worktrees" / "proj-task-g1-c1").exists()


def test_parse_plan_and_git_allowlist():
    assert code_node.parse_plan('```json\n{"subtasks": [{"agent": "aura-build", "brief": "x"}]}\n```') == [("build", "x")]
    with pytest.raises(code_node.CodeNodeError):
        code_node.parse_plan("no plan here")
    with pytest.raises(code_node.CodeNodeError):
        code_node.parse_plan('{"subtasks": [{"agent": "deploy", "brief": "x"}]}')
    for remote in ("push", "fetch", "pull", "remote", "clone", "ls-remote"):
        assert remote not in code_node.ALLOWED_GIT_SUBCOMMANDS
        with pytest.raises(ValueError):
            code_node._run_git_sync([remote], Path("."), 5.0, None)
    assert code_node.branch_name("task_graph:ab12", "n 1") == "aura/task-ab12-n-1"
