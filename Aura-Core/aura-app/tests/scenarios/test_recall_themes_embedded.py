"""Embedded-SurrealDB tests for theme recall (card W4-11).

Themes are made through the real dream path (``update_themes`` via
``enter_rem_sleep`` with a scripted fake client), then recalled through the
fact path with ``recall_themes_enabled``. The theme is a candidate in the
memories block, so the budget and trace treat it like a fact.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.recall import RecallEngine, RecallRequest
from tests.scenarios.runner import (
    _START,
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    StubLatentEngine,
    _build_dreaming,
)
from tests.scenarios.test_dreaming_v2_themes_embedded import FakeClient, _Layers
from tests.scenarios.test_recall_entity_channel_embedded import _fact, _learn, _manager

_SUMMARY = "The house renovation is progressing across kitchen bathroom roof and floors."
_JOBS = ["kitchen", "bathroom", "roof", "floors", "windows", "paint", "wiring", "plumbing",
         "garden", "garage", "stairs", "attic"]


@pytest.fixture
async def db(monkeypatch):
    for flag in (
        "dreaming_v2_enabled", "memory_v2_write_enabled", "recall_channels_enabled",
        "memory_v2_recall_enabled", "recall_themes_enabled",
    ):
        monkeypatch.setattr(settings, flag, True)
    embeddings = HashedBagOfWordsEmbeddings()
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: embeddings)
    set_clock(FakeClock(_START))
    database = EmbeddedSurrealDB()
    await database.connect()
    try:
        yield database
    finally:
        await database.close()
        set_clock(Clock())


async def _renovation(db, venue="app", n=12):
    """``n`` renovation facts, one every few days."""
    for i in range(n):
        set_clock(FakeClock(_START + timedelta(days=3 * i)))
        text = f"The house renovation {_JOBS[i]} work is {venue} step {i}"
        await _learn(
            db, HashedBagOfWordsEmbeddings(), text, venue=venue, conversation_id=text,
            entities=[{"name": "Renovation", "type": "project", "surface": "renovation"}],
            fact=_fact(content=text, about=["Renovation"], subject=None, predicate=None, object=None),
        )
    set_clock(FakeClock(_START + timedelta(days=3 * n + 4)))


async def _dream(db):
    engine = _build_dreaming(db)
    engine.set_dependencies(llm_layers=_Layers(FakeClient(_SUMMARY)))
    await engine.enter_rem_sleep()


async def _recall(db, question="how is the house renovation going?", venue="app", budget=100_000):
    engine = RecallEngine(memory_manager=_manager(db), latent_engine=StubLatentEngine())
    return await engine.recall(
        RecallRequest(
            user_id="owner", user_input=question, limit=5, include_cold_start=False,
            include_latent=False, token_budget=budget, venue=venue,
        )
    )


def _theme_items(packet):
    return [i for i in packet.trace.items if i.key.startswith("theme:")]


async def test_broad_question_gets_the_theme_line_first(db):
    await _renovation(db)
    await _dream(db)
    set_clock(FakeClock(_START + timedelta(days=40 + 4)))

    packet = await _recall(db)

    lines = packet.block_text("memories").splitlines()
    assert lines[0] == "<memories>"
    assert lines[1] == f'  <theme updated="4 days ago">{_SUMMARY}</theme>'
    assert sum("<fact " in line for line in lines) == 5
    (item,) = _theme_items(packet)
    assert item.fate == "kept" and item.source == "recall.themes"


async def test_guild_venue_never_gets_an_owner_theme(db):
    await _renovation(db)
    await _dream(db)
    await _renovation(db, venue="guild:g1/c1", n=2)

    packet = await _recall(db, venue="guild:g1/c1")

    assert "guild:g1/c1" in packet.block_text("memories")
    assert "<theme" not in packet.block_text("memories")
    assert _theme_items(packet) == []


async def test_token_budget_still_holds_with_a_theme(db):
    await _renovation(db)
    await _dream(db)
    full = await _recall(db)
    theme_tokens = _theme_items(full)[0].tokens
    budget = math.ceil(theme_tokens / settings.recall_share_memories) + 1

    packet = await _recall(db, budget=budget)

    block = next(b for b in packet.dynamic_blocks if b.kind == "memories")
    assert block.tokens <= int(budget * settings.recall_share_memories)
    assert "<theme" in block.text
    assert {i.fate for i in packet.trace.items} == {"kept", "over_budget"}
    assert _theme_items(packet)[0].fate == "kept"

    tiny = await _recall(db, budget=1)
    assert tiny.block_text("memories") is None
    assert _theme_items(tiny)[0].fate == "over_budget"


async def test_abstention_adds_no_theme(db, monkeypatch):
    monkeypatch.setattr(settings, "recall_abstain_enabled", True)
    await _renovation(db)
    await _dream(db)

    packet = await _recall(db, question="zebra quantum saxophone")

    assert 'abstain="true"' in packet.block_text("memories")
    assert _theme_items(packet) == []


async def test_ablation_flag_off_is_the_old_path(db, monkeypatch):
    await _renovation(db)
    await _dream(db)
    on = await _recall(db)
    monkeypatch.setattr(settings, "recall_themes_enabled", False)

    off = await _recall(db)

    assert "<theme" not in off.block_text("memories")
    assert _theme_items(off) == []
    assert off.block_text("memories").splitlines()[1:] == on.block_text("memories").splitlines()[2:]
