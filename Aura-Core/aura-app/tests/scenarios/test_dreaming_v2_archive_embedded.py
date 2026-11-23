"""Embedded-SurrealDB tests for archiving in the dream cycle (card W4-09).

The real schema through the scenario runner's adapter, the runner's
deterministic embeddings, ``store_episode`` + ``write_facts`` with scripted
extractions, and a ``FakeClock``. Nothing is deleted; archived rows are only
hidden from the v2 read paths. A fact counts as found only when it carries a
channel rank in the recall trace.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.recall import RecallEngine, RecallRequest
from aura.engines.recall.channels import (
    fact_dense_channel,
    fact_entity_channel,
    fact_graph_channel,
    fact_lexical_channel,
    fact_temporal_channel,
)
from aura.tools.recall_tools import what_changed_run
from tests.scenarios.runner import (
    _START,
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    StubLatentEngine,
    _build_dreaming,
)
from tests.scenarios.test_recall_entity_channel_embedded import (
    _fact,
    _learn,
    _manager,
)

_ANA = {"name": "Ana", "type": "person", "surface": "Ana"}


@pytest.fixture
async def db(monkeypatch):
    for flag in (
        "dreaming_v2_enabled",
        "memory_v2_write_enabled",
        "memory_v2_recall_enabled",
        "recall_channels_enabled",
        "recall_entity_channel_enabled",
        "recall_temporal_channel_enabled",
        "recall_graph_channel_enabled",
    ):
        monkeypatch.setattr(settings, flag, True)
    monkeypatch.setattr(settings, "dreaming_archive_superseded_days", 90)
    monkeypatch.setattr(settings, "dreaming_archive_ephemeral_days", 7)
    set_clock(FakeClock(_START))
    database = EmbeddedSurrealDB()
    await database.connect()
    try:
        yield database
    finally:
        await database.close()
        set_clock(Clock())


async def _learn_fact(db, text: str, *, entities=None, about=None, **kw):
    ids = await _learn(
        db, HashedBagOfWordsEmbeddings(), text, conversation_id=text,
        entities=entities,
        fact=_fact(content=text, about=about or [], **kw),
    )
    return ids[0]


async def _supersede(db, fact_id, days_ago: float) -> None:
    await db.query(
        "UPDATE $f SET valid_to = $t",
        {"f": fact_id, "t": _START - timedelta(days=days_ago)},
    )


async def _archived(db, table: str) -> dict[str, bool]:
    text = "content" if table == "fact" else "user_text"
    rows = await db.query(f"SELECT {text} AS text, archived FROM {table}")
    return {r["text"]: r["archived"] for r in rows}


async def _dream(db):
    return await _build_dreaming(db).enter_rem_sleep()


async def test_superseded_facts_archived_by_age_and_pin(db):
    old = await _learn_fact(db, "I live in Lisbon.")
    pinned = await _learn_fact(db, "I live in Porto.")
    recent = await _learn_fact(db, "I live in Faro.")
    await _learn_fact(db, "I live in Braga.")
    await _supersede(db, old, 91)
    await _supersede(db, pinned, 91)
    await _supersede(db, recent, 89)
    await db.query("UPDATE $f SET pinned = true", {"f": pinned})

    await _dream(db)

    assert await _archived(db, "fact") == {
        "I live in Lisbon.": True,
        "I live in Porto.": False,
        "I live in Faro.": False,
        "I live in Braga.": False,
    }


async def test_ephemeral_episodes_archived_and_nothing_deleted(db):
    embeddings = HashedBagOfWordsEmbeddings()
    set_clock(FakeClock(_START - timedelta(days=8)))
    await _learn_fact(db, "I live in Lisbon.")
    await _learn(db, embeddings, "thanks", conversation_id="e", fact=_fact())
    set_clock(FakeClock(_START - timedelta(days=2)))
    await _learn(db, embeddings, "hello", conversation_id="e2", fact=_fact())
    set_clock(FakeClock(_START))
    flags = {
        r["user_text"]: r["ephemeral"]
        for r in await db.query("SELECT user_text, ephemeral FROM episode")
    }
    assert flags == {"I live in Lisbon.": False, "thanks": True, "hello": True}
    before = len(await db.query("SELECT id FROM episode"))

    await _dream(db)

    assert await _archived(db, "episode") == {
        "I live in Lisbon.": False,  # old but not ephemeral
        "thanks": True,
        "hello": False,  # ephemeral but only 2 days old
    }
    assert len(await db.query("SELECT id FROM episode")) == before


async def test_archived_condition_matches_rows_without_the_field(db):
    """A row that predates the field has no value; ``!= true`` still matches it."""
    await db.query("REMOVE FIELD archived ON fact")
    fact_id = await _learn_fact(db, "I live in Lisbon.")
    await db.query(
        "DEFINE FIELD IF NOT EXISTS archived ON fact TYPE option<bool> DEFAULT false"
    )
    assert await db.query("SELECT id FROM fact WHERE archived != true")
    assert not await db.query("SELECT id FROM fact WHERE archived = false")
    await _supersede(db, fact_id, 91)

    await _dream(db)

    assert await _archived(db, "fact") == {"I live in Lisbon.": True}


async def test_ablation_flag_off_archives_nothing(db, monkeypatch):
    old = await _learn_fact(db, "I live in Lisbon.")
    await _supersede(db, old, 91)
    monkeypatch.setattr(settings, "dreaming_v2_enabled", False)
    await _dream(db)
    assert await _archived(db, "fact") == {"I live in Lisbon.": False}
    monkeypatch.setattr(settings, "dreaming_v2_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    await _dream(db)
    assert await _archived(db, "fact") == {"I live in Lisbon.": False}


async def _trace_ranks(db, question: str, fact_id) -> dict | None:
    engine = RecallEngine(memory_manager=_manager(db), latent_engine=StubLatentEngine())
    packet = await engine.recall(
        RecallRequest(
            user_id="owner", user_input=question, limit=20, include_cold_start=False,
            include_latent=False, token_budget=100_000, venue="app",
        )
    )
    for item in packet.trace.items:
        if item.key == str(fact_id):
            return item.channel_ranks or {}
    return None


async def test_archived_superseded_fact_is_found_by_no_channel(db):
    """The temporal channel keeps superseded facts, but not archived ones."""
    set_clock(FakeClock(_START - timedelta(days=100)))
    old = await _learn_fact(db, "I live in Lisbon.")
    set_clock(FakeClock(_START))
    await _supersede(db, old, 91)
    day = (_START - timedelta(days=100)).date().isoformat()
    question = f"where did I live on {day}?"
    assert "temporal" in (await _trace_ranks(db, question, old) or {})

    await _dream(db)

    assert (await _archived(db, "fact"))["I live in Lisbon."] is True
    assert await _trace_ranks(db, question, old) is None
    window = (_START - timedelta(days=101), _START - timedelta(days=99))
    assert await fact_temporal_channel(db, window, "app") == []


async def test_archived_current_fact_is_hidden_from_every_channel(db):
    """Each channel's own filter, with the row archived but still current."""
    await _learn_fact(db, "My sister is called Ana.", entities=[_ANA], about=["Ana"])
    target = await _learn_fact(
        db, "Ana resides in Porto.", entities=[_ANA], about=["Ana"]
    )
    rows = await db.query(
        "SELECT id FROM fact WHERE content = 'My sister is called Ana.'"
    )
    seed = str(rows[0]["id"])
    embedding = await HashedBagOfWordsEmbeddings().embed("Ana resides in Porto.")
    window = (_START - timedelta(days=1), _START + timedelta(days=1))

    async def found() -> set[str]:
        results = {
            "dense": await fact_dense_channel(db, embedding, "app"),
            "lexical": await fact_lexical_channel(db, "Ana resides in Porto", "app"),
            "entity": await fact_entity_channel(db, ["ana"], "app"),
            "temporal": await fact_temporal_channel(db, window, "app"),
            "graph": await fact_graph_channel(db, {seed: 1.0}, "app"),
        }
        return {
            name for name, hits in results.items()
            if str(target) in {h.memory_id for h in hits}
        }

    assert await found() == {"dense", "lexical", "entity", "temporal", "graph"}
    await db.query("UPDATE $f SET archived = true", {"f": target})
    assert await found() == set()


async def test_what_changed_marks_archived_link(db, monkeypatch):
    old = await _learn_fact(db, "I live in Lisbon.", entities=[_ANA], about=["Ana"])
    new = await _learn_fact(db, "I live in Porto.", entities=[_ANA], about=["Ana"])
    await db.query("RELATE $a->supersedes->$b", {"a": new, "b": old})
    await _supersede(db, old, 91)
    await _dream(db)
    engine = RecallEngine(memory_manager=_manager(db), latent_engine=StubLatentEngine())
    monkeypatch.setattr("aura.tools.recall_tools.get_recall_engine", lambda: engine)

    text = await what_changed_run(
        {"entity": "Ana", "_venue": "app", "_requester_role": "owner"}
    )
    assert "I live in Lisbon. (" in text and ", archived)" in text
    assert text.count("archived") == 1  # the current link is not marked
    assert "I live in Porto." in text
