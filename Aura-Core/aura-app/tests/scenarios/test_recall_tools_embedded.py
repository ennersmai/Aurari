"""Embedded-SurrealDB tests for the recall tools (card W4-05).

Seeds facts and edges through ``store_episode`` + ``write_facts`` and calls each
tool with the reserved ``_venue`` / ``_requester_role`` arguments the executor
sets. A guest venue must never see an owner fact through any tool.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.recall import RecallEngine
from aura.tools import recall_tools
from tests.scenarios.runner import HashedBagOfWordsEmbeddings, StubLatentEngine
from tests.scenarios.test_recall_entity_channel_embedded import (
    _fact,
    _learn,
    _manager,
    _open_db,
)

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
_GUEST = "guild:99/channel:7"
_ANA = {"name": "Ana", "type": "person", "surface": "Ana"}


def _args(venue: str = "app", role: str = "owner", **kwargs) -> dict:
    return {"_venue": venue, "_requester_role": role, **kwargs}


async def _seed(db, monkeypatch):
    """Ana lived in Lisbon, then Porto (owner); a guild fact about Ana's cat."""
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)
    monkeypatch.setattr(
        recall_tools,
        "get_recall_engine",
        lambda: RecallEngine(memory_manager=_manager(db), latent_engine=StubLatentEngine()),
    )
    embeddings = HashedBagOfWordsEmbeddings()
    clock = FakeClock(_START)
    set_clock(clock)
    ids = {}
    for key, text, obj in (
        ("lisbon", "Ana lives in Lisbon.", "Lisbon"),
        ("porto", "Ana lives in Porto.", "Porto"),
    ):
        clock.advance(86400)
        ids[key] = (await _learn(
            db, embeddings, text, conversation_id=key, entities=[_ANA],
            fact=_fact(content=text, subject="Ana", predicate="lives in",
                       object=obj, about=["Ana"]),
        ))[0]
    ids["cat"] = (await _learn(
        db, embeddings, "Ana's cat is called Miso.", venue=_GUEST,
        conversation_id="g1", entities=[_ANA],
        fact=_fact(content="Ana's cat is called Miso.", subject="Ana",
                   predicate="has cat", object="Miso", about=["Ana"]),
    ))[0]
    return {k: str(v) for k, v in ids.items()}


@pytest.mark.asyncio
async def test_each_tool_on_seeded_facts(monkeypatch):
    db = await _open_db()
    try:
        ids = await _seed(db, monkeypatch)

        out = await recall_tools.recall_run(_args(query="where does Ana live Porto"))
        assert "Ana lives in Porto." in out and ids["porto"] in out
        assert "miso" not in out.lower()

        out = await recall_tools.what_changed_run(_args(entity="ANA"))
        assert out.index("Lisbon") < out.index("Porto")
        assert "->" in out

        out = await recall_tools.evidence_run(_args(fact_id=ids["porto"]))
        assert "Ana lives in Porto." in out and "Lisbon" not in out

        out = await recall_tools.timeline_run(_args(entity="Ana"))
        assert out.index("Lisbon") < out.index("Porto")
        assert "episode" in out and "fact" in out and "Miso" not in out

        out = await recall_tools.timeline_run(_args(date_range="2026-01-02"))
        assert "Lisbon" in out or "Porto" in out

        assert "Pinned" in await recall_tools.pin_run(_args(fact_id=ids["porto"]))
        rows = await db.query("SELECT pinned FROM fact WHERE content = 'Ana lives in Porto.'")
        assert rows[0]["pinned"] is True
        assert "Unpinned" in await recall_tools.unpin_run(_args(fact_id=ids["porto"]))
        rows = await db.query("SELECT pinned FROM fact WHERE content = 'Ana lives in Porto.'")
        assert rows[0]["pinned"] is False
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_guest_venue_cannot_see_owner_facts_through_any_tool(monkeypatch):
    db = await _open_db()
    try:
        ids = await _seed(db, monkeypatch)
        guest = {"venue": _GUEST, "role": "guest"}

        out = await recall_tools.recall_run(_args(query="Ana lives in Porto Lisbon", **guest))
        assert "Porto" not in out and "Lisbon" not in out

        out = await recall_tools.timeline_run(_args(entity="Ana", **guest))
        assert "Porto" not in out and "Lisbon" not in out and "Miso" in out

        out = await recall_tools.what_changed_run(_args(entity="Ana", **guest))
        assert "Porto" not in out and "Lisbon" not in out

        for key in ("porto", "lisbon"):
            out = await recall_tools.evidence_run(_args(fact_id=ids[key], **guest))
            assert out == f"No evidence found for {ids[key]}."

        # Even an owner-role call from the guest venue cannot pin an owner fact.
        out = await recall_tools.pin_run(_args(venue=_GUEST, fact_id=ids["porto"]))
        assert out.startswith("No fact")
        rows = await db.query("SELECT pinned FROM fact WHERE content = 'Ana lives in Porto.'")
        assert rows[0]["pinned"] is False
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_guest_cannot_pin_even_a_fact_it_can_see(monkeypatch):
    db = await _open_db()
    try:
        ids = await _seed(db, monkeypatch)
        out = await recall_tools.pin_run(_args(venue=_GUEST, role="guest", fact_id=ids["cat"]))
        assert "only the owner" in out
        out = await recall_tools.unpin_run(_args(venue=_GUEST, role="guest", fact_id=ids["cat"]))
        assert "only the owner" in out
        rows = await db.query("SELECT pinned FROM fact WHERE content = \"Ana's cat is called Miso.\"")
        assert rows[0]["pinned"] is False
    finally:
        await db.close()
        set_clock(Clock())
