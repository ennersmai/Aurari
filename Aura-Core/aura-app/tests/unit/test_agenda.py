"""B1-02: agenda table and service (embedded SurrealDB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aura.autonomy.agenda import AgendaItem, AgendaService, _rid, effective_priority
from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def svc():
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    yield AgendaService(d)
    set_clock(Clock())
    await d.close()


async def test_create_reads_back_every_field(svc):
    exp = _START + timedelta(days=1)
    due = _START + timedelta(hours=2)
    content = "It's \"quoted\"; DROP TABLE x"
    it = await svc.create("finding", content, ["fact:1", "task_graph:a"], 0.7,
                          venue="discord:general", expires_at=exp, due_at=due, source="dream")
    got = await svc.get(it.id)
    assert got == it
    assert got.kind == "finding" and got.content == content
    assert got.refs == ["fact:1", "task_graph:a"] and got.priority == 0.7
    assert got.venue == "discord:general" and got.created_at == _START
    assert got.expires_at == exp and got.due_at == due and got.source == "dream"
    assert got.state == "pending" and got.delivered_at is None and got.resolved_at is None


async def test_defaults_and_priority_clamp(svc):
    a = await svc.create("observation", "x", ["r"], 5)
    b = await svc.create("observation", "y", ["r"], -1)
    assert a.priority == 1.0 and b.priority == 0.0 and a.venue == "app"
    assert a.expires_at is None and a.due_at is None


async def test_create_rejects_missing_refs_and_bad_kind(svc):
    for refs in ([], [""], None):
        with pytest.raises(ValueError, match="agenda item needs refs"):
            await svc.create("finding", "x", refs)
    with pytest.raises(ValueError):
        await svc.create("gossip", "x", ["r"])
    assert await svc.list() == []


async def test_decay_pure_and_monotone(svc, monkeypatch):
    monkeypatch.setattr(settings, "agenda_decay_per_hour_finding", 0.1)
    it = await svc.create("finding", "x", ["r"], 0.8)
    vals = [effective_priority(it, _START + timedelta(hours=h)) for h in (0, 1, 5, 24)]
    assert vals[0] == 0.8 and vals == sorted(vals, reverse=True) and vals[-1] > 0
    assert it.priority == 0.8
    nd = await svc.create("needs_decision", "x", ["r"], 0.8)
    assert effective_priority(nd, _START + timedelta(days=30)) == 0.8
    rem = AgendaItem(id="a:b", kind="reminder", content="c", priority=0.4, created_at=_START)
    assert effective_priority(rem, _START + timedelta(days=30)) == 0.4


async def test_expiry_moves_without_delivering(svc):
    a = await svc.create("finding", "a", ["r"], expires_at=_START + timedelta(hours=1))
    b = await svc.create("finding", "b", ["r"], expires_at=_START + timedelta(hours=5))
    c = await svc.create("finding", "c", ["r"])
    assert await svc.expire_due() == 0
    get_clock().advance(2 * 3600)
    assert await svc.expire_due() == 1
    ga = await svc.get(a.id)
    assert ga.state == "expired" and ga.delivered_at is None and ga.resolved_at is not None
    assert (await svc.get(b.id)).state == "pending" and (await svc.get(c.id)).state == "pending"
    assert await svc.expire_due() == 0


async def test_transitions_and_double_ack(svc):
    a = await svc.create("task_done", "a", ["r"])
    assert await svc.acknowledge(a.id) is True
    first = (await svc.get(a.id)).resolved_at
    get_clock().advance(60)
    assert await svc.acknowledge(a.id) is False
    assert await svc.dismiss(a.id) is False
    g = await svc.get(a.id)
    assert g.state == "acknowledged" and g.resolved_at == first
    b = await svc.create("task_done", "b", ["r"])
    assert await svc.dismiss(b.id) is True and (await svc.get(b.id)).state == "dismissed"
    assert await svc.acknowledge(b.id) is False
    assert await svc.acknowledge("agenda_item:missing") is False
    assert await svc.list(["pending"]) == []
    assert len(await svc.list(["acknowledged", "dismissed"])) == 2


async def test_delivered_item_can_be_resolved_and_expired(svc):
    a = await svc.create("finding", "a", ["r"], expires_at=_START + timedelta(hours=1))
    c = await svc.create("finding", "c", ["r"])
    for i in (a, c):
        await svc.db.query("UPDATE $rid SET state = 'delivered', delivered_at = $n",
                           {"rid": _rid(i.id), "n": _START})
    got = await svc.get(a.id)
    assert got.state == "delivered" and got.delivered_at == _START
    get_clock().advance(7200)
    assert await svc.expire_due() == 1
    assert (await svc.get(a.id)).state == "expired"
    assert await svc.dismiss(c.id) is True
