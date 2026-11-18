"""Shared utilities for unpacking SurrealDB query results.

SurrealDB's query() method can return nested structures (list-of-lists,
flat lists, or single dicts). These helpers normalise the output into a
flat list of row dicts, which is what every caller expects.
"""

from __future__ import annotations

from typing import Any


def extract_rows(result: Any) -> list[dict[str, Any]]:
    """Normalise SurrealDB query() output into a flat list of row dicts."""
    out: list[dict[str, Any]] = []
    if isinstance(result, dict):
        return [result]
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                out.append(item)
            elif isinstance(item, list):
                out.extend(r for r in item if isinstance(r, dict))
    return out


def strip_record_id(row: dict[str, Any]) -> dict[str, Any]:
    """Drop the SurrealDB 'id' field before Pydantic parsing."""
    if not isinstance(row, dict):
        return {}
    return {k: v for k, v in row.items() if k != "id"}
