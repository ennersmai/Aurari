"""Memory salience for memory v2 (W3-11).

Salience says how much a moment deserves to become a lasting memory. It is
built from three signals: how far the emotional state is from rest, the
prediction error of the moment (until predictions exist, a neutral 0.5), and
how deep the interaction was.
"""

import math

from aura.config import settings


def interaction_depth(
    response_length: int | None,
    reasoning_steps: int | None,
    tool_calls: int | None,
) -> float:
    """Return the interaction depth in [0, 1].

    This is the depth formula from ``MemoryManager``'s formation score, kept
    here so there is one copy: response length contributes 0.5, reasoning
    steps 0.3 and tool calls 0.2. A missing response length counts as 0.3;
    missing reasoning steps and tool calls count as 0.0.
    """
    len_score = min(1.0, response_length / 500) if response_length else 0.3
    step_score = min(1.0, reasoning_steps / 5) if reasoning_steps else 0.0
    tool_score = min(1.0, tool_calls / 3) if tool_calls else 0.0
    return (len_score * 0.5) + (step_score * 0.3) + (tool_score * 0.2)


def emotional_intensity(
    state: dict[str, float], baseline: dict[str, float]
) -> float:
    """Return the root mean square of the active deviations from ``baseline``.

    For each dimension, ``d = state - baseline``. Only dimensions whose
    ``abs(d)`` is at least ``settings.memory_salience_active_min`` are active;
    the result is the RMS of the active ``d`` values, capped at 1.0, or 0.0
    when none are active.

    The PRD asks for a rolling baseline. The emotion engine has a fixed
    configured baseline today, so callers pass ``EmotionEngine.config.baseline``
    (as a dict) until the rolling baseline lands.
    """
    deviations = []
    for dimension, value in state.items():
        d = value - baseline.get(dimension, 0.0)
        if abs(d) >= settings.memory_salience_active_min:
            deviations.append(d)
    if not deviations:
        return 0.0
    rms = math.sqrt(sum(d * d for d in deviations) / len(deviations))
    return max(0.0, min(1.0, rms))


def salience(
    intensity: float,
    prediction_error: float | None,
    depth: float,
) -> float:
    """Return the weighted salience of a moment.

    The weights are ``settings.memory_salience_weights`` for (emotional
    intensity, prediction error, interaction depth). ``prediction_error=None``
    means predictions do not exist yet, so a neutral 0.5 is used.
    """
    intensity_weight, prediction_weight, depth_weight = (
        settings.memory_salience_weights
    )
    if prediction_error is None:
        prediction_error = 0.5
    return (
        intensity * intensity_weight
        + prediction_error * prediction_weight
        + depth * depth_weight
    )