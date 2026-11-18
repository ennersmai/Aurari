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
from fastapi import HTTPException

from aura.engines.memory.manager import MemoryManager
from aura.api.routes.memory import pin_memory, unpin_memory
from tests.conftest import FakeDatabaseClient


def _make_manager(db: FakeDatabaseClient) -> MemoryManager:
    """Build a MemoryManager without running ``__init__`` (which would open a
    real database connection and load the embedding model) and wire in the
    fake database."""
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = db
    mm.embeddings = None
    return mm


class FailingDatabaseClient(FakeDatabaseClient):
    """A FakeDatabaseClient whose ``merge`` always raises."""

    def __init__(self, error_message: str = "DB merge failed"):
        super().__init__()
        self._error_message = error_message

    async def merge(self, thing: str, data: dict):
        raise Exception(self._error_message)


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


# =========================================================================
# BF-02: Pin and unpin report a failed database write
# =========================================================================

@pytest.mark.asyncio
async def test_set_core_raises_when_db_merge_fails():
    """A fake database whose ``merge`` raises makes ``set_core`` raise."""
    db = FailingDatabaseClient()
    mm = _make_manager(db)

    with pytest.raises(Exception, match="DB merge failed"):
        await mm.set_core("memory:xyz", True)

    with pytest.raises(Exception, match="DB merge failed"):
        await mm.set_core("memory:xyz", False)


@pytest.mark.asyncio
async def test_pin_route_returns_500_when_set_core_raises():
    """The pin route returns HTTP 500 with the expected JSON body when
    ``set_core`` raises."""
    db = FailingDatabaseClient()

    # Patch get_memory_manager to return a manager with the failing DB
    import aura.api.routes.memory as mem_routes
    original_get_mm = mem_routes.get_memory_manager

    def _mock_get_mm():
        return _make_manager(db)

    mem_routes.get_memory_manager = _mock_get_mm
    try:
        with pytest.raises(HTTPException) as exc_info:
            await pin_memory("memory:abc123")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == {"error": "Failed to update the memory", "memory_id": "memory:abc123"}
    finally:
        mem_routes.get_memory_manager = original_get_mm


@pytest.mark.asyncio
async def test_unpin_route_returns_500_when_set_core_raises():
    """The unpin route returns HTTP 500 with the expected JSON body when
    ``set_core`` raises."""
    db = FailingDatabaseClient()

    import aura.api.routes.memory as mem_routes
    original_get_mm = mem_routes.get_memory_manager

    def _mock_get_mm():
        return _make_manager(db)

    mem_routes.get_memory_manager = _mock_get_mm
    try:
        with pytest.raises(HTTPException) as exc_info:
            await unpin_memory("memory:abc123")
        assert exc_info.value.status_code == 500
        assert exc_info.value.detail == {"error": "Failed to update the memory", "memory_id": "memory:abc123"}
    finally:
        mem_routes.get_memory_manager = original_get_mm
