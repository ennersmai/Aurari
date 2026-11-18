"""BF-05: Memory reads time through the clock provider.

Tests that Memory timestamp defaults and _compute_decay_factor use the clock provider.
"""

import math
from datetime import datetime, timezone, timedelta

import pytest

from aura.clock import FakeClock, set_clock
from aura.engines.memory.manager import MemoryManager, RECENCY_HALF_LIFE_H
from aura.models.memory import Memory


def test_memory_timestamp_uses_fake_clock():
    """A new Memory() gets the fake clock's time as its timestamp."""
    # Set up a fake clock at a fixed time
    fixed_time = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    fake = FakeClock(fixed_time)
    set_clock(fake)

    try:
        # Create a memory without providing a timestamp
        mem = Memory(memory_id="memory:test", content="test memory")

        # The timestamp should match the fake clock's time (naive UTC)
        expected_naive = fixed_time.replace(tzinfo=None)
        assert mem.timestamp == expected_naive
    finally:
        # Restore real clock
        from aura.clock import Clock
        set_clock(Clock())


def test_compute_decay_factor_uses_fake_clock():
    """_compute_decay_factor on a memory 30 days old matches the formula."""
    # Set up a fake clock at a fixed time
    fixed_time = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    fake = FakeClock(fixed_time)
    set_clock(fake)

    try:
        # Create a manager instance without running __init__
        mm = MemoryManager.__new__(MemoryManager)

        # Create a memory row with timestamp = fixed_time - 30 days
        thirty_days_ago = fixed_time - timedelta(days=30)
        # _parse_ts expects timezone-aware, so we use the timezone-aware version
        row = {
            "timestamp": thirty_days_ago,  # timezone-aware
            "core_memory": False,
            "memory_type": "episodic",
            "emotional_intensity": 0.4,
            "recall_count": 0,
            "ephemeral": False,
        }

        # Compute decay factor
        decay = mm._compute_decay_factor(row)

        # Compute expected value from the formula
        # age_hours = 30 * 24 = 720 hours
        # half_life = RECENCY_HALF_LIFE_H = 48 hours (base)
        # emotional_intensity = 0.4 <= 0.7 (EMOTIONAL_PROTECTION_INTENSITY), no protection
        # recall_count = 0, no access strengthening
        # ephemeral = False, no acceleration
        # decay = exp(-0.693 * age_hours / half_life)
        age_hours = 30 * 24  # 720
        half_life = RECENCY_HALF_LIFE_H  # 48
        expected_decay = math.exp(-0.693 * age_hours / half_life)

        assert decay == pytest.approx(expected_decay, rel=1e-6)
    finally:
        # Restore real clock
        from aura.clock import Clock
        set_clock(Clock())


def test_compute_decay_factor_core_memory_returns_one():
    """Core memories return 1.0 regardless of clock."""
    fixed_time = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    fake = FakeClock(fixed_time)
    set_clock(fake)

    try:
        mm = MemoryManager.__new__(MemoryManager)

        row = {
            "timestamp": fixed_time - timedelta(days=30),
            "core_memory": True,
            "memory_type": "episodic",
            "emotional_intensity": 0.4,
            "recall_count": 0,
            "ephemeral": False,
        }

        decay = mm._compute_decay_factor(row)
        assert decay == 1.0
    finally:
        from aura.clock import Clock
        set_clock(Clock())


def test_compute_decay_factor_semantic_memory_returns_one():
    """Semantic memories return 1.0 regardless of clock."""
    fixed_time = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    fake = FakeClock(fixed_time)
    set_clock(fake)

    try:
        mm = MemoryManager.__new__(MemoryManager)

        row = {
            "timestamp": fixed_time - timedelta(days=90),
            "core_memory": False,
            "memory_type": "semantic",
            "emotional_intensity": 0.4,
            "recall_count": 0,
            "ephemeral": False,
        }

        decay = mm._compute_decay_factor(row)
        assert decay == 1.0
    finally:
        from aura.clock import Clock
        set_clock(Clock())