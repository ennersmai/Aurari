"""G4-04 (T16, T17): rows of the agent-loop parity table not covered elsewhere,
and the built-in tools that stay (agency PRD 4.1).

Rows already covered by G3/G4 tests are listed in docs/metrics/g4_parity.md.
"""

import base64
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

from aura.config import settings
from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import (
    get_tool_registry,
    load_builtin_tools,
    reset_tool_registry,
    sanitize_schema,
)
from aura.tools import filesystem, terminal

KEPT_TOOLS = [
    "web_search", "generate_chart",
    "read_file", "list_directory", "directory_tree", "search_files", "get_file_info",
    "write_file", "edit_file", "create_directory", "delete_file",
    "terminal", "execute_code",
]


class _NoSkillsDB:
    async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
        return []

    async def merge(self, thing: str, data: dict) -> Any:  # noqa: ARG002
        return []


@pytest.fixture
def executor():
    reset_tool_registry()
    for record in load_builtin_tools():
        get_tool_registry().register(record)
    ex = ToolExecutor.__new__(ToolExecutor)
    ex.logger = logging.getLogger("aura.executor.test")
    ex.db = _NoSkillsDB()
    ex._llm_layers = None
    try:
        yield ex
    finally:
        reset_tool_registry()


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """The filesystem tools only reach ALLOWED_PATHS; point them at tmp_path."""
    monkeypatch.setattr(filesystem, "ALLOWED_PATHS", [tmp_path.resolve()])
    return tmp_path


async def _call(ex, tool: str, **arguments):
    return await ex.execute_tool_call(
        {"tool": tool, "arguments": arguments}, requester_role="owner"
    )


def _text(result: dict) -> str:
    assert result["success"] is True, result
    # Tools that return a dict (write_file, terminal) come back as that dict.
    return str(result["result"]) if "result" in result else str(result)


def _walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_keys(v)


# --- Registration and schema (every kept tool) ---------------------------

@pytest.mark.parametrize("name", KEPT_TOOLS)
def test_kept_tool_registered_with_no_approval_argument(name):
    records = {r.name: r for r in load_builtin_tools()}
    assert name in records, f"{name} is missing from the built-in registry"
    record = records[name]
    assert record.transport == "builtin"
    schema = record.input_schema
    assert schema.get("type") == "object"
    # The registry's own filter is a no-op on what it registered.
    assert sanitize_schema(schema) == schema
    properties = schema.get("properties", {})
    assert "force_execute" not in properties
    assert not [k for k in properties if k.startswith("_")]
    assert not [r for r in schema.get("required", []) if r == "force_execute" or r.startswith("_")]


def test_sanitize_schema_would_remove_approval_fields():
    """Guards the check above: the filter does strip them when present."""
    dirty = {"type": "object", "properties": {"a": {"type": "string"}, "force_execute": {}, "_x": {}},
             "required": ["a", "force_execute"]}
    clean = sanitize_schema(dirty)
    assert set(clean["properties"]) == {"a"}
    assert clean["required"] == ["a"]


def test_web_search_schema_has_a_query():
    record = {r.name: r for r in load_builtin_tools()}["web_search"]
    assert "query" in record.input_schema["properties"]


# --- Real calls through the executor, owner only, in tmp_path ------------

@pytest.mark.asyncio
async def test_filesystem_tools_round_trip(executor, sandbox):
    target = sandbox / "notes" / "a.txt"
    _text(await _call(executor, "create_directory", path=str(target.parent)))
    assert target.parent.is_dir()

    _text(await _call(executor, "write_file", path=str(target), content="hello world"))
    assert target.read_text(encoding="utf-8") == "hello world"

    assert "hello world" in _text(await _call(executor, "read_file", path=str(target)))
    assert "a.txt" in _text(await _call(executor, "list_directory", path=str(target.parent)))
    assert "a.txt" in _text(await _call(executor, "directory_tree", path=str(sandbox)))
    assert "a.txt" in _text(await _call(executor, "search_files", path=str(sandbox), pattern="a.txt"))
    assert "a.txt" in _text(await _call(executor, "get_file_info", path=str(target)))

    res = await _call(executor, "edit_file", path=str(target), old_string="world", new_string="there")
    assert res["success"] is True, res
    assert target.read_text(encoding="utf-8") == "hello there"

    res = await _call(executor, "delete_file", path=str(target))
    assert res["success"] is True, res
    assert not target.exists()


