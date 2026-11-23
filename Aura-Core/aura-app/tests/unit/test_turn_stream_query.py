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
from aura.orchestrator.tool_loop import MAX_ROUNDS_SUFFIX
from tests.conftest import _TURN_FIXED_DATETIME


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

    # (c4) Recall Engine: the packet was assembled once (stream path).
    orch._fake_recall_engine.recall.assert_awaited_once()
    recall_request = orch._fake_recall_engine.recall.await_args.args[0]
    assert recall_request.user_input == "hello"
    assert recall_request.user_id == "default"
    assert recall_request.depth == 1
    assert recall_request.include_cold_start is False
    assert recall_request.learning_context is orch.learning_engine.get_learning_context.return_value

    # (c5) the memory/latent stores are no longer called from the coordinator.
    orch._fake_memory_manager.get_cold_start_context.assert_not_awaited()
    orch._fake_memory_manager.retrieve_memories.assert_not_awaited()

    # (c6) stream_l3_synthesis is called once with reasoning_enabled=<arg> and a
    # context with user_id == "default" and recent_critique is None.
    assert len(orch.llm_layers._stream_calls) == 1
    ctx, kwargs = orch.llm_layers._stream_calls[0]
    assert kwargs["reasoning_enabled"] is False  # P2-42: client value ignored
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
    """Multi-round streaming; changed on purpose by W2-33 (G1 single loop)."""
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

    # The stored response is the final round only.
    orch._post_response_chain.assert_awaited_once()
    assert orch._post_response_chain.await_args.kwargs["response"] == "round2"

    # The second context's user_input equals the round-1 results block.
    assert len(orch.llm_layers._stream_calls) == 2
    second_ctx, _ = orch.llm_layers._stream_calls[1]
    assert second_ctx.user_input == "hello\n\n[Tool Execution Results]\n[Round 1]\nR1"

    # requester_role is passed through to execute_and_feedback.
    assert orch.tool_executor.execute_and_feedback.await_count == 1
    assert orch.tool_executor.execute_and_feedback.await_args.kwargs["requester_role"] == role


# ---------------------------------------------------------------------------
# (f) after 5 rounds that all have tool calls, the max-rounds suffix is yielded
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_f_five_rounds_all_tool_calls_max_rounds_suffix(turn_orchestrator):
    """Five-round max-rounds behaviour; changed on purpose by W2-33 (G1 single loop)."""
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
    # One "\n\n" separator between each pair of rounds, and the suffix last.
    assert chunks.count("\n\n") == 4
    assert chunks[-1] == MAX_ROUNDS_SUFFIX


# ---------------------------------------------------------------------------
# (g) forced mode: the forced call seeds the loop
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_g_forced_mode_seeds_loop(turn_orchestrator):
    """Forced-mode seeding; changed on purpose by W2-33 (G1 single loop).

    changed on purpose by W2-38 (G1, keyword rule removed)
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={
            "intent": "TOOL_USE",
            "target_action": "skill:x",
            "routing_method": "vector_search",
        }
    )
    orch.learning_engine.get_skill = AsyncMock(
        return_value=SimpleNamespace(name="test_skill")
    )
    orch.learning_engine.db.select = AsyncMock(
        return_value=[{"definition": {"name": "t"}}]
    )
    # forced tool call yields a JSON tool call
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="OUT")
    # the single follow-up stream
    orch.llm_layers._stream_chunks_queue.append(["per", "sona"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    orch.llm_layers.l3_tool_call_mode.assert_awaited_once()
    # Only one stream_l3_synthesis call, with the seed as a tool-results block.
    assert len(orch.llm_layers._stream_calls) == 1
    ctx, _ = orch.llm_layers._stream_calls[0]
    assert ctx.user_input == "hello\n\n[Tool Execution Results]\n[Seed]\nOUT"
    assert chunks == ["per", "sona"]


# ---------------------------------------------------------------------------
# (h) forced mode where extract_tool_calls returns [] for the raw call ->
# plain stream loop; the tool call found in the streamed text starts round 2.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_h_forced_mode_no_raw_tool_calls_runs_plain_loop(turn_orchestrator):
    """Forced-mode fallback; changed on purpose by W2-33 (G1 single loop).

    changed on purpose by W2-38 (G1, keyword rule removed)
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(
        return_value={
            "intent": "TOOL_USE",
            "target_action": "skill:x",
            "routing_method": "vector_search",
        }
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
        side_effect=[[], ["call2"], []]
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
    assert second_ctx.user_input == "hello\n\n[Tool Execution Results]\n[Round 1]\nRES"


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
        # W3-12: the post-response chain receives the turn's venue/speaker.
        "venue", "speaker",
        # W4-06: and the turn's recall packet, for feedback.
        "packet",
        # W3-22: the post-response chain receives conversation_history for appraisal.
        "conversation_history",
    }
    assert set(kwargs.keys()) == expected_keys
    assert kwargs["venue"] == "app"
    assert kwargs["speaker"] == "owner"
    assert kwargs["user_input"] == "hello"
    assert kwargs["response"] == "".join(chunks)
    assert kwargs["response"] == "abcd"
    assert kwargs["user_id"] == "u1"
    assert kwargs["conversation_id"] == "c1"
    # P2-42: the client flag is ignored; flag off means enable_l2 True.
    assert kwargs["enable_l2"] is True


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
    call mode seeds the loop, so the single ``stream_l3_synthesis`` context's
    user_input carries the seed results.

    changed on purpose by W2-33 (G1 single loop)

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
    # forced tool call yields a JSON tool call -> it seeds the loop.
    orch.llm_layers.l3_tool_call_mode = AsyncMock(return_value='{"tool":"t"}')
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="OUT")
    # the single follow-up stream.
    orch.llm_layers._stream_chunks_queue.append(["per", "sona"])

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    expected_schema = json.dumps({"name": "web_search"}, indent=2)
    orch.llm_layers.l3_tool_call_mode.assert_awaited_once_with(
        query="hello", tool_schema=expected_schema
    )
    # Only one stream_l3_synthesis call, with the seed as a tool-results block.
    assert len(orch.llm_layers._stream_calls) == 1
    ctx, _ = orch.llm_layers._stream_calls[0]
    assert ctx.user_input == "hello\n\n[Tool Execution Results]\n[Seed]\nOUT"
    assert chunks == ["per", "sona"]


