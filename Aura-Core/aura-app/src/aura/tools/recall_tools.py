"""Recall tools over memory v2 (card W4-05, memory PRD 6.4).

``recall``, ``timeline``, ``evidence`` and ``what_changed`` read; ``pin`` and
``unpin`` write and are owner-only. Every tool reads only what the caller's
venue may see. The executor puts the venue and the caller's role in the
reserved ``_venue`` and ``_requester_role`` arguments, which a model cannot
set; each tool returns plain text.
"""

from typing import Any, Dict

from aura.clock import get_clock
from aura.engines.recall.engine import get_recall_engine
from aura.engines.recall.timeexpr import parse_range

_FACT_ID = {"fact_id": {"type": "string", "description": "A fact id, e.g. fact:abc123."}}


def _caller_venue(arguments: Dict[str, Any]) -> str:
    """The caller's venue; a non-owner never reads with the owner's ``app`` venue.

    ``app`` is the executor's default, so a non-owner arriving with it means a
    call site did not pass its venue: refuse rather than show owner memory.
    """
    venue = arguments.get("_venue") or "app"
    if venue == "app" and arguments.get("_requester_role") != "owner":
        raise PermissionError("recall tools need the caller's venue")
    return venue


def _definition(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


def _day(value: Any) -> str:
    return value.strftime("%Y-%m-%d")


async def recall_run(arguments: Dict[str, Any]) -> str:
    query = (arguments.get("query") or "").strip()
    if not query:
        return "Error: 'query' is required."
    facts = await get_recall_engine().recall_facts(
        query, _caller_venue(arguments), arguments.get("filters")
    )
    if not facts:
        return "No matching facts."
    return "\n".join(
        f"{f['id']} [{f['provenance']}, confidence {float(f['confidence']):.2f}, "
        f"{_day(f['recorded_at'])}] {f['content']}"
        for f in facts
    )


async def timeline_run(arguments: Dict[str, Any]) -> str:
    entity = (arguments.get("entity") or "").strip() or None
    date_range = (arguments.get("date_range") or "").strip()
    time_range = parse_range(date_range, get_clock().now()) if date_range else None
    if date_range and time_range is None:
        return f"Error: could not read a date range from '{date_range}'."
    if entity is None and time_range is None:
        return "Error: give an 'entity' or a 'date_range'."
    entries = await get_recall_engine().timeline(
        venue=_caller_venue(arguments), entity=entity, time_range=time_range
    )
    if not entries:
        return "Nothing on the timeline."
    return "\n".join(
        f"{_day(e['at'])} {e['kind']} {e['id']}: {e['text']}" for e in entries
    )


async def evidence_run(arguments: Dict[str, Any]) -> str:
    fact_id = (arguments.get("fact_id") or "").strip()
    if not fact_id:
        return "Error: 'fact_id' is required."
    episodes = await get_recall_engine().evidence(fact_id, venue=_caller_venue(arguments))
    if not episodes:
        return f"No evidence found for {fact_id}."
    return "\n".join(
        f"{_day(e['recorded_at'])} {e['id']}: {e['user_text']}" for e in episodes
    )


async def what_changed_run(arguments: Dict[str, Any]) -> str:
    entity = (arguments.get("entity") or "").strip()
    if not entity:
        return "Error: 'entity' is required."
    chains = await get_recall_engine().what_changed(entity, _caller_venue(arguments))
    if not chains:
        return f"No changes recorded about {entity}."
    return "\n".join(
        " -> ".join(f"{f['content']} ({_day(f['recorded_at'])})" for f in chain)
        for chain in chains
    )


async def _set_pinned(arguments: Dict[str, Any], pinned: bool) -> str:
    if arguments.get("_requester_role") != "owner":
        return "Error: only the owner can pin or unpin facts."
    fact_id = (arguments.get("fact_id") or "").strip()
    if not fact_id:
        return "Error: 'fact_id' is required."
    if not await get_recall_engine().set_pinned(fact_id, _caller_venue(arguments), pinned):
        return f"No fact {fact_id} found."
    return f"{'Pinned' if pinned else 'Unpinned'} {fact_id}."


async def pin_run(arguments: Dict[str, Any]) -> str:
    return await _set_pinned(arguments, True)


async def unpin_run(arguments: Dict[str, Any]) -> str:
    return await _set_pinned(arguments, False)


TOOLS = {
    "recall": {
        "definition": _definition(
            "recall",
            "Search memory for facts, ranked, with their provenance and confidence.",
            {
                "query": {"type": "string", "description": "What to look for."},
                "filters": {
                    "type": "object",
                    "description": "Optional: kind and/or provenance a fact must have.",
                    "properties": {"kind": {"type": "string"}, "provenance": {"type": "string"}},
                },
            },
            ["query"],
        ),
        "run": recall_run,
    },
    "timeline": {
        "definition": _definition(
            "timeline",
            "List remembered conversations and facts in time order, for an entity "
            "and/or a date range such as 'last week' or '2026-11-02'.",
            {
                "entity": {"type": "string", "description": "An entity name."},
                "date_range": {"type": "string", "description": "A time expression."},
            },
            [],
        ),
        "run": timeline_run,
    },
    "evidence": {
        "definition": _definition(
            "evidence", "Show the conversations a fact was learned from.", _FACT_ID, ["fact_id"]
        ),
        "run": evidence_run,
    },
    "what_changed": {
        "definition": _definition(
            "what_changed",
            "Show how facts about an entity changed over time, oldest first.",
            {"entity": {"type": "string", "description": "An entity name."}},
            ["entity"],
        ),
        "run": what_changed_run,
    },
    "pin": {
        "definition": _definition(
            "pin", "Pin a fact so it is not forgotten (owner only).", _FACT_ID, ["fact_id"]
        ),
        "run": pin_run,
    },
    "unpin": {
        "definition": _definition(
            "unpin", "Unpin a fact (owner only).", _FACT_ID, ["fact_id"]
        ),
        "run": unpin_run,
    },
}
