"""Emotion physics v2 tests (W1-15, PRD section 10 T1-T5).

These exercise the new physics in ``engines/emotion/physics.py``:
a true resting state, half-life decay, tick invariance, restart handling,
and no-latch behaviour. They run on the simulated clock where relevant and
do not start a database or load a model.
"""

import math
import random

import pytest

from aura.engines.emotion.physics import EmotionPhysics
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector


@pytest.fixture
def physics() -> EmotionPhysics:
    return EmotionPhysics(EmotionPhysicsConfig())


@pytest.fixture
def baseline(physics: EmotionPhysics) -> EmotionVector:
    return physics.config.baseline


def _spike(baseline: EmotionVector, emotion: str, amount: float = 0.4) -> EmotionVector:
    """Return a state equal to baseline except `emotion` raised above it."""
    values = baseline.model_dump()
    values[emotion] = max(0.0, min(1.0, values[emotion] + amount))
    return EmotionVector(**values)


# -- T1: Rest ----------------------------------------------------------------

def test_t1_rest_returns_to_baseline_within_one_hour(
    physics: EmotionPhysics, baseline: EmotionVector
):
    """T1: from baseline, after one simulated hour with no events, every
    dimension is within 0.01 of baseline."""
    current = baseline.model_copy()
    # One hour of 1 s ticks (pure decay from baseline: deviation is zero).
    for _ in range(3600):
        current = physics.tick(current, dt=1.0, baseline=baseline)

    for emotion, value in current.model_dump().items():
        assert abs(value - getattr(baseline, emotion)) < 0.01, (
            f"{emotion} drifted from baseline: {value} vs {getattr(baseline, emotion)}"
        )


def test_t1_rest_from_a_perturbed_state_settles_to_baseline(
    physics: EmotionPhysics, baseline: EmotionVector
):
    """T1 (stronger): a perturbed state with no further input settles back to
    within 0.01 of baseline after enough rest for every non-bond dimension.
    Bond dimensions (love/trust, 12 h half-life) are perturbed and then given
    a full 12 h of rest, which brings them back within 0.01 too."""
    # Perturb every dimension above its baseline.
    values = baseline.model_dump()
    for emotion in values:
        values[emotion] = max(0.0, min(1.0, values[emotion] + 0.3))
    current = EmotionVector(**values)

    # 12 hours of rest is enough for every half-life group (the longest is the
    # 12 h bond group) to bring a 0.3 deviation back below 0.01:
    # 0.3 * 0.5**(43200/43200) = 0.15 after one half-life, so we need several.
    # 7 half-lives -> 0.3 * 0.5**7 = 0.0023 < 0.01. 7 * 12 h = 84 h.
    for _ in range(84 * 3600):  # 84 hours of 1 s ticks
        current = physics.tick(current, dt=1.0, baseline=baseline)

    for emotion, value in current.model_dump().items():
        assert abs(value - getattr(baseline, emotion)) < 0.01, (
            f"{emotion} did not settle to baseline: {value} vs {getattr(baseline, emotion)}"
        )


# -- T2: Half-lives ----------------------------------------------------------

def test_t2_each_dimension_halves_in_its_configured_half_life(
    physics: EmotionPhysics, baseline: EmotionVector
):
    """T2: a spike on each dimension falls halfway in its configured
    half-life, within 5%."""
    for emotion, half_life in physics.half_lives.items():
        spike = _spike(baseline, emotion, amount=0.4)
        resting = getattr(baseline, emotion)
        initial_deviation = getattr(spike, emotion) - resting

        # One tick of exactly one half-life.
        after = physics.tick(spike, dt=half_life, baseline=baseline)
        new_deviation = getattr(after, emotion) - resting

        expected = initial_deviation * 0.5
        assert abs(new_deviation - expected) <= 0.05 * abs(expected), (
            f"{emotion}: deviation {new_deviation} not within 5% of {expected} "
            f"(half_life={half_life}s)"
        )


# -- T3: Tick invariance -----------------------------------------------------

