"""B1-08: behaviour scenarios T4, T5, T14 on the simulated clock.

Real AgendaDeliverer, channel, controls and registry on the embedded
SurrealDB with a FakeClock; routes are driven through the ASGI app.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from aura.api.routes import agenda as agenda_routes
from aura.api.routes import autonomy as autonomy_routes
from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, controls, delivery, registry, trace
from aura.autonomy.agenda import AgendaService
from aura.autonomy.controls import may_initiate
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.executor import delegation
from tests.scenarios.runner import EmbeddedSurrealDB

_MIDNIGHT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_NOON = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_NOON)
    set_clock(clock)
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "quiet_hours_start", "22:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "08:00")
    for mod in (agenda_mod, controls, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda d=d: d)
    controls.reset_cache()
    channel.reset()
    registry.reset()
    monkeypatch.setattr(delivery, "_deliverer", None)
    app = FastAPI()
    app.include_router(agenda_routes.router)
    app.include_router(autonomy_routes.router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    yield SimpleNamespace(db=d, client=client, clock=clock, svc=AgendaService(d))
    await client.aclose()
    registry.reset()
    set_clock(Clock())
    controls.reset_cache()
    channel.reset()
    await d.close()


def _types():
    return [e["type"] for e in channel.events_since(0)]


async def _create_reminder(env, content, due, expires=None):
    body = {"content": content, "kind": "reminder", "priority": 0.9, "due_at": due.isoformat()}
    if expires is not None:
        body["expires_at"] = expires.isoformat()
    r = await env.client.post("/agenda", json=body)
    assert r.status_code == 200, r.text
    return r.json()["id"]


async def test_t4_reminder_in_quiet_hours_waits_until_morning(env):
    env.clock.set(_MIDNIGHT + timedelta(hours=1))
    assert controls.quiet_hours_active()
    due = _MIDNIGHT + timedelta(hours=2)
    iid = await _create_reminder(env, "take the pills", due)
    dv = delivery.get_deliverer()

    env.clock.set(due)  # 02:00, quiet hours
    assert await dv.deliver_due() == []
    assert (await env.svc.get(iid)).state == "pending"
    assert "aura_message" not in _types()

    env.clock.set(_MIDNIGHT + timedelta(hours=7, minutes=59))
    assert await dv.deliver_due() == []

    env.clock.set(_MIDNIGHT + timedelta(hours=8))  # quiet hours over
    assert not controls.quiet_hours_active()
    got = await dv.deliver_due()
    assert [i.id for i in got] == [iid]
    item = await env.svc.get(iid)
    assert item.state == "delivered" and item.delivered_at == _MIDNIGHT + timedelta(hours=8)
    assert _types().count("aura_message") == 1


async def test_t4_reminder_that_expires_in_quiet_hours_is_never_delivered(env):
    env.clock.set(_MIDNIGHT + timedelta(hours=1))
    due = _MIDNIGHT + timedelta(hours=2)
    iid = await _create_reminder(env, "stale", due, expires=_MIDNIGHT + timedelta(hours=6))
    dv = delivery.get_deliverer()

    env.clock.set(due)
    assert await dv.deliver_due() == []
    env.clock.set(_MIDNIGHT + timedelta(hours=8))
    assert await dv.deliver_due() == []
    item = await env.svc.get(iid)
    assert item.state == "expired" and item.delivered_at is None
    assert "aura_message" not in _types()
    assert (await env.client.get("/agenda")).json()["items"] == []
    assert [i["id"] for i in (await env.client.get("/agenda?state=expired")).json()["items"]] == [iid]


async def test_t5_silent_delivers_and_starts_nothing_but_controls_stay_readable(env):
    await controls.set_level("silent", env.db)
    started: list[str] = []

    async def start_investigation():
        d = await may_initiate("finding", source="investigation")
        if d.allowed:
            started.append("x")

    ids = [await _create_reminder(env, "r", env.clock.now() + timedelta(minutes=5))]
    for kind in ("needs_decision", "task_done", "finding"):
        ids.append((await env.svc.create(kind, kind, ["ref:1"], 0.9)).id)
    dv = delivery.get_deliverer()

    for _ in range(24):  # a day in hourly steps, outside and inside quiet hours
        env.clock.advance(3600)
        assert await dv.deliver_due() == []
        await start_investigation()
        for kind in ("needs_decision", "reminder", "task_done"):
            assert not (await may_initiate(kind, owner_created=True)).allowed

    assert started == []
    assert [i.state for i in await env.svc.list()] == ["pending"] * 4
    assert "aura_message" not in _types()

    # controls stay readable and the owner can still resolve items
    state = (await env.client.get("/autonomy")).json()
    assert state["level"] == 0 and state["killed"] is False
    listed = (await env.client.get("/agenda")).json()["items"]
    assert {i["id"] for i in listed} == set(ids)
    assert (await env.client.post(f"/agenda/{ids[0]}/dismiss")).json()["state"] == "dismissed"
    traces = extract_rows(await env.db.query("SELECT * FROM autonomy_trace WHERE allowed = false"))
    assert traces and all(t["why"] == "level_0_reactive" for t in traces)

    # raising the level releases the waiting items through the real notify path
    env.clock.set(_NOON + timedelta(days=1))
    await env.client.put("/autonomy/level", json={"level": "important"})
    assert {i.kind for i in await env.svc.list(["delivered"])} == {"needs_decision", "task_done"}


class _FakeRunner:
    def __init__(self, task_id, autonomous):
        self.config = SimpleNamespace(autonomous=autonomous)
        self.task_id = task_id
        self.work = asyncio.ensure_future(asyncio.sleep(60))
        self.aborted = False

    async def abort(self):
        self.aborted = True
        self.work.cancel()
        await asyncio.gather(self.work, return_exceptions=True)


async def test_t14_kill_stops_running_investigation_and_delegation_within_2s(env, monkeypatch):
    investigation = asyncio.create_task(asyncio.sleep(60))
    registry.register_autonomous_task(investigation, "investigation", "question:1")
    auto, owner = _FakeRunner("task:auto", True), _FakeRunner("task:owner", False)
    monkeypatch.setattr(delegation, "_RUNNERS", {"task:auto": auto, "task:owner": owner})
    await asyncio.sleep(0)
    assert not investigation.done()

    t0 = time.monotonic()
    r = await env.client.post("/autonomy/kill")
    elapsed = time.monotonic() - t0
    try:
        assert r.status_code == 200 and elapsed < 2.0
        assert investigation.cancelled() and auto.aborted and auto.work.cancelled()
        assert not owner.aborted  # owner-requested work is not autonomous
        kinds = sorted(s["kind"] for s in r.json()["stopped"])
        assert kinds == ["delegation", "investigation"]
        assert registry.registered() == []

        # nothing may start again, and the kill is visible and readable
        assert controls.is_killed()
        d = await may_initiate("needs_decision")
        assert not d.allowed and d.reason == "killed"
        state = (await env.client.get("/autonomy")).json()
        assert state["killed"] is True and state["killed_at"]
        await env.svc.create("needs_decision", "x", ["ref:1"], 0.9)
        assert await delivery.get_deliverer().deliver_due() == []

        # resume clears the flag but restarts nothing
        assert (await env.client.post("/autonomy/resume")).json()["killed"] is False
        assert registry.registered() == [] and investigation.cancelled()
    finally:
        owner.work.cancel()
        await asyncio.gather(owner.work, return_exceptions=True)
