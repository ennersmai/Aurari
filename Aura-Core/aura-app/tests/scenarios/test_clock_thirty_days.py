"""Scenario test for BF-06: Dreaming reads time through the clock provider, 30-day scenario.

This test verifies that the DreamingEngine and MemoryManager correctly use the
clock provider for time-dependent operations, and that a 30-day-old memory
is correctly recognized as 30 days old when the fake clock is advanced.
"""

import math
from datetime import datetime, timedelta, timezone

import pytest

from aura.clock import FakeClock, set_clock
from aura.engines.dreaming.engine import DreamingEngine
from aura.engines.memory.manager import MemoryManager
from tests.scenarios.runner import (
    EmbeddedSurrealDB,
    _build_dreaming,
    _build_manager,
    _START,
)


async def _apply_schema(db: EmbeddedSurrealDB) -> None:
    """Ensure schema is applied (runner does this in connect)."""
    # The runner's connect() already applies schema, but we call it explicitly
    # to be safe if the db was created outside the runner.
    pass


async def _store_test_memory(manager: MemoryManager) -> str:
    """Store a test memory and return its ID."""
    memory_id = await manager.store_memory(
        content="Test memory for 30-day decay test",
        user_id="test_user",
        conversation_id="test_conv",
        emotional_signature={},
        importance=0.5,
        tags=["test"],
        resonance_score=None,
        formation_context=None,
        response_length=0,
    )
    return memory_id


async def _get_stored_memory(manager: MemoryManager, memory_id: str) -> dict:
    """Retrieve a stored memory by ID."""
    # Use the database directly to get the raw row
    # memory_id already includes the "memory:" prefix from store_memory
    result = await manager.db.select(memory_id)
    if result:
        return result[0]
    return {}


def _compute_expected_decay(age_days: float, emotional_intensity: float = 0.0, recall_count: int = 0, ephemeral: bool = False, memory_type: str = "episodic") -> float:
    """Compute the expected decay value using the same formula as the engines.

    This mirrors the logic in DreamingEngine._compute_decay and
    MemoryManager._compute_decay_factor.
    """
    # Semantic memories never fade
    if memory_type == "semantic":
        return 1.0

    age_hours = age_days * 24
    half_life = 48.0  # _RECENCY_HALF_LIFE_H

    if emotional_intensity > 0.7:
        half_life *= 4.0

    half_life += recall_count * 12.0

    if ephemeral:
        half_life /= 4.0

    half_life = max(half_life, 0.1)
    return math.exp(-0.693 * age_hours / half_life)


@pytest.mark.asyncio
async def test_dreaming_clock_thirty_days():
    """Test that DreamingEngine._compute_decay correctly computes 30-day decay
    when the fake clock is advanced 30 days.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        # Set up fake clock at start
        clock = FakeClock(_START)
        set_clock(clock)

        manager = _build_manager(db)
        dreaming = _build_dreaming(db)

        # Store a memory at day 0
        memory_id = await _store_test_memory(manager)
        memory_row = await _get_stored_memory(manager, memory_id)
        assert memory_row, "Memory should be stored"

        # Verify initial decay (day 0) - should be 1.0 (fresh memory)
        initial_decay = DreamingEngine._compute_decay(memory_row)
        expected_initial = _compute_expected_decay(0.0)
        assert abs(initial_decay - expected_initial) < 0.001, (
            f"Initial decay {initial_decay} != expected {expected_initial}"
        )

        # Also test MemoryManager._compute_decay_factor
        mm_decay = manager._compute_decay_factor(memory_row)
        assert abs(mm_decay - expected_initial) < 0.001, (
            f"MM initial decay {mm_decay} != expected {expected_initial}"
        )

        # Advance clock to day 30
        clock.set(_START + timedelta(days=30))

        # Re-fetch the memory row (timestamp hasn't changed, but clock has)
        memory_row = await _get_stored_memory(manager, memory_row.get("id", memory_id))
        assert memory_row, "Memory should still exist"

        # Compute decay at day 30 using DreamingEngine
        day30_decay = DreamingEngine._compute_decay(memory_row)
        expected_day30 = _compute_expected_decay(30.0)
        assert abs(day30_decay - expected_day30) < 0.001, (
            f"Day 30 decay {day30_decay} != expected {expected_day30}"
        )

        # Compute decay at day 30 using MemoryManager
        mm_decay_30 = manager._compute_decay_factor(memory_row)
        assert abs(mm_decay_30 - expected_day30) < 0.001, (
            f"MM day 30 decay {mm_decay_30} != expected {expected_day30}"
        )

        # Run a dream cycle at day 30 - it should see the memory as 30 days old
        # The dream cycle calls _tiered_pruning which uses the clock
        report = await dreaming.enter_rem_sleep()

        # Verify the memory still exists (not pruned - it's not ephemeral)
        memory_row_after = await _get_stored_memory(manager, memory_row.get("id", memory_id))
        assert memory_row_after, "Non-ephemeral memory should not be pruned"

        # The dream cycle should have completed
        assert report is not None

        print(f"Day 0 decay: {initial_decay:.6f}")
        print(f"Day 30 decay: {day30_decay:.6f}")
        print(f"Expected day 30 decay: {expected_day30:.6f}")
        print(f"Dream report: pruned={report.pruned}, core={report.core_memories}, total_active={report.total_active}")

    finally:
        await db.close()
        # Restore real clock
        from aura.clock import Clock, set_clock as _set_clock
        _set_clock(Clock())


@pytest.mark.asyncio
async def test_memory_manager_clock_thirty_days():
    """Test that MemoryManager._compute_decay_factor correctly computes 30-day decay."""
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        clock = FakeClock(_START)
        set_clock(clock)

        manager = _build_manager(db)

        # Store a memory at day 0
        memory_id = await _store_test_memory(manager)
        memory_row = await _get_stored_memory(manager, memory_id)
        assert memory_row

        # Verify initial decay
        initial_decay = manager._compute_decay_factor(memory_row)
        expected_initial = _compute_expected_decay(0.0)
        assert abs(initial_decay - expected_initial) < 0.001

        # Advance to day 30
        clock.set(_START + timedelta(days=30))

        memory_row = await _get_stored_memory(manager, memory_row.get("id", memory_id))
        assert memory_row

        # Verify day 30 decay
        day30_decay = manager._compute_decay_factor(memory_row)
        expected_day30 = _compute_expected_decay(30.0)
        assert abs(day30_decay - expected_day30) < 0.001

    finally:
        await db.close()
        from aura.clock import Clock, set_clock as _set_clock
        _set_clock(Clock())


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_dreaming_clock_thirty_days())
    asyncio.run(test_memory_manager_clock_thirty_days())
    print("All tests passed!")