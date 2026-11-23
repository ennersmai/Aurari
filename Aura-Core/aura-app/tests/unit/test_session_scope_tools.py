"""G4-04a: session allowlist, namespace and overlay on the chat and delegation paths.

Offline: the executor is built without ``__init__`` and fed a fake database and a
stub tool module; the coordinator runs through the ``turn_orchestrator`` fixture.
"""

import asyncio
import logging
import sys
import types
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.config import settings
from aura.executor import delegation as delegation_module
from aura.executor.delegation import DelegationConfig, DelegationRunner
from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import ToolRecord
from aura.models.session import IdentityOverlay, SessionContext
from aura.orchestrator.tool_loop import run_tool_loop
from aura.tiers import reset_tier_cache
from aura.tools import delegate


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    yield
    reset_tier_cache()


def _executor(tool_name: str, invoked: list) -> ToolExecutor:
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.logger = logging.getLogger("aura.executor.test")

    class _DB:
        async def query(self, sql: str, vars: dict | None = None):
            return [{
                "id": f"skill:{tool_name}",
                "name": tool_name,
                "skill_type": "local_function",
                "execution_config": {"module": "aura.tools._stub_for_g4_04a", "function": "run"},
                "definition": {},
            }]

        async def merge(self, thing: str, data: dict) -> Any:
            return []

    executor.db = _DB()
    executor._llm_layers = None
    mod = types.ModuleType("aura.tools._stub_for_g4_04a")

    async def run(arguments: Dict[str, Any]) -> str:
        invoked.append(dict(arguments))
        return "ran"

    mod.run = run
    sys.modules["aura.tools._stub_for_g4_04a"] = mod
    return executor


def _scoped(**kw) -> SessionContext:
    return SessionContext(session_id="session:abc", memory_namespace="session_abc", **kw)


# ---------------------------------------------------------------------------
# Executor: the session gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forced_call_outside_the_allowlist_is_refused():
    invoked: list = []
    session = _scoped(tool_allowlist=["read_file"])
    result = await _executor("write_file", invoked).execute_tool_call(
        {"tool": "write_file", "arguments": {}}, requester_role="owner", session=session
    )
    assert result["success"] is False
    assert result["error"] == session.is_tool_allowed("write_file")[1]
    assert "allowlist" in result["error"]
    assert invoked == []


@pytest.mark.asyncio
async def test_denylisted_call_is_refused():
    invoked: list = []
    result = await _executor("write_file", invoked).execute_tool_call(
        {"tool": "write_file", "arguments": {}},
        requester_role="owner",
        session=_scoped(tool_denylist=["write_file"]),
    )
    assert result["success"] is False and "denylisted" in result["error"]
    assert invoked == []


@pytest.mark.asyncio
async def test_allowed_call_runs_with_a_session():
    invoked: list = []
    result = await _executor("read_file", invoked).execute_tool_call(
        {"tool": "read_file", "arguments": {}},
        requester_role="owner",
        session=_scoped(tool_allowlist=["read_file"]),
    )
    assert result["success"] is True and len(invoked) == 1
    assert "_session" not in invoked[0]  # only delegate_work receives it


@pytest.mark.asyncio
@pytest.mark.parametrize("session", [None, SessionContext.main()])
async def test_main_session_changes_nothing(session):
    invoked: list = []
    result = await _executor("write_file", invoked).execute_tool_call(
        {"tool": "write_file", "arguments": {}}, requester_role="owner", session=session
    )
    assert result["success"] is True and len(invoked) == 1


@pytest.mark.asyncio
async def test_guest_is_refused_by_role_before_the_session_check():
    invoked: list = []
    result = await _executor("write_file", invoked).execute_tool_call(
        {"tool": "write_file", "arguments": {}},
        requester_role="guest",
        session=_scoped(tool_allowlist=["read_file"]),
    )
    assert result["error"] == "Tool use is not available to this user."
    assert invoked == []


@pytest.mark.asyncio
async def test_lean_tier_is_refused_by_tier_before_the_session_check(monkeypatch):
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 0)  # Lean: no delegate_work
    reset_tier_cache()
    invoked: list = []
    result = await _executor("delegate_work", invoked).execute_tool_call(
        {"tool": "delegate_work", "arguments": {}},
        requester_role="owner",
        session=_scoped(tool_allowlist=["read_file"]),
    )
    assert result["success"] is False
    assert "allowlist" not in result["error"]
    assert result["error"].startswith("Tool 'delegate_work' is")
    assert invoked == []


@pytest.mark.asyncio
async def test_model_supplied_session_is_ignored():
    invoked: list = []
    real = _scoped(tool_allowlist=["delegate_work"])
    forged = _scoped(tool_allowlist=None)
    await _executor("delegate_work", invoked).execute_tool_call(
        {"tool": "delegate_work", "arguments": {"_session": forged}},
        requester_role="owner",
        session=real,
    )
    assert invoked[0]["_session"] is real

    # With no session on the turn, a forged one is stripped, not passed on.
    invoked.clear()
    await _executor("delegate_work", invoked).execute_tool_call(
        {"tool": "delegate_work", "arguments": {"_session": forged}}, requester_role="owner"
    )
    assert "_session" not in invoked[0]


