"""W1-13: boost only once per retrieval, atomically.

Memory PRD F13: ``boost_on_recall`` was a non-atomic read-then-write. It
``SELECT``ed the current ``importance`` and ``recall_count``, then ``MERGE``d
the incremented values back. Two concurrent boosts on the same memory could
both read the same pre-boost values and both write ``recall_count + 1``,
losing one increment.

After W1-13 the whole thing is a single SurrealDB ``UPDATE`` that reads the
stored value and writes the new one in one statement. SurrealDB evaluates the
``SET`` expressions against the record image taken before the statement, and
serialises two updates on the same record, so two concurrent boosts raise
``recall_count`` by exactly two (and ``importance`` by ``2 * boost``, capped at
1.0). The preceding ``SELECT`` is gone.

The test fakes ``db.query`` so it applies the ``UPDATE`` the way SurrealDB
would: it parses the record id and the ``$boost`` parameter from the query and
mutates the stored row in place. Two ``boost_on_recall`` coroutines are awaited
concurrently with ``asyncio.gather``; afterwards ``recall_count`` must be
exactly two. A second test checks that the ``SELECT`` that used to precede the
write is no longer issued.
"""

import asyncio
import re

import pytest
from surrealdb import RecordID

from aura.engines.memory.manager import MemoryManager


# The boost query the manager now sends. Used to recognise the call and to pull
# the ``$mid`` and ``$boost`` parameters out of the params dict.
_BOOST_SQL_RE = re.compile(r"^\s*UPDATE \$mid SET", re.IGNORECASE)


def _row_key(mid: object) -> str:
    """Normalise a ``$mid`` parameter to the string key the fake rows dict
    uses.  W2-12 wraps the caller's string id in a ``RecordID`` before
    binding it, so ``$mid`` arrives as ``RecordID("memory", "abc")``; the
    fake stores rows keyed by the plain string ``"memory:abc"``."""
    if isinstance(mid, RecordID):
        return str(mid)
    return str(mid)


class _AtomicBoostFakeDB:
    """Minimal async db stand-in that applies the W1-13 boost ``UPDATE``.

    Only ``query`` is exercised by ``boost_on_recall``; it recognises the boost
    UPDATE and mutates the stored row in place, mirroring how SurrealDB applies a
    single ``UPDATE ... SET`` atomically. A lock serialises two concurrent
    applies so they cannot observe each other mid-write (they could not anyway
    inside a single awaited Python call, but the lock makes the contract
    explicit). Any other query raises ``NotImplementedError`` so the test
    cannot silently pass against a query it does not model.
    """

    def __init__(self, rows: dict[str, dict]):
        self._rows = rows
        self._lock = asyncio.Lock()
        self.queries: list[tuple[str, dict]] = []

    async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
        self.queries.append((sql, dict(vars or {})))
        if _BOOST_SQL_RE.match(sql):
            mid = _row_key(vars["mid"])
            boost = float(vars["boost"])
            async with self._lock:
                row = self._rows[mid]
                row["importance"] = min(1.0, float(row.get("importance", 0.5)) + boost)
                row["recall_count"] = int(row.get("recall_count", 0)) + 1
                row["last_recalled_at"] = vars["now"]
            return []
        raise NotImplementedError(f"Unexpected query: {sql}")


def _make_manager(rows: dict[str, dict]) -> tuple[MemoryManager, _AtomicBoostFakeDB]:
    """Build a MemoryManager (without running ``__init__``) wired to a fake db
    that atomically applies the boost UPDATE, and return both so the test can
    inspect the issued queries."""
    db = _AtomicBoostFakeDB(rows)
    mm = MemoryManager.__new__(MemoryManager)
    mm.db = db
    mm.embeddings = None
    return mm, db


@pytest.mark.asyncio
async def test_two_concurrent_boosts_raise_recall_count_by_exactly_two():
    """Two ``boost_on_recall`` coroutines awaited concurrently on the same
    memory must leave ``recall_count`` exactly two greater than before. The
    single atomic ``UPDATE`` replaces the old read-then-merge, so neither
    boost can read the other's pre-boost value and lose its increment."""
    rows = {"memory:abc": {"importance": 0.5, "recall_count": 0}}
    mm, db = _make_manager(rows)

    await asyncio.gather(
        mm.boost_on_recall("memory:abc", boost=0.05),
        mm.boost_on_recall("memory:abc", boost=0.05),
    )

    row = rows["memory:abc"]
    assert row["recall_count"] == 2
    # importance rose by 2 * boost and is still under the cap.
    assert row["importance"] == pytest.approx(0.5 + 0.05 + 0.05)
    # last_recalled_at was set on both boosts.
    assert row["last_recalled_at"] is not None


@pytest.mark.asyncio
async def test_importance_is_capped_at_one():
    """``math::min([1.0, importance + $boost])`` keeps importance from exceeding
    1.0 even after many boosts. The fake applies the same cap the query does."""
    rows = {"memory:abc": {"importance": 0.9, "recall_count": 0}}
    mm, db = _make_manager(rows)

    await asyncio.gather(
        mm.boost_on_recall("memory:abc", boost=0.2),
        mm.boost_on_recall("memory:abc", boost=0.2),
    )

    row = rows["memory:abc"]
    assert row["recall_count"] == 2
    assert row["importance"] == 1.0


@pytest.mark.asyncio
async def test_boost_is_a_single_update_with_no_preceding_read():
    """The rewrite sends exactly one ``UPDATE`` query and no ``SELECT``/``MERGE``
    before it. The old code did a ``SELECT ... FROM memory`` then a ``MERGE``;
    neither must appear anymore."""
    rows = {"memory:abc": {"importance": 0.5, "recall_count": 0}}
    mm, db = _make_manager(rows)

    await mm.boost_on_recall("memory:abc", boost=0.05)

    assert len(db.queries) == 1, "boost_on_recall must issue exactly one query"
    sql, params = db.queries[0]
    assert sql.strip().upper().startswith("UPDATE $MID SET")
    assert "MATH::MIN([1.0, IMPORTANCE + $BOOST])" in sql.upper()
    assert "RECALL_COUNT += 1" in sql.upper()
    assert "LAST_RECALLED_AT = $NOW" in sql.upper()
    # W2-12: the caller's string id is bound as a typed RecordID so the
    # embedded engine treats it as a record id, not a table name.
    assert isinstance(params["mid"], RecordID)
    assert str(params["mid"]) == "memory:abc"
    assert params["boost"] == 0.05
    assert "now" in params
    # No SELECT of the memory and no MERGE are issued.
    assert "SELECT" not in sql.upper()
    assert "MERGE" not in sql.upper()
