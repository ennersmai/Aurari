"""Test configuration and fixtures for Aura test suite."""

import asyncio
import logging

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock


class FakeDatabaseClient:
    """
    In-memory stand-in for aura.db.client.DatabaseClient.
    
    Stores rows in dictionaries and supports the basic CRUD operations
    needed for Wave 1 unit tests. Unsupported queries raise NotImplementedError.
    """
    
    def __init__(self):
        self._tables: dict[str, dict[str, dict[str, Any]]] = {}
        self._connected = True
    
    @property
    def is_connected(self) -> bool:
        return self._connected
    
    async def connect(self) -> None:
        self._connected = True
    
    async def close(self) -> None:
        self._connected = False
    
    def _get_table(self, table: str) -> dict[str, dict[str, Any]]:
        if table not in self._tables:
            self._tables[table] = {}
        return self._tables[table]
    
    async def query(self, sql: str, vars: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a SurrealQL query - minimal implementation for test support."""
        sql_lower = sql.strip().lower()
        
        # Handle simple SELECT count() queries
        if "count()" in sql_lower and "group all" in sql_lower:
            table = sql_lower.split("from")[1].split("where")[0].strip()
            table_data = self._get_table(table)
            # Apply WHERE filter if present (simplified)
            if "where" in sql_lower:
                where_clause = sql_lower.split("where")[1].split("group")[0].strip()
                # Very basic filtering for deprecated = false
                if "deprecated = false" in where_clause:
                    filtered = [r for r in table_data.values() if not r.get("deprecated", False)]
                    return [{"count": len(filtered)}]
            return [{"count": len(table_data)}]
        
        # Handle SELECT * FROM memory WHERE id = $mid
        if "from memory" in sql_lower and "where id" in sql_lower:
            table_data = self._get_table("memory")
            if vars and "mid" in vars:
                mid = vars["mid"]
                if mid in table_data:
                    return [table_data[mid]]
                return []
        
        # Handle SELECT for _fetch_thought_cluster (experience table)
        if "from experience" in sql_lower:
            return []
        
        # Handle SELECT for tiered_pruning
        if "from memory" in sql_lower and "ephemeral = true" in sql_lower:
            table_data = self._get_table("memory")
            filtered = []
            for row in table_data.values():
                if row.get("ephemeral") and not row.get("deprecated", False):
                    if "timestamp <" in sql_lower and vars and "cutoff" in vars:
                        cutoff = vars["cutoff"]
                        row_ts = row.get("timestamp")
                        if row_ts and row_ts < cutoff:
                            if "recall_count = 0" in sql_lower:
                                if row.get("recall_count", 0) == 0:
                                    filtered.append(row)
                            else:
                                filtered.append(row)
            return filtered
        
        # Handle SELECT for tier 3 pruning
        if "from memory" in sql_lower and "core_memory = false" in sql_lower and "ephemeral = false" in sql_lower:
            table_data = self._get_table("memory")
            filtered = []
            for row in table_data.values():
                if (not row.get("core_memory") and 
                    not row.get("ephemeral") and 
                    not row.get("deprecated", False)):
                    if "timestamp <" in sql_lower and vars and "cutoff" in vars:
                        cutoff = vars["cutoff"]
                        row_ts = row.get("timestamp")
                        if row_ts and row_ts < cutoff:
                            filtered.append(row)
            return filtered
        
        # Handle SELECT for _abstract_episodic_clusters
        if "from memory" in sql_lower and "memory_type = 'episodic'" in sql_lower:
            table_data = self._get_table("memory")
            filtered = []
            for row in table_data.values():
                if (row.get("memory_type") == "episodic" and 
                    not row.get("deprecated", False) and
                    not row.get("core_memory") and
                    row.get("embedding") is not None):
                    filtered.append(row)
            return filtered
        
        # Handle SELECT for emotional_reprocessing
        if "from memory" in sql_lower and "learned_from = false" in sql_lower:
            return []
        
        # Handle RELATE queries
        if sql_lower.startswith("relate"):
            return []
        
        # Handle MERGE queries
        if sql_lower.startswith("merge"):
            return []
        
        # Handle UPDATE queries
        if sql_lower.startswith("update"):
            return []
        
        raise NotImplementedError(f"Query not implemented in FakeDatabaseClient: {sql}")
    
    async def select(self, thing: str) -> list[dict[str, Any]]:
        """Select all records from a table."""
        table_data = self._get_table(thing)
        return list(table_data.values())
    
    async def create(self, thing: str, data: dict[str, Any]) -> Any:
        """Create a record."""
        table_data = self._get_table(thing)
        # Extract ID from the thing if it's a specific record ID like "memory:abc123"
        if ":" in thing:
            record_id = thing
        else:
            record_id = data.get("id", f"{thing}:{len(table_data)}")
        table_data[record_id] = data
        return [{"id": record_id, **data}]
    
    async def update(self, thing: str, data: dict[str, Any]) -> Any:
        """Update a record."""
        if ":" in thing:
            table_name, record_id = thing.split(":", 1)
        else:
            raise ValueError(f"Update requires specific record ID: {thing}")
        
        table_data = self._get_table(table_name)
        if record_id in table_data:
            table_data[record_id].update(data)
            return [{"id": thing, **table_data[record_id]}]
        return []
    
    async def merge(self, thing: str, data: dict[str, Any]) -> Any:
        """Merge data into a record."""
        return await self.update(thing, data)
    
    async def delete(self, thing: str) -> Any:
        """Delete a record."""
        if ":" in thing:
            table_name, record_id = thing.split(":", 1)
        else:
            raise ValueError(f"Delete requires specific record ID: {thing}")
        
        table_data = self._get_table(table_name)
        if record_id in table_data:
            del table_data[record_id]
            return [{"id": thing, "deleted": True}]
        return []


# Global fake database instance for tests
_fake_db: FakeDatabaseClient | None = None


def get_fake_db() -> FakeDatabaseClient:
    """Get or create the fake database instance."""
    global _fake_db
    if _fake_db is None:
        _fake_db = FakeDatabaseClient()
    return _fake_db


@pytest.fixture
def fake_db() -> FakeDatabaseClient:
    """Provide a fresh fake database for each test."""
    global _fake_db
    _fake_db = FakeDatabaseClient()
    return _fake_db


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global singletons between tests."""
    # Reset the fake DB
    global _fake_db
    _fake_db = None
    
    # Reset other singletons if needed
    import aura.db.client
    aura.db.client._db_client = None
    
    import aura.engines.memory.manager
    aura.engines.memory.manager._memory_manager = None
    
    import aura.engines.emotion.engine
    aura.engines.emotion.engine._emotion_engine = None
    
    yield
    
    # Cleanup after test
    _fake_db = None
    aura.db.client._db_client = None
    aura.engines.memory.manager._memory_manager = None
    aura.engines.emotion.engine._emotion_engine = None


# ===========================================================================
# W2-02: turn_orchestrator fixture
# ===========================================================================

# Fixed timestamp used by the emotion state the fixture returns, so tests are
# deterministic and do not depend on the wall clock.
_TURN_FIXED_DATETIME = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def turn_orchestrator(monkeypatch):
    """Build an :class:`Orchestrator` without running ``__init__``.

    ``Orchestrator.__init__`` calls ``get_db_client()``, builds a
    ``ToolExecutor`` and starts the idle state-machine loop, none of which is
    safe or useful in a unit test. This fixture constructs the instance with
    ``Orchestrator.__new__(Orchestrator)`` and wires every attribute
    ``process_query`` touches onto fakes, so the real ``process_query`` can run
    end-to-end against mocks with no database, LLM or network.

    The fixture follows card W2-02 exactly, with one documented deviation:
    ``IdentityContext`` has no ``core_identity`` / ``tone_and_style`` fields
    (see ``src/aura/models/identity.py`` — the required fields are ``narrative``
    and ``core_values``), so the card's prescribed
    ``IdentityContext(core_identity="Aura", tone_and_style="Helpful")`` is not
    constructible. The fixture returns a minimal valid
    ``IdentityContext(narrative="Aura", core_values={})`` instead. This mirrors
    a latent bug in ``stream_query`` (lines ~2189 and ~2216 of
    ``coordinator.py``), whose fallback constructs the same invalid object and
    would crash if ever reached. The difference is reported in the W2-02 log
    entry; ``src/`` is not changed.
    """
    from aura.orchestrator.coordinator import Orchestrator
    from aura.models.emotion import EmotionState, EmotionVector
    from aura.models.learning import LearningContext
    from aura.models.identity import IdentityContext
    from aura.models.goal import GoalContext

    orch = Orchestrator.__new__(Orchestrator)

    # --- bare instance attributes ------------------------------------------
    orch.logger = logging.getLogger("aura.orchestrator.test")
    orch.critique_buffer = {}
    orch._last_system_prompt = {}
    orch._state_lock = asyncio.Lock()

    # --- emotion engine ----------------------------------------------------
    emotion_state = EmotionState(
        timestamp=_TURN_FIXED_DATETIME,
        vector=EmotionVector(),
        dominant=("neutral", 0.0),
        description="Neutral",
    )
    emotion_engine = MagicMock()
    emotion_engine.get_current_state = AsyncMock(return_value=emotion_state)
    # _compute_resonance_score reads self.emotion_engine.config.baseline
    emotion_engine.config = MagicMock()
    emotion_engine.config.baseline = EmotionVector()
    orch.emotion_engine = emotion_engine

    # --- learning engine --------------------------------------------------
    # Card: "AsyncMock. get_learning_context returns LearningContext().
    # log_experience, ingest_mcp_server, ingest_local_tool_module and
    # get_skill are AsyncMocks. db.select and db.query are AsyncMocks that
    # return []."
    learning_engine = AsyncMock()
    learning_engine.get_learning_context = AsyncMock(return_value=LearningContext())
    learning_engine.log_experience = AsyncMock()
    learning_engine.ingest_mcp_server = AsyncMock()
    learning_engine.ingest_local_tool_module = AsyncMock()
    learning_engine.get_skill = AsyncMock()
    learning_engine.db = MagicMock()
    learning_engine.db.select = AsyncMock(return_value=[])
    learning_engine.db.query = AsyncMock(return_value=[])
    orch.learning_engine = learning_engine

    # --- identity engine ---------------------------------------------------
    identity_engine = MagicMock()
    # Card asks for IdentityContext(core_identity="Aura", tone_and_style=
    # "Helpful"), but IdentityContext has no such fields (see module docstring
    # note above). Use a minimal valid IdentityContext instead.
    identity_engine.get_identity_context = AsyncMock(
        return_value=IdentityContext(narrative="Aura", core_values={})
    )
    orch.identity_engine = identity_engine

    # --- goal engine -------------------------------------------------------
    goal_engine = MagicMock()
    goal_engine.get_goal_context = AsyncMock(return_value=GoalContext())
    goal_engine.check_goals_needing_autonomous_pursuit = AsyncMock(return_value=[])
    orch.goal_engine = goal_engine

    # --- llm layers -------------------------------------------------------
    llm_layers = MagicMock()
    llm_layers.l1_classify_intent = AsyncMock()
    llm_layers.l3_synthesis = AsyncMock()
    llm_layers.l3_tool_call_mode = AsyncMock()
    llm_layers.build_l3_system_prompt = MagicMock(return_value="PROMPT")

    # stream_l3_synthesis: a plain function that records (context, kwargs)
    # and returns an async generator over the next scripted list of chunks.
    # Used by stream_query (W2-03); process_query never calls it.
    stream_calls: list[tuple[Any, dict[str, Any]]] = []
    stream_chunks_queue: list[list[str]] = []

    def _stream_l3_synthesis(context, **kwargs):
        stream_calls.append((context, kwargs))

        async def _gen():
            chunks = stream_chunks_queue.pop(0) if stream_chunks_queue else []
            for c in chunks:
                yield c

        return _gen()

    llm_layers.stream_l3_synthesis = _stream_l3_synthesis
    # Expose the queues/records for tests that script or inspect streaming.
    llm_layers._stream_calls = stream_calls
    llm_layers._stream_chunks_queue = stream_chunks_queue
    orch.llm_layers = llm_layers

    # --- tool executor -----------------------------------------------------
    tool_executor = MagicMock()
    tool_executor.extract_tool_calls = MagicMock()
    tool_executor.execute_and_feedback = AsyncMock()
    orch.tool_executor = tool_executor

    # --- methods replaced on the instance ----------------------------------
    orch._sleep_gate = AsyncMock(return_value=(True, None))
    orch._record_user_interaction = AsyncMock()
    orch._publish_trace = MagicMock()
    orch._post_response_chain = AsyncMock()

    # --- module-level singletons imported inside process_query -------------
    fake_memory_manager = MagicMock()
    fake_memory_manager.retrieve_memories = AsyncMock(return_value=[])
    fake_memory_manager.get_cold_start_context = AsyncMock(
        return_value=SimpleNamespace(
            xml_block=None, core_memories=[], recent_memories=[]
        )
    )
    monkeypatch.setattr(
        "aura.engines.memory.manager.get_memory_manager",
        lambda: fake_memory_manager,
    )

    fake_latent_engine = MagicMock()
    fake_latent_engine.get_intuition_context = MagicMock(return_value=None)
    monkeypatch.setattr(
        "aura.engines.latent.engine.get_latent_engine",
        lambda: fake_latent_engine,
    )

    # Stash the fakes on the instance so tests can configure return values
    # (e.g. learning_engine.db.select for the forced-tool path) without
    # reaching back into the monkeypatch closures.
    orch._fake_memory_manager = fake_memory_manager
    orch._fake_latent_engine = fake_latent_engine

    return orch