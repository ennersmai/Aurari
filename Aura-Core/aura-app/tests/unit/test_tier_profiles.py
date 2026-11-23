"""P2-03: tier profiles (Lean, Core, Titan) and where each knob is wired.

Phase 2 plan, section 3.1. Offline: the coordinator runs through the
``turn_orchestrator`` fixture, the registry and executor are real but fed
fakes, and the override file lives in ``tmp_path``.
"""

import asyncio
import json
import logging
import sys
import types
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from aura import tiers
from aura.config import settings
from aura.executor.tool_registry import (
    ToolRecord,
    ToolRegistry,
    reset_tool_registry,
)
from aura.orchestrator import coordinator as coordinator_module
from aura.orchestrator.tool_loop import run_tool_loop as real_run_tool_loop
from aura.tiers import (
    CORE,
    LEAN,
    TITAN,
    TierProfile,
    active_profile,
    l3_reasoning_allowed,
    reset_tier_cache,
    trim_history,
)

TIERS = [(0, LEAN), (1, CORE), (2, TITAN)]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    reset_tier_cache()
    reset_tool_registry()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "tier_overrides.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", 0)
    yield
    reset_tier_cache()
    reset_tool_registry()


def _stack(monkeypatch, index: int) -> None:
    monkeypatch.setattr(settings, "model_stack_index", index)


# ---------------------------------------------------------------------------
# Profiles and overrides
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("index,profile", TIERS)
def test_active_profile_follows_stack_index(monkeypatch, index, profile):
    _stack(monkeypatch, index)
    assert active_profile() == profile


def test_default_numbers_match_the_table():
    assert (LEAN.tools_offered_max, CORE.tools_offered_max, TITAN.tools_offered_max) == (3, 6, 10)
    assert (LEAN.turn_budget_seconds, CORE.turn_budget_seconds, TITAN.turn_budget_seconds) == (45, 120, 300)
    assert (LEAN.turn_budget_usd, CORE.turn_budget_usd, TITAN.turn_budget_usd) == (0.03, 0.20, 1.00)
    assert (LEAN.context_budget_tokens, CORE.context_budget_tokens, TITAN.context_budget_tokens) == (5000, 10000, 20000)
    assert (LEAN.history_floor_exchanges, CORE.history_floor_exchanges, TITAN.history_floor_exchanges) == (3, 4, 6)
    assert [p.allow_delegate for p in (LEAN, CORE, TITAN)] == [False, False, True]
    assert [p.allow_task_graph for p in (LEAN, CORE, TITAN)] == [False, False, True]
    assert TITAN.task_graph_max_nodes == 8 and TITAN.task_budget_usd == 2.0 and TITAN.task_budget_minutes == 120


def test_profile_rejects_out_of_range_and_unknown_knobs():
    with pytest.raises(ValidationError):
        TierProfile(tools_offered_max=0)
    with pytest.raises(ValidationError):
        TierProfile(turn_budget_usd=-1)
    with pytest.raises(ValidationError):
        TierProfile(not_a_knob=1)


def test_override_file_changes_a_knob(monkeypatch, tmp_path):
    (tmp_path / "tier_overrides.json").write_text(json.dumps({"2": {"tools_offered_max": 12}}))
    _stack(monkeypatch, 2)
    assert active_profile().tools_offered_max == 12
    assert active_profile().allow_delegate is True  # untouched knobs keep defaults
    _stack(monkeypatch, 0)
    assert active_profile() == LEAN


def test_override_file_is_cached_by_mtime(monkeypatch, tmp_path):
    path = tmp_path / "tier_overrides.json"
    path.write_text(json.dumps({"0": {"tools_offered_max": 4}}))
    assert active_profile().tools_offered_max == 4
    reads = []
    real_read = type(path).read_text
    monkeypatch.setattr(type(path), "read_text", lambda self, *a, **k: reads.append(1) or real_read(self, *a, **k))
    active_profile()
    active_profile()
    assert reads == []  # unchanged mtime: no re-read
    path.write_text(json.dumps({"0": {"tools_offered_max": 5}}))
    import os
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 5_000_000_000))
    assert active_profile().tools_offered_max == 5


def test_corrupt_file_gives_defaults_and_one_warning(caplog, tmp_path):
    (tmp_path / "tier_overrides.json").write_text("{not json")
    with caplog.at_level(logging.WARNING, logger="aura.tiers"):
        for _ in range(3):
            assert active_profile() == LEAN
    assert len([r for r in caplog.records if r.name == "aura.tiers"]) == 1


