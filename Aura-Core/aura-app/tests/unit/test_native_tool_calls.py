"""W2-36: native function calling in the model clients.

Agency PRD 5.2: tool schemas travel in the OpenAI-format ``tools`` parameter,
and structured calls come back on ``message.tool_calls`` (or streamed as
``delta.tool_calls`` fragments). Every test runs against an
``httpx.MockTransport``; no network is used.
"""

import json
import logging

import httpx
import pytest

from aura.config import settings
from aura.engines.recall.models import ContextPacket, RecallTrace
from aura.executor.tool_registry import ToolRecord
from aura.llm.layers import LLMLayers, SynthesisContext
from aura.llm.provider import OpenRouterClient
from aura.llm.tool_calls import (
    ModelTurn,
    parse_openai_tool_calls,
    to_openai_tools,
)
from aura.orchestrator.tool_loop import NativeCalls

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    }
]

MESSAGES = [{"role": "user", "content": "search for x"}]


async def _client_with(handler) -> OpenRouterClient:
    client = OpenRouterClient(api_key="test-key", base_url="http://test.local")
    await client.client.aclose()
    client.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


def _blocking_body(message: dict) -> bytes:
    return json.dumps({"choices": [{"message": message}]}).encode()


@pytest.mark.asyncio
async def test_blocking_tool_call_becomes_a_model_turn():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_blocking_body(
                {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": '{"query": "x"}',
                            },
                        }
                    ],
                }
            ),
        )

    client = await _client_with(handler)
    try:
        turn = await client.complete_with_tools(
            messages=MESSAGES, model="test/model", tools=TOOLS
        )
    finally:
        await client.client.aclose()

    assert isinstance(turn, ModelTurn)
    assert turn.text == ""
    assert turn.tool_calls == [
        {"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}
    ]


@pytest.mark.asyncio
async def test_streamed_arguments_in_three_fragments_join_into_one_call():
    events = [
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "c1",
                                "type": "function",
                                "function": {
                                    "name": "web_search",
                                    "arguments": '{"query":',
                                },
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "function": {"arguments": ' "x"'}}
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": "}"}}]
                    }
                }
            ]
        },
        {"choices": [{"delta": {}}]},
    ]
    body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode())

    client = await _client_with(handler)
    try:
        items = [
            item
            async for item in client.stream_with_tools(
                messages=MESSAGES, model="test/model", tools=TOOLS
            )
        ]
    finally:
        await client.client.aclose()

    tool_items = [item for item in items if item[0] == "tool_calls"]
    assert len(tool_items) == 1
    assert tool_items[0][1] == [
        {"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}
    ]
    # Any text yielded for this response is tagged as text.
    assert all(kind == "text" for kind, _ in items if kind != "tool_calls")


@pytest.mark.asyncio
async def test_malformed_argument_json_becomes_empty_arguments(caplog):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_blocking_body(
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "c1",
                            "type": "function",
                            "function": {
                                "name": "web_search",
                                "arguments": "{not valid json",
                            },
                        }
                    ],
                }
            ),
        )

    client = await _client_with(handler)
    try:
        with caplog.at_level(logging.WARNING):
            turn = await client.complete_with_tools(
                messages=MESSAGES, model="test/model", tools=TOOLS
            )
    finally:
        await client.client.aclose()

    assert turn.tool_calls == [{"tool": "web_search", "arguments": {}, "id": "c1"}]
    assert any("not valid JSON" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_request_payload_carries_tools_and_tool_choice():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=_blocking_body({"content": "plain"}))

    client = await _client_with(handler)
    try:
        turn = await client.complete_with_tools(
            messages=MESSAGES, model="test/model", tools=TOOLS
        )
    finally:
        await client.client.aclose()

    assert turn.text == "plain"
    assert turn.tool_calls == []
    assert seen[0]["tools"] == TOOLS
    assert seen[0]["tool_choice"] == "auto"


def test_to_openai_tools_maps_a_tool_record():
    record = ToolRecord(
        name="web_search",
        description="Search the web.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        transport="builtin",
        risk="read",
    )

    assert to_openai_tools([record]) == TOOLS


def test_parse_tool_calls_keeps_calls_with_bad_json():
    calls = parse_openai_tool_calls(
        [
            {
                "id": "c2",
                "function": {"name": "web_search", "arguments": "not json"},
            }
        ]
    )

    assert calls == [{"tool": "web_search", "arguments": {}, "id": "c2"}]


