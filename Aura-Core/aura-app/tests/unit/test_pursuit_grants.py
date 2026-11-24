"""B3-04 (T11): pursuit grants and the risk check in execute_tool_call (embedded SurrealDB)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from aura.autonomy import agenda, controls, grants, registry, trace
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import (
    ToolRecord,
    get_tool_registry,
    load_builtin_tools,
    reset_tool_registry,
)
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GOAL = "goal:g1"
AUTO = {"goal_id": GOAL, "source": "pursuit"}


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    controls.reset_cache()
    for mod in (grants, agenda, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda: d)
    monkeypatch.setattr(settings, "goals_v2_enabled", True)
    d.clock = clock
    yield d
    controls.reset_cache()
    set_clock(Clock())
    await d.close()


@pytest.fixture
def ex(monkeypatch):
    reset_tool_registry()
    for record in load_builtin_tools():
        get_tool_registry().register(record)
    get_tool_registry().register(ToolRecord(
        name="mystery", description="", input_schema={}, transport="mcp", risk="weird",  # type: ignore[arg-type]
    ))
    e = ToolExecutor.__new__(ToolExecutor)
    e.logger = logging.getLogger("test.grants")
    e._llm_layers = None
    e.ran = []

    async def skill(name):
        return {"id": f"skill:{name}", "skill_type": "local_function", "execution_config": {}}

    async def run(name, arguments, config, data):
        e.ran.append((name, dict(arguments)))
        return {"success": True, "result": "ok", "error": None, "tool_name": name}

    monkeypatch.setattr(e, "_get_skill_by_name", skill)
    monkeypatch.setattr(e, "_execute_local_tool", run)
    yield e
    reset_tool_registry()


async def _call(e, tool, autonomous=AUTO):
    return await e.execute_tool_call(
        {"tool": tool, "arguments": {"path": "x", "_autonomous": {"goal_id": "forged"}}},
        requester_role="owner", autonomous=autonomous,
    )


async def _decisions(db):
    return extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'needs_decision'"))


async def _grant(scope="write", hours=1):
    return await grants.create(GOAL, scope, _START + timedelta(hours=hours), budget={"calls": 5})


async def test_write_without_grant_blocked_once_per_goal_and_tool(db, ex):
    r1 = await _call(ex, "write_file")
    r2 = await _call(ex, "write_file")
    assert not r1["success"] and "grant" in r1["error"] and not r2["success"]
    assert ex.ran == []
    items = await _decisions(db)
    assert len(items) == 1 and items[0]["refs"] == [GOAL, "write_file"]
    traces = extract_rows(await db.query("SELECT * FROM autonomy_trace WHERE allowed = false"))
    assert len(traces) == 2


async def test_live_grant_passes_and_forged_key_stripped(db, ex):
    await _grant("write")
    r = await _call(ex, "write_file")
    assert r["success"]
    assert "_autonomous" not in ex.ran[0][1]


async def test_grant_scope_must_match(db, ex):
    await _grant("write")
    assert not (await _call(ex, "terminal"))["success"]


async def test_expired_grant_blocks_and_is_revoked(db, ex):
    await _grant("write", hours=1)
    db.clock.advance(2 * 3600)
    assert not (await _call(ex, "write_file"))["success"]
    rows = extract_rows(await db.query("SELECT * FROM pursuit_grant"))
    assert rows[0]["revoked_at"] is not None


async def test_unknown_risk_and_unregistered_tool_need_grant(db, ex):
    assert not (await _call(ex, "mystery"))["success"]
    assert not (await _call(ex, "not_registered_anywhere"))["success"]
    await _grant("execute")
    assert (await _call(ex, "mystery"))["success"]


async def test_read_tool_needs_no_grant(db, ex):
    assert (await _call(ex, "read_file"))["success"]
    assert await _decisions(db) == []


async def test_owner_call_unaffected(db, ex):
    assert (await _call(ex, "write_file", autonomous=None))["success"]
    assert await _decisions(db) == []


async def test_guest_still_refused_even_with_grant(db, ex):
    await _grant("write")
    r = await ex.execute_tool_call({"tool": "write_file", "arguments": {}},
                                   requester_role="guest", autonomous=AUTO)
    assert not r["success"] and ex.ran == []


async def test_db_error_fails_closed(db, ex, monkeypatch):
    await _grant("write")

    class Broken:
        async def query(self, *a, **k):
            raise RuntimeError("down")

    monkeypatch.setattr(grants, "get_db_client", lambda: Broken())
    assert not (await _call(ex, "write_file"))["success"]


def _keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _keys(v)


async def test_model_schema_has_no_autonomous_argument(db, ex):
    for rec in get_tool_registry().all():
        assert "_autonomous" not in set(_keys(rec.input_schema))


async def test_kill_revokes_grants(db, ex, monkeypatch):
    await _grant("write")
    await registry.kill(db)
    rows = extract_rows(await db.query("SELECT * FROM pursuit_grant WHERE revoked_at IS NONE"))
    assert rows == []
    assert not (await _call(ex, "write_file"))["success"]


async def test_flag_off_changes_nothing(db, ex, monkeypatch):
    monkeypatch.setattr(settings, "goals_v2_enabled", False)
    # Non-autonomous calls are exactly as today.
    for tool in ("write_file", "terminal", "mystery", "read_file"):
        assert (await _call(ex, tool, autonomous=None))["success"]
    # Autonomous calls without grants: read only, nothing recorded (fail closed).
    for tool in ("write_file", "terminal", "mystery"):
        assert not (await _call(ex, tool))["success"]
    assert (await _call(ex, "read_file"))["success"]
    assert await _decisions(db) == []
    assert extract_rows(await db.query("SELECT * FROM autonomy_trace")) == []
