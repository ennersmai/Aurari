"""W2-10: tests for the unified ``_turn_pipeline``.

Behaviour PRD B0 (section 4.4) — the merge of ``process_query`` and
``stream_query`` into a single ``_turn_pipeline`` that both entry points
drive. These tests pin the pipeline's observable contract:

* (a) ``stream=False`` yields exactly one event, of kind ``done``.
* (b) ``stream=True`` yields ``delta`` events whose joined text equals what
  ``stream_query`` yields, then one ``done`` event.
* (c) With ``stream=True`` and a guest ``requester_role``, the role reaches
  ``execute_and_feedback``.

The tests drive the real ``Orchestrator._turn_pipeline`` through the
``turn_orchestrator`` fixture (see ``tests/conftest.py``), which wires every
engine and the LLM layers onto mocks so no database, LLM or network is
touched. They do not change ``src/``.

W2-02 and W2-03 remain unchanged and continue to pin ``process_query`` and
``stream_query`` end-to-end; this file pins the new pipeline seam directly.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helper: drain background tasks created by the pipeline's
# ``asyncio.create_task(self._post_response_chain(...))`` so they do not leak
# between tests or trip "Task was destroyed but it is pending" warnings.
# ---------------------------------------------------------------------------
async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def _collect(agen):
    """Collect all events from an async generator into a list."""
    out = []
    async for ev in agen:
        out.append(ev)
    return out


# ---------------------------------------------------------------------------
# (a) _turn_pipeline(stream=False) yields exactly one event, of kind "done".
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_turn_pipeline_blocking_yields_single_done_event(turn_orchestrator):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    events = await _collect(
        orch._turn_pipeline(
            "hello",
            "u1",
            None,
            stream=False,
            context_limit=None,
            enable_l2=True,
            conversation_id="c1",
            reasoning_enabled=False,
            l2_reasoning_enabled=False,
            session_id=None,
            context_mode="deep_work",
            requester_role="owner",
        )
    )
    await _drain()

    # Exactly one event, and it is a "done" carrying the response.
    assert len(events) == 1
    assert events[0].kind == "done"
    assert events[0].text == "resp"
    # No "delta" events were yielded.
    assert all(ev.kind != "delta" for ev in events)


# ---------------------------------------------------------------------------
# (b) stream=True deltas' joined text equals what stream_query yields, then
#     one "done" event.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_b_turn_pipeline_streaming_deltas_match_stream_query_then_done(
    turn_orchestrator,
):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="R1")
    # Round 1 chunks, round 2 chunks.
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd1"])
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd2"])

    # Drive _turn_pipeline(stream=True) and collect its events.
    pipeline_events = await _collect(
        orch._turn_pipeline(
            "hello",
            "u1",
            None,
            stream=True,
            context_limit=None,
            enable_l2=True,
            conversation_id="c1",
            reasoning_enabled=False,
            l2_reasoning_enabled=False,
            session_id=None,
            context_mode="deep_work",
            requester_role="owner",
        )
    )
    await _drain()

    # Re-queue the same scripted chunks for a fresh stream_query run on the
    # same orchestrator, then collect what stream_query yields.
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd1"])
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd2"])
    # extract_tool_calls needs a fresh side_effect (the previous one was
    # consumed by the pipeline run).
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])

    stream_chunks = []
    async for chunk in orch.stream_query("hello", user_id="u1"):
        stream_chunks.append(chunk)
    await _drain()

    # The delta events' joined text equals what stream_query yields.
    delta_texts = [ev.text for ev in pipeline_events if ev.kind == "delta"]
    assert "".join(delta_texts) == "".join(stream_chunks)
    # And the per-chunk sequence matches (one delta per stream_query chunk).
    assert delta_texts == stream_chunks

    # Exactly one "done" event, after all the deltas, carrying the accumulated
    # response (real chunks only, separators excluded — matching today's
    # full_response).
    done_events = [ev for ev in pipeline_events if ev.kind == "done"]
    assert len(done_events) == 1
    assert pipeline_events[-1].kind == "done"
    assert done_events[0].text == "round1round2"


# ---------------------------------------------------------------------------
# (c) With stream=True and a guest requester_role, the role reaches
#     execute_and_feedback.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_c_turn_pipeline_streaming_passes_guest_role_to_execute_and_feedback(
    turn_orchestrator,
):
    orch = turn_orchestrator
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.tool_executor.extract_tool_calls = MagicMock(side_effect=[["call"], []])
    orch.tool_executor.execute_and_feedback = AsyncMock(return_value="R1")
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd1"])
    orch.llm_layers._stream_chunks_queue.append(["rou", "nd2"])

    await _collect(
        orch._turn_pipeline(
            "hello",
            "u1",
            None,
            stream=True,
            context_limit=None,
            enable_l2=True,
            conversation_id="c1",
            reasoning_enabled=False,
            l2_reasoning_enabled=False,
            session_id=None,
            context_mode="deep_work",
            requester_role="guest",
        )
    )
    await _drain()

    # The guest requester_role reached execute_and_feedback.
    assert orch.tool_executor.execute_and_feedback.await_count == 1
    assert orch.tool_executor.execute_and_feedback.await_args.kwargs["requester_role"] == "guest"