@pytest.mark.asyncio
async def test_filesystem_refuses_a_path_outside_the_allowed_root(executor, sandbox, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside") / "x.txt"
    res = await _call(executor, "write_file", path=str(outside), content="no")
    assert not outside.exists()
    assert "Access denied" in str(res), res


@pytest.mark.asyncio
async def test_non_owner_cannot_call_a_built_in_tool(executor, sandbox):
    target = sandbox / "g.txt"
    res = await executor.execute_tool_call(
        {"tool": "write_file", "arguments": {"path": str(target), "content": "x"}},
        requester_role="trusted",
    )
    assert res["success"] is False
    assert not target.exists()


@pytest.mark.asyncio
async def test_terminal_safe_command_runs_and_unsafe_waits(executor, sandbox, monkeypatch):
    res = await _call(executor, "terminal", command="echo g4parity", cwd=str(sandbox))
    assert res["success"] is True, res
    assert "g4parity" in str(res)

    marker = sandbox / "ran.txt"
    res = await _call(
        executor, "terminal",
        command=f'python -c "open(r\'{marker}\', \'w\').write(\'x\')"',
        cwd=str(sandbox), force_execute=True,
    )
    assert res.get("status") == "WAITING_APPROVAL", res
    assert not marker.exists(), "an unsafe command must not run on a forged approval"
    assert "force_execute" not in terminal.TOOL_DEFINITION["parameters"]["properties"]


@pytest.mark.asyncio
async def test_execute_code_runs_python(executor, sandbox, monkeypatch):
    monkeypatch.setattr(settings, "code_execution_enabled", True)
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
    res = await _call(executor, "execute_code", code="print(1)", language="python", working_dir=str(sandbox))
    payload = json.loads(_text(res))
    assert payload["success"] is True, payload
    assert payload["stdout"] == "1"


@pytest.mark.asyncio
async def test_generate_chart_is_local_and_returns_a_config(executor):
    out = _text(await _call(
        executor, "generate_chart", chart_type="bar", labels=["a", "b"],
        datasets=[{"label": "n", "data": [1, 2]}],
    ))
    match = re.fullmatch(r"\[CHARTJS:(.+)\]", out)
    assert match, out
    config = json.loads(base64.b64decode(match.group(1)))
    assert config["type"] == "bar"
    assert config["data"]["labels"] == ["a", "b"]


# --- Per-session allowlist, namespace, overlay (SessionContext) ----------

def test_session_context_carries_allowlist_namespace_and_overlay():
    from aura.models.session import IdentityOverlay, Session, SessionContext

    session = Session.new_scoped(
        "scoped",
        identity_overlay=IdentityOverlay(core_values={"precision": 0.9}),
        tool_allowlist=["read_file"],
        tool_denylist=["terminal"],
    )
    ctx = SessionContext.from_session(session)
    assert ctx.memory_namespace == session.memory_namespace != "global"
    assert ctx.identity_overlay.core_values == {"precision": 0.9}
    assert ctx.is_tool_allowed("read_file") == (True, "")
    allowed, reason = ctx.is_tool_allowed("write_file")
    assert allowed is False and "allowlist" in reason
    allowed, reason = ctx.is_tool_allowed("terminal")
    assert allowed is False and "denylist" in reason
    assert SessionContext.main().is_tool_allowed("write_file") == (True, "")
