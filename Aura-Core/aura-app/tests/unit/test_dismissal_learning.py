"""B5-03: dismissal learning, three-strikes mute (T3), reply rate, ablation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.autonomy import agenda as agenda_mod
from aura.autonomy import channel, controls, delivery, learning, trace
from aura.autonomy import interruptibility as interrupt
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
    monkeypatch.setattr(settings, "dismissal_learning_enabled", True)
    monkeypatch.setattr(settings, "interruptibility_model_enabled", False)
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "quiet_hours_start", "22:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "08:00")
    for mod in (agenda_mod, controls, trace, learning):
        monkeypatch.setattr(mod, "get_db_client", lambda d=d: d)
    controls.reset_cache()
    learning.reset_cache()
    channel.reset()
    monkeypatch.setattr(delivery, "_deliverer", None)
    await controls.set_level("open", d)
    yield d
    controls.reset_cache()
    learning.reset_cache()
    channel.reset()
    await d.close()


async def _deliver(svc, kind, priority=0.9):
    """Create an item and deliver it through the real deliverer."""
    get_clock().advance(1)
    item = await svc.create(kind, f"{kind} item", ["r"], priority, source="aura")
    got = await AgendaDeliverer(svc).deliver_due()
    assert [i.id for i in got] == [item.id]
    return item


async def _dismiss(d, svc, kind):
    item = await _deliver(svc, kind)
    assert await svc.dismiss(item.id)
    await learning.record_outcome(kind, "dismissed", item_id=item.id, db=d)
    return item


async def _ack(d, svc, kind):
    item = await _deliver(svc, kind)
    assert await svc.acknowledge(item.id)
    await learning.record_outcome(kind, "acknowledged", item_id=item.id, db=d)


async def test_three_dismissals_mute_only_that_kind_for_a_day(env):
    svc = AgendaService(env)
    for _ in range(3):
        await _dismiss(env, svc, "finding")
    assert await learning.is_muted("finding", db=env)
    assert not await learning.is_muted("question_for_you", db=env)
    d = await controls.may_initiate("finding", db=env)
    assert not d.allowed and d.reason == "kind_muted_by_learning"
    assert (await controls.may_initiate("question_for_you", db=env)).allowed
    assert (await controls.may_initiate("observation", db=env)).allowed
    rows = extract_rows(await env.query("SELECT * FROM autonomy_trace WHERE action = 'mute:finding'"))
    assert len(rows) == 1
    # a muted kind is not delivered
    item = await svc.create("finding", "later", ["r"], 0.9, source="aura")
    assert await AgendaDeliverer(svc).deliver_due() == []
    assert (await svc.get(item.id)).state == "pending"
    # the mute ends after a day
    get_clock().advance(86400 + 1)
    assert not await learning.is_muted("finding", db=env)
    assert (await controls.may_initiate("finding", db=env)).allowed


async def test_acknowledge_resets_streak(env):
    svc = AgendaService(env)
    await _dismiss(env, svc, "finding")
    await _dismiss(env, svc, "finding")
    await _ack(env, svc, "finding")
    await _dismiss(env, svc, "finding")
    await _dismiss(env, svc, "finding")
    assert not await learning.is_muted("finding", db=env)
    assert (await learning.get_stats("finding", env)).consecutive_dismissals == 2


async def test_ignored_after_timeout_counts_as_dismissal(env):
    svc = AgendaService(env)
    item = await _deliver(svc, "finding")
    get_clock().advance(settings.agenda_ignore_hours * 3600 - 10)
    assert await learning.sweep_ignored(db=env) == 0
    get_clock().advance(20)
    assert await learning.sweep_ignored(db=env) == 1
    row = await svc.get(item.id)
    assert row.state == "expired"
    s = await learning.get_stats("finding", env)
    assert s.ignored == 1 and s.consecutive_dismissals == 1
    assert s.threshold_delta == pytest.approx(settings.dismissal_raise_step)
    assert await learning.sweep_ignored(db=env) == 0  # idempotent


async def test_deliver_due_sweeps_ignored_items(env):
    svc = AgendaService(env)
    await _deliver(svc, "finding")
    get_clock().advance(settings.agenda_ignore_hours * 3600 + 1)
    await AgendaDeliverer(svc).deliver_due()
    assert (await learning.get_stats("finding", env)).ignored == 1


async def test_thresholds_stay_inside_clamps(env):
    for _ in range(100):
        await learning.record_outcome("observation", "dismissed", db=env)
    s = await learning.get_stats("observation", env)
    assert s.threshold_delta == pytest.approx(settings.dismissal_threshold_ceiling)
    for _ in range(200):
        await learning.record_outcome("observation", "acknowledged", db=env)
    s = await learning.get_stats("observation", env)
    assert s.threshold_delta == pytest.approx(settings.dismissal_threshold_floor)


async def test_threshold_override_in_delivery(env):
    base = float(settings.delivery_threshold_finding)
    await learning.record_outcome("finding", "dismissed", db=env)
    assert delivery.threshold("finding") == pytest.approx(base + settings.dismissal_raise_step)
    assert delivery.threshold("reminder") == pytest.approx(float(settings.delivery_threshold_reminder))
    for _ in range(40):
        await learning.record_outcome("finding", "acknowledged", db=env)
    assert delivery.threshold("finding") >= 0.0


async def test_owner_unmute_lifts_learned_mute(env):
    for _ in range(3):
        await learning.record_outcome("finding", "dismissed", db=env)
    assert await learning.is_muted("finding", db=env)
    await controls.unmute_kind("finding", env)
    assert not await learning.is_muted("finding", db=env)


async def test_dismissal_log_feeds_interruptibility_penalty(env):
    svc = AgendaService(env)
    await _dismiss(env, svc, "finding")
    await learning.refresh(env)
    get_clock().advance(60)
    ages = interrupt.collect_signals(get_clock().now()).dismissal_ages_seconds
    assert len(ages) == 1 and ages[0] == pytest.approx(60, abs=1)


async def test_stats_reply_rate(env):
    svc = AgendaService(env)
    await _ack(env, svc, "finding")
    await _dismiss(env, svc, "finding")
    await _ack(env, svc, "finding")
    await _dismiss(env, svc, "finding")
    f = (await learning.stats_report(env))["finding"]
    assert f["delivered"] == 4 and f["acknowledged"] == 2 and f["dismissed"] == 2
    assert f["reply_rate"] == pytest.approx(0.5)


async def test_stats_route(env):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from aura.api.routes import autonomy as routes

    await learning.record_delivered("finding", env)
    await learning.record_outcome("finding", "acknowledged", db=env)
    app = FastAPI()
    app.include_router(routes.router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = (await c.get("/autonomy/stats")).json()
    assert body["enabled"] is True
    assert body["kinds"]["finding"]["reply_rate"] == pytest.approx(1.0)


async def test_flag_off_changes_nothing(env, monkeypatch):
    monkeypatch.setattr(settings, "dismissal_learning_enabled", False)
    svc = AgendaService(env)
    for _ in range(4):
        await _dismiss(env, svc, "finding")
    assert extract_rows(await env.query("SELECT * FROM agenda_kind_stats")) == []
    assert delivery.threshold("finding") == pytest.approx(float(settings.delivery_threshold_finding))
    assert (await controls.may_initiate("finding", db=env)).allowed
    assert interrupt.collect_signals(get_clock().now()).dismissal_ages_seconds == ()
    get_clock().advance(settings.agenda_ignore_hours * 3600 + 1)
    assert await learning.sweep_ignored(db=env) == 0
