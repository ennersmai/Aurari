"""Embedded-SurrealDB test for the fact rerank (card W4-04)."""

from __future__ import annotations

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from tests.scenarios.runner import HashedBagOfWordsEmbeddings
from tests.scenarios.test_recall_entity_channel_embedded import (
    _START,
    _fact,
    _learn,
    _open_db,
    _recall,
)


@pytest.mark.asyncio
async def test_rerank_flag_off_keeps_fused_order_and_on_returns_the_facts(monkeypatch):
    monkeypatch.setattr(settings, "recall_channels_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_recall_enabled", True)

    db = await _open_db()
    set_clock(FakeClock(_START))
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        for i, thing in enumerate(["tea", "chess", "rain"]):
            await _learn(
                db, embeddings, f"I like {thing} a lot.", conversation_id=f"c{i}",
                fact=_fact(content=f"I like {thing} a lot.", subject="I",
                           predicate="like", object=thing, about=[]),
            )
        question = "what do I like? tea"

        monkeypatch.setattr(settings, "recall_rerank_enabled", False)
        off = await _recall(db, "app", question)
        off_keys = [i.key for i in sorted(off.trace.items, key=lambda i: i.rank)]
        scores = [i.fused_score for i in sorted(off.trace.items, key=lambda i: i.rank)]
        assert scores == sorted(scores, reverse=True)

        monkeypatch.setattr(settings, "recall_rerank_enabled", True)
        on = await _recall(db, "app", question)
        on_keys = {i.key for i in on.trace.items}
        assert on_keys == set(off_keys)
    finally:
        await db.close()
        set_clock(Clock())
