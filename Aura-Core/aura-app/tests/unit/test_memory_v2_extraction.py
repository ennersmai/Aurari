"""Tests for memory v2 extraction (card W3-13).

The extraction call is exercised with a fake LLM client; the failure and
storage paths drive the embedded in-memory SurrealDB through the scenario
runner's adapter and deterministic embedding stub.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.memory.v2.episodes import store_episode
from aura.engines.memory.v2.extraction import (
    Extraction,
    build_prompt,
    extract,
    run_extraction,
)
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

_EXTRACTION = {
    "entities": [
        {"name": "Miso", "type": "other", "surface": "my cat"},
    ],
    "facts": [
        {
            "content": "The speaker has a cat named Miso.",
            "kind": "fact",
            "subject": "I",
            "predicate": "have",
            "object": "a cat named Miso",
            "about": ["Miso"],
            "asserted_by": "user",
            "implied": False,
            "negates": False,
        }
    ],
    "questions": ["What is the cat's name?"],
    "predictions": ["The cat will come up again."],
}


class FakeClient:
    """A client that returns one canned reply and records every call."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: list[dict] = []

    async def complete(self, messages, model, temperature=0.7, **kwargs):
        self.calls.append(
            {"messages": messages, "model": model, "temperature": temperature}
        )
        return self.reply


def _payload() -> dict:
    return json.loads(json.dumps(_EXTRACTION))


async def _open_db() -> EmbeddedSurrealDB:
    db = EmbeddedSurrealDB()
    await db.connect()
    return db


async def _store(
    db: EmbeddedSurrealDB,
    embeddings: HashedBagOfWordsEmbeddings,
    text: str,
    *,
    aura_text: str = "Aura replies.",
    venue: str = "app",
    conversation_id: str | None = "c1",
):
    return await store_episode(
        db,
        embeddings,
        user_text=text,
        aura_text=aura_text,
        speaker="owner",
        venue=venue,
        conversation_id=conversation_id,
        emotional_signature={"joy": 0.2},
        salience=0.4,
    )


async def _episode_row(db: EmbeddedSurrealDB, episode_id) -> dict:
    rows = await db.query("SELECT * FROM $episode_id", {"episode_id": episode_id})
    assert len(rows) == 1
    return rows[0]


# ---------------------------------------------------------------------------
# reply parsing
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_bare_json_reply_validates():
    client = FakeClient(json.dumps(_payload()))

    result = await extract(
        client,
        {"user_text": "My cat is called Miso.", "aura_text": "Noted."},
        [],
    )

    assert isinstance(result, Extraction)
    assert result.facts[0].content == "The speaker has a cat named Miso."
    assert result.entities[0].name == "Miso"


@pytest.mark.asyncio
async def test_fenced_json_reply_validates():
    client = FakeClient("Here it is:\n```json\n" + json.dumps(_payload()) + "\n```\n")

    result = await extract(
        client,
        {"user_text": "My cat is called Miso.", "aura_text": "Noted."},
        [],
    )

    assert result.questions == ["What is the cat's name?"]
    assert result.facts[0].asserted_by == "user"


@pytest.mark.asyncio
async def test_unknown_entity_type_becomes_other(caplog):
    payload = _payload()
    payload["entities"][0]["type"] = "animal"
    payload["facts"][0]["kind"] = "rumour"
    client = FakeClient(json.dumps(payload))

    result = await extract(client, {"user_text": "hi", "aura_text": "hello"}, [])

    assert result.entities[0].type == "other"
    assert result.facts[0].kind == "fact"


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------
def test_prompt_contains_the_two_previous_episodes_and_speaker_labels():
    previous = [
        {"user_text": "first question", "aura_text": "first reply"},
        {"user_text": "second question", "aura_text": "second reply"},
    ]
    episode = {"user_text": "current question", "aura_text": "current reply"}

    messages = build_prompt(episode, previous)

    assert [message["role"] for message in messages] == ["system", "user"]
    system = messages[0]["content"]
    assert '"entities"' in system
    assert "each fact is one self-contained sentence" in system.lower()
    assert "asserted_by" in system

    user = messages[1]["content"]
    assert "first question" in user
    assert "first reply" in user
    assert "second question" in user
    assert "second reply" in user
    assert "current question" in user
    assert "current reply" in user
    assert user.count("speaker:") == 3
    assert user.count("Aura:") == 3


