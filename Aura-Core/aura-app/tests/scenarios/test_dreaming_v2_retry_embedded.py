"""Embedded-SurrealDB tests for dreaming v2 retry extraction (card W4-08).

The real schema through the scenario runner's adapter, the runner's
deterministic embeddings, a scripted fake extraction client, and a
``FakeClock`` moved so each episode is recorded at a known time. Episode state
is set only through the real write functions (``store_episode`` leaves an
episode ``pending``; ``run_extraction`` moves it to ``failed``).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import store_episode
from tests.scenarios.runner import (
    _START,
    EmbeddedSurrealDB,
    HashedBagOfWordsEmbeddings,
    _build_dreaming,
)


class FakeExtractionClient:
    """Scripted client: returns one fact for the episode, or raises."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    async def complete(self, messages, model=None, temperature=0, **kwargs) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError("scripted extraction failure")
        return json.dumps(
            {
                "entities": [],
                "facts": [
                    {
                        "content": "I live in Lisbon.",
                        "kind": "fact",
                        "subject": "I",
                        "predicate": "live in",
                        "object": "Lisbon",
                        "about": [],
                        "asserted_by": "user",
                        "implied": False,
                        "negates": False,
                    }
                ],
                "questions": [],
                "predictions": [],
            }
        )


class _Layers:
    def __init__(self, client):
        self.client = client


@pytest.fixture
async def db(monkeypatch):
    monkeypatch.setattr(settings, "dreaming_v2_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", True)
    monkeypatch.setattr(settings, "dreaming_retry_min_age_minutes", 10)
    monkeypatch.setattr(settings, "dreaming_retry_batch", 20)
    monkeypatch.setattr(settings, "memory_extraction_max_attempts", 3)
    embeddings = HashedBagOfWordsEmbeddings()
    # run_extraction writes facts with the process-wide embeddings client.
    monkeypatch.setattr("aura.llm.embeddings.get_embeddings_client", lambda: embeddings)
    set_clock(FakeClock(_START))
    database = EmbeddedSurrealDB()
    await database.connect()
    try:
        yield database
    finally:
        await database.close()
        set_clock(Clock())


async def _episode(db, text: str, minutes_ago: float, n: int = 0):
    """Store one turn recorded ``minutes_ago`` before the dream; clock back to now."""
    set_clock(FakeClock(_START - timedelta(minutes=minutes_ago)))
    episode_id = await store_episode(
        db,
        HashedBagOfWordsEmbeddings(),
        user_text=text,
        aura_text="Noted.",
        speaker="owner",
        venue="app",
        conversation_id=f"c{n}",
        emotional_signature={"joy": 0.2},
        salience=0.4,
    )
    set_clock(FakeClock(_START))
    return episode_id


async def _dream(db, client):
    engine = _build_dreaming(db)
    engine._llm_layers = _Layers(client)
    return await engine.enter_rem_sleep()


async def _status(db, episode_id):
    rows = await db.query(
        "SELECT extraction_status, extraction_attempts FROM $rid", {"rid": episode_id}
    )
    return rows[0]["extraction_status"], rows[0]["extraction_attempts"]


async def test_old_pending_episode_is_extracted_and_facts_written(db):
    episode_id = await _episode(db, "I live in Lisbon.", minutes_ago=20)
    client = FakeExtractionClient()

    report = await _dream(db, client)

    assert (report.retried, report.extracted) == (1, 1)
    assert (await _status(db, episode_id))[0] == "done"
    facts = await db.query("SELECT content FROM fact")
    assert [f["content"] for f in facts] == ["I live in Lisbon."]  # written once


async def test_fresh_and_failed_episodes_are_left_alone(db, monkeypatch):
    fresh = await _episode(db, "I live in Porto.", minutes_ago=1, n=1)
    # Drive a second episode to "failed" through the real path.
    failed = await _episode(db, "I live in Madrid.", minutes_ago=30, n=2)
    monkeypatch.setattr(settings, "memory_extraction_max_attempts", 1)
    await _dream(db, FakeExtractionClient(fail=True))
    assert (await _status(db, failed))[0] == "failed"

    client = FakeExtractionClient()
    report = await _dream(db, client)

    assert (report.retried, report.extracted) == (0, 0)
    assert client.calls == 0
    assert (await _status(db, fresh))[0] == "pending"
    assert (await _status(db, failed))[0] == "failed"
    assert await db.query("SELECT id FROM fact") == []


async def test_failing_client_counts_attempts_until_max_then_failed(db):
    episode_id = await _episode(db, "I live in Rome.", minutes_ago=20)
    client = FakeExtractionClient(fail=True)

    for expected_attempts, expected_status in [(1, "pending"), (2, "pending"), (3, "failed")]:
        report = await _dream(db, client)
        assert (report.retried, report.extracted) == (1, 0)
        assert await _status(db, episode_id) == (expected_status, expected_attempts)

    # Now failed: the next cycle does not touch it.
    report = await _dream(db, client)
    assert report.retried == 0
    assert client.calls == 3


async def test_batch_cap_holds_and_oldest_go_first(db, monkeypatch):
    monkeypatch.setattr(settings, "dreaming_retry_batch", 2)
    oldest = await _episode(db, "I live in A.", minutes_ago=60, n=1)
    middle = await _episode(db, "I live in B.", minutes_ago=50, n=2)
    newest = await _episode(db, "I live in C.", minutes_ago=40, n=3)

    report = await _dream(db, FakeExtractionClient())

    assert (report.retried, report.extracted) == (2, 2)
    assert (await _status(db, oldest))[0] == "done"
    assert (await _status(db, middle))[0] == "done"
    assert (await _status(db, newest))[0] == "pending"


@pytest.mark.parametrize("flag", ["dreaming_v2_enabled", "memory_v2_write_enabled"])
async def test_flag_off_does_nothing(db, monkeypatch, flag):
    monkeypatch.setattr(settings, flag, False)
    episode_id = await _episode(db, "I live in Berlin.", minutes_ago=20)
    client = FakeExtractionClient()

    report = await _dream(db, client)

    assert (report.retried, report.extracted) == (0, 0)
    assert client.calls == 0
    assert (await _status(db, episode_id)) == ("pending", 0)
