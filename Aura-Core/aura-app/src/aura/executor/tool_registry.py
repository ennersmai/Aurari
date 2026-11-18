"""Tool registry: one record per capability (agency PRD 5.1, card W2-28).

Every tool Aura can call is one ``ToolRecord`` with its schema, transport,
risk, health and rolling stats. Builtins are loaded from ``aura.tools.*``
modules, MCP and learned local tools come from ``skill`` rows. Schemas are
sanitised so no approval field can travel to a model or a tool call
(section 10 rule 3).
"""

import importlib
import logging
import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from aura.clock import get_clock

logger = logging.getLogger(__name__)

Transport = Literal["builtin", "mcp", "opencode", "http"]
Risk = Literal["read", "write", "execute", "send"]


@dataclass
class ToolHealth:
    status: Literal["online", "offline", "unknown"] = "unknown"
    last_check: datetime | None = None
    error: str | None = None


@dataclass
class ToolStats:
    calls: int = 0
    successes: int = 0
    latencies_ms: deque[float] = field(default_factory=lambda: deque(maxlen=50))

    @property
    def median_latency_ms(self) -> float | None:
        """Median of the recorded latencies, None when empty."""
        if not self.latencies_ms:
            return None
        return statistics.median(self.latencies_ms)

    @property
    def success_rate(self) -> float | None:
        """Successes / calls, None when no call was recorded."""
        if self.calls == 0:
            return None
        return self.successes / self.calls


@dataclass
class ToolRecord:
    name: str
    description: str
    input_schema: dict
    transport: Transport
    risk: Risk
    health: ToolHealth = field(default_factory=ToolHealth)
    stats: ToolStats = field(default_factory=ToolStats)
    source: str = ""  # module name, or the skill record id
    description_embedding: list[float] | None = None


# Risk of the builtin tools, by name (card step 3).
BUILTIN_RISK: dict[str, Risk] = {
    "read_file": "read",
    "list_directory": "read",
    "directory_tree": "read",
    "search_files": "read",
    "get_file_info": "read",
    "workspace_info": "read",
    "web_search": "read",
    "generate_chart": "read",
    "write_file": "write",
    "edit_file": "write",
    "create_directory": "write",
    "delete_file": "write",
    "terminal": "execute",
    "execute_code": "execute",
}

BUILTIN_MODULES = ("chartjs", "code_executor", "filesystem", "terminal", "web_search")


def _deep_copy(value: Any) -> Any:
    """Copy dicts and lists recursively; scalars are immutable."""
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


def _is_banned_key(key: Any) -> bool:
    """Approval fields never travel in a schema: `force_execute` and `_`-prefixed names."""
    return isinstance(key, str) and (key == "force_execute" or key.startswith("_"))


def _sanitize_object(node: dict) -> dict:
    """Clean one schema node (already deep-copied)."""
    cleaned = dict(node)

    properties = cleaned.get("properties")
    if isinstance(properties, dict):
        new_properties: dict = {}
        for prop_name, prop_schema in properties.items():
            if _is_banned_key(prop_name):
                continue
            if isinstance(prop_schema, dict) and prop_schema.get("type") == "object":
                prop_schema = _sanitize_object(prop_schema)
            new_properties[prop_name] = prop_schema
        cleaned["properties"] = new_properties

    required = cleaned.get("required")
    if isinstance(required, list):
        cleaned["required"] = [r for r in required if not _is_banned_key(r)]

    return cleaned


