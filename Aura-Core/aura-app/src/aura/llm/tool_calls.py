"""Native function calling: OpenAI-format tool schemas and tool-call parsing.

Agency PRD 5.2: tool schemas travel through the model API's ``tools``
parameter and structured calls come back in the response. The calls use the
same ``{"tool": name, "arguments": {...}}`` shape ``extract_tool_calls``
returns, so the tool executor needs no change; ``id`` is carried along for
providers that report one.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Iterable

logger = logging.getLogger(__name__)


@dataclass
class ModelTurn:
    """One model response: its text and any native tool calls."""

    text: str
    tool_calls: list[dict]
    cost: float = 0.0  # USD for this call when the provider reports it (OpenRouter usage.cost)


def to_openai_tools(records: Iterable[Any]) -> list[dict]:
    """Map ``ToolRecord``s to OpenAI ``tools`` entries.

    Records are duck-typed (``name``, ``description``, ``input_schema``) so
    this module does not import the registry.
    """
    return [
        {
            "type": "function",
            "function": {
                "name": record.name,
                "description": record.description,
                "parameters": record.input_schema,
            },
        }
        for record in records
    ]


def _parse_arguments(name: str, raw: Any) -> dict:
    """Parse an OpenAI ``arguments`` value, keeping the call on bad JSON."""
    if isinstance(raw, dict):
        return raw
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return {}
    try:
        arguments = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        logger.warning(
            "Tool call %r had arguments that are not valid JSON; using {}: %r",
            name,
            raw,
        )
        return {}
    if not isinstance(arguments, dict):
        logger.warning(
            "Tool call %r had JSON arguments that are not an object; using {}: %r",
            name,
            raw,
        )
        return {}
    return arguments


def _to_call(name: str, arguments: Any, call_id: str) -> dict:
    return {
        "tool": name,
        "arguments": _parse_arguments(name, arguments),
        "id": call_id or "",
    }


def parse_openai_tool_calls(raw: Any) -> list[dict]:
    """Parse ``message.tool_calls`` into executor-shaped calls.

    Malformed argument JSON becomes ``{}`` with a warning, and the call is
    kept so the executor's repair can run.
    """
    calls: list[dict] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        function = entry.get("function") or {}
        if not isinstance(function, dict):
            function = {}
        name = function.get("name") or ""
        calls.append(
            _to_call(
                name if isinstance(name, str) else str(name),
                function.get("arguments"),
                entry.get("id") or "",
            )
        )
    return calls


class StreamToolCallAccumulator:
    """Join streamed ``delta.tool_calls`` fragments by index."""

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, str]] = {}

    def add(self, fragments: Any) -> None:
        """Append one delta's fragments (``delta.tool_calls``)."""
        for position, entry in enumerate(fragments or []):
            if not isinstance(entry, dict):
                continue
            index = entry.get("index", position)
            if not isinstance(index, int):
                index = position
            part = self._parts.setdefault(
                index, {"id": "", "name": "", "arguments": ""}
            )
            if entry.get("id") and not part["id"]:
                part["id"] = str(entry["id"])
            function = entry.get("function") or {}
            if not isinstance(function, dict):
                continue
            name = function.get("name")
            if name:
                part["name"] += name if isinstance(name, str) else str(name)
            arguments = function.get("arguments")
            if arguments:
                part["arguments"] += (
                    arguments if isinstance(arguments, str) else json.dumps(arguments)
                )

    def calls(self) -> list[dict]:
        """The joined calls, in index order."""
        return [
            _to_call(part["name"], part["arguments"], part["id"])
            for _, part in sorted(self._parts.items())
        ]