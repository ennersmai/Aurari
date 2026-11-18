"""W2-03: characterisation tests for ``Orchestrator.stream_query``.

Behaviour PRD B0 — a safety net of pinned observable behaviour for
``stream_query`` before the turn-pipeline merge in later W2 cards. These
tests do not change ``src/``; they pin what the code does today. Every test
drives the real ``Orchestrator.stream_query`` through the
``turn_orchestrator`` fixture (see ``tests/conftest.py``), which wires every
engine and the LLM layers onto mocks so no database, LLM or network is
touched.

The fixture is shared with W2-02 (``test_turn_process_query.py``); see its
docstring for the documented ``IdentityContext`` deviation, which mirrors a
latent bug in ``stream_query``'s fallback path (lines ~2189 and ~2216 of
``coordinator.py``) and is reported in the W2-02 log entry. ``src/`` is not
changed.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import DEFAULT, AsyncMock, MagicMock

import pytest

from aura.config import settings


# ---------------------------------------------------------------------------
# Helper: drain background tasks created by stream_query's
# ``asyncio.create_task(self._post_response_chain(...))`` so they do not leak
# between tests or trip "Task was destroyed but it is pending" warnings.
# ---------------------------------------------------------------------------
async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def _collect(agen):
    """Collect all chunks from an async generator into a list."""
    out: list[str] = []
    async for chunk in agen:
        out.append(chunk)
    return out


# ---------------------------------------------------------------------------
# (a) sleep gate blocked -> one item per character
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_sleep_gate_blocked_yields_one_char_per_character(turn_orchestrator):
    orch = turn_orchestrator
    orch._sleep_gate = AsyncMock(return_value=(False, "zz"))

    chunks = await _collect(orch.stream_query("hi", user_id="u1"))

    assert chunks == ["z", "z"]
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


# ---------------------------------------------------------------------------
# (b) early replies: same text as W2-02, one char per char, same learning call
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_b_connect_mcp_with_url_streams_chars_and_calls_ingest_mcp_server(turn_orchestrator):
    orch = turn_orchestrator
    orch.learning_engine.ingest_mcp_server = AsyncMock(return_value="connected to foo")

    chunks = await _collect(orch.stream_query("System: Connect MCP foo http://x/sse", user_id="u1"))

    orch.learning_engine.ingest_mcp_server.assert_awaited_once_with(
        "foo",
        {"transport": "sse", "url": "http://x/sse", "timeout_s": 15, "server": "foo"},
    )
    assert "".join(chunks) == "✅ connected to foo"
    # one item per character
    assert len(chunks) == len("✅ connected to foo")
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


@pytest.mark.asyncio
async def test_b_ingest_tool_streams_chars_and_calls_ingest_local_tool_module(turn_orchestrator):
    orch = turn_orchestrator
    orch.learning_engine.ingest_local_tool_module = AsyncMock(return_value="ingested bar")

    chunks = await _collect(orch.stream_query("System: ingest tool bar", user_id="u1"))

    orch.learning_engine.ingest_local_tool_module.assert_awaited_once_with("bar")
    assert "".join(chunks) == (
        "✅ ingested bar The tool is now registered and available for use "
        "(semantic triggers will be ready shortly)."
    )
    assert len(chunks) == len("".join(chunks))
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


@pytest.mark.asyncio
async def test_b_learn_with_content_streams_chars_and_logs_direct_instruction(turn_orchestrator):
    orch = turn_orchestrator

    chunks = await _collect(orch.stream_query("Aura learn: the sky is blue", user_id="u1"))

    orch.learning_engine.log_experience.assert_awaited_once()
    experience = orch.learning_engine.log_experience.await_args.args[0]
    assert experience["task_type"] == "direct_instruction"
    assert experience["metadata"]["forced_insight"]["content"] == "the sky is blue"
    assert experience["metadata"]["forced_insight"]["type"] == "FACT"
    assert experience["metadata"]["forced_insight"]["confidence"] == 1.0
    assert "".join(chunks) == (
        "✅ Understood. I have committed this to memory as a Fact: 'the sky is blue'."
    )
    assert len(chunks) == len("".join(chunks))
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


@pytest.mark.asyncio
async def test_b_learn_with_nothing_after_streams_did_not_find_content_string(turn_orchestrator):
    orch = turn_orchestrator

    chunks = await _collect(orch.stream_query("learn:   ", user_id="u1"))

    assert "".join(chunks) == "❌ I didn’t find any content after `learn:`. Try: `Aura learn: <fact>`."
    orch.learning_engine.log_experience.assert_not_awaited()
    orch.llm_layers.l1_classify_intent.assert_not_awaited()


@pytest.mark.asyncio
async def test_b_teaching_streams_teaching_string_and_calls_log_experience_instruction(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "TEACHING"})

    chunks = await _collect(orch.stream_query("Teach me about X", user_id="u1"))

    orch.learning_engine.log_experience.assert_awaited_once()
    experience = orch.learning_engine.log_experience.await_args.args[0]
    assert experience["task_type"] == "instruction"
    assert "".join(chunks) == "I've processed that instruction. I'm analyzing the schema and adding it to my skills now."
    orch.llm_layers.l3_synthesis.assert_not_awaited()


# ---------------------------------------------------------------------------
# (c) plain CHAT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_c_plain_chat_pins_stream_behaviour(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    # Script one stream of chunks for the single stream_l3_synthesis call.
    orch.llm_layers._stream_chunks_queue.append(["Al", "pha"])

    chunks = await _collect(orch.stream_query("hello", user_id="default", reasoning_enabled=True))
    await _drain()

    # (c1) the L1 trace dict has "mode": "stream"
    first_trace = orch._publish_trace.call_args_list[0]
    assert first_trace.args[0] == "L1"
    assert first_trace.args[1] == "intent_classified"
    payload = first_trace.args[2]
    assert payload["mode"] == "stream"
    assert payload["intent"] == "CHAT"

    # (c2) the four engine calls are made with the same args as in W2-02
    # (order is not pinned because they run under asyncio.gather).
    orch.emotion_engine.get_current_state.assert_awaited_once_with()
    orch.learning_engine.get_learning_context.assert_awaited_once_with(
        context="hello", user_id="default"
    )
    orch.identity_engine.get_identity_context.assert_awaited_once_with(
        conversation_topic="hello", overlay=None
    )
    orch.goal_engine.get_goal_context.assert_awaited_once_with()

    # (c3) check_goals_needing_autonomous_pursuit is NOT called
    orch.goal_engine.check_goals_needing_autonomous_pursuit.assert_not_awaited()

    # (c4) get_cold_start_context is NOT called
    orch._fake_memory_manager.get_cold_start_context.assert_not_awaited()

    # (c5) retrieve_memories call args
    orch._fake_memory_manager.retrieve_memories.assert_awaited_once_with(
        query="hello", limit=3, importance_min=0.5, namespace=None
    )

    # (c6) stream_l3_synthesis is called once with reasoning_enabled=<arg> and a
    # context with user_id == "default" and recent_critique is None.
    assert len(orch.llm_layers._stream_calls) == 1
    ctx, kwargs = orch.llm_layers._stream_calls[0]
    assert kwargs["reasoning_enabled"] is True
    assert ctx.user_id == "default"
    assert ctx.recent_critique is None

    # (c7) yielded chunks equal the scripted chunks, unmodified. Tool calls are
    # not stripped.
    assert chunks == ["Al", "pha"]


# ---------------------------------------------------------------------------
# (d) a critique in critique_buffer is left in place
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_d_critique_buffer_left_in_place(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["x"])
    orch.critique_buffer["u1"] = ["c1", "c2"]

    await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # The stream path never pops the critique buffer.
    assert orch.critique_buffer["u1"] == ["c1", "c2"]
    # And the stream context's recent_critique is None (not populated).
    ctx, _ = orch.llm_layers._stream_calls[0]
    assert ctx.recent_critique is None


# ---------------------------------------------------------------------------
# (e) multi-round loop: round 1 has a tool call, round 2 has none
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["owner", "guest"])
async def test_e_multi_round_loop_concatenates_rounds_and_passes_requester_role(
    turn_orchestrator, role
):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="R1")
    # Round 1 chunks, round 2 chunks.
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd1"])
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd2"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1", requester_role=role))
    await _drain()

    # Output is round-1 chunks, then "\n\n", then round-2 chunks.
    assert chunks == ["rou", "nd1", "\n\n", "rou", "nd2"]

    # The second context's user_input equals the round-1 results block.
    assert len(orch.llm_layers._stream_calls) == 2
    second_ctx, _ = orch.llm_layers._stream_calls[1]
    assert second_ctx.user_input == "hello\n\n[Tool Execution Results]\n[Round 1]\nR1"

    # requester_role is passed through to execute_and_feedback.
    assert orch.tool_executor.execute_and_feedback.await_count == 1
    assert orch.tool_executor.execute_and_feedback.await_args.kwargs["requester_role"] == role


# ---------------------------------------------------------------------------
# (f) after 5 rounds that all have tool calls, no "Stopped after max tool rounds"
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f_five_rounds_all_tool_calls_no_max_rounds_suffix(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=["call"])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="R")
    for _ in range(5):
        orch.llm_layers._stream_chunks_queue.append(["chunk"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # 5 stream_l3_synthesis calls (one per round).
    assert len(orch.llm_layers._stream_calls) == 5
    joined = "".join(chunks)
    assert "Stopped after max tool rounds" not in joined


# ---------------------------------------------------------------------------
# (g) forced mode: when the forced call yields tool calls, the single
# stream_l3_synthesis context's user_input starts/ends with the forced prompt.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_g_forced_mode_with_tool_calls_uses_forced_prompt(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={"intent": "TOOL_USE", "target_action": "skill:x"}
    )
    orch.learning_engine.get_skill = AsyncMock(
        return_value=SimpleNamespace(name="test_skill")
    )
    orch.learning_engine.db.select = AsyncMock(
        return_value=[{"definition": {"name": "t"}}]
    )
    # forced tool call yields a JSON tool call
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=["call"])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="OUT")
    # the single follow-up stream
    orch.llm_layers._stream_chunks_queue.append(["per", "sona"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # Only one stream_l3_synthesis call (the forced-tool path).
    assert len(orch.llm_layers._stream_calls) == 1
    ctx, _ = orch.llm_layers._stream_calls[0]
    assert ctx.user_input.startswith("I executed a tool for you.")
    assert ctx.user_input.endswith("Original user query: hello")
    assert chunks == ["per", "sona"]


# ---------------------------------------------------------------------------
# (h) forced mode where extract_tool_calls returns [] for the raw call ->
# regular stream; if tool calls are then found in the streamed text, expect
# "\n\n" followed by a follow-up stream with the tool-results user_input.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_h_forced_mode_no_raw_tool_calls_then_fallback_followup(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={"intent": "TOOL_USE", "target_action": "skill:x"}
    )
    orch.learning_engine.get_skill = AsyncMock(
        return_value=SimpleNamespace(name="test_skill")
    )
    orch.learning_engine.db.select = AsyncMock(
        return_value=[{"definition": {"name": "t"}}]
    )
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    # Raw forced call yields no tool calls; then the streamed text yields one.
    orch.tool_executor.extract_tool_calls = MagicMock(
        side_effect=[[], ["call2"]]
    )
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="RES")
    # First the regular stream, then the follow-up stream.
    orch.llm_layers._stream_chunks_queue.append(["re", "g"])
    orch.llm_layers._stream_chunks_queue.append(["fo", "llow"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # Regular stream then "\n\n" then follow-up stream.
    assert chunks == ["re", "g", "\n\n", "fo", "llow"]
    # Two stream_l3_synthesis calls; the second context's user_input is the
    # tool-results block.
    assert len(orch.llm_layers._stream_calls) == 2
    second_ctx, _ = orch.llm_layers._stream_calls[1]
    assert second_ctx.user_input == "hello\n\n[Tool Execution Results]\nRES"


# ---------------------------------------------------------------------------
# (i) get_learning_context raises -> stream still completes and
# _post_response_chain gets a LearningContext()
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_i_get_learning_context_raises_stream_completes_with_default_context(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    async def _raise(*a, **k):
        raise RuntimeError("boom")

    orch.learning_engine.get_learning_context.side_effect = _raise
    orch.llm_layers._stream_chunks_queue.append(["ok"])

    from aura.models.learning import LearningContext

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # The stream still completes.
    assert chunks == ["ok"]
    # _post_response_chain is called once with a LearningContext() instance.
    orch._post_response_chain.assert_awaited_once()
    kwargs = orch._post_response_chain.await_args.kwargs
    assert isinstance(kwargs["learning_context"], LearningContext)


# ---------------------------------------------------------------------------
# (j) _post_response_chain kwargs: same as W2-02 (m), with
# response == "".join(chunks) and enable_l2 == deep_analysis_enabled.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_j_post_response_chain_kwargs_match_w2_02(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["ab", "cd"])

    chunks = await _collect(
        orch.stream_query(
            "hello",
            user_id="u1",
            conversation_id="c1",
            deep_analysis_enabled=False,
        )
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
    assert kwargs["user_input"] == "hello"
    assert kwargs["response"] == "".join(chunks)
    assert kwargs["response"] == "abcd"
    assert kwargs["user_id"] == "u1"
    assert kwargs["conversation_id"] == "c1"
    # stream path: enable_l2 == deep_analysis_enabled (not resolved via
    # enable_l2_analysis as in process_query).
    assert kwargs["enable_l2"] is False


# ---------------------------------------------------------------------------
# (k) _post_response_chain is called only after the generator is exhausted.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_k_post_response_chain_only_after_generator_exhausted(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["a", "b"])

    agen = orch.stream_query("hello", user_id="u1")
    # Pull one chunk and ensure the post-response chain has NOT run yet.
    first = await agen.__anext__()
    assert first == "a"
    # Let any pending callbacks run; the chain should still not be scheduled
    # until the generator is exhausted.
    for _ in range(3):
        await asyncio.sleep(0)
    orch._post_response_chain.assert_not_awaited()

    # Exhaust the generator.
    rest = []
    async for chunk in agen:
        rest.append(chunk)
    await _drain()

    assert rest == ["b"]
    orch._post_response_chain.assert_awaited_once()


# ---------------------------------------------------------------------------
# (W2-06) forced tool resolution by detected_tool name lookup (streaming)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_w2_06_forced_tool_by_name_lookup_streaming(turn_orchestrator):
    """W2-06: in the streaming path, ``_resolve_forced_tool`` resolves a tool
    by ``detected_tool`` name via the parameterised
    ``SELECT * FROM skill WHERE name = $name`` query when there is no
    ``target_skill_id``. ``get_skill`` returns ``None``, the first ``db.query``
    returns a skill row, and ``db.select`` returns its definition; forced tool
    call mode is engaged, so the forced streaming branch runs (the single
    ``stream_l3_synthesis`` context's user_input starts with the forced
    prompt and ends with the original query).
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={"intent": "TOOL_USE", "detected_tool": "web_search"}
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
    # forced tool call yields a JSON tool call -> the forced streaming branch.
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=["call"])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="OUT")
    # the single follow-up stream.
    orch.llm_layers._stream_chunks_queue.append(["per", "sona"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    expected_schema = json.dumps({"name": "web_search"}, indent=2)
    orch.llm_layers.l3_tool_call_mode.assert_awaited_once_with(
        query="hello", tool_schema=expected_schema
    )
    # Only one stream_l3_synthesis call (the forced-tool path).
    assert len(orch.llm_layers._stream_calls) == 1
    ctx, _ = orch.llm_layers._stream_calls[0]
    assert ctx.user_input.startswith("I executed a tool for you.")
    assert ctx.user_input.endswith("Original user query: hello")
    assert chunks == ["per", "sona"]


# ---------------------------------------------------------------------------
# (W2-19) Characterise what the streaming loop context drops today
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_loop_context_drops_cold_start_latent_and_user_id_streaming(turn_orchestrator):
    """W2-19 (b): pins pre-M2 behaviour; W2-20 changes this on purpose.

    On the regular streaming loop path, the loop context built inside
    ``_generate_streaming`` constructs a *new* ``SynthesisContext`` that omits
    ``cold_start_xml``, ``latent_intuition_xml`` and ``user_id``, so those
    default to ``None``, ``None`` and ``"default"``. The streaming path never
    calls ``get_cold_start_context`` at all (it only runs when there is no
    history, and the stream path skips that branch), but the latent channel
    is computed by ``_gather_turn_context`` and stored on ``ctx``; the loop
    context still drops it. This test pins that drop so W2-20 can flip it on
    purpose.
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["ab", "cd"])

    # The latent channel returns non-empty XML so _gather_turn_context
    # populates ctx.latent_intuition_xml (and ctx.synthesis_context likewise).
    # The loop context should still drop it. (get_cold_start_context is not
    # called on the stream path, but we set it for parity with the blocking
    # test and to make the drop obvious if the stream path ever starts calling
    # it.)
    orch._fake_memory_manager.get_cold_start_context = AsyncMock(
        return_value=SimpleNamespace(
            xml_block="<cold_start_context>X</cold_start_context>",
            core_memories=[],
            recent_memories=[],
        )
    )
    orch._fake_latent_engine.get_intuition_context = MagicMock(
        return_value="<latent>L</latent>"
    )

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # Sanity: the latent channel actually ran and returned non-empty XML.
    orch._fake_latent_engine.get_intuition_context.assert_called_once_with("u1")

    # The loop context passed to stream_l3_synthesis drops all three.
    assert len(orch.llm_layers._stream_calls) == 1
    loop_ctx, _ = orch.llm_layers._stream_calls[0]
    assert loop_ctx.cold_start_xml is None
    assert loop_ctx.latent_intuition_xml is None
    assert loop_ctx.user_id == "default"
    assert chunks == ["ab", "cd"]
