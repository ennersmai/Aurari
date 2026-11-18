"""W1-06: emotional intensity that can reach its thresholds.

The old ``_compute_emotional_intensity`` computed the L2 magnitude of the
full 27-dimension signature and normalised by ``sqrt(27)`` (~5.2). That meant a
strong but narrow emotion (e.g. three dimensions at 0.8) only scored ~0.27 and
could never reach the formation/decay thresholds that gate on intensity.

The new implementation computes the RMS of the *active* (>=0.1) dimensions and
clamps to [0, 1], so a genuinely intense event can reach 1.0.
"""

import pytest

from aura.engines.memory.manager import _compute_emotional_intensity


def test_three_dimensions_at_0_8_give_0_8():
    """Three active dimensions all at 0.8 -> RMS == 0.8."""
    sig = {"joy": 0.8, "interest": 0.8, "trust": 0.8}
    assert _compute_emotional_intensity(sig) == pytest.approx(0.8)


def test_empty_signature_gives_0_0():
    """No signature -> no intensity."""
    assert _compute_emotional_intensity({}) == 0.0


def test_fourteen_dimensions_at_1_0_give_1_0():
    """Fourteen active dimensions all at 1.0 -> RMS == 1.0 (clamped)."""
    sig = {f"dim_{i}": 1.0 for i in range(14)}
    assert _compute_emotional_intensity(sig) == pytest.approx(1.0)


def test_below_threshold_dimensions_are_ignored():
    """Values below 0.1 are treated as inactive and do not count toward RMS,
    so a signature with only sub-threshold values reads as 0.0."""
    sig = {"joy": 0.05, "sadness": 0.09}
    assert _compute_emotional_intensity(sig) == 0.0


def test_mixed_active_and_inactive_dimensions():
    """Only the active dimensions contribute to the RMS."""
    sig = {"joy": 0.8, "interest": 0.8, "trust": 0.8, "boredom": 0.05}
    assert _compute_emotional_intensity(sig) == pytest.approx(0.8)
