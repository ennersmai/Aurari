"""P2-29: the Council skill document on the real schema (embedded SurrealDB)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.engines.learning.skill_store import SkillStore
from aura.tools import council
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db():
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    yield d
    set_clock(Clock())
    await d.close()


async def test_seed_creates_trusted_approved_skill_once(db):
    store = SkillStore(db)
    doc = await council.seed_council_skill(store)
    assert doc.name == "council" and doc.state == "trusted" and doc.active_version == 1
    version = await store.get_version(doc.id, 1)
    assert version.approved_at == _START and version.rejected is False
    assert version.tools == ["council"]
    for part in council.SYNTHESIS_PARTS:
        assert part in version.body
    again = await council.seed_council_skill(store)
    assert again.id == doc.id
    assert len(await store.list_versions(doc.id)) == 1
