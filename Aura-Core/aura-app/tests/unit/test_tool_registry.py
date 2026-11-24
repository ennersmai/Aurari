"""W2-28: Tool registry — records, loaders and the schema sanitiser.

Offline tests for ``aura.executor.tool_registry`` (card W2-28): builtin
loading, skill-row conversion, schema sanitising, registry bookkeeping and
``refresh`` against a fake database.
"""

import importlib
import logging
import math
import sys
import types
from typing import Any, Dict

import pytest

from aura.executor.tool_registry import (
    BUILTIN_MODULES,
    BUILTIN_RISK,
    ToolHealth,
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


def test_load_builtin_tools_returns_the_15_builtin_records():
    records = load_builtin_tools()
    names = sorted(r.name for r in records)
    assert names == sorted(BUILTIN_RISK.keys())
    assert len(records) == 23  # 15 + six recall tools (W4-05) + plan_task (P2-08) + request_pursuit (B3-05); the last two hidden by all() unless enabled
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
    assert len(records) == 22  # 21 builtins + 1 MCP tool
    # The local_function row for web_search only copied its embedding.
    web_search = registry.get("web_search")
    assert web_search.description_embedding == [0.42]
    assert web_search.transport == "builtin"
    # The MCP row was registered.
    assert registry.get("some_tool").transport == "mcp"


async def test_refresh_keeps_builtins_when_the_database_fails():
    registry = get_tool_registry()
    await registry.refresh(RaisingDB())
    assert len(registry.all()) == 21


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


# ---------------------------------------------------------------------------
# W2-29: Executor reports calls and MCP health to the registry
# ---------------------------------------------------------------------------


def _make_executor_with_registry(tool_module: types.ModuleType) -> ToolExecutor:
    """Build a ``ToolExecutor`` without running ``__init__`` and wire a fake
    database plus a stub tool module, so execute_tool_call can route a
    ``local_function`` tool to the supplied module."""
    from aura.executor.tool_executor import ToolExecutor
    import sys

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.logger = __import__("logging").getLogger("aura.executor.test")

    # Fake database: the only query execute_tool_call issues before running
    # the tool is the skill lookup. We return one local_function skill record
    # that points at the supplied tool module.
    class _FakeDB:
        async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
            return [{
                "id": "skill:stub_tool",
                "name": "stub_tool",
                "skill_type": "local_function",
                "execution_config": {
                    "module": "aura.tools._stub_for_w2_29",
                    "function": "run",
                },
                "definition": {},
            }]

        async def merge(self, thing: str, data: dict) -> Any:  # noqa: ARG002
            return []

    executor.db = _FakeDB()

    # Register the supplied stub tool module so the executor's import finds it.
    sys.modules["aura.tools._stub_for_w2_29"] = tool_module

    # Self-healing is not used here.
    executor._llm_layers = None
    return executor


def _stub_tool_module(invoked: list[Dict[str, Any]]) -> types.ModuleType:
    """Create a throwaway tool module whose ``run`` records its call."""
    mod = types.ModuleType("aura.tools._stub_for_w2_29")

    async def run(arguments: Dict[str, Any]) -> str:
        invoked.append(dict(arguments))
        return "ok:" + str(arguments.get("x"))

    mod.run = run
    return mod


@pytest.fixture(autouse=True)
def _reset_registry_for_w2_29():
    """Reset the tool registry before and after each test in this module."""
    reset_tool_registry()
    yield
    reset_tool_registry()


@pytest.mark.asyncio
async def test_owner_call_records_stats_in_registry():
    """An owner call to a registered tool increments calls, successes and
    records a latency in the registry."""
    # Register a fake tool in the registry.
    registry = get_tool_registry()
    registry.register(ToolRecord(
        name="stub_tool",
        description="stub",
        input_schema={"type": "object", "properties": {}},
        transport="builtin",
        risk="read",
    ))

    invoked: list[Dict[str, Any]] = []
    executor = _make_executor_with_registry(_stub_tool_module(invoked))

    result = await executor.execute_tool_call(
        {"tool": "stub_tool", "arguments": {"x": 1}},
        requester_role="owner",
    )

    assert result["success"] is True
    assert len(invoked) == 1

    record = registry.get("stub_tool")
    assert record is not None
    assert record.stats.calls == 1
    assert record.stats.successes == 1
    assert len(record.stats.latencies_ms) == 1
    assert record.stats.latencies_ms[0] > 0


@pytest.mark.asyncio
async def test_guest_call_does_not_record_stats():
    """A guest call is refused before the tool runs and must not be recorded
    in the registry."""
    registry = get_tool_registry()
    registry.register(ToolRecord(
        name="stub_tool",
        description="stub",
        input_schema={"type": "object", "properties": {}},
        transport="builtin",
        risk="read",
    ))

    invoked: list[Dict[str, Any]] = []
    executor = _make_executor_with_registry(_stub_tool_module(invoked))

    result = await executor.execute_tool_call(
        {"tool": "stub_tool", "arguments": {"x": 1}},
        requester_role="guest",
    )

    assert result["success"] is False
    assert invoked == []

    record = registry.get("stub_tool")
    assert record is not None
    assert record.stats.calls == 0


@pytest.mark.asyncio
async def test_mark_mcp_skill_offline_updates_health():
    """_mark_mcp_skill_offline with tool_name updates the registry health to
    offline, sets the error, and stamps last_check."""
    from aura.clock import Clock, FakeClock, set_clock
    from aura.executor.tool_executor import ToolExecutor

    clock = FakeClock()
    set_clock(clock)
    try:
        registry = get_tool_registry()
        registry.register(ToolRecord(
            name="t",
            description="test",
            input_schema={"type": "object", "properties": {}},
            transport="builtin",
            risk="read",
        ))

        executor = ToolExecutor.__new__(ToolExecutor)
        executor.logger = __import__("logging").getLogger("aura.executor.test")
        executor._llm_layers = None
        # merge must be async because the method awaits it
        class _FakeDB:
            @staticmethod
            async def merge(thing: str, data: dict) -> None:
                pass
        executor.db = _FakeDB()

        clock.advance(60)
        await executor._mark_mcp_skill_offline(
            skill_id="skill:x",
            execution_config={},
            error="e",
            tool_name="t",
        )

        health = registry.get("t").health
        assert health.status == "offline"
        assert health.error == "e"
        assert health.last_check == clock.now()
    finally:
        set_clock(Clock())


# ---------------------------------------------------------------------------
# W2-30: Tool selection by similarity and recent success
# ---------------------------------------------------------------------------


class DeterministicEmbedder:
    """Fake embedder that returns deterministic vectors for testing.

    Each unique input text gets a unique but deterministic vector.
    """

    def __init__(self):
        self._cache: dict[str, list[float]] = {}
        self.call_count = 0

    async def embed(self, text: str) -> list[float] | None:
        self.call_count += 1
        if not text or not text.strip():
            return None
        if text not in self._cache:
            # Generate a deterministic vector based on the hash of the text
            import hashlib

            h = hashlib.md5(text.encode()).hexdigest()
            # Convert to 768-dimensional vector (normalized)
            vec = []
            for i in range(0, len(h), 2):
                byte_val = int(h[i : i + 2], 16)
                vec.append((byte_val - 127.5) / 127.5)
            # Pad or truncate to 768
            while len(vec) < 768:
                vec.extend(vec[: min(len(vec), 768 - len(vec))])
            vec = vec[:768]
            # Normalize
            norm = math.sqrt(sum(x * x for x in vec))
            if norm > 0:
                vec = [x / norm for x in vec]
            self._cache[text] = vec
        return self._cache[text]


def _make_tool_record(name: str, description: str, calls: int = 0, successes: int = 0) -> ToolRecord:
    """Create a tool record with optional call stats."""
    record = ToolRecord(
        name=name,
        description=description,
        input_schema={"type": "object", "properties": {}},
        transport="builtin",
        risk="read",
        health=ToolHealth(status="online"),
    )
    record.stats.calls = calls
    record.stats.successes = successes
    return record


@pytest.mark.asyncio
async def test_select_tools_returns_top_k_by_similarity():
    """20 registered tools, request similar to tool t07: 8 tools returned and t07 is first."""
    registry = ToolRegistry()
    embedder = DeterministicEmbedder()

    # Register 20 tools: t00 through t19
    for i in range(20):
        desc = f"tool number {i:02d} does something specific"
        registry.register(_make_tool_record(f"t{i:02d}", desc))

    # Make t07's description_embedding identical to the request embedding
    # by pre-setting it before select_tools is called
    request = "find the user's lost file in the home directory"
    request_embedding = await embedder.embed(request)
    registry.get("t07").description_embedding = request_embedding

    selected = await registry.select_tools(request, requester_role="owner", embed=embedder.embed)

    # Should return top 8
    assert len(selected) == 8
    # t07 should be first (most similar - identical embedding)
    assert selected[0].name == "t07"


@pytest.mark.asyncio
async def test_select_tools_success_weight_breaks_ties():
    """Two tools with equal similarity, one with 4/4 success, one with 0/4: successful ranks higher."""
    registry = ToolRegistry()
    embedder = DeterministicEmbedder()

    # Two tools with identical descriptions (same similarity to request)
    registry.register(_make_tool_record("tool_a", "search for files in the project", calls=4, successes=4))
    registry.register(_make_tool_record("tool_b", "search for files in the project", calls=4, successes=0))

    request = "search for files in the project"
    selected = await registry.select_tools(request, requester_role="owner", embed=embedder.embed)

    # Both should be returned (only 2 tools, threshold is 15)
    assert len(selected) == 2
    # tool_a (successful) should rank higher than tool_b
    assert selected[0].name == "tool_a"
    assert selected[1].name == "tool_b"


@pytest.mark.asyncio
async def test_select_tools_below_threshold_returns_all_no_embed():
    """10 tools (below threshold 15): all 10 returned, embed never called."""
    registry = ToolRegistry()
    embedder = DeterministicEmbedder()

    for i in range(10):
        registry.register(_make_tool_record(f"t{i}", f"tool {i} description"))

    selected = await registry.select_tools("any request", requester_role="owner", embed=embedder.embed)

    assert len(selected) == 10
    assert embedder.call_count == 0


@pytest.mark.asyncio
async def test_select_tools_guest_returns_empty():
    """requester_role='guest' with 20 tools: [] returned."""
    registry = ToolRegistry()

    for i in range(20):
        registry.register(_make_tool_record(f"t{i}", f"tool {i} description"))

    selected = await registry.select_tools("any request", requester_role="guest")

    assert selected == []


@pytest.mark.asyncio
async def test_select_tools_offline_tool_never_returned():
    """An offline tool is never returned regardless of similarity."""
    registry = ToolRegistry()
    embedder = DeterministicEmbedder()

    # Online tool
    registry.register(_make_tool_record("online_tool", "find the user's lost file"))
    # Offline tool with same description
    offline_tool = _make_tool_record("offline_tool", "find the user's lost file")
    offline_tool.health.status = "offline"
    registry.register(offline_tool)

    request = "find the user's lost file"
    selected = await registry.select_tools(request, requester_role="owner", embed=embedder.embed)

    assert len(selected) == 1
    assert selected[0].name == "online_tool"


@pytest.mark.asyncio
async def test_select_tools_embedding_failure_falls_back_to_name_order(caplog):
    """If embedding fails, return first top_k by name and log warning."""
    registry = ToolRegistry()

    for i in range(20):
        registry.register(_make_tool_record(f"t{i:02d}", f"tool {i} description"))

    # Embedder that raises
    async def failing_embed(text: str) -> None:
        raise RuntimeError("embedding service down")

    # Capture logs with caplog
    with caplog.at_level(logging.WARNING):
        selected = await registry.select_tools("any request", requester_role="owner", embed=failing_embed)

    # Should return first 8 by name (t00 through t07)
    assert len(selected) == 8
    assert [r.name for r in selected] == [f"t{i:02d}" for i in range(8)]
    # Check warning was logged
    assert any("Tool selection: request embedding failed" in record.message for record in caplog.records)
