"""W3-11: memory salience.

Salience is built from emotional intensity, prediction error and interaction
depth. These tests pin the three helpers in
``aura.engines.memory.v2.salience`` and the depth formula that moved out of
``MemoryManager``.
"""

import math

import pytest

from aura.engines.memory.v2.salience import (
    emotional_intensity,
    interaction_depth,
    salience,
)
from aura.models.emotion import EmotionPhysicsConfig


BASELINE = EmotionPhysicsConfig().baseline.model_dump()


# ---------------------------------------------------------------------------
# emotional_intensity
# ---------------------------------------------------------------------------
def test_resting_state_equal_to_baseline_gives_zero_intensity():
    assert emotional_intensity(BASELINE, BASELINE) == 0.0


def test_three_strong_dimensions_give_a_higher_intensity_than_one():
    one_state = dict(BASELINE)
    one_state["joy"] = BASELINE["joy"] + 0.3
    one = emotional_intensity(one_state, BASELINE)

    three_state = dict(BASELINE)
    three_state["joy"] = BASELINE["joy"] + 0.3
    three_state["fear"] = BASELINE["fear"] + 0.4
    three_state["anger"] = BASELINE["anger"] + 0.5
    three = emotional_intensity(three_state, BASELINE)

    assert three > one


def test_hand_computed_rms_of_active_deviations():
    baseline = {"joy": 0.2, "fear": 0.0, "anger": 0.3, "calm": 0.0}
    state = {"joy": 0.5, "fear": 0.4, "anger": 0.0, "calm": 0.05}

    # Deviations: +0.3, +0.4, -0.3 and +0.05. The last is below the 0.1
    # active threshold, so the RMS is sqrt((0.3^2 + 0.4^2 + 0.3^2) / 3).
    expected = math.sqrt((0.3**2 + 0.4**2 + 0.3**2) / 3)
    assert emotional_intensity(state, baseline) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# salience
# ---------------------------------------------------------------------------
def test_missing_prediction_error_uses_neutral_half():
    assert salience(1.0, None, 0.0) == pytest.approx(salience(1.0, 0.5, 0.0))
    assert salience(1.0, None, 0.0) == pytest.approx(0.4 + 0.5 * 0.4)


def test_salience_uses_the_configured_weights():
    # (intensity 0.5 * 0.4) + (prediction error 0.5 * 0.4) + (depth 0.5 * 0.2)
    assert salience(0.5, 0.5, 0.5) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# interaction_depth: the MemoryManager depth formula, unchanged
# ---------------------------------------------------------------------------
def test_interaction_depth_matches_the_old_formula():
    # No response length counts as 0.3, so depth is 0.3 * 0.5.
    assert interaction_depth(0, 0, 0) == pytest.approx(0.15)
    assert interaction_depth(250, 0, 0) == pytest.approx(0.25)
    assert interaction_depth(500, 5, 3) == pytest.approx(1.0)
    assert interaction_depth(1000, 10, 6) == pytest.approx(1.0)