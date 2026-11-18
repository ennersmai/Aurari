"""W2-28: Tool registry — records, loaders and the schema sanitiser.

Offline tests for ``aura.executor.tool_registry`` (card W2-28): builtin
loading, skill-row conversion, schema sanitising, registry bookkeeping and
``refresh`` against a fake database.
"""

import pytest

from aura.executor.tool_registry import (
    BUILTIN_MODULES,
    BUILTIN_RISK,
    ToolRecord,
    ToolRegistry,
    get_tool_registry,
    load_builtin_tools,
    records_from_skill_rows,
    reset_tool_registry,
    sanitize_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _walk_keys(node):
    """Yield every dict key anywhere in a nested dict/list structure."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from _walk_keys(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_keys(value)


def _mcp_row(**overrides):
    row = {
        "id": "skill:mcp1",
        "name": "Some Tool",
        "tool_name": "some_tool",
        "skill_type": "mcp_tool",
        "definition": {
            "name": "some_tool",
            "description": "An MCP tool",
            "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
        },
        "execution_config": {"status": "offline", "last_error": "boom"},
    }
    row.update(overrides)
    return row


class FakeDB:
    def __init__(self, rows):
        self.rows = rows

    async def query(self, query, params=None):
        return self.rows


class RaisingDB:
    async def query(self, query, params=None):
        raise RuntimeError("db down")


@pytest.fixture(autouse=True)
def _fresh_registry():
    reset_tool_registry()
    yield
    reset_tool_registry()


# ---------------------------------------------------------------------------
# load_builtin_tools
# ---------------------------------------------------------------------------


def test_load_builtin_tools_returns_the_14_builtin_records():
    records = load_builtin_tools()
    names = sorted(r.name for r in records)
    assert names == sorted(BUILTIN_RISK.keys())
    assert len(records) == 14
    assert all(r.transport == "builtin" for r in records)
    assert all(r.health.status == "online" for r in records)
    # Every record comes from one of the builtin modules.
    assert all(r.source in BUILTIN_MODULES for r in records)
    # Risk follows BUILTIN_RISK.
    for record in records:
        assert record.risk == BUILTIN_RISK[record.name]


def test_builtin_schemas_carry_no_approval_fields():
    for record in load_builtin_tools():
        for key in _walk_keys(record.input_schema):
            assert key != "force_execute"
            assert not (isinstance(key, str) and key.startswith("_"))


def test_builtin_records_keep_their_real_schemas():
    # The builtin definitions store their schema under `parameters` or
    # `inputSchema`; the registry must keep the real properties either way.
    by_name = {r.name: r for r in load_builtin_tools()}
    assert "query" in by_name["web_search"].input_schema["properties"]
    assert "command" in by_name["terminal"].input_schema["properties"]
    assert "path" in by_name["read_file"].input_schema["properties"]
    assert "code" in by_name["execute_code"].input_schema["properties"]
    assert "chart_type" in by_name["generate_chart"].input_schema["properties"]


# ---------------------------------------------------------------------------
# sanitize_schema
# ---------------------------------------------------------------------------


def test_sanitize_schema_removes_banned_keys_including_nested():
    schema = {
        "type": "object",
        "properties": {
            "force_execute": {"type": "boolean"},
            "_secret": {"type": "string"},
            "ok": {"type": "string"},
            "nested": {
                "type": "object",
                "properties": {
                    "force_execute": {"type": "boolean"},
                    "_hidden": {"type": "string"},
                    "inner": {"type": "string"},
                },
                "required": ["force_execute", "_hidden", "inner"],
            },
        },
        "required": ["force_execute", "_secret", "ok"],
    }
    cleaned = sanitize_schema(schema)

    assert set(cleaned["properties"]) == {"ok", "nested"}
    assert cleaned["required"] == ["ok"]
    nested = cleaned["properties"]["nested"]
    assert set(nested["properties"]) == {"inner"}
    assert nested["required"] == ["inner"]

    # The input is not mutated.
    assert "force_execute" in schema["properties"]
    assert "_secret" in schema["properties"]
    assert set(schema["required"]) == {"force_execute", "_secret", "ok"}
    assert "force_execute" in schema["properties"]["nested"]["properties"]


def test_sanitize_schema_non_dict_input():
    assert sanitize_schema(None) == {"type": "object", "properties": {}}
    assert sanitize_schema("nope") == {"type": "object", "properties": {}}


def test_sanitize_schema_does_not_mutate_nested_non_object_schemas():
    schema = {"type": "object", "properties": {"n": {"type": "number", "minimum": 0}}}
    cleaned = sanitize_schema(schema)
    cleaned["properties"]["n"]["minimum"] = 99
    assert schema["properties"]["n"]["minimum"] == 0


# ---------------------------------------------------------------------------
# records_from_skill_rows
# ---------------------------------------------------------------------------


def test_records_from_skill_rows_mcp_tool_health_and_risk():
    records = records_from_skill_rows([_mcp_row()])
    assert len(records) == 1
    record = records[0]
    assert record.name == "some_tool"
    assert record.transport == "mcp"
    assert record.risk == "execute"
    assert record.health.status == "offline"
    assert record.health.error == "boom"
    assert record.source == "skill:mcp1"
    assert record.input_schema == {"type": "object", "properties": {"q": {"type": "string"}}}


def test_records_from_skill_rows_skips_other_types_and_bad_rows():
    rows = [
        {"skill_type": "concept", "definition": {"name": "x"}},
        {"skill_type": "mcp_tool", "definition": "not a dict"},
        {"skill_type": "local_function", "definition": {"description": "no name"}},
        _mcp_row(),
    ]
    records = records_from_skill_rows(rows)
    assert [r.name for r in records] == ["some_tool"]


def test_records_from_skill_rows_local_function_risk_falls_back_to_execute():
    row = {
        "id": "skill:lf1",
        "tool_name": "mystery_tool",
        "skill_type": "local_function",
        "definition": {"name": "mystery_tool", "description": "d", "parameters": {}},
        "execution_config": {"module": "aura.tools.mystery", "function": "run"},
    }
    records = records_from_skill_rows([row])
    assert records[0].transport == "builtin"
    assert records[0].risk == "execute"
    assert records[0].health.status == "unknown"


def test_records_from_skill_rows_mcp_status_online_and_embedding():
    row = _mcp_row(
        execution_config={"status": "online"},
        description_embedding=[0.1, 0.2],
    )
    records = records_from_skill_rows([row])
    assert records[0].health.status == "online"
    assert records[0].health.error is None
    assert records[0].description_embedding == [0.1, 0.2]


# ---------------------------------------------------------------------------
# refresh
# ---------------------------------------------------------------------------


async def test_refresh_registers_builtins_then_skill_rows():
    mcp_row = _mcp_row(description_embedding=[0.9])
    local_row = {
        "id": "skill:ws",
        "name": "Web Search",
        "tool_name": "web_search",
        "skill_type": "local_function",
        "definition": {"name": "web_search", "description": "x", "parameters": {}},
        "execution_config": {"module": "aura.tools.web_search", "function": "run"},
        "description_embedding": [0.42],
    }
    registry = get_tool_registry()
    await registry.refresh(FakeDB([mcp_row, local_row]))

    records = registry.all()
    assert len(records) == 15  # 14 builtins + 1 MCP tool
    # The local_function row for web_search only copied its embedding.
    web_search = registry.get("web_search")
    assert web_search.description_embedding == [0.42]
    assert web_search.transport == "builtin"
    # The MCP row was registered.
    assert registry.get("some_tool").transport == "mcp"


async def test_refresh_keeps_builtins_when_the_database_fails():
    registry = get_tool_registry()
    await registry.refresh(RaisingDB())
    assert len(registry.all()) == 14


async def test_refresh_mcp_tool_replaces_same_name_record():
    mcp_row = _mcp_row(tool_name="terminal")
    registry = get_tool_registry()
    await registry.refresh(FakeDB([mcp_row]))
    assert registry.get("terminal").transport == "mcp"


# ---------------------------------------------------------------------------
# Registry bookkeeping
# ---------------------------------------------------------------------------


def _record(name, description=""):
    return ToolRecord(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
        transport="builtin",
        risk="read",
    )


def test_record_call_stats():
    registry = ToolRegistry()
    registry.register(_record("t"))
    registry.record_call("t", True, 10)
    registry.record_call("t", False, 30)
    registry.record_call("t", True, 20)
    stats = registry.get("t").stats
    assert stats.calls == 3
    assert stats.successes == 2
    assert stats.success_rate == pytest.approx(2 / 3)
    assert stats.median_latency_ms == 20


def test_record_call_ignores_unknown_names():
    registry = ToolRegistry()
    registry.record_call("ghost", True, 5)
    assert registry.get("ghost") is None


def test_register_replaces_record_but_keeps_stats():
    registry = ToolRegistry()
    registry.register(_record("t"))
    registry.record_call("t", True, 10)
    registry.record_call("t", True, 20)

    registry.register(_record("t", description="new"))
    kept = registry.get("t")
    assert kept.description == "new"
    assert kept.stats.calls == 2
    assert kept.stats.successes == 2


def test_get_and_all_sorted_by_name():
    registry = ToolRegistry()
    registry.register(_record("zeta"))
    registry.register(_record("alpha"))
    assert [r.name for r in registry.all()] == ["alpha", "zeta"]
    assert registry.get("zeta").name == "zeta"
    assert registry.get("nope") is None


def test_set_health_stamps_last_check():
    from aura.clock import Clock, FakeClock, set_clock

    try:
        clock = FakeClock()
        set_clock(clock)
        registry = ToolRegistry()
        registry.register(_record("t"))
        clock.advance(60)
        registry.set_health("t", "offline", error="boom")
        health = registry.get("t").health
        assert health.status == "offline"
        assert health.error == "boom"
        assert health.last_check == clock.now()
    finally:
        set_clock(Clock())
