"""B5-02: delivery threshold, refractory period, trace rows, ablation."""

from __future__ import annotations

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


@pytest.fixture(autouse=True)
def _restore_clock():
    yield
    set_clock(Clock())


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
    controls.reset_cache()
    channel.reset()
    await d.close()


async def _traces(d):
    return extract_rows(await d.query("SELECT * FROM autonomy_trace WHERE source = 'agenda_delivery'"))


async def _mk(svc, kind, priority=0.6):
    return await svc.create(kind, f"{kind} item", ["r"], priority, source="aura")


def _active(monkeypatch, factor=0.4):
    """Owner active in the app: interruptibility == factor."""
    monkeypatch.setattr(settings, "interrupt_typing_factor", factor)
    channel.update_presence({"typing": False})


async def test_needs_decision_delivers_where_finding_would_not(env, monkeypatch):
    _active(monkeypatch, 0.4)  # product 0.6 * 0.4 = 0.24: below finding 0.3, above needs_decision 0.15
    svc = AgendaService(env)
    f = await _mk(svc, "finding")
    n = await _mk(svc, "needs_decision")
    got = await AgendaDeliverer(svc).deliver_due()
    assert [i.id for i in got] == [n.id]
    assert (await svc.get(f.id)).state == "pending"


async def test_deferral_writes_trace_row_and_is_silent(env, monkeypatch):
    _active(monkeypatch, 0.4)
    svc = AgendaService(env)
    f = await _mk(svc, "finding")
    assert await AgendaDeliverer(svc).deliver_due() == []
    rows = [t for t in await _traces(env) if t["action"] == "defer:finding"]
    assert len(rows) == 1 and rows[0]["refs"] == [f.id]
    assert rows[0]["cost"]["product"] == pytest.approx(0.24)
    assert rows[0]["cost"]["threshold"] == pytest.approx(settings.delivery_threshold_finding)
    assert [e["type"] for e in channel.events_since(0)] == []


async def test_delivery_trace_records_product_and_threshold(env):
    svc = AgendaService(env)
    await _mk(svc, "finding", 0.9)
    await AgendaDeliverer(svc).deliver_due()
    row = next(t for t in await _traces(env) if t["action"] == "deliver:finding")
    assert row["cost"]["product"] == pytest.approx(0.9) and row["cost"]["threshold"] > 0


async def test_refractory_delays_second_item_then_delivers(env):
    svc = AgendaService(env)
    a = await _mk(svc, "finding", 0.9)
    get_clock().advance(1)  # distinct created_at: delivery order is by creation
    b = await _mk(svc, "finding", 0.9)
    dv = AgendaDeliverer(svc)
    assert [i.id for i in await dv.deliver_due()] == [a.id]
    assert (await svc.get(b.id)).state == "pending"  # waits, not dropped
    assert dv._next_wake == pytest.approx(settings.delivery_refractory_seconds)
    get_clock().advance(settings.delivery_refractory_seconds - 2)
    assert await dv.deliver_due() == []
    get_clock().advance(2)
    assert [i.id for i in await dv.deliver_due()] == [b.id]


async def test_refractory_survives_new_deliverer(env):
    svc = AgendaService(env)
    await _mk(svc, "finding", 0.9)
    await AgendaDeliverer(svc).deliver_due()
    await _mk(svc, "finding", 0.9)
    assert await AgendaDeliverer(svc).deliver_due() == []


async def test_quiet_hours_defers_silently_and_arms_boundary(env):
    set_clock(FakeClock(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)))
    svc = AgendaService(env)
    await _mk(svc, "finding", 0.9)
    dv = AgendaDeliverer(svc)
    assert await dv.deliver_due() == []
    assert dv._next_wake == pytest.approx(9 * 3600)
    assert await _traces(env) == []


async def test_seconds_to_quiet_end_same_day(env):
    assert delivery.seconds_to_quiet_end(datetime(2026, 1, 1, 6, 0, tzinfo=timezone.utc)) == 2 * 3600


async def test_ablation_model_off_uses_fixed_cooldown(env, monkeypatch):
    monkeypatch.setattr(settings, "interruptibility_model_enabled", False)
    svc = AgendaService(env)
    # low product (0.05 * 1.0) and no refractory: both deliver, no threshold applied
    a = await _mk(svc, "observation", 0.05)
    b = await _mk(svc, "observation", 0.05)
    dv = AgendaDeliverer(svc)
    assert {i.id for i in await dv.deliver_due()} == {a.id, b.id}
    assert dv._next_wake is None
    assert not [t for t in await _traces(env) if t["action"].startswith("defer")]
    # the old fixed cooldown still blocks right after owner activity
    channel.update_presence({"typing": False})
    c = await _mk(svc, "observation", 0.9)
    assert await dv.deliver_due() == []
    get_clock().advance(settings.interrupt_fixed_cooldown_seconds + 1)
    assert [i.id for i in await dv.deliver_due()] == [c.id]
