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

from aura.executor.tool_registry import ToolRecord
from aura.llm.provider import OpenRouterClient
from aura.llm.tool_calls import (
    ModelTurn,
    parse_openai_tool_calls,
    to_openai_tools,
)

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