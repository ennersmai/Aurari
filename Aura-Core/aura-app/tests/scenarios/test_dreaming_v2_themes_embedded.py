"""Embedded-SurrealDB tests for dream themes and entity summaries (card W4-10).

The real schema through the scenario runner's adapter, deterministic
embeddings, ``store_episode`` + ``write_facts`` with scripted extractions, a
``FakeClock`` and a scripted fake model client (never a real one). The client
records each prompt so a call can be told apart and its facts inspected.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from tests.scenarios.runner import (
    _START,
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    _build_dreaming,
)
from tests.scenarios.test_recall_entity_channel_embedded import _fact, _learn


class FakeClient:
    def __init__(self, reply: str = "A short scripted summary."):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, messages, model=None, temperature=0, **kwargs) -> str:
        self.prompts.append(messages[-1]["content"])
        return self.reply

    def count(self, kind: str) -> int:
        return sum(1 for p in self.prompts if f"about one {kind}" in p)


class _Layers:
    def __init__(self, client):
        self.client = client


@pytest.fixture
async def db(monkeypatch):
    for flag in ("dreaming_v2_enabled", "memory_v2_write_enabled"):
        monkeypatch.setattr(settings, flag, True)
    for name, value in (
        ("dreaming_theme_min_facts", 4),
        ("dreaming_theme_max_per_cycle", 10),
        ("dreaming_entity_summary_max_per_cycle", 10),
        ("dreaming_theme_summary_words", 80),
    ):
        monkeypatch.setattr(settings, name, value)
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


_WORDS = ["copper", "walnut", "granite", "linen", "cedar", "marble", "oak",
          "slate", "brass", "pine", "velvet", "maple", "quartz", "ivory"]


async def _learn_about(db, topic: str, n: int, venue="app", start=0):
    """``n`` facts about one entity (``topic``), each with its own words."""
    for i in range(start, start + n):
        text = f"{topic} {_WORDS[i]} {_WORDS[(i + 5) % 14]} {venue}"
        await _learn(
            db, HashedBagOfWordsEmbeddings(), text, venue=venue, conversation_id=text,
            entities=[{"name": topic, "type": "project", "surface": topic}],
            fact=_fact(content=text, about=[topic], subject=None, predicate=None, object=None),
        )


async def _dream(db, client):
    engine = _build_dreaming(db)
    engine.set_dependencies(llm_layers=_Layers(client))
    return await engine.enter_rem_sleep()


async def _themes(db):
    return await db.query("SELECT * FROM theme")


async def test_theme_created_once_then_updated_not_duplicated(db):
    client = FakeClient()
    await _learn_about(db, "Kitchen", 5)

    await _dream(db, client)
    themes = await _themes(db)
    assert len(themes) == 1
    assert themes[0]["visibility"] == "owner"
    assert themes[0]["fact_count"] == 5
    first_id = themes[0]["id"]
    assert themes[0]["content"] == "A short scripted summary."
    assert len(themes[0]["embedding"]) == 768
    assert client.count("topic") == 1

    await _dream(db, client)  # nothing changed: no new call, no new theme
    assert len(await _themes(db)) == 1
    assert client.count("topic") == 1

    set_clock(FakeClock(_START + timedelta(days=1)))
    await _learn_about(db, "Kitchen", 1, start=5)
    await _dream(db, client)
    themes = await _themes(db)
    assert len(themes) == 1 and themes[0]["id"] == first_id
    assert themes[0]["fact_count"] == 6
    assert client.count("topic") == 2
    members = await db.query("SELECT in FROM member_of WHERE out = $t", {"t": themes[0]["id"]})
    assert len(members) == 6


async def test_no_theme_mixes_visibilities(db):
    await _learn_about(db, "Garden", 4, venue="app")
    await _learn_about(db, "Garden", 4, venue="guild:g1/c1")
    client = FakeClient()

    await _dream(db, client)

    themes = await _themes(db)
    assert sorted(t["visibility"] for t in themes) == ["guild:g1", "owner"]
    for theme in themes:
        rows = await db.query(
            "SELECT in.visibility AS v FROM member_of WHERE out = $t", {"t": theme["id"]}
        )
        assert len(rows) == 4 and {r["v"] for r in rows} == {theme["visibility"]}


async def test_entity_summary_ignores_guild_and_private_facts(db):
    await _learn_about(db, "Garden", 2, venue="app")
    await _learn_about(db, "Garden", 1, venue="guild:g1/c1")
    await _learn_about(db, "Garden", 1, venue="dm:ana")
    client = FakeClient("Garden summary.")

    await _dream(db, client)

    prompts = [p for p in client.prompts if "about one entity" in p]
    assert len(prompts) == 1
    assert "app" in prompts[0] and "guild" not in prompts[0] and "dm:ana" not in prompts[0]
    row = (await db.query("SELECT summary, summary_updated_at FROM entity WHERE name = 'Garden'"))[0]
    assert row["summary"] == "Garden summary."
    assert row["summary_updated_at"] is not None

    # A newer guild fact alone does not make the entity stale; an owner one does.
    set_clock(FakeClock(_START + timedelta(days=1)))
    await _learn_about(db, "Garden", 1, venue="guild:g1/c1", start=10)
    await _dream(db, client)
    assert client.count("entity") == 1
    await _learn_about(db, "Garden", 1, venue="app", start=11)
    await _dream(db, client)
    assert client.count("entity") == 2


async def test_summary_is_trimmed_and_empty_reply_skips(db):
    await _learn_about(db, "Kitchen", 4)
    await _dream(db, FakeClient("   "))
    assert await _themes(db) == []
    row = (await db.query("SELECT summary, summary_updated_at FROM entity WHERE name = 'Kitchen'"))[0]
    assert row["summary"] is None and row["summary_updated_at"] is None

    await _dream(db, FakeClient("word " * 200))
    assert len((await _themes(db))[0]["content"].split()) == 80


async def test_caps_leave_the_rest_for_the_next_cycle(db, monkeypatch):
    monkeypatch.setattr(settings, "dreaming_theme_max_per_cycle", 1)
    monkeypatch.setattr(settings, "dreaming_entity_summary_max_per_cycle", 1)
    await _learn_about(db, "Kitchen", 4)
    await _learn_about(db, "Garden", 5)
    client = FakeClient()

    await _dream(db, client)
    assert len(await _themes(db)) == 1
    assert client.count("topic") == 1 and client.count("entity") == 1

    await _dream(db, client)
    assert len(await _themes(db)) == 2
    assert client.count("topic") == 2 and client.count("entity") == 2
    summarised = await db.query("SELECT name FROM entity WHERE summary != NONE")
    assert {r["name"] for r in summarised} == {"Kitchen", "Garden"}


async def test_ablation_flags_off_do_nothing(db, monkeypatch):
    await _learn_about(db, "Kitchen", 5)
    client = FakeClient()
    monkeypatch.setattr(settings, "dreaming_v2_enabled", False)
    await _dream(db, client)
    monkeypatch.setattr(settings, "dreaming_v2_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    await _dream(db, client)
    assert client.prompts == [] and await _themes(db) == []
