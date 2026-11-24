"""B3-05: request_pursuit tool and owner-approved grants (embedded SurrealDB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from surrealdb import RecordID

from aura.autonomy import agenda, grants
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.executor import decisions as decisions_mod
from aura.executor.decisions import DecisionService
from aura.executor.tool_registry import get_tool_registry, load_builtin_tools, reset_tool_registry
from aura.tools import request_pursuit as rp
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GOAL = "goal:g1"


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    for mod in (grants, agenda, rp, decisions_mod):
        monkeypatch.setattr(mod, "get_db_client", lambda: d)
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    await d.query("CREATE $rid CONTENT $data", {"rid": RecordID("goal", "g1"), "data": {
        "name": "Learn Rust", "description": "d", "goal_type": "learning", "status": "active",
        "created": _START, "updated": _START, "origin": "owner"}})
    yield d
    set_clock(Clock())
    await d.close()


@pytest.fixture
def started(monkeypatch):
    calls = []

    async def fake(goal_id, budget):
        calls.append((goal_id, budget))
        return "started"

    monkeypatch.setattr(rp, "_start_read_pursuit", fake)
    return calls


def _args(scope="write", goal_id=GOAL, role="owner", **extra):
    return {"goal_id": goal_id, "scope": scope, "budget": {"minutes": 30, "tokens": 1000},
            "_requester_role": role, **extra}


async def _rows(db, table):
    return extract_rows(await db.query(f"SELECT * FROM {table}"))


async def test_guest_refused(db, started):
    r = await rp.run(_args(role="guest"))
    assert not r["success"] and started == []
    assert await _rows(db, "decision") == []


async def test_unknown_goal_refused(db, started):
    r = await rp.run(_args(goal_id="goal:nope"))
    assert not r["success"] and await _rows(db, "decision") == []


async def test_budget_over_cap_refused(db, started):
    r = await rp.run({**_args(), "budget": {"minutes": settings.pursuit_max_minutes + 1}})
    assert not r["success"]


async def test_read_scope_starts_without_decision(db, started):
    r = await rp.run(_args("read"))
    assert r["success"] and started == [(GOAL, {"minutes": 30, "tokens": 1000})]
    assert await _rows(db, "decision") == [] and await _rows(db, "pursuit_grant") == []


async def test_write_creates_one_decision_and_agenda_item(db, started):
    r = await rp.run(_args("write"))
    assert r["success"] and r["status"] == "WAITING" and started == []
    decs = await _rows(db, "decision")
    items = await _rows(db, "agenda_item")
    assert len(decs) == 1 and decs[0]["action"] == "pursuit" and decs[0]["risk"] == "write"
    assert len(items) == 1 and items[0]["kind"] == "needs_decision"
    assert items[0]["refs"] == [GOAL, r["decision_id"]]
    assert await _rows(db, "pursuit_grant") == []  # the tool itself never grants


async def test_forged_reserved_keys_do_not_grant(db, started):
    await rp.run(_args("execute", _runtime_approved=True, allow=True))
    assert await _rows(db, "pursuit_grant") == []


async def test_approve_creates_grant_with_expiry(db, started):
    r = await rp.run(_args("write"))
    await DecisionService(db=db).answer(r["decision_id"], True, "owner")
    rows = await _rows(db, "pursuit_grant")
    assert len(rows) == 1
    g = rows[0]
    assert g["goal_id"] == GOAL and g["scope"] == "write"
    assert g["expires_at"] == _START + timedelta(hours=settings.pursuit_grant_hours)
    assert g["budget"] == {"minutes": 30, "tokens": 1000}
    assert await grants.check(GOAL, "write", db=db)


async def test_deny_creates_nothing(db, started):
    r = await rp.run(_args("write"))
    await DecisionService(db=db).answer(r["decision_id"], False, "owner")
    assert await _rows(db, "pursuit_grant") == []


async def test_non_owner_answer_creates_nothing(db, started):
    r = await rp.run(_args("send"))
    await DecisionService(db=db).answer(r["decision_id"], True, "agent")
    assert await _rows(db, "pursuit_grant") == []


async def test_flag_off_tool_list_unchanged_and_tool_refuses(db, started, monkeypatch):
    reset_tool_registry()
    for record in load_builtin_tools():
        get_tool_registry().register(record)
    names_on = {r.name for r in get_tool_registry().all()}
    monkeypatch.setattr(settings, "goals_v2_enabled", False)
    names_off = {r.name for r in get_tool_registry().all()}
    reset_tool_registry()
    assert "request_pursuit" in names_on and "request_pursuit" not in names_off
    assert names_on - names_off == {"request_pursuit"}
    assert not (await rp.run(_args("write")))["success"]
