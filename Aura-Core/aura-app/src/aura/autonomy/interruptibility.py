"""Interruptibility model (B5-01, PRD 8.1). Pure, no model call, no I/O.

``interruptibility(signals, now)`` maps what we know about the owner to 0..1.
``collect_signals`` reads in-memory state only (presence, running delegations).
Presence data is read here and sent nowhere else.
"""

from dataclasses import dataclass
from datetime import datetime

from aura.config import settings


@dataclass(frozen=True)
class Signals:
    quiet_hours: bool = False
    typing: bool = False
    seconds_since_interaction: float | None = None
    watching_running_task: bool = False
    seconds_since_owner_message: float | None = None
    dismissal_ages_seconds: tuple[float, ...] = ()


def _curve(seconds: float | None) -> float:
    """Rises from the floor to 1 over the rise window, flat, then falls after long absence."""
    if seconds is None:
        return 1.0
    floor = min(1.0, settings.interrupt_curve_floor)
    seconds = max(0.0, seconds)
    rise = settings.interrupt_rise_seconds
    if seconds < rise:
        return floor + (1.0 - floor) * (seconds / rise)
    start = settings.interrupt_absence_hours * 3600.0
    if seconds <= start:
        return 1.0
    fall = settings.interrupt_absence_fall_hours * 3600.0
    if fall <= 0 or seconds >= start + fall:
        return floor
    return 1.0 - (1.0 - floor) * ((seconds - start) / fall)


def _dismissal_penalty(ages: tuple[float, ...]) -> float:
    half = settings.interrupt_dismissal_halflife_seconds
    total = 0.0
    for age in ages:
        decay = 0.5 ** (max(0.0, age) / half) if half > 0 else 0.0
        total += settings.interrupt_dismissal_penalty * decay
    return min(1.0, total)


def interruptibility(signals: Signals, now: datetime | None = None) -> float:
    """0 (never interrupt) to 1 (free to interrupt). ``now`` is unused: ages are in the signals."""
    if signals.quiet_hours:
        return 0.0
    value = _curve(signals.seconds_since_owner_message)
    age = signals.seconds_since_interaction
    active = age is not None and age < settings.interrupt_active_seconds
    typing = signals.typing and (age is None or age < settings.interrupt_typing_stale_seconds)
    if typing or active:
        value *= settings.interrupt_typing_factor
    if signals.watching_running_task:
        value *= settings.interrupt_watching_factor
    value *= 1.0 - _dismissal_penalty(signals.dismissal_ages_seconds)
    return max(0.0, min(1.0, value))


def _age(then: datetime | None, now: datetime) -> float | None:
    return None if then is None else max(0.0, (now - then).total_seconds())


def collect_signals(now: datetime) -> Signals:
    """Assemble the inputs from presence, running delegations and quiet hours."""
    from aura.autonomy import channel
    from aura.autonomy.controls import quiet_hours_active
    from aura.executor import delegation

    p = channel.presence
    watching = bool(p.watching) and delegation.get_runner(p.watching) is not None
    return Signals(
        quiet_hours=quiet_hours_active(now),
        typing=p.typing,
        seconds_since_interaction=_age(p.last_interaction_at, now),
        watching_running_task=watching,
        seconds_since_owner_message=_age(p.last_owner_message_at, now),
        dismissal_ages_seconds=(),  # B5-03 supplies the dismissal log; zero until then
    )


def fixed_cooldown(signals: Signals, now: datetime | None = None) -> float:
    """Ablation control: 0 within the cooldown of owner activity, else the stub value 1.0."""
    ages = [a for a in (signals.seconds_since_interaction, signals.seconds_since_owner_message) if a is not None]
    if ages and min(ages) < settings.interrupt_fixed_cooldown_seconds:
        return 0.0
    return 1.0
