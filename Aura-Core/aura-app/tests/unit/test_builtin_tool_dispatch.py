"""Builtin tools run without a skill row, and the turn's venue reaches them (W4-05).

Builtins come from ``BUILTIN_MODULES``; the registry offers them to the model,
so the executor must be able to run them even when register_local_tools.surql
has no row for them. The venue passed to ``execute_and_feedback`` must arrive
in the reserved ``_venue`` argument, and a non-owner arriving with the owner's
``app`` venue is refused by the recall tools.
"""

import logging
import sys
import types
from typing import Any

import pytest

from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import (
    ToolHealth,
    ToolRecord,
    get_tool_registry,
    reset_tool_registry,
)
from aura.tools.recall_tools import _caller_venue


class _NoSkillsDB:
    async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
        return []

    async def merge(self, thing: str, data: dict) -> Any:  # noqa: ARG002
        return []


@pytest.fixture
def executor_with_builtin():
    seen: list[dict] = []

    async def run(arguments: dict) -> str:
        seen.append(dict(arguments))
        return "ran"

    module = types.ModuleType("aura.tools._builtin_stub_w4_05")
    module.TOOLS = {"stub_builtin": {"definition": {"name": "stub_builtin"}, "run": run}}
    sys.modules["aura.tools._builtin_stub_w4_05"] = module

    reset_tool_registry()
    get_tool_registry().register(
        ToolRecord(
            name="stub_builtin",
            description="",
            input_schema={"type": "object", "properties": {}},
            transport="builtin",
            risk="read",
            source="_builtin_stub_w4_05",
            health=ToolHealth(status="online"),
        )
    )

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.logger = logging.getLogger("aura.executor.test")
    executor.db = _NoSkillsDB()
    executor._llm_layers = None
    try:
        yield executor, seen
    finally:
        reset_tool_registry()
        sys.modules.pop("aura.tools._builtin_stub_w4_05", None)


@pytest.mark.asyncio
async def test_builtin_without_skill_row_runs_with_the_turns_venue(executor_with_builtin):
    executor, seen = executor_with_builtin
    await executor.execute_and_feedback(
        [{"tool": "stub_builtin", "arguments": {"_venue": "app"}}],
        requester_role="owner",
        venue="guild:99/channel:7",
    )
    assert len(seen) == 1
    assert seen[0]["_venue"] == "guild:99/channel:7"  # not forgeable by the model
    assert seen[0]["_requester_role"] == "owner"


def test_unknown_tool_still_reports_not_found():
    reset_tool_registry()
    assert ToolExecutor._builtin_skill("no_such_tool") is None


def test_recall_tools_refuse_a_non_owner_with_the_owner_venue():
    with pytest.raises(PermissionError):
        _caller_venue({"_venue": "app", "_requester_role": "trusted"})
    assert _caller_venue({"_venue": "app", "_requester_role": "owner"}) == "app"
    assert (
        _caller_venue({"_venue": "guild:9/channel:1", "_requester_role": "trusted"})
        == "guild:9/channel:1"
    )