# ---------------------------------------------------------------------------
# model selection
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_extraction_model_uses_l2_model(monkeypatch):
    monkeypatch.setattr(settings, "memory_extraction_model", "")
    monkeypatch.setattr(settings, "l2_model", "test/l2-model")
    client = FakeClient(json.dumps(_payload()))

    await extract(client, {"user_text": "hi", "aura_text": "hello"}, [])

    assert client.calls[0]["model"] == "test/l2-model"
    assert client.calls[0]["temperature"] == 0


@pytest.mark.asyncio
async def test_configured_extraction_model_is_used(monkeypatch):
    monkeypatch.setattr(settings, "memory_extraction_model", "test/extraction-model")
    client = FakeClient(json.dumps(_payload()))

    await extract(client, {"user_text": "hi", "aura_text": "hello"}, [])

    assert client.calls[0]["model"] == "test/extraction-model"


# ---------------------------------------------------------------------------
# run_extraction: success and failure bookkeeping
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_success_stores_extraction_and_marks_done():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode_id = await _store(db, embeddings, "My cat is called Miso.")
        client = FakeClient(json.dumps(_payload()))

        result = await run_extraction(db, client, episode_id)

        assert result is not None
        row = await _episode_row(db, episode_id)
        assert row["extraction_status"] == "done"
        assert row["extraction"]["facts"][0]["content"] == (
            "The speaker has a cat named Miso."
        )
        assert row["extraction"]["entities"][0]["name"] == "Miso"
        assert row["extraction_attempts"] == 0
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_invalid_json_stays_pending_with_one_attempt_and_error():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode_id = await _store(db, embeddings, "hello")
        client = FakeClient("I cannot produce JSON today.")

        result = await run_extraction(db, client, episode_id)

        assert result is None
        row = await _episode_row(db, episode_id)
        assert row["extraction_status"] == "pending"
        assert row["extraction_attempts"] == 1
        assert "No JSON object" in row["extraction_error"]
        assert row.get("extraction") is None
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_third_failure_marks_failed_and_episode_survives():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        episode_id = await _store(db, embeddings, "hello")
        client = FakeClient("still not JSON")

        for _ in range(2):
            assert await run_extraction(db, client, episode_id) is None
            row = await _episode_row(db, episode_id)
            assert row["extraction_status"] == "pending"

        assert await run_extraction(db, client, episode_id) is None

        row = await _episode_row(db, episode_id)
        assert row["extraction_status"] == "failed"
        assert row["extraction_attempts"] == 3
        assert row["extraction_error"]
        assert row["user_text"] == "hello"
    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_run_extraction_uses_the_two_previous_episodes_in_the_venue():
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()
        await _store(db, embeddings, "first episode", venue="app")
        clock.advance(60)
        await _store(db, embeddings, "second episode", venue="app")
        clock.advance(60)
        await _store(db, embeddings, "third episode", venue="app")
        clock.advance(60)
        current = await _store(db, embeddings, "fourth episode", venue="app")

        # A newer episode in another venue must not enter the prompt.
        clock.advance(60)
        await _store(db, embeddings, "other venue", venue="guild:1/channel:2")

        client = FakeClient(json.dumps(_payload()))
        await run_extraction(db, client, current)

        user = client.calls[0]["messages"][1]["content"]
        assert "first episode" not in user
        assert "second episode" in user
        assert "third episode" in user
        assert "fourth episode" in user
        assert "other venue" not in user
    finally:
        await db.close()
        set_clock(Clock())