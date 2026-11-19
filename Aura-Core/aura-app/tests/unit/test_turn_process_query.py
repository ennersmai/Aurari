"""W2-02: characterisation tests for ``Orchestrator.process_query``.

Behaviour PRD B0 (B6, section 4.4) — a safety net of pinned observable
behaviour for ``process_query`` before the turn-pipeline merge in later
W2 cards. These tests do not change ``src/``; they pin what the code does
today. Every test drives the real ``Orchestrator.process_query`` through
the ``turn_orchestrator`` fixture (see ``tests/conftest.py``), which wires
every engine and the LLM layers onto mocks so no database, LLM or network
is touched.

One documented deviation from the card: ``IdentityContext`` has no
``core_identity`` / ``tone_and_style`` fields, so the card's prescribed
``IdentityContext(core_identity="Aura", tone_and_style="Helpful")`` is not
constructible. The fixture returns a minimal valid ``IdentityContext``
instead; see the fixture docstring. This mirrors a latent bug in
``stream_query``'s fallback path and is reported in the W2-02 log entry.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import DEFAULT, AsyncMock, MagicMock

import pytest

from aura.config import settings
from tests.conftest import _TURN_FIXED_DATETIME


# ---------------------------------------------------------------------------
# Helper: drain background tasks created by process_query's
# ``asyncio.create_task(self._post_response_chain(...))`` so they do not leak
# between tests or trip "Task was destroyed but it is pending" warnings.
# ---------------------------------------------------------------------------
async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


# ---------------------------------------------------------------------------
# (a) sleep gate
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_sleep_gate_blocked_returns_message_and_skips_l1(turn_orchestrator):
    orch = turn_orchestrator
    orch._sleep_gate = AsyncMock(return_value=(False, "asleep"))

    result = await orch.process_query("hi", user_id="u1")

    assert result == "asleep"
    orch.llm_layers.l1_classify_intent.assert_not_called()


@pytest.mark.asyncio
async def test_a_sleep_gate_blocked_none_returns_system_unavailable(turn_orchestrator):
    orch = turn_orchestrator
    orch._sleep_gate = AsyncMock(return_value=(False, None))

    result = await orch.process_query("hi", user_id="u1")

    assert result == "System unavailable."
    orch.llm_layers.l1_classify_intent.assert_not_called()


# ---------------------------------------------------------------------------
# (b) System: Connect MCP ...
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_b_connect_mcp_no_target_reaches_l1(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="ok")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    # "System: Connect MCP foo" has nothing after "foo", so the connect regex
    # (which needs \s+(.+)) does not match; the ingest/learn regexes do not
    # match either, so the turn reaches L1.
    await orch.process_query("System: Connect MCP foo", user_id="u1")

    orch.llm_layers.l1_classify_intent.assert_awaited_once_with("System: Connect MCP foo")
    await _drain()


@pytest.mark.asyncio
async def test_b_connect_mcp_with_url_calls_ingest_mcp_server_and_returns_check(turn_orchestrator):
    orch = turn_orchestrator
    orch.learning_engine.ingest_mcp_server = AsyncMock(return_value="connected to foo")

    result = await orch.process_query(
        "System: Connect MCP foo http://x/sse", user_id="u1"
    )

    orch.learning_engine.ingest_mcp_server.assert_awaited_once_with(
        "foo",
        {"transport": "sse", "url": "http://x/sse", "timeout_s": 15, "server": "foo"},
    )
    assert result == "✅ connected to foo"
    # Early reply: no L1, no L3.
    orch.llm_layers.l1_classify_intent.assert_not_awaited()
    orch.llm_layers.l3_synthesis.assert_not_awaited()


# ---------------------------------------------------------------------------
# (c) System: ingest tool ...
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_c_ingest_tool_calls_ingest_local_tool_module(turn_orchestrator):
    orch = turn_orchestrator
    orch.learning_engine.ingest_local_tool_module = AsyncMock(return_value="ingested bar")

    result = await orch.process_query("System: ingest tool bar", user_id="u1")

    orch.learning_engine.ingest_local_tool_module.assert_awaited_once_with("bar")
    assert result == (
        "✅ ingested bar The tool is now registered and available for use "
        "(semantic triggers will be ready shortly)."
    )
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


# ---------------------------------------------------------------------------
# (d) Aura learn: ...
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_d_learn_with_content_logs_direct_instruction_and_returns_fact_string(turn_orchestrator):
    orch = turn_orchestrator

    result = await orch.process_query("Aura learn: the sky is blue", user_id="u1")

    orch.learning_engine.log_experience.assert_awaited_once()
    experience = orch.learning_engine.log_experience.await_args.args[0]
    assert experience["task_type"] == "direct_instruction"
    assert experience["metadata"]["forced_insight"]["content"] == "the sky is blue"
    assert experience["metadata"]["forced_insight"]["type"] == "FACT"
    assert experience["metadata"]["forced_insight"]["confidence"] == 1.0
    assert result == (
        "✅ Understood. I have committed this to memory as a Fact: 'the sky is blue'."
    )
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


@pytest.mark.asyncio
async def test_d_learn_with_nothing_after_returns_did_not_find_content_string(turn_orchestrator):
    orch = turn_orchestrator
    # The learn regex is r'(?:aura\s+)?learn(?:\s+this)?\s*:\s*(.+)' — the
    # capturing group needs at least one character, so a bare "learn:" does
    # NOT match and falls through to L1 (see
    # test_d_bare_learn_reaches_l1_difference). The "didn't find any content"
    # path only fires when the regex matches but the captured text strips to
    # empty, i.e. whitespace after the colon. That is the card's intent
    # ("learn: with nothing after it"); the bare "learn:" literal would not.
    result = await orch.process_query("learn:   ", user_id="u1")

    assert result == "❌ I didn’t find any content after `learn:`. Try: `Aura learn: <fact>`."
    orch.learning_engine.log_experience.assert_not_awaited()
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


@pytest.mark.asyncio
async def test_d_bare_learn_reaches_l1_difference(turn_orchestrator):
    """Card-vs-code difference (reported in the W2-02 log entry): the card
    says ``"learn:" with nothing after it`` returns the "didn't find any
    content" string, but the learn regex's capturing group requires at least
    one character, so a bare ``"learn:"`` does not match and the turn reaches
    L1 instead. This test pins what the code actually does."""
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={"intent": "CHAT", "confidence": 0.9}
    )
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="ok")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    await orch.process_query("learn:", user_id="u1")

    # Bare "learn:" does not match the learn regex; L1 is called.
    orch.llm_layers.l1_classify_intent.assert_awaited_once_with("learn:")
    await _drain()


# ---------------------------------------------------------------------------
# (e) TEACHING fast lane
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_e_teaching_calls_log_experience_instruction_and_returns_teaching_string(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "TEACHING"})

    result = await orch.process_query("Teach me about X", user_id="u1")

    orch.learning_engine.log_experience.assert_awaited_once()
    experience = orch.learning_engine.log_experience.await_args.args[0]
    assert experience["task_type"] == "instruction"
    assert result == "I've processed that instruction. I'm analyzing the schema and adding it to my skills now."
    orch.llm_layers.l3_synthesis.assert_not_awaited()


# ---------------------------------------------------------------------------
# (f) Plain CHAT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f_plain_chat_pins_observed_behaviour(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="hello response")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    # Record the order of engine calls across separate mocks via side_effects
    # that append a tag and return DEFAULT (so each mock still uses its
    # configured return_value).
    order: list[str] = []

    async def _emotion(*a, **k):
        order.append("emotion")
        return DEFAULT

    async def _learning(*a, **k):
        order.append("learning")
        return DEFAULT

    async def _identity(*a, **k):
        order.append("identity")
        return DEFAULT

    async def _goal(*a, **k):
        order.append("goal")
        return DEFAULT

    async def _pursuit(*a, **k):
        order.append("pursuit")
        return DEFAULT

    orch.emotion_engine.get_current_state.side_effect = _emotion
    orch.learning_engine.get_learning_context.side_effect = _learning
    orch.identity_engine.get_identity_context.side_effect = _identity
    orch.goal_engine.get_goal_context.side_effect = _goal
    orch.goal_engine.check_goals_needing_autonomous_pursuit.side_effect = _pursuit

    result = await orch.process_query("hello", user_id="default")

    # (f1) L1 trace payload: no "mode" key. _publish_trace is also called
    # later with the L3 synthesis_complete trace; pin the first call here.
    assert orch._publish_trace.call_count >= 1
    first_call = orch._publish_trace.call_args_list[0]
    assert first_call.args[0] == "L1"
    assert first_call.args[1] == "intent_classified"
    payload = first_call.args[2]
    assert payload == {
        "intent": "CHAT",
        "confidence": 0.0,
        "model": settings.l1_model,
    }
    assert "mode" not in payload

    # (f2) engine call order
    assert order == ["emotion", "learning", "identity", "goal", "pursuit"]

    # (f3) engine call args
    orch.emotion_engine.get_current_state.assert_awaited_once_with()
    orch.learning_engine.get_learning_context.assert_awaited_once_with(
        context="hello", user_id="default"
    )
    orch.identity_engine.get_identity_context.assert_awaited_once_with(
        conversation_topic="hello", overlay=None
    )
    orch.goal_engine.get_goal_context.assert_awaited_once_with()
    orch.goal_engine.check_goals_needing_autonomous_pursuit.assert_awaited_once_with()

    # (f4) Recall Engine: the packet was assembled once with the turn's input.
    orch._fake_recall_engine.recall.assert_awaited_once()
    recall_request = orch._fake_recall_engine.recall.await_args.args[0]
    assert recall_request.user_input == "hello"
    assert recall_request.user_id == "default"
    assert recall_request.depth == 2
    assert recall_request.include_cold_start is True
    assert recall_request.learning_context is orch.learning_engine.get_learning_context.return_value

    # (f5) the memory/latent stores are no longer called from the coordinator
    # (W2-20): recall replaces them. They are stashed on the fixture for tests
    # that want to drive them directly, so confirm they were *not* awaited here.
    orch._fake_memory_manager.get_cold_start_context.assert_not_awaited()
    orch._fake_memory_manager.retrieve_memories.assert_not_awaited()

    # (f6) cached system prompt
    assert orch._last_system_prompt["default"] == "PROMPT"

    # (f7) l3_synthesis called once with the right kwargs; loop context fields
    orch.llm_layers.l3_synthesis.assert_awaited_once()
    synth_kwargs = orch.llm_layers.l3_synthesis.await_args.kwargs
    assert synth_kwargs["max_history_messages"] == 20
    assert synth_kwargs["reasoning_enabled"] is False
    loop_ctx = orch.llm_layers.l3_synthesis.await_args.args[0]
    assert loop_ctx.user_input == "hello"
    # Today the loop context omits user_id, so it defaults to "default".
    assert loop_ctx.user_id == "default"
    assert loop_ctx.recent_critique is None
    assert loop_ctx.resonance_score is None
    assert loop_ctx.cold_start_xml is None

    # (f8) return value is the L3 text with tool calls stripped
    assert result == "hello response"

    await _drain()


# ---------------------------------------------------------------------------
# (g) context_limit -> max_history_messages
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_g_context_limit_sets_max_history_messages(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="ok")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    await orch.process_query("hello", user_id="u1", context_limit=7)

    assert orch.llm_layers.l3_synthesis.await_args.kwargs["max_history_messages"] == 7
    await _drain()


# ---------------------------------------------------------------------------
# (h) critique buffer -> recent_critique, and entry removed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_h_critique_buffer_joined_and_popped(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="ok")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.critique_buffer["u1"] = ["c1", "c2"]

    await orch.process_query("hello", user_id="u1")

    loop_ctx = orch.llm_layers.l3_synthesis.await_args.args[0]
    assert loop_ctx.recent_critique == "c1\n\nc2"
    # The buffer entry is removed (popped).
    assert "u1" not in orch.critique_buffer
    await _drain()


# ---------------------------------------------------------------------------
# (i) tool loop: one tool round then stop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "guest"])
async def test_i_tool_loop_two_l3_calls_and_requester_role(turn_orchestrator, role):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(side_effect=["round1", "round2"])
    # extract_tool_calls returns [call] then []
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="R1")

    await orch.process_query("hello", user_id="u1", requester_role=role)

    # Two l3_synthesis calls
    assert orch.llm_layers.l3_synthesis.await_count == 2
    # Second loop context user_input includes the round-1 results block.
    second_ctx = orch.llm_layers.l3_synthesis.await_args_list[1].args[0]
    assert second_ctx.user_input == "hello\n\n[Tool Execution Results]\n[Round 1]\nR1"
    # Every execute_and_feedback call carries the requester_role through.
    assert orch.tool_executor.execute_and_feedback.await_count == 1
    assert orch.tool_executor.execute_and_feedback.await_args.kwargs["requester_role"] == role
    await _drain()


# ---------------------------------------------------------------------------
# (j) tool calls every round -> 5 l3_synthesis calls + max-rounds suffix
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_j_tool_calls_every_round_stops_after_max_rounds(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(
        side_effect=["r1", "r2", "r3", "r4", "r5"]
    )
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=["call"])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="R")

    result = await orch.process_query("hello", user_id="u1")

    assert orch.llm_layers.l3_synthesis.await_count == 5
    assert result.endswith(
        "\n\n(Stopped after max tool rounds; ask me to continue if needed.)"
    )
    await _drain()


# ---------------------------------------------------------------------------
# (k) "weather" stays chat: the keyword rule is gone (W2-38)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k_weather_stays_chat(turn_orchestrator):
    """changed on purpose by W2-38 (G1, keyword rule removed)"""
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="weather response")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    await orch.process_query("what is the weather today", user_id="u1")

    # W2-38 removed the keyword fallback: "weather" no longer rewrites a CHAT
    # intent to TOOL_USE, so the [MAG] forced-tool path is never entered and no
    # forced tool call is made.
    orch.llm_layers.l3_tool_call_mode.assert_not_awaited()
    orch.learning_engine.get_skill.assert_not_awaited()
    for call in orch.learning_engine.db.query.await_args_list:
        assert "skill" not in call.args[0].lower()
    orch.llm_layers.l3_synthesis.assert_awaited_once()
    await _drain()


# ---------------------------------------------------------------------------
# (W2-38) L1 TOOL_USE without a trigger match does not force a tool call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_llm_tool_use_without_trigger_does_not_force(turn_orchestrator):
    """changed on purpose by W2-38 (G1, keyword rule removed)"""
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={"intent": "TOOL_USE", "target_action": "skill:x"}
    )
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="final answer")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    result = await orch.process_query("hello", user_id="u1")

    # Without routing_method == "vector_search" the forced seed is skipped:
    # only the trigger-phrase fast lane may force a tool call.
    orch.llm_layers.l3_tool_call_mode.assert_not_awaited()
    orch.llm_layers.l3_synthesis.assert_awaited_once()
    assert result == "final answer"
    await _drain()


# ---------------------------------------------------------------------------
# (l) forced seed: target_skill_id path
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_l_forced_seed_target_skill_id_seeds_tool_loop(turn_orchestrator):
    """changed on purpose by W2-38 (G1, keyword rule removed)"""
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={
            "intent": "TOOL_USE",
            "target_action": "skill:x",
            "routing_method": "vector_search",
        }
    )
    # get_skill returns an object with a .name attribute.
    orch.learning_engine.get_skill = AsyncMock(
        return_value=SimpleNamespace(name="test_skill")
    )
    # db.select returns a record whose definition is a non-empty dict.
    orch.learning_engine.db.select = AsyncMock(
        return_value=[{"definition": {"name": "t"}}]
    )
    # forced seed: l3_tool_call_mode returns text with a tool call; the seed
    # execute_and_feedback returns "SEED"; the loop's l3_synthesis returns a
    # final response with no further tool calls.
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    orch.tool_executor.extract_tool_calls = MagicMock(
        side_effect=[["seed_call"], []]
    )
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="SEED")
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="final answer")

    result = await orch.process_query("hello", user_id="u1")

    expected_schema = json.dumps({"name": "t"}, indent=2)
    orch.llm_layers.l3_tool_call_mode.assert_awaited_once_with(
        query="hello", tool_schema=expected_schema
    )
    # The seed results land in the first loop input as "[Seed]\n...".
    loop_ctx = orch.llm_layers.l3_synthesis.await_args.args[0]
    assert loop_ctx.user_input == "hello\n\n[Tool Execution Results]\n[Seed]\nSEED"
    assert result == "final answer"
    await _drain()


# ---------------------------------------------------------------------------
# (m) _post_response_chain kwargs and enable_l2 resolution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_m_post_response_chain_kwargs_enable_l2_from_deep_when_none(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    # enable_l2_analysis is None -> enable_l2 == deep_analysis_enabled (False here).
    await orch.process_query(
        "hello",
        user_id="u1",
        conversation_id="c1",
        deep_analysis_enabled=False,
        enable_l2_analysis=None,
    )
    await _drain()

    orch._post_response_chain.assert_awaited_once()
    kwargs = orch._post_response_chain.await_args.kwargs
    expected_keys = {
        "user_input", "response", "emotional_before", "user_id",
        "conversation_id", "goal_context", "learning_context",
        "enable_l2", "l2_reasoning_enabled", "resonance_score",
    }
    assert set(kwargs.keys()) == expected_keys
    assert kwargs["enable_l2"] is False
    assert kwargs["user_input"] == "hello"
    assert kwargs["response"] == "resp"
    assert kwargs["user_id"] == "u1"
    assert kwargs["conversation_id"] == "c1"


@pytest.mark.asyncio
async def test_m_post_response_chain_enable_l2_from_enable_l2_analysis_when_set(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    # enable_l2_analysis is set -> enable_l2 == enable_l2_analysis (True here),
    # regardless of deep_analysis_enabled (False).
    await orch.process_query(
        "hello",
        user_id="u1",
        deep_analysis_enabled=False,
        enable_l2_analysis=True,
    )
    await _drain()

    kwargs = orch._post_response_chain.await_args.kwargs
    assert kwargs["enable_l2"] is True


# ---------------------------------------------------------------------------
# (n) llm_layers.context_mode == context_mode argument after the call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_n_context_mode_is_set_on_llm_layers(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="ok")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    await orch.process_query("hello", user_id="u1", context_mode="deep_work")

    # process_query does: self.llm_layers.context_mode = context_mode.
    # llm_layers is a MagicMock, so the assignment stores the value verbatim.
    assert orch.llm_layers.context_mode == "deep_work"
    await _drain()


# ---------------------------------------------------------------------------
# (W2-06) forced tool resolution by detected_tool name lookup
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_w2_06_forced_tool_by_name_lookup(turn_orchestrator):
    """W2-06: ``_resolve_forced_tool`` resolves a tool by ``detected_tool``
    name via the parameterised ``SELECT * FROM skill WHERE name = $name`` query
    when there is no ``target_skill_id``. ``get_skill`` returns ``None`` (no
    record-id hit), the first ``db.query`` returns a skill row, and
    ``db.select`` returns its definition; forced tool call mode is engaged and
    ``l3_tool_call_mode`` is called with that definition as JSON.

    changed on purpose by W2-38 (G1, keyword rule removed)
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={
            "intent": "TOOL_USE",
            "detected_tool": "web_search",
            "routing_method": "vector_search",
        }
    )
    # No target_skill_id path: get_skill returns None.
    orch.learning_engine.get_skill = AsyncMock(return_value=None)
    # First db.query (exact name match) returns a skill row.
    orch.learning_engine.db.query = AsyncMock(
        return_value=[{"id": "skill:ws", "name": "web_search"}]
    )
    # db.select returns the full skill record with a definition.
    orch.learning_engine.db.select = AsyncMock(
        return_value=[{"definition": {"name": "web_search"}}]
    )
    # forced seed: l3_tool_call_mode returns text with a tool call; the seed
    # execute_and_feedback returns "SEED"; the loop's l3_synthesis returns a
    # final response with no further tool calls.
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    orch.tool_executor.extract_tool_calls = MagicMock(
        side_effect=[["seed_call"], []]
    )
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="SEED")
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="final answer")

    result = await orch.process_query("hello", user_id="u1")

    expected_schema = json.dumps({"name": "web_search"}, indent=2)
    orch.llm_layers.l3_tool_call_mode.assert_awaited_once_with(
        query="hello", tool_schema=expected_schema
    )
    assert result == "final answer"
    await _drain()


