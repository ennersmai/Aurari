"""Test configuration and fixtures for Aura test suite."""

import pytest
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock


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