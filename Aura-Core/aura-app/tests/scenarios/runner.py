"""Scenario runner for the Aura memory system (PRD §8.1, M0 remainder).

Card W2-01.

The runner drives the real :class:`MemoryManager` and
:class:`DreamingEngine` against a real in-memory SurrealDB (the embedded
engine of the installed ``surrealdb`` package, ``mem://``) so that a
scenario can be replayed offline and probes can be answered through the
same retrieval path the app uses.

No file under ``src/`` is changed by this card.  The app's
``DatabaseClient`` was written for the websocket SurrealDB API and is
incompatible with the embedded engine in two ways the runner has to
bridge *without* editing ``src/``:

1. ``query()`` on surrealdb 3.0.0 returns one entry per statement
   (``[[rows], [rows], ...]``); the app expects a flat list of row
   dicts.  The adapter flattens a single-statement response to that
   flat list.
2. The embedded connection has no ``merge`` method and treats a string
   record id such as ``"memory:abc"`` as a *table name* rather than a
   ``table:record`` pair, so CRUD calls that take a string record id are
   converted to ``RecordID`` objects and ``merge`` is implemented with
   an ``UPDATE ... MERGE`` query.

Everything else — the queries the manager emits, the schema, the
clock — is the app's real code path.  Queries the embedded engine
rejects (e.g. string record ids bound into ``UPDATE $mid``) fail the
same way they would against any server and are caught by the
manager/dreaming engines' own ``try/except`` blocks; the runner does
not paper over them.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from surrealdb import AsyncSurreal
from surrealdb.types import RecordID

from aura.clock import FakeClock, set_clock
from aura.engines.dreaming.engine import DreamingEngine
from aura.engines.memory.manager import MemoryManager


# ---------------------------------------------------------------------------
# Dataclasses (card step 1)
# ---------------------------------------------------------------------------


@dataclass
class Turn:
    """A single user utterance in a scenario."""

    user_id: str
    conversation_id: str
    text: str
    at_day: float


@dataclass
class Probe:
    """A recall probe asked at a point in the scenario timeline."""

    user_id: str
    question: str
    gold: list[str]
    at_day: float


@dataclass
class Scenario:
    """A replayable scenario: turns, dream cycles, then probes."""

    name: str
    turns: list[Turn]
    dream_at_days: list[float]
    probes: list[Probe]


@dataclass
class ProbeResult:
    """The outcome of answering one probe."""

    question: str
    gold_found: dict[str, bool]
    packet_chars: int


# ---------------------------------------------------------------------------
# Deterministic embedding stub (card step 3)
# ---------------------------------------------------------------------------


# The schema (scripts/init_schema.surql) locks the embedding field to
# ``option<array<float, 768>>`` — nomic-embed-text-v1.5's dimension.  The
# stub must produce exactly 768 floats.
_EMBED_DIM = 768


class HashedBagOfWordsEmbeddings:
    """Deterministic, offline 768-dim normalised hashed bag-of-words.

    No model download, no network.  Each whitespace token is hashed into
    one of 768 buckets; the bucket value is the (length-weighted) sum of
    the token's counts.  The resulting vector is L2-normalised so cosine
    similarity (which the schema's HNSW index and the manager's
    ``vector::similarity::cosine`` both use) is well defined.
    """

    dimension = _EMBED_DIM

    async def embed(self, text: str | None) -> list[float] | None:
        if not text or not text.strip():
            return None
        vec = [0.0] * _EMBED_DIM
        for token in re.findall(r"\w+", text.lower()):
            h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            bucket = int.from_bytes(h[:4], "little") % _EMBED_DIM
            # Weight longer tokens slightly more so "biscuit" isn't identical
            # to "biscuits" but still dominates short stopwords.
            weight = 1.0 + math.log(max(len(token), 1))
            vec[bucket] += weight
        norm = math.sqrt(sum(v * v for v in vec))
        if norm <= 0.0:
            # Degenerate input: return a deterministic unit-ish vector.
            return [1.0 / math.sqrt(_EMBED_DIM)] * _EMBED_DIM
        return [v / norm for v in vec]

    async def embed_batch(self, texts: list[str]) -> list[list[float] | None]:
        return [await self.embed(t) for t in texts]

    async def close(self) -> None:  # pragma: no cover - parity with real client
        pass


# ---------------------------------------------------------------------------
# In-memory embedded SurrealDB adapter (card step 2)
# ---------------------------------------------------------------------------


def _scripts_dir() -> Path:
    """Location of the app's ``.surql`` schema scripts."""
    return Path(__file__).resolve().parents[2] / "scripts"


