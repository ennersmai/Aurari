"""B4-01: question scoring without learning value (embedded SurrealDB, FakeClock)."""

from __future__ import annotations

import random
from datetime import datetime, timezone

import pytest

from aura.autonomy import curiosity
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.engines.memory.v2.episodes import store_episode
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "curiosity_enabled", True)
    monkeypatch.setattr(settings, "curiosity_random_choice", False)
    monkeypatch.setattr(settings, "workspaces", {})
    yield d
    set_clock(Clock())
    await d.close()


async def _entity(db, name, type_="concept"):
    rows = extract_rows(await db.query(
        "CREATE entity CONTENT $d",
        {"d": {"name": name, "type": type_, "aliases": [], "created_at": _START}},
    ))
    return rows[0]["id"]


async def _question(db, content, visibility="owner"):
    await db.query("CREATE question CONTENT $d", {"d": {
        "content": content, "visibility": visibility, "recorded_at": _START}})


async def _episode_mentioning(db, entity_id):
    ep = await store_episode(
        db, HashedBagOfWordsEmbeddings(), user_text="hello", aura_text="hi",
        speaker="owner", venue="app", conversation_id="c", emotional_signature={}, salience=0.5)
    await db.query("RELATE $e->mentions->$n", {"e": ep, "n": entity_id})


async def _goal(db, name, description):
    await db.query("CREATE goal CONTENT $d", {"d": {
        "name": name, "description": description, "goal_type": "learning", "status": "active",
        "created": _START, "updated": _START, "origin": "user"}})


async def _setup(db):
    await _goal(db, "Ship Rustlang port", "port the parser")
    await _entity(db, "Rustlang", "tool")
    recent = await _entity(db, "Gardening", "concept")
    await _episode_mentioning(db, recent)
    await _entity(db, "Tolkien", "concept")
    await _question(db, "Which version of Rustlang does the parser need?")
    await _question(db, "Is Tolkien older than Orwell?")


async def test_relevant_tractable_ranks_above_irrelevant(db):
    await _setup(db)
    out = await curiosity.pick_questions(_START, 5, db=db)
    assert "Rustlang" in out[0].content
    assert out[0].route == "search" and out[0].score == 1.0
    assert all("Tolkien" not in o.content for o in out)  # irrelevant: parked
    rows = extract_rows(await db.query("SELECT * FROM question WHERE content CONTAINS 'Tolkien'"))
    assert rows[0]["score"] == 0.0 and rows[0]["parked_reason"] == "below_minimum_score"
    top = extract_rows(await db.query("SELECT * FROM question WHERE content CONTAINS 'Rustlang'"))[0]
    assert top["score"] == 1.0 and top["scored_at"] is not None and top["tractability"] == 1.0


async def test_recent_topic_counts_less_than_goal(db):
    await _setup(db)
    await _question(db, "Why is Gardening so popular at 5am?")
    out = await curiosity.pick_questions(_START, 5, db=db)
    by = {o.content: o for o in out}
    g = by["Which version of Rustlang does the parser need?"]
    r = by["Why is Gardening so popular at 5am?"]
    assert g.relevance == 1.0 and r.relevance == 0.5 and g.score > r.score


async def test_preference_question_routes_ask_user(db):
    await _setup(db)
    await _entity(db, "Rustlang")
    await _question(db, "Does the owner prefer Rustlang over Go?")
    out = await curiosity.pick_questions(_START, 5, db=db)
    q = next(o for o in out if "prefer" in o.content)
    assert q.route == "ask_user" and q.tractability == 1.0


async def test_workspace_question_routes_read(db, monkeypatch):
    await _setup(db)
    monkeypatch.setattr(settings, "workspaces", {"proj": "C:/work/proj"})
    await _question(db, "What does the Rustlang parser in proj do?")
    out = await curiosity.pick_questions(_START, 5, db=db)
    assert next(o for o in out if "in proj" in o.content).route == "read"


async def test_guest_visibility_never_scored(db):
    await _setup(db)
    await _question(db, "Which Rustlang edition do guests use?", visibility="guild:42")
    await _question(db, "Which Rustlang crate do guests use?", visibility="private:discord_9")
    out = await curiosity.pick_questions(_START, 10, db=db)
    assert all("guests" not in o.content for o in out)
    rows = extract_rows(await db.query("SELECT * FROM question WHERE content CONTAINS 'guests'"))
    assert len(rows) == 2 and all(r.get("score") is None for r in rows)


async def test_random_mode_differs_from_scored_under_seed(db, monkeypatch):
    await _setup(db)
    for i in range(6):
        await _question(db, f"Which Rustlang release number {i} fixed it?")
    scored = [o.content for o in await curiosity.pick_questions(_START, 7, db=db)]
    monkeypatch.setattr(settings, "curiosity_random_choice", True)
    rnd = [o.content for o in await curiosity.pick_questions(_START, 7, db=db, rng=random.Random(3))]
    assert sorted(rnd) == sorted(scored) and rnd != scored
    again = [o.content for o in await curiosity.pick_questions(_START, 7, db=db, rng=random.Random(3))]
    assert again == rnd


async def test_scoring_is_stable(db):
    await _setup(db)
    for i in range(3):
        await _question(db, f"Which Rustlang release number {i} fixed it?")
    a = [o.content for o in await curiosity.pick_questions(_START, 10, db=db)]
    b = [o.content for o in await curiosity.pick_questions(_START, 10, db=db)]
    assert a == b and len(a) == 4


async def test_flag_off_returns_nothing(db, monkeypatch):
    await _setup(db)
    monkeypatch.setattr(settings, "curiosity_enabled", False)
    assert await curiosity.pick_questions(_START, 5, db=db) == []
    rows = extract_rows(await db.query("SELECT * FROM question"))
    assert all(r.get("score") is None for r in rows)


def test_learning_value_is_constant():
    assert curiosity.learning_value({"content": "x"}) == 1.0