# ---------------------------------------------------------------------------
# (W2-19/20) The blocking loop context carries the Recall packet
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_loop_context_carries_packet_blocking(turn_orchestrator):
    """W2-19 (a) -> W2-20: the loop context carries the Recall packet.

    Previously (pre-M2) the blocking loop context built a new
    ``SynthesisContext`` that dropped ``cold_start_xml``,
    ``latent_intuition_xml`` and ``user_id``. W2-20 routes the turn through
    the Recall Engine, so the loop context now carries the packet the engine
    returned. This test pins that carry so a later card does not silently drop
    it again.
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="ok")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    # The fixture's fake recall engine returns an empty packet by default;
    # replace it with one carrying a non-empty cold-start block so the carry is
    # observable.
    from aura.engines.recall.models import Block, ContextPacket, RecallTrace
    packet = ContextPacket(
        stable_blocks=[Block(kind="cold_start", text="<cold_start_context>X</cold_start_context>", tokens=1, stable=True)],
        dynamic_blocks=[],
        abstain=False,
        trace=RecallTrace(
            turn_id="t", user_id="u1", query="hello",
            created_at=_TURN_FIXED_DATETIME,
            budget_tokens=0, tokens_before=0, tokens_after=0,
            items=[], channel_errors={},
        ),
    )
    orch._fake_recall_engine.recall = AsyncMock(return_value=packet)

    # No conversation_history -> the blocking path runs.
    await orch.process_query("hello", user_id="u1")

    # The loop context passed to l3_synthesis carries the packet.
    orch.llm_layers.l3_synthesis.assert_awaited_once()
    loop_ctx = orch.llm_layers.l3_synthesis.await_args.args[0]
    assert loop_ctx.packet is packet
    await _drain()