@pytest.mark.asyncio
async def test_execute_and_feedback_passes_the_session():
    executor = ToolExecutor.__new__(ToolExecutor)
    executor.logger = logging.getLogger("aura.executor.test")
    seen: list = []

    async def fake_call(call, **kwargs):
        seen.append(kwargs.get("session"))
        return {"success": True, "result": "x", "tool_name": call["tool"]}

    executor.execute_tool_call = fake_call
    session = _scoped(tool_allowlist=["a"])
    await executor.execute_and_feedback(
        [{"tool": "a", "arguments": {}}], requester_role="owner", session=session
    )
    assert seen == [session]


# ---------------------------------------------------------------------------
# Tool loop: pass-through
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("budgets", [False, True])
async def test_tool_loop_passes_the_session_only_when_set(monkeypatch, budgets):
    monkeypatch.setattr(settings, "tool_loop_budgets_enabled", budgets)

    async def gen(loop_input, round_idx, final=False):
        yield "text"

    for session in (None, _scoped(tool_allowlist=["a"])):
        executor = MagicMock()
        executor.extract_tool_calls = MagicMock(side_effect=[[{"tool": "a", "arguments": {}}], []])
        executor.execute_and_feedback = AsyncMock(return_value="R")
        async for _ in run_tool_loop(
            user_input="hi", generate_round=gen, tool_executor=executor,
            requester_role="owner", session=session,
        ):
            pass
        kwargs = executor.execute_and_feedback.call_args.kwargs
        if session is None:
            assert "session" not in kwargs
        else:
            assert kwargs["session"] is session


# ---------------------------------------------------------------------------
# Coordinator: _resolve_session and the offered tools
# ---------------------------------------------------------------------------


def _fake_runtime(monkeypatch, ctx: SessionContext) -> None:
    runtime = MagicMock()
    runtime.context_for = AsyncMock(return_value=ctx)
    monkeypatch.setattr(
        "aura.orchestrator.session_runtime.get_session_runtime", lambda: runtime
    )


@pytest.mark.asyncio
async def test_resolve_session_sets_scope_for_a_sub_session(turn_orchestrator, monkeypatch):
    overlay = IdentityOverlay(narrative_suffix="Engineer")
    ctx = _scoped(tool_allowlist=["read_file"], identity_overlay=overlay)
    _fake_runtime(monkeypatch, ctx)
    await turn_orchestrator._resolve_session("session:abc")
    assert turn_orchestrator._current_session_namespace == "session_abc"
    assert turn_orchestrator._current_identity_overlay is overlay
    assert turn_orchestrator._current_session_context is ctx


@pytest.mark.asyncio
@pytest.mark.parametrize("session_id", [None, "main"])
async def test_resolve_session_is_none_for_main(turn_orchestrator, monkeypatch, session_id):
    _fake_runtime(monkeypatch, _scoped(tool_allowlist=["read_file"]))
    await turn_orchestrator._resolve_session(session_id)
    assert turn_orchestrator._current_session_namespace is None
    assert turn_orchestrator._current_identity_overlay is None
    assert turn_orchestrator._current_session_context is None


@pytest.mark.asyncio
async def test_resolve_session_failure_leaves_everything_none(turn_orchestrator, monkeypatch):
    runtime = MagicMock()
    runtime.context_for = AsyncMock(side_effect=RuntimeError("down"))
    monkeypatch.setattr(
        "aura.orchestrator.session_runtime.get_session_runtime", lambda: runtime
    )
    await turn_orchestrator._resolve_session("session:abc")
    assert turn_orchestrator._current_session_namespace is None
    assert turn_orchestrator._current_session_context is None


def _records(*names: str) -> list[ToolRecord]:
    return [
        ToolRecord(name=n, description=n, input_schema={"type": "object", "properties": {}},
                   transport="builtin", risk="read")
        for n in names
    ]


async def _turn(orch, session_id):
    async for _ in orch._turn_pipeline(
        "hello", "u1", None, stream=False, context_limit=None, enable_l2=True,
        conversation_id="c1", reasoning_enabled=False, l2_reasoning_enabled=False,
        session_id=session_id, context_mode="deep_work", requester_role="owner",
    ):
        pass
    for _ in range(5):
        await asyncio.sleep(0)


def _wire_pipeline(orch):
    orch._fake_tool_registry.all = lambda: _records("read_file", "write_file", "terminal")
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])