# ---------------------------------------------------------------------------
# (W2-19/20) The streaming loop context carries the Recall packet
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_loop_context_carries_packet_streaming(turn_orchestrator):
    """W2-19 (b) -> W2-20: the streaming loop context carries the Recall packet.

    Previously (pre-M2) the streaming loop context built a new
    ``SynthesisContext`` that dropped ``cold_start_xml``,
    ``latent_intuition_xml`` and ``user_id``. W2-20 routes the turn through
    the Recall Engine, so the loop context now carries the packet the engine
    returned. This test pins that carry so a later card does not silently drop
    it again.
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["ab", "cd"])

    # Replace the fixture's empty packet with one carrying a latent block so
    # the carry is observable.
    from aura.engines.recall.models import Block, ContextPacket, RecallTrace
    packet = ContextPacket(
        stable_blocks=[],
        dynamic_blocks=[Block(kind="latent", text="<latent>L</latent>", tokens=1, stable=False)],
        abstain=False,
        trace=RecallTrace(
            turn_id="t", user_id="u1", query="hello",
            created_at=_TURN_FIXED_DATETIME,
            budget_tokens=0, tokens_before=0, tokens_after=0,
            items=[], channel_errors={},
        ),
    )
    orch._fake_recall_engine.recall = AsyncMock(return_value=packet)

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # The loop context passed to stream_l3_synthesis carries the packet.
    assert len(orch.llm_layers._stream_calls) == 1
    loop_ctx, _ = orch.llm_layers._stream_calls[0]
    assert loop_ctx.packet is packet
    assert chunks == ["ab", "cd"]


# ---------------------------------------------------------------------------
# (BF-04) IdentityContext fallback fixes
# ---------------------------------------------------------------------------
# BF-04: the streaming branch builds IdentityContext in two fallback places
# (timeout fallback and per-result fallback). Both previously used invalid
# fields (core_identity, tone_and_style). The fix replaces them with the
# valid fields (narrative, core_values). These tests force each fallback
# and verify the L3 context gets a valid IdentityContext with the expected
# narrative.

@pytest.mark.asyncio
async def test_bf_04_identity_fallback_per_result_raises(turn_orchestrator):
    """BF-04(a): identity_engine.get_identity_context raises -> per-result
    fallback constructs IdentityContext(narrative="I am Aura.", core_values={}).
    The stream completes and the loop context's identity_context has the
    expected narrative.
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["ok"])

    # Make identity_engine.get_identity_context raise an exception
    async def _raise_identity(*a, **k):
        raise RuntimeError("identity engine down")

    orch.identity_engine.get_identity_context.side_effect = _raise_identity

    chunks = await _collect(orch.stream_query("hello", user_id="u1"))
    await _drain()

    # Stream completes
    assert chunks == ["ok"]

    # The loop context passed to stream_l3_synthesis has a valid
    # IdentityContext with the expected narrative.
    assert len(orch.llm_layers._stream_calls) == 1
    loop_ctx, _ = orch.llm_layers._stream_calls[0]
    assert loop_ctx.identity_context.narrative == "I am Aura."
    assert loop_ctx.identity_context.core_values == {}


@pytest.mark.asyncio
async def test_bf_04_identity_fallback_timeout(turn_orchestrator, monkeypatch):
    """BF-04(b): context gathering times out (asyncio.wait_for raises
    TimeoutError) -> timeout fallback constructs IdentityContext(narrative="I am Aura.", core_values={}).
    The stream completes and the loop context's identity_context has the
    expected narrative.
    """
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    orch.llm_layers._stream_chunks_queue.append(["ok"])

    # Patch asyncio.wait_for to immediately raise TimeoutError
    original_wait_for = asyncio.wait_for

    async def _timeout_wait_for(coro, timeout):
        raise asyncio.TimeoutError("forced timeout for test")

    monkeypatch.setattr(asyncio, "wait_for", _timeout_wait_for)

    try:
        chunks = await _collect(orch.stream_query("hello", user_id="u1"))
        await _drain()

        # Stream completes
        assert chunks == ["ok"]

        # The loop context passed to stream_l3_synthesis has a valid
        # IdentityContext with the expected narrative.
        assert len(orch.llm_layers._stream_calls) == 1
        loop_ctx, _ = orch.llm_layers._stream_calls[0]
        assert loop_ctx.identity_context.narrative == "I am Aura."
        assert loop_ctx.identity_context.core_values == {}
    finally:
        # Restore original wait_for
        monkeypatch.setattr(asyncio, "wait_for", original_wait_for)