@pytest.mark.parametrize(
    "content",
    [
        {"0": {"tools_offered_max": 0}},
        {"0": {"turn_budget_usd": -5}},
        {"1": {"mystery": 1}},
        {"7": {}},
        [1, 2],
    ],
)
def test_invalid_values_give_defaults_and_one_warning(caplog, tmp_path, content):
    (tmp_path / "tier_overrides.json").write_text(json.dumps(content))
    with caplog.at_level(logging.WARNING, logger="aura.tiers"):
        for _ in range(3):
            assert active_profile() == LEAN
    assert len([r for r in caplog.records if r.name == "aura.tiers"]) == 1


def test_missing_file_is_defaults_without_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="aura.tiers"):
        assert active_profile() == LEAN
    assert caplog.records == []


# ---------------------------------------------------------------------------
# L3 reasoning decision
# ---------------------------------------------------------------------------


def test_l3_reasoning_is_never_without_a_route_or_stakes():
    for profile in (LEAN, CORE, TITAN):
        assert l3_reasoning_allowed(profile, None, None) is False
        assert l3_reasoning_allowed(profile, None, 0.99) is (profile is TITAN)


def test_l3_reasoning_decision_with_real_inputs():
    assert l3_reasoning_allowed(LEAN, "think", 0.99) is False
    assert l3_reasoning_allowed(CORE, "think", None) is True
    assert l3_reasoning_allowed(CORE, "chat", 0.99) is False
    assert l3_reasoning_allowed(TITAN, "chat", 0.7) is True
    assert l3_reasoning_allowed(TITAN, "chat", 0.69) is False


# ---------------------------------------------------------------------------
# trim_history
# ---------------------------------------------------------------------------


def _msgs(n: int, chars: int) -> list[dict[str, str]]:
    return [{"role": "user" if i % 2 == 0 else "assistant", "content": f"{i:03d}" + "x" * (chars - 3)} for i in range(n)]


def _count(text: str) -> int:
    return len(text) // 4


def test_trim_history_newest_first_to_budget():
    # Core: 7000 tokens of history, 500 tokens per message -> 14 messages.
    kept = trim_history(_msgs(40, 2000), CORE, _count)
    assert len(kept) == 14
    assert kept[-1]["content"].startswith("039")


def test_trim_history_never_below_the_floor():
    # Lean: 3500 tokens; 2000 tokens per message would fit one, floor is 6.
    kept = trim_history(_msgs(40, 8000), LEAN, _count)
    assert len(kept) == LEAN.history_floor_exchanges * 2


def test_trim_history_short_history_is_untouched():
    history = _msgs(4, 100)
    assert trim_history(history, LEAN, _count) == history


# ---------------------------------------------------------------------------
# Registry: tools offered
# ---------------------------------------------------------------------------


class _Embedder:
    async def embed(self, text: str):
        h = abs(hash(text)) % 1000
        return [1.0, h / 1000.0]


def _registry(count: int = 12) -> ToolRegistry:
    registry = ToolRegistry()
    names = [f"tool_{i:02d}" for i in range(count - 1)] + ["delegate_work"]
    for name in names:
        registry.register(ToolRecord(
            name=name,
            description=f"does {name}",
            input_schema={"type": "object", "properties": {}},
            transport="builtin",
            risk="read",
        ))
    return registry


@pytest.mark.asyncio
@pytest.mark.parametrize("index,profile", TIERS)
async def test_select_tools_count_per_tier(monkeypatch, index, profile):
    _stack(monkeypatch, index)
    monkeypatch.setattr(settings, "tool_selection_threshold", 100)  # below the cap path
    offered = await _registry().select_tools(
        "hi",
        requester_role="owner",
        embed=_Embedder().embed,
        top_k=active_profile().tools_offered_max,
        exclude=tiers.gated_tools_denied(active_profile()),
    )
    assert len(offered) == profile.tools_offered_max


@pytest.mark.asyncio
async def test_delegate_work_is_filtered_before_the_cap():
    registry = _registry()
    lean = await registry.select_tools(
        "hi", requester_role="owner", embed=_Embedder().embed,
        top_k=12, exclude=tiers.gated_tools_denied(LEAN),
    )
    titan = await registry.select_tools(
        "hi", requester_role="owner", embed=_Embedder().embed,
        top_k=12, exclude=tiers.gated_tools_denied(TITAN),
    )
    assert "delegate_work" not in [r.name for r in lean]
    assert len(lean) == 11  # the gated tool does not take a slot
    assert "delegate_work" in [r.name for r in titan]


@pytest.mark.asyncio
async def test_select_tools_defaults_unchanged_without_top_k(monkeypatch):
    monkeypatch.setattr(settings, "tool_selection_threshold", 100)
    offered = await _registry().select_tools("hi", requester_role="owner", embed=_Embedder().embed)
    assert len(offered) == 12  # under the threshold, no cap: today's behaviour


