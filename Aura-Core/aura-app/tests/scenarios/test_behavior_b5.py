"""B5-02 behaviour scenario T2: a finding waits while the owner types, then delivers."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, controls, delivery, trace
from aura.autonomy.agenda import AgendaService
from aura.autonomy.delivery import AgendaDeliverer
from aura.clock import Clock, FakeClock, get_clock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from tests.scenarios.runner import EmbeddedSurrealDB

_NOON = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def env(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    set_clock(FakeClock(_NOON))
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "interruptibility_model_enabled", True)
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


async def test_t2_finding_delivers_only_after_typing_stops(env):
    svc = AgendaService(env)
    dv = AgendaDeliverer(svc)
    delivery._deliverer = dv
    channel.update_presence({"typing": True})
    item = await svc.create("finding", "answer to your question", ["q"], 0.8, source="aura")

    assert await dv.deliver_due() == []  # typing: 0.8 * 0.1 < threshold
    assert (await svc.get(item.id)).state == "pending"

    get_clock().advance(10)
    channel.update_presence({"typing": False})  # presence event: re-evaluation scheduled
    await asyncio.sleep(0.2)  # let the scheduled task run (embedded db)
    assert (await svc.get(item.id)).state == "pending"  # still within the active window

    get_clock().advance(settings.interrupt_active_seconds + 1)
    got = await dv.deliver_due()
    assert [i.id for i in got] == [item.id]
    rows = extract_rows(await env.query("SELECT * FROM autonomy_trace WHERE source = 'agenda_delivery'"))
    actions = [r["action"] for r in rows]
    assert "defer:finding" in actions and "deliver:finding" in actions


async def test_typing_stopped_event_triggers_reevaluation(env, monkeypatch):
    svc = AgendaService(env)
    dv = AgendaDeliverer(svc)
    delivery._deliverer = dv
    channel.update_presence({"typing": True})
    item = await svc.create("needs_decision", "pick one", ["q"], 0.9, source="aura")
    assert await dv.deliver_due() == []  # 0.9 * 0.1 = 0.09 < 0.15
    get_clock().advance(settings.interrupt_active_seconds + 1)
    channel.update_presence({"typing": False})  # interaction now: active again at 0.1
    await asyncio.sleep(0.2)
    assert (await svc.get(item.id)).state == "pending"
    monkeypatch.setattr(settings, "interrupt_typing_factor", 0.5)  # 0.9 * 0.5 = 0.45 >= 0.15
    channel.update_presence({"typing": True})
    channel.update_presence({"typing": False})
    await asyncio.sleep(0.3)
    assert (await svc.get(item.id)).state == "delivered"