def test_t3_tick_invariance_1s_vs_10s(
    physics: EmotionPhysics, baseline: EmotionVector
):
    """T3: the same scenario at 1 s and at 10 s ticks ends within 0.01."""
    # Identical starting perturbation on a core and a fast dimension.
    start = _spike(baseline, "joy", 0.4)
    start = _spike(start, "curiosity", 0.4)

    # Scenario: 60 simulated seconds of decay.
    run_1s = start.model_copy()
    for _ in range(60):
        run_1s = physics.tick(run_1s, dt=1.0, baseline=baseline)

    run_10s = start.model_copy()
    for _ in range(6):
        run_10s = physics.tick(run_10s, dt=10.0, baseline=baseline)

    for emotion in run_1s.model_dump():
        assert abs(getattr(run_1s, emotion) - getattr(run_10s, emotion)) < 0.01, (
            f"{emotion}: 1 s ticks ({getattr(run_1s, emotion)}) vs "
            f"10 s ticks ({getattr(run_10s, emotion)}) diverged"
        )


# -- T4: Restart -------------------------------------------------------------

def test_t4_restart_six_hours_decay_matches_continuous(
    physics: EmotionPhysics, baseline: EmotionVector
):
    """T4: a state loaded 6 simulated hours later has decayed by 6 hours.
    A single tick of dt = 6 h must equal 6 h of 1 s ticks, within 0.01."""
    start = _spike(baseline, "joy", 0.5)
    start = _spike(start, "sadness", 0.5)
    start = _spike(start, "curiosity", 0.5)

    six_hours = 6 * 3600  # seconds

    # Restart path: one big tick covering the whole gap.
    restarted = physics.tick(start.model_copy(), dt=six_hours, baseline=baseline)

    # Continuous path: 6 h of 1 s ticks.
    continuous = start.model_copy()
    for _ in range(six_hours):
        continuous = physics.tick(continuous, dt=1.0, baseline=baseline)

    for emotion in continuous.model_dump():
        assert abs(getattr(restarted, emotion) - getattr(continuous, emotion)) < 0.01, (
            f"{emotion}: restart ({getattr(restarted, emotion)}) vs "
            f"continuous ({getattr(continuous, emotion)}) diverged"
        )

    # And both must show real decay over the 6 h (sanity): a 15 min core
    # half-life means 6 h = 24 half-lives, so joy is essentially at baseline.
    assert abs(getattr(restarted, "joy") - getattr(baseline, "joy")) < 0.01


# -- T5: No latch ------------------------------------------------------------

def test_t5_no_latch_random_impulses_then_rest_returns_to_baseline(
    physics: EmotionPhysics, baseline: EmotionVector
):
    """T5: 1,000 random impulses followed by rest returns to baseline.

    The PRD's "one hour of rest" was written for its own design where bond
    dimensions (love, trust) are "not decayed here, see section 6". Card W1-15
    step 5 keeps love/trust on a 12-hour half-life "for now", so they *are*
    decayed in ``tick`` — just slowly. The coupling matrix (step 3) spreads
    impulses onto love/trust (joy, empathy, compassion, gratitude all amplify
    love), so after 1,000 random impulses love/trust carry a real deviation
    that one hour cannot clear. To satisfy the pass condition ("returns to
    baseline") under the card's 12-hour bond half-life, the rest runs for
    enough bond half-lives (7 * 12 h = 84 h) to bring a 0.3 deviation under
    0.01. The non-bond dimensions settle far sooner (their longest half-life
    is 30 min), so this still verifies the no-latch property for every group.
    """
    rng = random.Random(20260218)  # deterministic
    target_dims = list(baseline.model_dump().keys())

    current = baseline.model_copy()
    for _ in range(1000):
        # One random dimension per impulse, modest delta.
        emotion = rng.choice(target_dims)
        delta = rng.uniform(-0.3, 0.3)
        current = physics.apply_influence(current, {emotion: delta}, intensity=1.0)

    # 7 half-lives of the slowest group (bond, 12 h) -> deviation * 0.5**7
    # = 0.3 * 0.0078 = 0.0023 < 0.01. 7 * 12 h = 84 h = 302400 s of 1 s ticks.
    for _ in range(302400):
        current = physics.tick(current, dt=1.0, baseline=baseline)

    for emotion, value in current.model_dump().items():
        assert abs(value - getattr(baseline, emotion)) < 0.01, (
            f"{emotion} did not return to baseline after rest: {value} vs "
            f"{getattr(baseline, emotion)}"
        )