# ---------------------------------------------------------------------------
# Executor gate
# ---------------------------------------------------------------------------


def _executor(invoked: list):
    from aura.executor.tool_executor import ToolExecutor

    executor = ToolExecutor.__new__(ToolExecutor)
    executor.logger = logging.getLogger("aura.executor.test")

    class _DB:
        async def query(self, sql: str, vars: dict | None = None):
            return [{
                "id": "skill:stub",
                "name": "delegate_work",
                "skill_type": "local_function",
                "execution_config": {"module": "aura.tools._stub_for_p2_03", "function": "run"},
                "definition": {},
            }]

        async def merge(self, thing: str, data: dict) -> Any:
            return []

    executor.db = _DB()
    executor._llm_layers = None
    mod = types.ModuleType("aura.tools._stub_for_p2_03")

    async def run(arguments: Dict[str, Any]) -> str:
        invoked.append(arguments)
        return "ran"

    mod.run = run
    sys.modules["aura.tools._stub_for_p2_03"] = mod
    return executor


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("tool", ["delegate_work", "plan_task"])
async def test_executor_refuses_gated_tools_on_lean_and_core(monkeypatch, index, tool):
    _stack(monkeypatch, index)
    invoked: list = []
    result = await _executor(invoked).execute_tool_call({"tool": tool, "arguments": {}}, requester_role="owner")
    assert result["success"] is False
    assert "not available on this tier" in result["error"]
    assert invoked == []


@pytest.mark.asyncio
async def test_executor_allows_delegate_work_on_titan(monkeypatch):
    _stack(monkeypatch, 2)
    invoked: list = []
    result = await _executor(invoked).execute_tool_call(
        {"tool": "delegate_work", "arguments": {}}, requester_role="owner"
    )
    assert result["success"] is True
    assert len(invoked) == 1


@pytest.mark.asyncio
async def test_guest_is_refused_by_the_role_check_even_on_titan(monkeypatch):
    _stack(monkeypatch, 2)
    invoked: list = []
    result = await _executor(invoked).execute_tool_call(
        {"tool": "delegate_work", "arguments": {}}, requester_role="guest"
    )
    assert result["error"] == "Tool use is not available to this user."
    assert invoked == []


@pytest.mark.asyncio
async def test_guest_role_error_wins_over_the_tier_error_on_lean(monkeypatch):
    _stack(monkeypatch, 0)
    result = await _executor([]).execute_tool_call(
        {"tool": "delegate_work", "arguments": {}}, requester_role="guest"
    )
    assert result["error"] == "Tool use is not available to this user."


@pytest.mark.asyncio
async def test_flag_off_gate_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    invoked: list = []
    result = await _executor(invoked).execute_tool_call(
        {"tool": "delegate_work", "arguments": {}}, requester_role="owner"
    )
    assert result["success"] is True and len(invoked) == 1


# ---------------------------------------------------------------------------
# Coordinator: the knobs as the pipeline applies them
# ---------------------------------------------------------------------------


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


@pytest.fixture
def wired(turn_orchestrator, monkeypatch):
    """The turn orchestrator with a real registry and a recording tool loop."""
    orch = turn_orchestrator
    registry = _registry()
    monkeypatch.setattr(settings, "tool_selection_threshold", 100)
    real_select = registry.select_tools
    embedder = _Embedder()
    calls: list[dict] = []

    async def select(text, **kwargs):
        calls.append(kwargs)
        return await real_select(text, embed=embedder.embed, **kwargs)

    orch._fake_tool_registry.select_tools = select
    orch._select_calls = calls

    loop_kwargs: list[dict] = []

    def recording_loop(**kwargs):
        loop_kwargs.append(kwargs)
        return real_run_tool_loop(**kwargs)

    monkeypatch.setattr(coordinator_module, "run_tool_loop", recording_loop)
    orch._loop_kwargs = loop_kwargs
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    return orch


