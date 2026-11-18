"""W1-01: requester role on every tool call.

Agency PRD S1, section 5.3. Before W1-01, ``ToolExecutor.execute_tool_call``
and ``ToolExecutor.execute_and_feedback`` took no role argument, so any
caller (including Discord guests) could trigger tool execution. W1-01 adds
a required keyword argument ``requester_role: Literal["owner", "trusted",
"guest"]`` and refuses every role other than ``owner`` before any tool is
run.

The tests build a ``ToolExecutor`` without running ``__init__`` (which would
open a real database connection) and wire a fake database plus a fake tool
module. A guest call must return the refusal with ``success: False`` and
must never invoke the tool function. An owner call must still execute the
tool.
"""

import asyncio
import importlib
import sys
import types
from typing import Any, Dict

import pytest

from aura.executor.tool_executor import ToolExecutor


def _make_executor(tool_module: types.ModuleType) -> ToolExecutor:
    """Build a ``ToolExecutor`` without running ``__init__`` and wire a fake
    database plus a stub tool module, so execute_tool_call can route a
    ``local_function`` tool to the supplied module."""
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
                    "module": "aura.tools._stub_for_w1_01",
                    "function": "run",
                },
                "definition": {},
            }]

        async def merge(self, thing: str, data: dict) -> Any:  # noqa: ARG002
            return []

    executor.db = _FakeDB()

    # Register the supplied stub tool module so the executor's import finds it.
    sys.modules["aura.tools._stub_for_w1_01"] = tool_module

    # Self-healing is not used here.
    executor._llm_layers = None
    return executor


def _stub_tool_module(invoked: list[Dict[str, Any]]) -> types.ModuleType:
    """Create a throwaway tool module whose ``run`` records its call."""
    mod = types.ModuleType("aura.tools._stub_for_w1_01")

    async def run(arguments: Dict[str, Any]) -> str:
        invoked.append(dict(arguments))
        return "ok:" + str(arguments.get("x"))

    mod.run = run
    return mod


@pytest.mark.asyncio
async def test_guest_call_is_refused_and_tool_never_invoked():
    """A guest requester_role must be refused with success=False and the
    configured message, and the tool function must never be called."""
    invoked: list[Dict[str, Any]] = []
    executor = _make_executor(_stub_tool_module(invoked))

    result = await executor.execute_tool_call(
        {"tool": "stub_tool", "arguments": {"x": 1}},
        requester_role="guest",
    )

    assert result["success"] is False
    assert result["error"] == "Tool use is not available to this user."
    assert result["tool_name"] == "stub_tool"
    # The tool function was never invoked.
    assert invoked == []


@pytest.mark.asyncio
async def test_trusted_call_is_also_refused():
    """Only owner may execute tools; ``trusted`` is refused too (the card
    lists the three roles but only owner is permitted)."""
    invoked: list[Dict[str, Any]] = []
    executor = _make_executor(_stub_tool_module(invoked))

    result = await executor.execute_tool_call(
        {"tool": "stub_tool", "arguments": {"x": 1}},
        requester_role="trusted",
    )

    assert result["success"] is False
    assert result["error"] == "Tool use is not available to this user."
    assert invoked == []


@pytest.mark.asyncio
async def test_owner_call_still_executes():
    """An owner requester_role must run the tool as before W1-01."""
    invoked: list[Dict[str, Any]] = []
    executor = _make_executor(_stub_tool_module(invoked))

    result = await executor.execute_tool_call(
        {"tool": "stub_tool", "arguments": {"x": 1}},
        requester_role="owner",
    )

    # The tool function was invoked exactly once with the supplied arguments.
    assert len(invoked) == 1
    assert invoked[0] == {"x": 1}
    # The executor wraps the tool's string result in a success dict.
    assert result["success"] is True
    assert "ok:1" in result["result"]


@pytest.mark.asyncio
async def test_guest_via_execute_and_feedback_is_refused():
    """execute_and_feedback forwards requester_role to execute_tool_call,
    so a guest batch is refused wholesale and no tool runs."""
    invoked: list[Dict[str, Any]] = []
    executor = _make_executor(_stub_tool_module(invoked))

    feedback = await executor.execute_and_feedback(
        [{"tool": "stub_tool", "arguments": {"x": 1}}],
        requester_role="guest",
    )

    assert invoked == []
    # The feedback string reports the failure (not success).
    assert "Tool use is not available to this user." in feedback
    assert "failed" in feedback.lower()


@pytest.mark.asyncio
async def test_owner_via_execute_and_feedback_executes():
    """An owner batch through execute_and_feedback runs the tool."""
    invoked: list[Dict[str, Any]] = []
    executor = _make_executor(_stub_tool_module(invoked))

    feedback = await executor.execute_and_feedback(
        [{"tool": "stub_tool", "arguments": {"x": 2}}],
        requester_role="owner",
    )

    assert len(invoked) == 1
    assert invoked[0] == {"x": 2}
    assert "succeeded" in feedback.lower()