@pytest.mark.asyncio
async def test_complete_without_tools_still_returns_text():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_blocking_body({"content": "hello"}))

    client = await _client_with(handler)
    try:
        text = await client.complete(messages=MESSAGES, model="test/model")
    finally:
        await client.client.aclose()

    assert text == "hello"


# =============================================================================
# W2-37: layers use the native tools path only when l3_native_tools is on
# =============================================================================

def _record() -> ToolRecord:
    return ToolRecord(
        name="web_search",
        description="Search the web.",
        input_schema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        transport="builtin",
        risk="read",
    )


def _empty_packet() -> ContextPacket:
    from datetime import datetime, timezone

    return ContextPacket(
        stable_blocks=[],
        dynamic_blocks=[],
        abstain=False,
        trace=RecallTrace(
            turn_id="t",
            user_id="default",
            query="hi",
            created_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            budget_tokens=0,
            tokens_before=0,
            tokens_after=0,
            items=[],
            channel_errors={},
        ),
    )


class _ToolPathClient:
    """Records which layer method ran and what it received."""

    def __init__(self, error: Exception | None = None):
        self.calls: list[str] = []
        self.seen: list[dict] = []
        self.error = error

    async def complete(self, *, messages, model, **kwargs):
        self.calls.append("complete")
        self.seen.append({"messages": messages, **kwargs})
        return "text reply"

    async def complete_with_tools(self, *, messages, model, tools, **kwargs):
        self.calls.append("complete_with_tools")
        self.seen.append({"messages": messages, "tools": tools, **kwargs})
        if self.error is not None:
            raise self.error
        return ModelTurn(
            text="native reply",
            tool_calls=[
                {"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}
            ],
        )

    async def stream_complete(self, *, messages, model, **kwargs):
        self.calls.append("stream_complete")
        self.seen.append({"messages": messages, **kwargs})
        yield "text reply"

    async def stream_with_tools(self, *, messages, model, tools, **kwargs):
        self.calls.append("stream_with_tools")
        self.seen.append({"messages": messages, "tools": tools, **kwargs})
        yield ("text", "native ")
        yield (
            "tool_calls",
            [{"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}],
        )


def _layers_with(client) -> LLMLayers:
    layers = LLMLayers.__new__(LLMLayers)
    layers.client = client
    return layers


def _context() -> SynthesisContext:
    return SynthesisContext(
        user_input="hi",
        packet=_empty_packet(),
        offered_tools=[_record()],
    )


@pytest.mark.asyncio
async def test_flag_off_tools_call_complete_not_complete_with_tools(monkeypatch):
    monkeypatch.setattr(settings, "l3_native_tools", False)
    client = _ToolPathClient()
    layers = _layers_with(client)

    result = await layers.l3_synthesis(_context(), tools=[_record()])

    assert client.calls == ["complete"]
    assert result == "text reply"
    # The schemas still travel in the prompt when the flag is off.
    assert "<available_tools>" in client.seen[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_flag_on_tools_call_complete_with_tools(monkeypatch):
    monkeypatch.setattr(settings, "l3_native_tools", True)
    client = _ToolPathClient()
    layers = _layers_with(client)

    result = await layers.l3_synthesis(_context(), tools=[_record()])

    assert client.calls == ["complete_with_tools"]
    assert isinstance(result, ModelTurn)
    assert result.text == "native reply"
    assert result.tool_calls == [
        {"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}
    ]
    # The schemas move to the API parameter, out of the prompt.
    assert client.seen[0]["tools"] == to_openai_tools([_record()])
    assert "<available_tools>" not in client.seen[0]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_complete_with_tools_error_falls_back_to_complete(monkeypatch, caplog):
    monkeypatch.setattr(settings, "l3_native_tools", True)
    client = _ToolPathClient(error=RuntimeError("400 tools not supported"))
    layers = _layers_with(client)

    with caplog.at_level(logging.WARNING):
        result = await layers.l3_synthesis(_context(), tools=[_record()])

    assert client.calls == ["complete_with_tools", "complete"]
    assert result == "text reply"
    assert any("falling back" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_flag_on_stream_ends_with_native_calls_marker(monkeypatch):
    monkeypatch.setattr(settings, "l3_native_tools", True)
    client = _ToolPathClient()
    layers = _layers_with(client)

    items = [item async for item in layers.stream_l3_synthesis(
        _context(), tools=[_record()]
    )]

    assert client.calls == ["stream_with_tools"]
    assert items[0] == "native "
    assert isinstance(items[-1], NativeCalls)
    assert items[-1].calls == [
        {"tool": "web_search", "arguments": {"query": "x"}, "id": "c1"}
    ]
    assert "<available_tools>" not in client.seen[0]["messages"][0]["content"]