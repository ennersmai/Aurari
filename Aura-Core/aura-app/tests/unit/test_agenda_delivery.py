"""B1-05: agenda delivery (T4, T5) and agenda routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI

from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, controls, delivery, trace
from aura.autonomy.agenda import AgendaService
from aura.autonomy.delivery import AgendaDeliverer
from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "quiet_hours_start", "22:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "08:00")
    for mod in (agenda_mod, controls, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda d=d: d)
    controls.reset_cache()
    channel.reset()
    monkeypatch.setattr(delivery, "_deliverer", None)
    await controls.set_level("open", d)
    yield d
    set_clock(Clock())
    controls.reset_cache()
    channel.reset()
    await d.close()


def _types():
    return [e["type"] for e in channel.events_since(0)]


async def _traces(d):
    from aura.db.query_utils import extract_rows

    return extract_rows(await d.query("SELECT * FROM autonomy_trace WHERE source = 'agenda_delivery'"))


async def test_delivers_once_sets_state_publishes_and_traces(env):
    svc = AgendaService(env)
    it = await svc.create("reminder", "call", ["owner:manual"], 0.9, source="owner")
    dv = AgendaDeliverer(svc)
    assert [i.id for i in await dv.deliver_due()] == [it.id]
    assert await dv.deliver_due() == []
    got = await svc.get(it.id)
    assert got.state == "delivered" and got.delivered_at == _START
    assert _types().count("aura_message") == 1 and _types().count("agenda_update") == 1
    assert len([t for t in await _traces(env) if t["action"] == "deliver:reminder"]) == 1


async def test_low_priority_is_quiet_indicator_only(env):
    svc = AgendaService(env)
    await svc.create("reminder", "meh", ["owner:manual"], 0.2, source="owner")
    await AgendaDeliverer(svc).deliver_due()
    assert "aura_message" not in _types() and "agenda_update" in _types()


async def test_future_due_not_delivered_early(env):
    svc = AgendaService(env)
    it = await svc.create("reminder", "later", ["r"], 0.9, due_at=_START + timedelta(minutes=5), source="owner")
    dv = AgendaDeliverer(svc)
    assert await dv.deliver_due() == []
    get_clock().advance(300)
    assert [i.id for i in await dv.deliver_due()] == [it.id]


async def test_quiet_hours_wait_then_deliver_or_expire(env):
    svc = AgendaService(env)
    set_clock(FakeClock(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)))
    keep = await svc.create("reminder", "keep", ["r"], 0.9, source="owner")
    gone = await svc.create(
        "reminder", "gone", ["r"], 0.9, source="owner",
        expires_at=datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc),
    )
    dv = AgendaDeliverer(svc)
    assert await dv.deliver_due() == []
    assert (await svc.get(keep.id)).state == "pending" and "aura_message" not in _types()
    set_clock(FakeClock(datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc)))
    assert await dv.deliver_due() == []  # still quiet, but gone has expired
    assert (await svc.get(gone.id)).state == "expired"
    set_clock(FakeClock(datetime(2026, 1, 2, 8, 30, tzinfo=timezone.utc)))
    assert [i.id for i in await dv.deliver_due()] == [keep.id]


async def test_silent_stores_but_does_not_deliver(env):
    await controls.set_level("silent", env)
    svc = AgendaService(env)
    it = await svc.create("reminder", "x", ["r"], 0.9, source="owner")
    assert await AgendaDeliverer(svc).deliver_due() == []
    assert "aura_message" not in _types()
    assert [i.id for i in await svc.list(["pending"])] == [it.id]


async def test_muted_kind_waits(env):
    await controls.mute_kind("reminder", env)
    svc = AgendaService(env)
    it = await svc.create("reminder", "x", ["r"], 0.9, source="owner")
    dv = AgendaDeliverer(svc)
    assert await dv.deliver_due() == []
    assert (await svc.get(it.id)).state == "pending"
    await controls.unmute_kind("reminder", env)
    assert [i.id for i in await dv.deliver_due()] == [it.id]


async def test_concurrent_deliver_publishes_once(env):
    svc = AgendaService(env)
    await svc.create("reminder", "x", ["r"], 0.9, source="owner")
    dv = AgendaDeliverer(svc)
    await asyncio.gather(dv.deliver_due(), dv.deliver_due())
    assert _types().count("aura_message") == 1


async def test_rearm_computes_delay_and_cancels_on_stop(env):
    svc = AgendaService(env)
    dv = AgendaDeliverer(svc)
    assert await dv.rearm() is None
    await svc.create("reminder", "a", ["r"], 0.9, due_at=_START + timedelta(seconds=90), source="owner")
    await svc.create("reminder", "b", ["r"], 0.9, due_at=_START + timedelta(seconds=30), source="owner")
    assert await dv.next_delay() == 30.0
    dv._running = True
    assert await dv.rearm() == 30.0
    first = dv._timer
    assert first is not None
    assert await dv.rearm() == 30.0
    await asyncio.sleep(0)
    assert first.cancelled() and dv._timer is not first
    await dv.stop()
    assert dv._timer is None


async def test_timer_fires_and_delivers(env):
    svc = AgendaService(env)
    it = await svc.create("reminder", "x", ["r"], 0.9, due_at=_START + timedelta(seconds=1), source="owner")
    dv = AgendaDeliverer(svc)
    dv._running = True
    set_clock(FakeClock(_START + timedelta(seconds=1)))
    await dv._wait_and_deliver(0.01)
    assert (await svc.get(it.id)).state == "delivered"
    await dv.stop()


async def test_routes_round_trip(env):
    from aura.api.routes import agenda as routes

    app = FastAPI()
    app.include_router(routes.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/agenda", json={"content": "stretch", "kind": "reminder"})
        assert r.status_code == 200
        body = r.json()
        assert body["refs"] == ["owner:manual"] and body["state"] == "delivered"
        assert (await c.post("/agenda", json={"content": "x", "kind": "finding"})).status_code == 422
        due = (_START + timedelta(hours=1)).isoformat()
        r2 = await c.post("/agenda", json={"content": "later", "kind": "observation", "due_at": due})
        assert r2.json()["state"] == "pending"
        listed = (await c.get("/agenda")).json()["items"]
        assert len(listed) == 2
        assert len((await c.get("/agenda?state=pending")).json()["items"]) == 1
        assert (await c.get("/agenda?state=bogus")).status_code == 400
        iid = body["id"]
        assert (await c.post(f"/agenda/{iid}/ack")).json()["state"] == "acknowledged"
        assert (await c.post(f"/agenda/{iid}/ack")).status_code == 409
        assert (await c.post(f"/agenda/{r2.json()['id']}/dismiss")).json()["state"] == "dismissed"
        assert (await c.post("/agenda/agenda_item:nope/ack")).status_code == 404
    assert _types().count("agenda_update") >= 4
