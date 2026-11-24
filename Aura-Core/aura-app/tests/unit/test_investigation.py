"""B4-02: bounded, read-only, pausable investigations (embedded SurrealDB, fake LLM, fake tools)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import pytest

from aura.autonomy import agenda, controls, grants, investigation, registry, trace
from aura.autonomy.investigation import InvestigationBudget, InvestigationRunner
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import get_tool_registry, load_builtin_tools, reset_tool_registry
from aura.models.proposal import Proposal, ProposalKind
from aura.orchestrator.workspace import PauseToken, Winner, Workspace
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
CALL_READ = '{"tool": "read_file", "arguments": {"path": "a.txt"}}'
CALL_WRITE = '{"tool": "write_file", "arguments": {"path": "a.txt", "content": "x"}}'
REPORT = (
    "- Pixel the cat eats kibble twice a day, per https://vet.example/pixel\n"
    "- The vet recommends a weight check every six months\n"
)


class FakeLLM:
    """Scripted replies; the last one repeats. Counts model calls."""

    def __init__(self, replies, hang_on=None):
        self.replies, self.calls, self.hang_on = list(replies), 0, hang_on

    async def complete(self, messages, model=None, **kw):
        i = self.calls
        self.calls += 1
        if self.hang_on is not None and i == self.hang_on:
            await asyncio.sleep(30)
        return self.replies[min(i, len(self.replies) - 1)]


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    controls.reset_cache()
    for mod in (grants, agenda, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda: d)
    monkeypatch.setattr(settings, "curiosity_enabled", True)
    monkeypatch.setattr(settings, "l3_native_tools", False)
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    d.clock = clock
    yield d
    controls.reset_cache()
    set_clock(Clock())
    await d.close()


@pytest.fixture
def ex(monkeypatch, db):
    reset_tool_registry()
    for record in load_builtin_tools():
        get_tool_registry().register(record)
    e = ToolExecutor.__new__(ToolExecutor)
    e.logger = logging.getLogger("test.investigation")
    e._llm_layers = None
    e.ran = []
    e.tool_seconds = 0
    e.block = None

    async def skill(name):
        return {"id": f"skill:{name}", "skill_type": "local_function", "execution_config": {}}

    async def run(name, arguments, config, data):
        e.ran.append(name)
        db.clock.advance(e.tool_seconds)
        if e.block is not None:
            await e.block.wait()
        return {"success": True, "result": "page text\nURL: https://vet.example/pixel", "error": None,
                "tool_name": name}

    monkeypatch.setattr(e, "_get_skill_by_name", skill)
    monkeypatch.setattr(e, "_execute_local_tool", run)
    yield e
    reset_tool_registry()


async def _question(db, visibility="owner", content="What does Pixel eat?"):
    rows = await db.query(
        "CREATE question CONTENT $d",
        {"d": {"content": content, "visibility": visibility, "status": "open", "recorded_at": _START}},
    )
    return rows[0]


def _runner(db, ex, llm):
    return InvestigationRunner(llm_client=llm, executor=ex, db=db, embeddings=HashedBagOfWordsEmbeddings())


BIG = InvestigationBudget(max_tokens=10**6, max_tool_calls=50, max_minutes=60)


async def _row(db, q):
    return extract_rows(await db.query("SELECT * FROM $id", {"id": q["id"]}))[0]


@pytest.mark.parametrize("reason,budget", [
    ("max_tool_calls", InvestigationBudget(10**6, 2, 60)),
    ("max_tokens", InvestigationBudget(1, 50, 60)),
    ("max_minutes", InvestigationBudget(10**6, 50, 1)),
])
async def test_each_limit_stops_and_records_reason(db, ex, reason, budget):
    ex.tool_seconds = 45
    q = await _question(db)
    r = await _runner(db, ex, FakeLLM([CALL_READ])).run(q, "search", budget, PauseToken())
    assert r.state == "partial" and r.reason == reason
    row = await _row(db, q)
    assert row["status"] == "partial" and row["investigation"]["reason"] == reason
    traces = extract_rows(await db.query("SELECT * FROM autonomy_trace WHERE action = 'investigation:partial'"))
    assert len(traces) == 1 and traces[0]["cost"]["tool_calls"] == r.tool_calls
    if reason == "max_tool_calls":
        assert len(ex.ran) == 2


async def test_write_tool_blocked_once_with_needs_decision(db, ex):
    q = await _question(db)
    llm = FakeLLM([CALL_WRITE, CALL_WRITE, REPORT])
    await _runner(db, ex, llm).run(q, "search", BIG, PauseToken())
    assert "write_file" not in ex.ran
    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'needs_decision'"))
    assert len(items) == 1 and "write_file" in items[0]["refs"]


async def test_read_tool_runs_without_decision(db, ex):
    q = await _question(db)
    await _runner(db, ex, FakeLLM([CALL_READ, REPORT])).run(q, "read", BIG, PauseToken())
    assert ex.ran == ["read_file"]
    assert extract_rows(await db.query("SELECT * FROM agenda_item")) == []


async def test_pause_mid_run_within_two_seconds_and_resume(db, ex):
    q = await _question(db)
    token = PauseToken()
    llm = FakeLLM([CALL_READ, REPORT], hang_on=1)
    runner = _runner(db, ex, llm)
    task = asyncio.create_task(runner.run(q, "search", BIG, token))
    while llm.calls < 2:
        await asyncio.sleep(0.01)
    t0 = time.monotonic()
    token.pause()
    r = await asyncio.wait_for(task, 2)
    assert time.monotonic() - t0 < 2
    assert r.state == "paused" and r.tool_calls == 1
    row = await _row(db, q)
    assert row["status"] == "open" and row["investigation"]["state"] == "paused"
    assert "page text" in row["investigation"]["notes"]

    # Next winning cycle: progress is kept and the run finishes.
    llm.hang_on = None
    r2 = await runner.run(row, "search", BIG, PauseToken())
    assert r2.state == "resolved" and r2.tool_calls >= 1
    assert (await _row(db, q))["status"] == "resolved"


async def test_findings_stored_external_with_sources(db, ex):
    q = await _question(db)
    r = await _runner(db, ex, FakeLLM([CALL_READ, REPORT])).run(q, "search", BIG, PauseToken())
    assert r.state == "resolved" and len(r.fact_ids) == 2
    facts = extract_rows(await db.query("SELECT * FROM fact"))
    assert {f["provenance"] for f in facts} == {"external"}
    assert all(f["sources"] == ["https://vet.example/pixel"] for f in facts)
    assert all(f["confidence"] == settings.memory_external_confidence for f in facts)
    assert (await _row(db, q))["resolved_by"] == "investigation"


async def test_kill_switch_cancels_run(db, ex):
    ex.block = asyncio.Event()
    q = await _question(db)
    task = asyncio.create_task(_runner(db, ex, FakeLLM([CALL_READ])).run(q, "search", BIG, PauseToken()))
    while not ex.ran:
        await asyncio.sleep(0.01)
    assert [t["kind"] for t in registry.registered()] == ["investigation"]
    await registry.cancel_all("test")
    r = await asyncio.wait_for(task, 2)
    assert r.state == "cancelled"
    assert (await _row(db, q))["status"] == "open"


async def test_guest_question_refused_without_model_call(db, ex):
    q = await _question(db, visibility="guest")
    llm = FakeLLM([REPORT])
    r = await _runner(db, ex, llm).run(q, "search", BIG, PauseToken())
    assert r.state == "refused" and llm.calls == 0 and ex.ran == []


async def test_flag_off_no_handler_and_runner_refuses(db, ex, monkeypatch):
    monkeypatch.setattr(settings, "curiosity_enabled", False)
    ws = Workspace()
    assert investigation.register(ws) is False
    assert ProposalKind.INVESTIGATE not in ws._handlers
    llm = FakeLLM([REPORT])
    r = await _runner(db, ex, llm).run(await _question(db), "search", BIG, PauseToken())
    assert r.state == "refused" and llm.calls == 0
    monkeypatch.setattr(settings, "curiosity_enabled", True)
    assert investigation.register(ws) is True and ProposalKind.INVESTIGATE in ws._handlers


async def test_handler_runs_winning_proposal(db, ex, monkeypatch):
    q = await _question(db, content="What does the web say about https://vet.example?")
    ws = Workspace()
    handler = investigation.make_handler(_runner(db, ex, FakeLLM([CALL_READ, REPORT])), ws)
    p = Proposal(source="curiosity", kind=ProposalKind.INVESTIGATE, summary="look it up",
                 refs=[str(q["id"])])
    await handler(Winner(proposal=p, score=1.0, cost_score=0.1, drive_gain=1.0))
    assert (await _row(db, q))["status"] == "resolved"