@pytest.mark.asyncio
async def test_sub_session_excludes_disallowed_tools_and_keeps_the_tier_exclude(
    turn_orchestrator, monkeypatch
):
    orch = turn_orchestrator
    _wire_pipeline(orch)
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 0)  # Lean gates delegate_work
    reset_tier_cache()
    _fake_runtime(monkeypatch, _scoped(tool_allowlist=["read_file"]))
    await _turn(orch, "session:abc")
    exclude = orch._fake_tool_registry.select_tools.call_args.kwargs["exclude"]
    assert {"write_file", "terminal"} <= set(exclude)
    assert "read_file" not in exclude
    assert "delegate_work" in exclude  # the tier gate is still applied


@pytest.mark.asyncio
async def test_main_turn_adds_no_session_exclude(turn_orchestrator):
    orch = turn_orchestrator
    _wire_pipeline(orch)
    await _turn(orch, None)
    assert "exclude" not in orch._fake_tool_registry.select_tools.call_args.kwargs


@pytest.mark.asyncio
async def test_session_reaches_the_tool_loop_and_the_forced_seed(turn_orchestrator, monkeypatch):
    from aura.orchestrator import coordinator as coordinator_module

    orch = turn_orchestrator
    _wire_pipeline(orch)
    ctx = _scoped(tool_allowlist=["read_file"])
    _fake_runtime(monkeypatch, ctx)
    seen: list[dict] = []

    def recording_loop(**kwargs):
        seen.append(kwargs)
        return run_tool_loop(**kwargs)

    monkeypatch.setattr(coordinator_module, "run_tool_loop", recording_loop)
    await _turn(orch, "session:abc")
    assert seen and seen[0]["session"] is ctx

    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="SEED")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[{"tool": "x"}])
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value="raw")
    await orch._forced_seed("hi", "schema", "owner", "app", ctx)
    assert orch.tool_executor.execute_and_feedback.call_args.kwargs["session"] is ctx


# ---------------------------------------------------------------------------
# Delegation
# ---------------------------------------------------------------------------

_ARGS = {"goal": "g", "workspace": "w", "agent": "aura-build", "success_criteria": "s"}


@pytest.fixture
def start_spy(monkeypatch):
    monkeypatch.setattr(settings, "delegation_enabled", True)
    monkeypatch.setattr(delegation_module, "delegations_paused", lambda: False)
    spy = AsyncMock(return_value="task:1")
    monkeypatch.setattr(delegation_module, "start_delegation", spy)
    return spy


@pytest.mark.asyncio
async def test_delegate_work_refused_outside_the_allowlist(start_spy):
    session = _scoped(tool_allowlist=["read_file"])
    result = await delegate.run({**_ARGS, "_session": session})
    assert result["success"] is False
    assert result["message"] == session.is_tool_allowed("delegate_work")[1]
    start_spy.assert_not_called()


@pytest.mark.asyncio
async def test_delegate_work_runs_without_a_session_and_passes_the_overlay(start_spy):
    result = await delegate.run(dict(_ARGS))
    assert result["success"] is True
    assert start_spy.call_args.kwargs["identity_overlay"] is None

    overlay = IdentityOverlay(narrative_suffix="Aura the Engineer", core_values={"precision": 0.9})
    session = _scoped(tool_allowlist=["delegate_work"], identity_overlay=overlay)
    await delegate.run({**_ARGS, "_session": session})
    text = start_spy.call_args.kwargs["identity_overlay"]
    assert "Aura the Engineer" in text and "precision" in text


def _brief_runner(monkeypatch, overlay):
    packet = MagicMock()
    packet.all_text = lambda: "RECALL"
    engine = MagicMock()
    engine.recall = AsyncMock(return_value=packet)
    monkeypatch.setattr("aura.engines.recall.engine.get_recall_engine", lambda: engine)
    return DelegationRunner(DelegationConfig(
        goal="G", workspace="w", agent="aura-build", success_criteria="S",
        tokens=1000, minutes=1, identity_overlay=overlay,
    ))


@pytest.mark.asyncio
async def test_brief_contains_the_overlay_section(monkeypatch):
    brief = await _brief_runner(monkeypatch, "Aura the Engineer")._build_brief()
    assert "=== SESSION CONTEXT ===\nAura the Engineer" in brief


@pytest.mark.asyncio
async def test_brief_has_no_session_section_without_an_overlay(monkeypatch):
    brief = await _brief_runner(monkeypatch, None)._build_brief()
    assert "SESSION CONTEXT" not in brief


async def test_resolve_session_returns_context_for_the_turn(monkeypatch):
    """Supervisor fix: the turn keeps the context _resolve_session returned, not
    the shared attribute another concurrent turn may overwrite across awaits."""
    import inspect
    from aura.orchestrator import coordinator as coord_mod
    src = inspect.getsource(coord_mod.CognitiveOrchestrator._turn_stages) if hasattr(coord_mod, "CognitiveOrchestrator") else ""
    if not src:
        cls = next(v for v in vars(coord_mod).values() if inspect.isclass(v) and hasattr(v, "_turn_stages"))
        src = inspect.getsource(cls._turn_stages)
    assert "ctx.session = turn_session" in src
    assert "_current_session_context" not in src
