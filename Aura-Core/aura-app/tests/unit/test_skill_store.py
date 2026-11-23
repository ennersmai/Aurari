"""G5-01: skill documents, versions and flags on the real schema (embedded SurrealDB)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import Settings
from aura.db.query_utils import extract_rows, to_record_id
from aura.engines.learning.skill_store import SkillStore
from tests.scenarios.runner import EmbeddedSurrealDB, _scripts_dir

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    yield d
    set_clock(Clock())
    await d.close()


async def test_doc_and_three_versions_round_trip(db):
    store = SkillStore(db)
    vec = [0.0] * 768
    vec[3] = 1.0
    doc = await store.create_doc(
        "deploy-site", "Use when shipping the site.", tags=["ops", "web"],
        state="trusted", origin_speaker="guest", workspace="ws1",
        when_embedding=vec,
    )
    assert doc.id.startswith("skill_doc:")
    assert doc.name == "deploy-site" and doc.when_to_use == "Use when shipping the site."
    assert doc.tags == ["ops", "web"] and doc.state == "trusted"
    assert doc.origin_speaker == "guest" and doc.workspace == "ws1"
    assert doc.when_embedding == vec
    assert doc.created_at == _START and doc.updated_at == _START
    assert doc.active_version is None and doc.previous_version is None
    assert doc.last_used_at is None and doc.retired_at is None and doc.flagged is None
    assert doc.node is None

    v1 = await store.add_version(
        doc.id, "body one", "taught", tools=["bash"], examples=["task:1"],
        pitfalls=["no sudo"], source_task="task:9", change_note="first",
        approved=True, approved_by="owner",
    )
    assert v1.version == 1 and v1.skill == doc.id
    assert v1.body == "body one" and v1.tools == ["bash"] and v1.examples == ["task:1"]
    assert v1.pitfalls == ["no sudo"] and v1.source == "taught"
    assert v1.source_task == "task:9" and v1.change_note == "first"
    assert v1.approved_at == _START and v1.approved_by == "owner"
    assert v1.rejected is False
    assert (v1.attempts, v1.successes, v1.practice_attempts, v1.practice_successes) == (0, 0, 0, 0)
    assert v1.created_at == _START

    set_clock(FakeClock(_START + timedelta(minutes=5)))
    v2 = await store.add_version(doc.id, "body two", "corrected")
    v3 = await store.add_version(doc.id, "body three", "distilled")
    assert [v2.version, v3.version] == [2, 3]
    assert v2.approved_at is None and v2.source_task is None and v2.change_note is None

    got = await store.list_versions(doc.id)
    assert [v.version for v in got] == [1, 2, 3]
    assert [v.body for v in got] == ["body one", "body two", "body three"]
    assert (await store.get_version(doc.id, 1)).body == "body one"
    assert await store.get_version(doc.id, 4) is None


async def test_duplicate_name_refused(db):
    store = SkillStore(db)
    await store.create_doc("a", "when a")
    with pytest.raises(ValueError):
        await store.create_doc("a", "other")
    # The index itself refuses a direct duplicate write too.
    with pytest.raises(Exception):
        await db.query(
            "CREATE skill_doc CONTENT $d",
            {"d": {"name": "a", "when_to_use": "x", "created_at": _START, "updated_at": _START}},
        )


async def test_duplicate_version_number_refused_by_index(db):
    store = SkillStore(db)
    doc = await store.create_doc("a", "when a")
    await store.add_version(doc.id, "b", "taught")
    with pytest.raises(Exception):
        await db.query(
            "CREATE skill_version CONTENT $d",
            {"d": {"skill": to_record_id(doc.id), "version": 1, "body": "x",
                   "source": "taught", "created_at": _START}},
        )


async def test_list_docs_hides_unapproved(db):
    store = SkillStore(db)
    a = await store.create_doc("approved-one", "w")
    b = await store.create_doc("inert-one", "w")
    c = await store.create_doc("rejected-one", "w", state="retired")
    await store.add_version(a.id, "x", "taught", approved=True, approved_by="owner")
    await store.add_version(b.id, "x", "distilled")
    await store.add_version(c.id, "x", "distilled", approved=True)
    await db.query(
        "UPDATE skill_version SET rejected = true WHERE skill = $s", {"s": to_record_id(c.id)}
    )

    assert [d.name for d in await store.list_docs()] == ["approved-one"]
    assert [d.name for d in await store.list_docs(include_unapproved=True)] == [
        "approved-one", "inert-one", "rejected-one"]
    assert [d.name for d in await store.list_docs(state="candidate")] == ["approved-one"]
    assert [d.name for d in await store.list_docs(state="candidate", include_unapproved=True)] == [
        "approved-one", "inert-one"]


async def test_state_active_and_touch(db):
    store = SkillStore(db)
    doc = await store.create_doc("s", "w")
    for _ in range(2):
        await store.add_version(doc.id, "b", "taught", approved=True)
    with pytest.raises(ValueError):
        await store.set_active(doc.id, 7)

    await store.set_active(doc.id, 1)
    got = await store.get_doc("s")
    assert got.active_version == 1 and got.previous_version is None
    set_clock(FakeClock(_START + timedelta(hours=1)))
    await store.set_active(doc.id, 2)
    got = await store.get_doc("s")
    assert got.active_version == 2 and got.previous_version == 1
    assert got.updated_at == _START + timedelta(hours=1)

    await store.touch_used(doc.id)
    assert (await store.get_doc("s")).last_used_at == _START + timedelta(hours=1)

    await store.set_state(doc.id, "retired")
    got = await store.get_doc("s")
    assert got.state == "retired" and got.retired_at == _START + timedelta(hours=1)
    await store.set_state(doc.id, "trusted")
    got = await store.get_doc("s")
    assert got.state == "trusted" and got.retired_at is None
    with pytest.raises(ValueError):
        await store.set_state(doc.id, "bogus")


async def test_skill_use_fields_round_trip(db):
    store = SkillStore(db)
    doc = await store.create_doc("s", "w")
    await db.query(
        "CREATE skill_use CONTENT $d",
        {"d": {"skill": to_record_id(doc.id), "version": 1, "turn_id": "t1", "task_id": "k1",
               "requester_role": "owner", "tools": ["bash"], "fact_ids": ["fact:1"],
               "outcome": "positive", "counted": True, "practice": True, "created_at": _START}},
    )
    row = extract_rows(await db.query("SELECT * FROM skill_use"))[0]
    assert (row["version"], row["turn_id"], row["task_id"]) == (1, "t1", "k1")
    assert row["requester_role"] == "owner" and row["tools"] == ["bash"]
    assert row["fact_ids"] == ["fact:1"] and row["outcome"] == "positive"
    assert row["counted"] is True and row["practice"] is True and row["created_at"] == _START
    assert extract_rows(await db.query("SELECT * FROM skill_use WHERE turn_id = 't1'"))
    assert extract_rows(await db.query("SELECT * FROM skill_use WHERE task_id = 'k1'"))


def test_flag_default_off_and_env(monkeypatch):
    assert Settings.model_fields["skills_v2_enabled"].default is False
    monkeypatch.setenv("AURA_SKILLS_V2_ENABLED", "true")
    assert Settings().skills_v2_enabled is True


def test_schema_statements_idempotent_and_old_skill_untouched():
    raw = (_scripts_dir() / "schema_v2.surql").read_text(encoding="utf-8")
    block = raw.split("SKILLS V2 (G5-01")[1]
    stmts = [s.strip() for s in re.sub(r"--[^\n]*", "", block).split(";") if s.strip()]
    assert all(" IF NOT EXISTS " in s for s in stmts if s.startswith("DEFINE"))
    assert not any(re.search(r"\bON skill\b", s) for s in stmts)