def sanitize_schema(schema: dict) -> dict:
    """Return a deep copy of ``schema`` without approval fields.

    Under ``properties``, the key ``force_execute`` and every key starting
    with ``_`` are removed, and the same names are removed from ``required``.
    Recurses into nested ``properties`` of object-typed properties.
    A non-dict input returns an empty object schema.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    return _sanitize_object(_deep_copy(schema))


def _schema_from_definition(definition: dict) -> dict:
    """The input schema of a tool definition, whatever key it is stored under.

    Builtin modules use ``parameters`` (terminal, web_search) or
    ``inputSchema`` (chartjs, code_executor, filesystem); skill rows store
    the same mix. The card's skill-row rule (step 5) is applied to builtins
    too, so the real schema is kept instead of an empty one.
    """
    for key in ("parameters", "inputSchema", "input_schema"):
        candidate = definition.get(key)
        if isinstance(candidate, dict):
            return candidate
    return {}


def load_builtin_tools() -> list[ToolRecord]:
    """Load one ToolRecord per builtin tool from the aura.tools modules."""
    records: list[ToolRecord] = []
    for module_name in BUILTIN_MODULES:
        try:
            module = importlib.import_module(f"aura.tools.{module_name}")
        except Exception as e:
            logger.warning(f"Tool registry: failed to import aura.tools.{module_name}: {e}")
            continue

        definitions: list[dict] = []
        tools_dict = getattr(module, "TOOLS", None)
        if isinstance(tools_dict, dict):
            for tool_spec in tools_dict.values():
                if isinstance(tool_spec, dict) and isinstance(tool_spec.get("definition"), dict):
                    definitions.append(tool_spec["definition"])
        else:
            tool_definition = getattr(module, "TOOL_DEFINITION", None)
            if isinstance(tool_definition, dict):
                definitions.append(tool_definition)

        for definition in definitions:
            name = definition.get("name")
            if not name:
                continue
            records.append(
                ToolRecord(
                    name=name,
                    description=definition.get("description", ""),
                    input_schema=sanitize_schema(_schema_from_definition(definition)),
                    transport="builtin",
                    risk=BUILTIN_RISK.get(name, "execute"),
                    source=module_name,
                    health=ToolHealth(status="online"),
                )
            )
    return records


def records_from_skill_rows(rows: list[dict]) -> list[ToolRecord]:
    """Turn `skill` rows (`mcp_tool` / `local_function`) into ToolRecords."""
    records: list[ToolRecord] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        skill_type = row.get("skill_type")
        if skill_type not in ("mcp_tool", "local_function"):
            continue
        definition = row.get("definition")
        if not isinstance(definition, dict):
            continue

        name = row.get("tool_name") or definition.get("name") or row.get("name")
        if not name:
            continue

        health = ToolHealth()
        if skill_type == "mcp_tool":
            transport: Transport = "mcp"
            # Do not guess MCP risk from risk_level; MCP tools are `execute`
            # until G3's policy table says otherwise.
            risk: Risk = "execute"
            execution_config = row.get("execution_config")
            if isinstance(execution_config, dict):
                status = execution_config.get("status")
                if status in ("online", "offline"):
                    health.status = status
                last_error = execution_config.get("last_error")
                if last_error:
                    health.error = str(last_error)
        else:
            transport = "builtin"
            risk = BUILTIN_RISK.get(name, "execute")

        records.append(
            ToolRecord(
                name=name,
                description=definition.get("description", ""),
                input_schema=sanitize_schema(_schema_from_definition(definition)),
                transport=transport,
                risk=risk,
                health=health,
                source=str(row.get("id") or ""),
                description_embedding=row.get("description_embedding"),
            )
        )
    return records


class ToolRegistry:
    """In-memory registry of every tool record."""

    def __init__(self) -> None:
        self._records: dict[str, ToolRecord] = {}

    def register(self, record: ToolRecord) -> None:
        """Add or replace a record; an existing record's stats are kept."""
        existing = self._records.get(record.name)
        if existing is not None:
            record.stats = existing.stats
        self._records[record.name] = record

    def get(self, name: str) -> ToolRecord | None:
        return self._records.get(name)

    def all(self) -> list[ToolRecord]:
        return sorted(self._records.values(), key=lambda r: r.name)

    def record_call(self, name: str, success: bool, latency_ms: float) -> None:
        """Record one call; a no-op for unknown names."""
        record = self._records.get(name)
        if record is None:
            return
        record.stats.calls += 1
        if success:
            record.stats.successes += 1
        record.stats.latencies_ms.append(latency_ms)

    def set_health(self, name: str, status: Literal["online", "offline", "unknown"], error: str | None = None) -> None:
        """Update a record's health, stamping last_check from the clock provider."""
        record = self._records.get(name)
        if record is None:
            return
        record.health = ToolHealth(status=status, last_check=get_clock().now(), error=error)

    async def refresh(self, db: Any) -> None:
        """Rebuild the registry: builtins first, then `skill` rows.

        A database error is logged at warning; the builtins stay.
        """
        for record in load_builtin_tools():
            self.register(record)

        try:
            rows = await db.query(
                "SELECT id, name, tool_name, skill_type, definition, execution_config, "
                "description_embedding FROM skill WHERE skill_type IN $types",
                {"types": ["mcp_tool", "local_function"]},
            )
        except Exception as e:
            logger.warning(f"Tool registry: failed to load skill rows: {e}")
            return

        for record in records_from_skill_rows(rows or []):
            if (
                record.transport == "builtin"
                and record.name in self._records
                and self._records[record.name].transport == "builtin"
            ):
                # A local_function row for a builtin: only copy the embedding.
                self._records[record.name].description_embedding = record.description_embedding
                continue
            self.register(record)


_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Return the process-wide registry, creating it on first use."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry


def reset_tool_registry() -> None:
    """Replace the process-wide registry (for tests)."""
    global _registry
    _registry = ToolRegistry()
