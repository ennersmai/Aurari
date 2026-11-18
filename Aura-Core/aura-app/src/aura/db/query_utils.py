"""Shared utilities for unpacking SurrealDB query results.

SurrealDB's query() method can return nested structures (list-of-lists,
flat lists, or single dicts). These helpers normalise the output into a
flat list of row dicts, which is what every caller expects.
"""

from __future__ import annotations

from typing import Any

try:
    from surrealdb import RecordID
except Exception:
    RecordID = None  # type: ignore[assignment,misc]


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


def to_record_id(thing: Any) -> Any:
    """Convert a ``\"table:id\"`` string to a SurrealDB ``RecordID``.

    The embedded SurrealDB engine (and strict server modes) treat the whole
    string ``\"memory:abc\"`` as a *table name* when it is bound to
    a parameter that the database expects to be a record id, so a string
    record id must be converted to a typed ``RecordID`` before being
    passed to ``UPDATE $mid`` / ``SELECT ... FROM $rid`` and similar
    queries.  This mirrors the inline conversion that already lives in
    ``api/routes/learning.py`` (the ``skill_ref`` block near
    "Ensure we query with a proper RecordID when possible").

    A ``\"table:id\"`` string with both a non-empty table and a non-empty
    id becomes ``RecordID(table, id)``.  Anything else — a value that is
    already a ``RecordID``, a bare table name like ``\"memory\"`` with no
    colon, or any non-string value — is returned unchanged.
    """
    if RecordID is not None and isinstance(thing, RecordID):
        return thing
    if isinstance(thing, str) and ":" in thing:
        table, _, rid = thing.partition(":")
        if table and rid and RecordID is not None:
            return RecordID(table, rid)
    return thing