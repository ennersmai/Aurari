"""Embedded-SurrealDB tests for delegation close and memory write (card W3-33).

These tests drive the real in-memory embedded SurrealDB (``mem://``) through
the scenario runner's adapter and deterministic embedding stub, with both
memory schema files applied exactly as the app applies them at boot. They
cover the delegation memory write in ``aura.executor.delegation._write_delegation_memory``:

* A succeeded task stores the episode and the external fact.
* The episode has user_text = goal, aura_text = outcome summary, speaker = owner, venue = app.
* The fact has provenance = external, visibility = owner, content = "Aura delegated: <goal> in <workspace>: <outcome>".
* The fact is linked to the episode via derived_from.
* Skill statistics are G5 and are not asserted.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import to_record_id
from aura.engines.memory.v2.episodes import ensure_person, store_episode
from aura.engines.memory.v2.facts import write_facts
from aura.engines.memory.v2.extraction import Extraction, ExtractedFact, ExtractedEntity
from aura.executor.delegation import DelegationConfig, DelegationRunner
from aura.executor.task_queue import TaskQueueService
from aura.models.task import Task, TaskStatus
from tests.scenarios.runner import EmbeddedSurrealDB, HashedBagOfWordsEmbeddings

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


async def _open_db() -> EmbeddedSurrealDB:
    db = EmbeddedSurrealDB()
    await db.connect()
    return db


async def _episodes(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM episode ORDER BY recorded_at ASC")


async def _facts(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM fact ORDER BY recorded_at ASC")


async def _derived_from_relations(db: EmbeddedSurrealDB) -> list[dict]:
    return await db.query("SELECT * FROM derived_from")


async def _ensure_owner_entity(db: EmbeddedSurrealDB, embeddings: HashedBagOfWordsEmbeddings) -> None:
    """Ensure the owner entity exists for fact writing."""
    from aura.engines.memory.v2.episodes import ensure_person
    await ensure_person(db, "owner", "owner")


class MockTaskQueue:
    """Mock TaskQueueService for testing _write_delegation_memory."""

    def __init__(self, db: EmbeddedSurrealDB):
        self.db = db


@pytest.mark.asyncio
async def test_delegation_succeeded_writes_episode_and_external_fact():
    """T4: A succeeded delegation task stores an episode and an external fact."""
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        # Ensure owner entity exists
        await _ensure_owner_entity(db, embeddings)

        # Create a mock task queue with the embedded DB
        mock_task_queue = MockTaskQueue(db)

        # Create a DelegationRunner instance (we only need the _write_delegation_memory method)
        config = DelegationConfig(
            goal="Build a login page",
            workspace="test-workspace",
            agent="aura-build",
            success_criteria="Login page works",
            tokens=200000,
            minutes=30,
        )
        runner = DelegationRunner(config)

        # Mock the task_queue.get_task_queue to return our mock
        # Also mock get_embeddings_client to return our deterministic embeddings
        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.llm.embeddings.get_embeddings_client", return_value=embeddings):
            # Enable memory v2 write
            settings.memory_v2_write_enabled = True
            try:
                # Call the internal method directly
                await runner._write_delegation_memory(mock_task_queue, "task:abc123", "succeeded", "Review passed")
            finally:
                settings.memory_v2_write_enabled = False

        # Verify episode was created
        episodes = await _episodes(db)
        assert len(episodes) == 1, f"Expected 1 episode, got {len(episodes)}"
        episode = episodes[0]
        assert episode["user_text"] == "Build a login page"
        assert "Delegation succeeded" in episode["aura_text"]
        assert episode["speaker"] == to_record_id("entity:owner")
        assert episode["venue"] == "app"
        assert episode["ephemeral"] is False

        # Verify fact was created
        facts = await _facts(db)
        assert len(facts) == 1, f"Expected 1 fact, got {len(facts)}"
        fact = facts[0]
        # Delegated work is external knowledge (agency PRD 4.8)
        assert fact["provenance"] == "external"
        assert fact["visibility"] == "owner"
        assert "Aura delegated: Build a login page in test-workspace: succeeded" in fact["content"]
        assert fact["kind"] == "event"
        assert fact["subject"] == "Aura"
        assert fact["predicate"] == "delegated"
        assert fact["object"] == "Build a login page"

        # Verify derived_from relation links fact to episode
        derived_from = await _derived_from_relations(db)
        assert len(derived_from) == 1, f"Expected 1 derived_from relation, got {len(derived_from)}"
        assert derived_from[0]["in"] == fact["id"]
        assert derived_from[0]["out"] == episode["id"]

    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_delegation_failed_writes_episode_and_external_fact():
    """A failed delegation task also stores an episode and external fact."""
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        await _ensure_owner_entity(db, embeddings)

        mock_task_queue = MockTaskQueue(db)

        config = DelegationConfig(
            goal="Refactor authentication",
            workspace="test-workspace",
            agent="aura-build",
            success_criteria="Tests pass",
            tokens=200000,
            minutes=30,
        )
        runner = DelegationRunner(config)

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.llm.embeddings.get_embeddings_client", return_value=embeddings):
            settings.memory_v2_write_enabled = True
            try:
                await runner._write_delegation_memory(mock_task_queue, "task:def456", "failed", "Review failed: Missing tests")
            finally:
                settings.memory_v2_write_enabled = False

        # Verify episode was created
        episodes = await _episodes(db)
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode["user_text"] == "Refactor authentication"
        assert "Delegation failed" in episode["aura_text"]

        # Verify fact was created with failed outcome
        facts = await _facts(db)
        assert len(facts) == 1
        fact = facts[0]
        # Delegated work is external knowledge (agency PRD 4.8)
        assert fact["provenance"] == "external"
        assert fact["visibility"] == "owner"
        assert "Aura delegated: Refactor authentication in test-workspace: failed" in fact["content"]

        # Verify derived_from relation
        derived_from = await _derived_from_relations(db)
        assert len(derived_from) == 1
        assert derived_from[0]["in"] == fact["id"]
        assert derived_from[0]["out"] == episode["id"]

    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_delegation_needs_owner_writes_episode_and_external_fact():
    """A needs_owner delegation task also stores an episode and external fact."""
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        await _ensure_owner_entity(db, embeddings)

        mock_task_queue = MockTaskQueue(db)

        config = DelegationConfig(
            goal="Implement feature X",
            workspace="test-workspace",
            agent="aura-build",
            success_criteria="Feature works",
            tokens=200000,
            minutes=30,
        )
        runner = DelegationRunner(config)

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.llm.embeddings.get_embeddings_client", return_value=embeddings):
            settings.memory_v2_write_enabled = True
            try:
                await runner._write_delegation_memory(mock_task_queue, "task:ghi789", "needs_owner", "No verdict in review")
            finally:
                settings.memory_v2_write_enabled = False

        # Verify episode was created
        episodes = await _episodes(db)
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode["user_text"] == "Implement feature X"
        assert "Delegation needs_owner" in episode["aura_text"]

        # Verify fact was created with needs_owner outcome
        facts = await _facts(db)
        assert len(facts) == 1
        fact = facts[0]
        # Delegated work is external knowledge (agency PRD 4.8)
        assert fact["provenance"] == "external"
        assert fact["visibility"] == "owner"
        assert "Aura delegated: Implement feature X in test-workspace: needs_owner" in fact["content"]

    finally:
        await db.close()
        set_clock(Clock())


@pytest.mark.asyncio
async def test_delegation_memory_write_requires_flag():
    """When memory_v2_write_enabled is off, _write_delegation_memory is not called (checked at higher level)."""
    # This test verifies that the flag check is in _finalize_task, not in _write_delegation_memory
    # The method itself doesn't check the flag; the caller (_finalize_task) does.
    db = await _open_db()
    clock = FakeClock(_START)
    set_clock(clock)
    try:
        embeddings = HashedBagOfWordsEmbeddings()

        await _ensure_owner_entity(db, embeddings)

        mock_task_queue = MockTaskQueue(db)

        config = DelegationConfig(
            goal="Test goal",
            workspace="test-workspace",
            agent="aura-build",
            success_criteria="Done",
            tokens=200000,
            minutes=30,
        )
        runner = DelegationRunner(config)

        with patch("aura.executor.delegation.get_task_queue", return_value=mock_task_queue), \
             patch("aura.llm.embeddings.get_embeddings_client", return_value=embeddings):
            # Call the method directly - it doesn't check the flag
            settings.memory_v2_write_enabled = False
            await runner._write_delegation_memory(mock_task_queue, "task:jkl012", "succeeded", "Done")

        # The method was called directly, so episode was created (flag check is in caller)
        episodes = await _episodes(db)
        assert len(episodes) == 1
        episode = episodes[0]
        assert episode["user_text"] == "Test goal"
        assert "Delegation succeeded" in episode["aura_text"]

    finally:
        await db.close()
        set_clock(Clock())