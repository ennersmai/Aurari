"""Mood: a slow running average of the emotional state (Emotion PRD 6.2).

Pure maths only. Mood is three numbers in [-1, 1] (valence, arousal, control),
the continuous-time moving average of the state's projection, advanced by real
elapsed time. The engine owns the state and the clock.
"""

AXES = ("valence", "arousal", "control")

# The positive dimensions of the valence split (same set as
# EmotionEngine._compute_valence). The mood baseline shift acts on these only.
POSITIVE_DIMENSIONS = (
    "joy", "love", "interest", "trust", "curiosity", "fascination",
    "wonder", "awe", "beauty", "serenity", "empathy", "compassion",
    "gratitude", "pride", "certainty",
)


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def project(
    vector: dict[str, float], baseline: dict[str, float], weights: dict[str, float]
) -> float:
    """Weighted sum of the dimensions' deviations from baseline, clamped to [-1, 1]."""
    total = sum(
        w * (vector.get(dim, 0.0) - baseline.get(dim, 0.0))
        for dim, w in weights.items()
    )
    return _clamp(total)


def project_mood(
    vector: dict[str, float],
    baseline: dict[str, float],
    weights: dict[str, dict[str, float]],
) -> dict[str, float]:
    """Project onto all three axes; ``weights`` maps axis name to a weight dict."""
    return {axis: project(vector, baseline, weights[axis]) for axis in AXES}


def decay_factor(dt: float, half_life: float) -> float:
    """Fraction of the gap to the target that closes in ``dt`` seconds."""
    if dt <= 0.0:
        return 0.0
    return 1.0 - 0.5 ** (dt / half_life)


def step(
    mood: dict[str, float], target: dict[str, float], dt: float, half_life: float
) -> dict[str, float]:
    """Move mood toward ``target``: m += (target - m) * (1 - 0.5 ** (dt / half_life))."""
    k = decay_factor(dt, half_life)
    return {
        axis: _clamp(mood[axis] + (target[axis] - mood[axis]) * k) for axis in AXES
    }


def decay(mood: dict[str, float], dt: float, half_life: float) -> dict[str, float]:
    """Decay mood toward neutral (0) by ``dt`` seconds."""
    return step(mood, {axis: 0.0 for axis in AXES}, dt, half_life)


def baseline_shift(valence: float, gain: float, cap: float) -> float:
    """Shift of the positive dimensions' resting point: gain * valence, capped."""
    return _clamp(gain * valence, -cap, cap)
