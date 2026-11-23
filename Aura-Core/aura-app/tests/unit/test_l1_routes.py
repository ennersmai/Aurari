"""P2-06: L1 route and stakes.

Parsing is tested directly. Coordinator plumbing runs the real ``_turn_pipeline``
(``turn_orchestrator`` fixture) with L1 mocked to return canned JSON per message.
No real model calls.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.config import settings
from aura.llm.layers import LLMLayers, SynthesisContext, parse_route
from aura.orchestrator.coordinator import TASK_UNAVAILABLE_NOTE
from aura.tiers import reset_tier_cache

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "l1_routes.json"
INTENTS = {"chat": "CHAT", "think": "CHAT", "tool": "TOOL_USE", "task": "TOOL_USE", "teach": "TEACHING"}

# The L1 prompt exactly as it was before P2-06 (flag off must reproduce it).
OLD_PROMPT = '''Analyze the user input.
INPUT: "hello there"

CLASSIFY into one of these categories:
1. "TEACHING": User is providing a JSON schema, code block, or explicit rule to learn.
2. "TOOL_USE": User is asking to perform an action (weather, stocks, database, search, read file, list dir, filesystem, source code).
3. "CHAT": Casual conversation, emotional venting, or philosophical query.

OUTPUT JSON (REQUIRED FORMAT - NO OTHER TEXT):
{
  "intent": "TEACHING" | "TOOL_USE" | "CHAT",
  "confidence": 0.9,
  "needs_agentic_rag": true,
  "detected_tool": "web_search" | "read_file" | "list_directory" | "filesystem" | null,
  "target_action": "skill_id_if_known" | null
}
'''


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "o.json"))
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    monkeypatch.setattr(settings, "l1_routes_enabled", False)
    monkeypatch.setattr(settings, "layer_l1_enabled", True)
    monkeypatch.setattr(settings, "model_stack_index", settings.model_stack_index)
    yield
    reset_tier_cache()


# ---------------------------------------------------------------- parse_route


def test_parse_route_valid():
    assert parse_route({"route": "think", "stakes": 0.4}) == ("think", 0.4, "CHAT")


def test_parse_route_missing_fields():
    assert parse_route({}) == ("chat", 0.0, "CHAT")


@pytest.mark.parametrize("route", ["bogus", "", None, 3, ["tool"], {"a": 1}, True])
def test_parse_route_unknown_or_non_string_route_is_chat(route):
    assert parse_route({"route": route, "stakes": 0.2})[0] == "chat"


def test_parse_route_normalises_case():
    assert parse_route({"route": " TOOL "})[0] == "tool"


@pytest.mark.parametrize(
    "stakes,want",
    [(5, 1.0), (1.5, 1.0), (-2, 0.0), ("0.6", 0.6), ("high", 0.0), (None, 0.0),
     (True, 0.0), ([0.9], 0.0), (float("nan"), 0.0), (float("inf"), 1.0), (0.55, 0.55)],
)
def test_parse_route_stakes_clamped_and_defaulted(stakes, want):
    assert parse_route({"route": "think", "stakes": stakes})[1] == want


def test_parse_route_ignores_extra_fields():
    assert parse_route({"route": "tool", "x": 1, "confidence": 0.9}) == ("tool", 0.0, "TOOL_USE")


def test_parse_route_non_dict_does_not_raise():
    assert parse_route(None) == ("chat", 0.0, "CHAT")  # type: ignore[arg-type]


@pytest.mark.parametrize("route,intent", INTENTS.items())
def test_intent_is_derived_from_route(route, intent):
    assert parse_route({"route": route})[2] == intent


# ------------------------------------------------------------- L1 classifier


def _layers(monkeypatch, canned=None):
    layers = LLMLayers.__new__(LLMLayers)
    layers.l5_structure_analysis = AsyncMock(return_value=canned)
    # No vector fast path: embeddings fail, so it falls through to the LLM.
    monkeypatch.setattr(
        "aura.llm.embeddings.get_embeddings_client", MagicMock(side_effect=RuntimeError("no"))
    )
    return layers


async def test_flag_off_prompt_is_byte_identical(monkeypatch):
    layers = _layers(monkeypatch, {"intent": "CHAT", "confidence": 0.9})
    result = await layers.l1_classify_intent("hello there")
    assert layers.l5_structure_analysis.await_args.args[0] == OLD_PROMPT
    assert "route" not in result and "stakes" not in result


async def test_flag_off_does_not_parse_route(monkeypatch):
    layers = _layers(monkeypatch, {"intent": "TOOL_USE", "route": "teach", "stakes": 0.9})
    result = await layers.l1_classify_intent("x")
    assert result["intent"] == "TOOL_USE"


async def test_flag_on_prompt_lists_every_route(monkeypatch):
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    layers = _layers(monkeypatch, {"route": "think", "stakes": 0.8, "intent": "TOOL_USE"})
    result = await layers.l1_classify_intent("hello there")
    prompt = layers.l5_structure_analysis.await_args.args[0]
    for route in INTENTS:
        assert f'"{route}"' in prompt
    assert '"stakes"' in prompt
    # Intent is overridden by the route.
    assert (result["route"], result["stakes"], result["intent"]) == ("think", 0.8, "CHAT")


async def test_flag_on_malformed_result_defaults_to_chat(monkeypatch):
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    layers = _layers(monkeypatch, {"route": 7, "stakes": "lots", "intent": "TEACHING"})
    result = await layers.l1_classify_intent("x")
    assert (result["route"], result["stakes"], result["intent"]) == ("chat", 0.0, "CHAT")


async def test_flag_on_empty_result_is_chat(monkeypatch):
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    layers = _layers(monkeypatch, {})
    result = await layers.l1_classify_intent("x")
    assert (result["route"], result["stakes"]) == ("chat", 0.0)


async def test_vector_fast_path_gives_tool(monkeypatch):
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    layers = LLMLayers.__new__(LLMLayers)
    layers.l5_structure_analysis = AsyncMock()
    emb = MagicMock()
    emb.embed = AsyncMock(return_value=[0.1, 0.2])
    db = MagicMock()
    db.query = AsyncMock(return_value=[{"similarity": 0.99, "confidence": 1.0, "target_action": None}])
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: emb)
    monkeypatch.setattr("aura.db.client.get_db_client", lambda: db)
    result = await layers.l1_classify_intent("x")
    layers.l5_structure_analysis.assert_not_awaited()
    assert (result["route"], result["stakes"], result["intent"]) == ("tool", 0.0, "TOOL_USE")


# ------------------------------------------------------------------- fixture


def _fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_fixture_has_five_per_route():
    data = _fixture()
    assert len(data) == 25
    for route in INTENTS:
        assert sum(1 for d in data if d["route"] == route) == 5


async def test_fixture_through_mocked_l1(monkeypatch):
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    data = _fixture()
    canned = {d["message"]: {"route": d["route"], "stakes": d["stakes"]} for d in data}
    layers = _layers(monkeypatch)
    layers.l5_structure_analysis = AsyncMock(
        side_effect=lambda prompt, **kw: dict(
            next(v for m, v in canned.items() if f'INPUT: "{m}"' in prompt)
        )
    )
    for d in data:
        result = await layers.l1_classify_intent(d["message"])
        assert result["route"] == d["route"]
        assert result["intent"] == INTENTS[d["route"]]
        assert result["stakes"] == d["stakes"]


# ------------------------------------------------------------- coordinator


class _Tool:
    def __init__(self, name):
        self.name = name
        self.risk = "low"
        self.description = name
        self.input_schema = {}


@pytest.fixture
def orch(turn_orchestrator, monkeypatch):
    o = turn_orchestrator
    o._mp = monkeypatch
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    o.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    o.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    o._log_interaction_experience = AsyncMock()
    o._fake_tool_registry.select_tools = AsyncMock(
        return_value=[_Tool("read_file"), _Tool("plan_task"), _Tool("web_search")]
    )
    return o


async def _turn(o, l1, *, index=0, tiers=True, reasoning=True):
    o._mp.setattr(settings, "model_stack_index", index)
    o._mp.setattr(settings, "tier_profiles_enabled", tiers)
    o.llm_layers.l1_classify_intent = AsyncMock(return_value=l1)
    async for _ in o._turn_pipeline(
        "do it", "u1", None, stream=False, context_limit=None, enable_l2=False,
        conversation_id="c1", reasoning_enabled=reasoning, l2_reasoning_enabled=False,
        session_id=None, context_mode="deep_work", requester_role="owner",
    ):
        pass


def _reasoning(o):
    return o.llm_layers.l3_synthesis.call_args.kwargs["reasoning_enabled"]


def _l1(route, stakes=0.0):
    return {"intent": INTENTS[route], "route": route, "stakes": stakes, "confidence": 0.9}


async def test_think_on_core_turns_reasoning_on_and_lean_off(orch):
    await _turn(orch, _l1("think"), index=1)
    assert _reasoning(orch) is True
    await _turn(orch, _l1("think"), index=0)
    assert _reasoning(orch) is False


async def test_core_reasons_only_on_think_not_on_stakes(orch):
    await _turn(orch, _l1("chat", 0.95), index=1)
    assert _reasoning(orch) is False


async def test_titan_high_stakes_turns_reasoning_on(orch):
    await _turn(orch, _l1("chat", 0.7), index=2)
    assert _reasoning(orch) is True
    await _turn(orch, _l1("chat", 0.69), index=2)
    assert _reasoning(orch) is False


async def test_client_toggle_still_wins_when_off(orch):
    await _turn(orch, _l1("think"), index=2, reasoning=False)
    assert _reasoning(orch) is False


async def test_routes_do_not_change_reasoning_without_tier_profiles(orch):
    await _turn(orch, _l1("think", 0.9), index=0, tiers=False, reasoning=True)
    assert _reasoning(orch) is True
    await _turn(orch, _l1("think", 0.9), index=2, tiers=False, reasoning=False)
    assert _reasoning(orch) is False


async def test_route_and_stakes_traced(orch):
    await _turn(orch, _l1("think", 0.8), index=1)
    traces = [c.args for c in orch._publish_trace.call_args_list if c.args[1] == "intent_classified"]
    assert traces[0][2]["route"] == "think" and traces[0][2]["stakes"] == 0.8


async def test_task_on_core_adds_note_once(orch):
    await _turn(orch, _l1("task"), index=1)
    ctx = orch.llm_layers.l3_synthesis.call_args.args[0]
    assert ctx.prompt_notes == [TASK_UNAVAILABLE_NOTE]
    prompt = LLMLayers.__new__(LLMLayers).build_l3_system_prompt(ctx)
    assert prompt.count(TASK_UNAVAILABLE_NOTE) == 1


async def test_task_without_tier_profiles_adds_no_note(orch):
    await _turn(orch, _l1("task"), index=1, tiers=False)
    assert orch.llm_layers.l3_synthesis.call_args.args[0].prompt_notes == []


async def test_task_on_titan_puts_plan_task_first_no_note(orch):
    await _turn(orch, _l1("task"), index=2)
    ctx = orch.llm_layers.l3_synthesis.call_args.args[0]
    assert [t.name for t in ctx.offered_tools] == ["plan_task", "read_file", "web_search"]
    assert ctx.prompt_notes == []


async def test_task_on_titan_without_plan_task_is_a_no_op(orch):
    orch._fake_tool_registry.select_tools = AsyncMock(return_value=[_Tool("read_file")])
    await _turn(orch, _l1("task"), index=2)
    ctx = orch.llm_layers.l3_synthesis.call_args.args[0]
    assert [t.name for t in ctx.offered_tools] == ["read_file"]


async def test_non_task_route_leaves_tools_and_notes_alone(orch):
    await _turn(orch, _l1("tool"), index=2)
    ctx = orch.llm_layers.l3_synthesis.call_args.args[0]
    assert [t.name for t in ctx.offered_tools] == ["read_file", "plan_task", "web_search"]
    assert ctx.prompt_notes == []


async def test_flag_off_leaves_turn_unchanged(orch):
    orch._mp.setattr(settings, "l1_routes_enabled", False)
    await _turn(orch, {"intent": "CHAT", "route": "think", "stakes": 1.0}, index=2)
    assert _reasoning(orch) is False
    assert SynthesisContext(user_input="x").prompt_notes == []
