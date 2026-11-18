"""W1-10: a way to make a core memory.

Memory PRD F3: there was no way to promote an existing memory to a core
memory (or demote one).  This card adds ``MemoryManager.set_core`` and two
thin HTTP routes (``POST /memory/{id}/pin`` and ``POST /memory/{id}/unpin``)
that call it.

Pinning merges ``{"core_memory": True, "ephemeral": False}`` so the memory
becomes core *and* stops being ephemeral (core memories must persist).
Unpinning merges only ``{"core_memory": False}``.
"""

import pytest

from aura.engines.memory.manager import MemoryManager
from tests.conftest import FakeDatabaseClient


def _make_manager(db: FakeDatabaseClient) -> MemoryManager:
    """Build a MemoryManager without running ``__init__`` (which would open a
    real database connection and load the embedding model) and wire in the
    fake database."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = db
    mm.embeddings = None
    return mm


@pytest.mark.asyncio
async def test_pin_sets_core_and_clears_ephemeral():
    """Pinning a memory sets ``core_memory = True`` and ``ephemeral = False``."""
    db = FakeDatabaseClient()
    table = db._get_table("memory")
    mid = "memory:abc123"
    # Store under the record-id part so FakeDatabaseClient.merge (which splits
    # "memory:abc123" into table="memory", record_id="abc123") finds the row.
    table["abc123"] = {
        "id": mid,
        "content": "the user's birthday",
        "core_memory": False,
        "ephemeral": True,
    }

    mm = _make_manager(db)
    await mm.set_core(mid, True)

    row = table["abc123"]
    assert row["core_memory"] is True
    assert row["ephemeral"] is False


@pytest.mark.asyncio
async def test_unpin_clears_core():
    """Unpinning a memory clears ``core_memory`` and leaves ``ephemeral``
    untouched (only the core flag is merged)."""
    db = FakeDatabaseClient()
    table = db._get_table("memory")
    mid = "memory:abc123"
    table["abc123"] = {
        "id": mid,
        "content": "the user's birthday",
        "core_memory": True,
        "ephemeral": False,
    }

    mm = _make_manager(db)
    await mm.set_core(mid, False)

    row = table["abc123"]
    assert row["core_memory"] is False
    # unpinning only merges core_memory; ephemeral stays as it was
    assert row["ephemeral"] is False


@pytest.mark.asyncio
async def test_pin_merges_exactly_the_expected_payload():
    """Pin calls ``db.merge`` with exactly ``{"core_memory": True,
    "ephemeral": False}`` and nothing else."""
    db = FakeDatabaseClient()
    mm = _make_manager(db)

    merges: list[tuple[str, dict]] = []
    original_merge = db.merge

    async def _capture(thing, data):
        merges.append((thing, dict(data)))
        return await original_merge(thing, data)

    db.merge = _capture  # type: ignore[assignment]

    await mm.set_core("memory:xyz", True)

    assert len(merges) == 1
    thing, payload = merges[0]
    assert thing == "memory:xyz"
    assert payload == {"core_memory": True, "ephemeral": False}


@pytest.mark.asyncio
async def test_unpin_merges_exactly_the_expected_payload():
    """Unpin calls ``db.merge`` with exactly ``{"core_memory": False}`` and
    nothing else (it must not touch ``ephemeral``)."""
    db = FakeDatabaseClient()
    mm = _make_manager(db)

    merges: list[tuple[str, dict]] = []
    original_merge = db.merge

    async def _capture(thing, data):
        merges.append((thing, dict(data)))
        return await original_merge(thing, data)

    db.merge = _capture  # type: ignore[assignment]

    await mm.set_core("memory:xyz", False)

    assert len(merges) == 1
    thing, payload = merges[0]
    assert thing == "memory:xyz"
    assert payload == {"core_memory": False}