async def _apply_surql_file(db: AsyncSurreal, file_name: str, label: str) -> None:
    """Apply a ``.surql`` script the same way the app does at startup.

    Mirrors ``aura.main._apply_surql_file``: strip ``--`` line comments
    and ``/* */`` block comments, split on ``;``, run each statement.
    Errors are swallowed (the app logs them as warnings) so the
    idempotent re-run semantics are preserved.  ``label`` is accepted
    for parity with the app's helper and is otherwise unused here.
    """
    path = _scripts_dir() / file_name
    if not path.exists():
        return
    raw = path.read_text(encoding="utf-8")
    cleaned = "\n".join(
        line
        for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    cleaned = re.sub(r"/\*.*?\*/", "", cleaned, flags=re.DOTALL)
    for stmt in cleaned.split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        try:
            await db.query(stmt)
        except Exception:  # noqa: BLE001 — mirror app's swallow-on-error
            pass


# Schema files the app applies at boot, in boot order (see aura.main.lifespan).
_SCHEMA_FILES = [
    ("init_schema.surql", "Core schema (structural)"),
    ("seed_emotions.surql", "Emotion + identity seeds"),
    ("register_local_tools.surql", "Local tool registrations"),
    ("seed_cultural_nodes.surql", "Cultural node seeds"),
    ("setup_tasks.surql", "Task scaffolding"),
]


def _to_record_id(thing: str) -> RecordID | str:
    """Convert a ``"table:id"`` string to a ``RecordID``.

    The embedded engine treats the whole string as a table name when it
    contains a single colon, so ``"memory:abc"`` must become
    ``RecordID("memory", "abc")``.  Strings without a colon (a bare table
    name like ``"memory"``) are returned unchanged.
    """
    if isinstance(thing, str) and ":" in thing:
        table, _, rid = thing.partition(":")
        if table and rid:
            return RecordID(table, rid)
    return thing


class EmbeddedSurrealDB:
    """A thin adapter that presents the app's ``DatabaseClient`` interface
    over the embedded in-memory SurrealDB engine.

    Only the methods ``MemoryManager`` / ``DreamingEngine`` actually call
    (``query``, ``create``, ``merge``, ``delete``) plus ``select`` /
    ``update`` for parity are implemented.
    """

    def __init__(self) -> None:
        self._client: AsyncSurreal | None = None
        self._connected: bool = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._client is not None

    async def connect(self) -> None:
        self._client = AsyncSurreal("mem://")
        await self._client.connect()
        # The embedded engine has no auth; just select the namespace/db the
        # app uses (the schema files open with ``USE NS aura DB main;``).
        await self._client.use("aura", "main")
        # Apply the schema the same way the app does at startup.
        for file_name, label in _SCHEMA_FILES:
            await _apply_surql_file(self._client, file_name, label)
        self._connected = True

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:  # noqa: BLE001
                pass
        self._connected = False
        self._client = None

    @staticmethod
    def _flatten(result: Any) -> list[Any]:
        """Normalise a surrealdb 3.0 ``query`` response to the flat row
        list the app expects.

        surrealdb 3.0 returns one entry per statement (issue #232 fix);
        a single-statement ``SELECT`` therefore comes back as
        ``[[rows...]]``.  The app's queries are all single-statement, so
        we unwrap the outer list.  A statement that produces no value
        (``DEFINE``) yields ``None`` and is normalised to ``[]``.
        """
        if isinstance(result, list):
            if len(result) == 1:
                inner = result[0]
                return inner if isinstance(inner, list) else ([inner] if inner is not None else [])
            # Multi-statement: return the per-statement results as-is.
            return result
        if result is None:
            return []
        if isinstance(result, dict):
            return [result]
        return [result]

    async def query(self, sql: str, vars: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("Database not connected")
        result = await self._client.query(sql, vars)
        return self._flatten(result)

    async def select(self, thing: str) -> list[dict[str, Any]]:
        if self._client is None:
            raise RuntimeError("Database not connected")
        target = _to_record_id(thing)
        result = await self._client.select(target)
        # ``select`` on a table returns a flat list; on a record id it can
        # return a single dict or None.
        if isinstance(result, list):
            return result
        if result is None:
            return []
        return [result]

    async def create(self, thing: str, data: dict[str, Any]) -> Any:
        if self._client is None:
            raise RuntimeError("Database not connected")
        target = _to_record_id(thing)
        return await self._client.create(target, data)

    async def update(self, thing: str, data: dict[str, Any]) -> Any:
        if self._client is None:
            raise RuntimeError("Database not connected")
        target = _to_record_id(thing)
        return await self._client.update(target, data)

    async def merge(self, thing: str, data: dict[str, Any]) -> Any:
        """Merge data into a record.

        The embedded connection has no ``merge`` method, so implement it
        with a parameterised ``UPDATE ... MERGE`` query (SurrealDB native
        merge), binding the record id as a typed ``RecordID``.
        """
        if self._client is None:
            raise RuntimeError("Database not connected")
        rid = _to_record_id(thing)
        if not isinstance(rid, RecordID):
            # Fall back to a plain UPDATE for bare table names.
            return await self._client.update(thing, data)
        result = await self._client.query(
            "UPDATE $rid MERGE $data", {"rid": rid, "data": data}
        )
        return self._flatten(result)

    async def delete(self, thing: str) -> Any:
        if self._client is None:
            raise RuntimeError("Database not connected")
        target = _to_record_id(thing)
        return await self._client.delete(target)


# ---------------------------------------------------------------------------
# Runner (card step 5)
# ---------------------------------------------------------------------------


# Fixed scenario start date so the FakeClock is deterministic.
_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _build_manager(db: EmbeddedSurrealDB) -> MemoryManager:
    """Construct a MemoryManager wired to the embedded DB and the
    deterministic embedding stub, without opening a real DB connection
    or loading the embedding model.

    ``MemoryManager.__init__`` sets ``self.db`` / ``self.embeddings`` to
    the app's process-wide singletons (which are never connected and
    never load a model until ``embed()`` is called); we overwrite both
    with the offline versions the card specifies.
    """
    manager = MemoryManager()
    manager.db = db  # type: ignore[assignment]
    manager.embeddings = HashedBagOfWordsEmbeddings()  # type: ignore[assignment]
    return manager


def _build_dreaming(db: EmbeddedSurrealDB) -> DreamingEngine:
    """Construct a DreamingEngine wired to the embedded DB with no LLM
    dependencies, exactly as the app constructs it minus the LLM layers
    the offline runner does not have.
    """
    engine = DreamingEngine()
    engine.db = db  # type: ignore[assignment]
    # The app calls set_dependencies(llm_layers=..., learning_engine=...).
    # Offline there is no LLM and no learning engine, so pass None — the
    # dreaming phases that need them are gated on `if self._llm_layers:`.
    engine.set_dependencies(llm_layers=None, learning_engine=None)
    return engine


# Event ordering: at a given day, turns run first, then dreams, then probes.
_PHASE_ORDER = {"turn": 0, "dream": 1, "probe": 2}


async def run(scenario: Scenario) -> list[ProbeResult]:
    """Run a scenario and return the probe results.

    Feeds each turn through ``MemoryManager.store_memory`` with the
    arguments the app uses, runs ``DreamingEngine.enter_rem_sleep`` at
    each dream time (dependencies set as the app sets them), then
    answers each probe with ``retrieve_for_l3`` as the app calls it,
    recording whether each gold string appears in the returned packet
    text.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        clock = FakeClock(_START)
        set_clock(clock)

        manager = _build_manager(db)
        dreaming = _build_dreaming(db)

        # Build a single chronological timeline with a phase tiebreaker so
        # a turn, a dream and a probe on the same day run in that order.
        events: list[tuple[float, int, str, Any]] = []
        for turn in scenario.turns:
            events.append((turn.at_day, _PHASE_ORDER["turn"], "turn", turn))
        for day in scenario.dream_at_days:
            events.append((day, _PHASE_ORDER["dream"], "dream", day))
        for probe in scenario.probes:
            events.append((probe.at_day, _PHASE_ORDER["probe"], "probe", probe))
        events.sort(key=lambda e: (e[0], e[1]))

        results: list[ProbeResult] = []
        for at_day, _phase, kind, payload in events:
            clock.set(_START + timedelta(days=at_day))

            if kind == "turn":
                turn: Turn = payload
                # The app builds `content = f"User: {user_input}\nAura: {aura_response}"`
                # and stores with these keyword arguments (coordinator.py).
                content = f"User: {turn.text}\nAura: "
                await manager.store_memory(
                    content=content,
                    user_id=turn.user_id,
                    conversation_id=turn.conversation_id,
                    emotional_signature={},
                    importance=0.5,
                    tags=["conversation", "interaction"],
                    resonance_score=None,
                    formation_context=None,
                    response_length=0,
                )
            elif kind == "dream":
                await dreaming.enter_rem_sleep()
            elif kind == "probe":
                probe: Probe = payload
                # The app's standard (non-streaming) call (llm/layers.py).
                _memories, packet_xml = await manager.retrieve_for_l3(
                    query=probe.question,
                    current_emotions=None,
                    user_id=probe.user_id,
                    limit=5,
                    depth=2,
                )
                gold_found = {g: (g in (packet_xml or "")) for g in probe.gold}
                results.append(
                    ProbeResult(
                        question=probe.question,
                        gold_found=gold_found,
                        packet_chars=len(packet_xml or ""),
                    )
                )
        return results
    finally:
        await db.close()
        # Leave the global clock in a clean state for the next test.
        from aura.clock import Clock, set_clock as _set_clock

        _set_clock(Clock())
