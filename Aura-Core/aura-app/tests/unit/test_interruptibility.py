"""B5-01: interruptibility model and the fixed-cooldown ablation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from aura.autonomy import channel, delivery
from aura.autonomy import interruptibility as im
from aura.autonomy.interruptibility import Signals, interruptibility
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.executor import delegation

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    set_clock(FakeClock(_START))
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "quiet_hours_start", "22:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "08:00")
    channel.reset()
    yield
    set_clock(Clock())
    channel.reset()


def test_defaults_and_flag_off():
    assert settings.interruptibility_model_enabled is False
    assert settings.interrupt_fixed_cooldown_seconds == 600
    assert settings.interrupt_typing_factor == 0.1


def test_pure():
    s = Signals(typing=True, seconds_since_owner_message=1000.0, dismissal_ages_seconds=(10.0,))
    assert interruptibility(s, _START) == interruptibility(s, _START + timedelta(days=3))


def test_signals_move_value_the_right_way():
    base = Signals(seconds_since_owner_message=3600.0)
    assert interruptibility(base, _START) == 1.0
    assert interruptibility(Signals(typing=True, seconds_since_owner_message=3600.0), _START) == pytest.approx(0.1)
    active = Signals(seconds_since_interaction=5.0, seconds_since_owner_message=3600.0)
    assert interruptibility(active, _START) == pytest.approx(0.1)
    watch = Signals(watching_running_task=True, seconds_since_owner_message=3600.0)
    assert interruptibility(watch, _START) == pytest.approx(0.3)
    both = Signals(typing=True, watching_running_task=True, seconds_since_owner_message=3600.0)
    assert interruptibility(both, _START) == pytest.approx(0.03)
    d1 = interruptibility(Signals(seconds_since_owner_message=3600.0, dismissal_ages_seconds=(0.0,)), _START)
    d2 = interruptibility(Signals(seconds_since_owner_message=3600.0, dismissal_ages_seconds=(0.0, 0.0)), _START)
    old = interruptibility(Signals(seconds_since_owner_message=3600.0, dismissal_ages_seconds=(36000.0,)), _START)
    assert d2 < d1 < old < 1.0


def test_quiet_hours_exactly_zero():
    assert interruptibility(Signals(quiet_hours=True, seconds_since_owner_message=3600.0), _START) == 0.0
    set_clock(FakeClock(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)))
    assert im.collect_signals(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)).quiet_hours is True
    assert delivery.interruptibility(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)) == 1.0  # flag off: no presence


def test_typing_recovers_after_it_stops():
    ages = [0.0, 10.0, 31.0, 120.0]
    vals = [
        interruptibility(Signals(typing=(a == 0.0), seconds_since_interaction=a, seconds_since_owner_message=3600.0), _START)
        for a in ages
    ]
    assert vals[0] < 0.2 and vals[1] < 0.2
    assert vals[2] == 1.0 and vals[3] == 1.0
    # a stale typing flag is ignored
    stale = Signals(typing=True, seconds_since_interaction=120.0, seconds_since_owner_message=3600.0)
    assert interruptibility(stale, _START) == 1.0


def test_curve_rises_then_falls_with_fake_clock(monkeypatch):
    monkeypatch.setattr(settings, "quiet_hours_end", "22:00")  # no quiet window in this test
    clock = FakeClock(_START)
    set_clock(clock)
    channel.note_owner_message()
    channel.presence.last_interaction_at = None  # isolate the curve from the active window
    seen = []
    for secs in (0, 150, 300, 3600, 8 * 3600, 16 * 3600, 24 * 3600, 48 * 3600):
        now = _START + timedelta(seconds=secs)
        seen.append(interruptibility(im.collect_signals(now), now))
    assert seen[0] == pytest.approx(settings.interrupt_curve_floor)
    assert seen[0] < seen[1] < seen[2] == 1.0 == seen[3] == seen[4]
    assert seen[4] == 1.0 > seen[5] > seen[6]
    assert seen[6] == seen[7] == pytest.approx(settings.interrupt_curve_floor)


def test_collect_signals_from_presence_and_runner(monkeypatch):
    channel.update_presence({"typing": True, "active_view": "tasks", "watching": "t1"})
    assert channel.presence.watching == "t1"
    now = _START + timedelta(seconds=40)
    assert im.collect_signals(now).watching_running_task is False  # no runner
    monkeypatch.setattr(delegation, "get_runner", lambda tid: object() if tid == "t1" else None)
    s = im.collect_signals(now)
    assert s.watching_running_task and s.typing
    assert s.seconds_since_interaction == pytest.approx(40.0)
    channel.update_presence({"typing": False, "watching": None})
    assert channel.presence.watching is None


def test_ablation_fixed_cooldown_when_off(monkeypatch):
    monkeypatch.setattr(settings, "interruptibility_model_enabled", False)
    assert delivery.interruptibility(_START) == 1.0  # nothing known: stub value
    channel.note_owner_message()
    assert delivery.interruptibility(_START + timedelta(seconds=599)) == 0.0
    assert delivery.interruptibility(_START + timedelta(seconds=601)) == 1.0
    # the model would already give a different (graded) value at 300 s
    monkeypatch.setattr(settings, "interruptibility_model_enabled", True)
    channel.presence.last_interaction_at = None
    mid = delivery.interruptibility(_START + timedelta(seconds=150))
    assert 0.0 < mid < 1.0