async def _turn(orch, *, history=None, reasoning=True, enable_l2=True, l2_reasoning=True, role="owner"):
    events = []
    async for ev in orch._turn_pipeline(
        "hello",
        "u1",
        history,
        stream=False,
        context_limit=None,
        enable_l2=enable_l2,
        conversation_id="c1",
        reasoning_enabled=reasoning,
        l2_reasoning_enabled=l2_reasoning,
        session_id=None,
        context_mode="deep_work",
        requester_role=role,
    ):
        events.append(ev)
    await _drain()
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("index,profile", TIERS)
async def test_pipeline_budgets_per_tier(wired, monkeypatch, index, profile):
    _stack(monkeypatch, index)
    history = _msgs(40, 2000)
    await _turn(wired, history=history)

    # Tools offered and the gate.
    offered = wired.llm_layers.l3_synthesis.call_args.kwargs["tools"]
    assert len(offered) == profile.tools_offered_max
    assert wired._select_calls[0]["top_k"] == profile.tools_offered_max
    if not profile.allow_delegate:
        assert "delegate_work" not in [r.name for r in offered]
        assert wired._select_calls[0]["exclude"] == {"delegate_work", "plan_task"}
    else:
        assert wired._select_calls[0]["exclude"] == set()

    # Budgets handed to the tool loop (unused until P2-41).
    loop = wired._loop_kwargs[0]
    assert loop["turn_budget_seconds"] == profile.turn_budget_seconds
    assert loop["turn_budget_usd"] == profile.turn_budget_usd

    # Recall gets 30%, history is trimmed to the other 70% (floor honoured).
    recall_request = wired._fake_recall_engine.recall.call_args.args[0]
    assert recall_request.token_budget == int(0.3 * profile.context_budget_tokens)
    sent = wired.llm_layers.l3_synthesis.call_args.args[0].conversation_history
    history_budget = profile.context_budget_tokens - recall_request.token_budget
    expected = max(history_budget // 500, profile.history_floor_exchanges * 2)
    assert len(sent) == expected
    assert sent[-1] == history[-1]


@pytest.mark.asyncio
async def test_pipeline_records_tier_in_the_trace(wired, monkeypatch):
    _stack(monkeypatch, 2)
    await _turn(wired)
    events = [c.args for c in wired._publish_trace.call_args_list if c.args[1] == "profile_applied"]
    assert len(events) == 1
    payload = events[0][2]
    assert payload["tier_name"] == "titan"
    assert payload["tools_offered_max"] == TITAN.tools_offered_max


@pytest.mark.asyncio
@pytest.mark.parametrize("index", [0, 1, 2])
async def test_l3_reasoning_is_off_on_every_tier_until_p2_06(wired, monkeypatch, index):
    _stack(monkeypatch, index)
    await _turn(wired, reasoning=True)
    assert wired.llm_layers.l3_synthesis.call_args.kwargs["reasoning_enabled"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "index,client_l2,client_l2r,want_l2,want_l2r",
    [
        (0, True, True, False, False),   # Lean: profile off, ceiling wins
        (1, True, True, True, False),    # Core: analysis yes, no L2 reasoning
        (2, True, True, True, True),     # Titan: both
        (2, False, True, False, True),   # the client can still switch things off
        (2, True, False, True, False),
    ],
)
async def test_l2_ceiling_rule(wired, monkeypatch, index, client_l2, client_l2r, want_l2, want_l2r):
    _stack(monkeypatch, index)
    await _turn(wired, enable_l2=client_l2, l2_reasoning=client_l2r)
    kwargs = wired._post_response_chain.call_args.kwargs
    assert kwargs["enable_l2"] is want_l2
    assert kwargs["l2_reasoning_enabled"] is want_l2r


@pytest.mark.asyncio
async def test_guest_gets_no_tools_on_titan(wired, monkeypatch):
    _stack(monkeypatch, 2)
    await _turn(wired, role="guest")
    # The registry is only consulted for the owner; its guest answer is [].
    assert wired.llm_layers.l3_synthesis.call_args.kwargs["tools"] == []


@pytest.mark.asyncio
async def test_flag_off_is_todays_behaviour(wired, monkeypatch):
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    _stack(monkeypatch, 0)  # Lean, but the profile must not govern
    history = _msgs(40, 2000)
    await _turn(wired, history=history, reasoning=True, enable_l2=True, l2_reasoning=True)

    assert wired._select_calls[0] == {"requester_role": "owner"}
    offered = wired.llm_layers.l3_synthesis.call_args.kwargs["tools"]
    assert len(offered) == 12 and "delegate_work" in [r.name for r in offered]
    assert wired.llm_layers.l3_synthesis.call_args.kwargs["reasoning_enabled"] is True
    loop = wired._loop_kwargs[0]
    assert loop["turn_budget_seconds"] is None and loop["turn_budget_usd"] is None
    assert wired._fake_recall_engine.recall.call_args.args[0].token_budget is None
    assert wired.llm_layers.l3_synthesis.call_args.args[0].conversation_history == history
    post = wired._post_response_chain.call_args.kwargs
    assert post["enable_l2"] is True and post["l2_reasoning_enabled"] is True
    assert not [c for c in wired._publish_trace.call_args_list if c.args[1] == "profile_applied"]
