"""Tests for the DecisionService and decision routes."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from aura.executor.decisions import DecisionService, get_decision_service, set_decision_service
from aura.api.routes.decisions import router as decisions_router
from fastapi.testclient import TestClient
from fastapi import FastAPI


class FakeOpenCodeClient:
    """Fake OpenCode client for testing."""

    def __init__(self):
        self.answered: list[tuple[str, str, bool]] = []

    async def answer_permission(self, session_id: str, request_id: str, allow: bool) -> None:
        self.answered.append((session_id, request_id, allow))


class FakeDB:
    """In-memory fake database for testing DecisionService."""

    def __init__(self):
        self._decisions: dict[str, dict] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"decision:{self._counter}"

    async def create(self, table: str, data: dict) -> list[dict]:
        if table != "decision":
            raise NotImplementedError(f"Table {table} not supported")
        decision_id = self._next_id()
        record = {"id": decision_id, **data}
        self._decisions[decision_id] = record
        return [record]

    async def select(self, thing: str) -> list[dict]:
        if thing in self._decisions:
            return [self._decisions[thing]]
        return []

    async def query(self, sql: str, vars: dict | None = None) -> list[dict]:
        sql_lower = sql.lower()
        if "from decision" in sql_lower and "status = 'pending'" in sql_lower:
            pending = [d for d in self._decisions.values() if d.get("status") == "pending"]
            # Order by created_at DESC
            pending.sort(key=lambda d: d.get("created_at", datetime.min), reverse=True)
            return pending
        if sql_lower == "select * from decision":
            return list(self._decisions.values())
        if sql_lower.startswith("update decision"):
            # Handle UPDATE ... SET status = 'expired' WHERE session_id = $sid AND status = 'pending'
            if vars and "sid" in vars:
                count = 0
                for d in self._decisions.values():
                    if d.get("session_id") == vars["sid"] and d.get("status") == "pending":
                        d["status"] = "expired"
                        d["decided_at"] = vars.get("now")
                        count += 1
                return [{"result": [{} for _ in range(count)]}]
            # Handle other UPDATE queries
            if vars and "mid" in vars:
                mid = vars["mid"]
                if mid in self._decisions:
                    return [{"result": [self._decisions[mid]]}]
        return []

    async def merge(self, thing: str, data: dict) -> list[dict]:
        # thing is like "decision:1" - use it directly as the key
        if thing in self._decisions:
            self._decisions[thing].update(data)
            return [self._decisions[thing]]
        return []


@pytest.fixture
def fake_db():
    """Provide a fresh fake database for each test."""
    return FakeDB()


@pytest.fixture
def fake_client():
    """Provide a fresh fake OpenCode client."""
    return FakeOpenCodeClient()


@pytest.fixture
def decision_service(fake_db, fake_client):
    """Provide a DecisionService with fake dependencies."""
    service = DecisionService(db=fake_db, client=fake_client)
    # Also set as global for route tests
    set_decision_service(service)
    yield service
    set_decision_service(None)


class TestDecisionService:
    """Tests for DecisionService."""

    @pytest.mark.asyncio
    async def test_create_decision(self, decision_service):
        """Test creating a pending decision."""
        decision = await decision_service.create(
            kind="permission",
            session_id="session:abc123",
            request_id="req:123",
            action="bash",
            resources=["ls -la"],
            risk="execute",
            workspace="/home/user/project",
            message="Run ls command",
            task_id="task:xyz",
        )

        assert decision["kind"] == "permission"
        assert decision["session_id"] == "session:abc123"
        assert decision["request_id"] == "req:123"
        assert decision["action"] == "bash"
        assert decision["resources"] == ["ls -la"]
        assert decision["risk"] == "execute"
        assert decision["workspace"] == "/home/user/project"
        assert decision["message"] == "Run ls command"
        assert decision["task_id"] == "task:xyz"
        assert decision["status"] == "pending"
        assert decision["created_at"] is not None
        assert decision["decided_at"] is None
        assert decision["decided_by"] is None
        assert "id" in decision
        assert decision["id"].startswith("decision:")

    @pytest.mark.asyncio
    async def test_pending_list_empty(self, decision_service):
        """Test listing pending decisions when empty."""
        pending = await decision_service.pending()
        assert pending == []

    @pytest.mark.asyncio
    async def test_pending_list_newest_first(self, decision_service):
        """Test that pending decisions are returned newest first."""
        # Create three decisions with small delays to ensure different timestamps
        d1 = await decision_service.create("permission", "s1", "r1", "read", ["a"], "read")
        d2 = await decision_service.create("permission", "s2", "r2", "write", ["b"], "write")
        d3 = await decision_service.create("permission", "s3", "r3", "bash", ["c"], "execute")

        pending = await decision_service.pending()
        assert len(pending) == 3
        # Newest first
        assert pending[0]["id"] == d3["id"]
        assert pending[1]["id"] == d2["id"]
        assert pending[2]["id"] == d1["id"]

    @pytest.mark.asyncio
    async def test_answer_allow(self, decision_service, fake_client):
        """Test answering a decision with allow=True."""
        decision = await decision_service.create(
            "permission", "session:abc", "req:1", "bash", ["ls"], "execute"
        )
        decision_id = decision["id"]

        updated = await decision_service.answer(decision_id, True, "owner")

        assert updated["status"] == "allowed"
        assert updated["decided_by"] == "owner"
        assert updated["decided_at"] is not None
        # Check client was called with correct args
        assert len(fake_client.answered) == 1
        assert fake_client.answered[0] == ("session:abc", "req:1", True)

    @pytest.mark.asyncio
    async def test_answer_deny(self, decision_service, fake_client):
        """Test answering a decision with allow=False."""
        decision = await decision_service.create(
            "permission", "session:abc", "req:1", "write", ["file.txt"], "write"
        )
        decision_id = decision["id"]

        updated = await decision_service.answer(decision_id, False, "owner")

        assert updated["status"] == "denied"
        assert updated["decided_by"] == "owner"
        assert updated["decided_at"] is not None
        assert len(fake_client.answered) == 1
        assert fake_client.answered[0] == ("session:abc", "req:1", False)

    @pytest.mark.asyncio
    async def test_answer_calls_client_after_record_update(self, decision_service, fake_client):
        """Test that client is called only after the record is updated to allowed/denied."""
        decision = await decision_service.create(
            "permission", "session:abc", "req:1", "bash", ["ls"], "execute"
        )
        decision_id = decision["id"]

        # Track call order
        call_order = []

        original_answer = fake_client.answer_permission

        async def tracking_answer(sid, rid, allow):
            call_order.append("client_called")
            await original_answer(sid, rid, allow)

        fake_client.answer_permission = tracking_answer

        # Patch merge to track when record is updated
        original_merge = decision_service._db.merge

        async def tracking_merge(thing, data):
            call_order.append("record_updated")
            return await original_merge(thing, data)

        decision_service._db.merge = tracking_merge

        await decision_service.answer(decision_id, True, "owner")

        # Record should be updated before client is called
        assert call_order.index("record_updated") < call_order.index("client_called")

    @pytest.mark.asyncio
    async def test_answer_non_pending_raises(self, decision_service):
        """Test that answering a non-pending decision raises."""
        decision = await decision_service.create(
            "permission", "session:abc", "req:1", "bash", ["ls"], "execute"
        )
        decision_id = decision["id"]

        # First answer
        await decision_service.answer(decision_id, True, "owner")

        # Second answer should raise
        with pytest.raises(ValueError, match="not pending"):
            await decision_service.answer(decision_id, False, "owner")

    @pytest.mark.asyncio
    async def test_answer_nonexistent_raises(self, decision_service):
        """Test that answering a non-existent decision raises."""
        with pytest.raises(ValueError, match="not found"):
            await decision_service.answer("decision:999", True, "owner")

    @pytest.mark.asyncio
    async def test_answer_without_client_raises(self, fake_db):
        """Test that answering without a client raises RuntimeError."""
        service = DecisionService(db=fake_db, client=None)
        decision = await service.create("permission", "session:abc", "req:1", "bash", ["ls"], "execute")
        
        with pytest.raises(RuntimeError, match="No OpenCode client configured"):
            await service.answer(decision["id"], True, "owner")

    @pytest.mark.asyncio
    async def test_expire_for_session(self, decision_service):
        """Test expiring pending decisions for a session."""
        # Create decisions for two different sessions
        await decision_service.create("permission", "session:1", "req:1", "bash", ["a"], "execute")
        await decision_service.create("permission", "session:1", "req:2", "write", ["b"], "write")
        await decision_service.create("permission", "session:2", "req:3", "read", ["c"], "read")

        # Expire session:1
        count = await decision_service.expire_for_session("session:1")
        assert count == 2

        # Check statuses
        pending = await decision_service.pending()
        assert len(pending) == 1
        assert pending[0]["session_id"] == "session:2"
        assert pending[0]["status"] == "pending"

        # The expired ones should no longer be pending
        all_decisions = await decision_service._db.query("SELECT * FROM decision")
        expired = [d for d in all_decisions if d.get("status") == "expired"]
        assert len(expired) == 2

    @pytest.mark.asyncio
    async def test_expire_for_session_no_pending(self, decision_service):
        """Test expire_for_session when no pending decisions exist."""
        await decision_service.create("permission", "session:1", "req:1", "bash", ["a"], "execute")
        await decision_service.answer("decision:1", True, "owner")

        count = await decision_service.expire_for_session("session:1")
        assert count == 0


class TestDecisionRoutes:
    """Tests for the decision API routes."""

    @pytest.fixture
    def app(self, decision_service):
        """Create a FastAPI app with the decisions router."""
        app = FastAPI()
        app.include_router(decisions_router)
        return app

    @pytest.fixture
    def client(self, app):
        """Create a test client."""
        return TestClient(app)

    def test_list_pending_empty(self, client):
        """Test GET /decisions returns empty list initially."""
        response = client.get("/decisions")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["decisions"] == []
        assert data["count"] == 0

    def test_list_pending_with_decisions(self, client, decision_service):
        """Test GET /decisions returns pending decisions."""
        import asyncio
        asyncio.run(decision_service.create("permission", "s1", "r1", "bash", ["ls"], "execute"))
        asyncio.run(decision_service.create("permission", "s2", "r2", "write", ["f"], "write"))

        response = client.get("/decisions")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["count"] == 2
        assert len(data["decisions"]) == 2

    def test_answer_allow(self, client, decision_service, fake_client):
        """Test POST /decisions/{id} with allow=true."""
        import asyncio
        decision = asyncio.run(decision_service.create("permission", "s1", "r1", "bash", ["ls"], "execute"))
        decision_id = decision["id"]

        response = client.post(f"/decisions/{decision_id}", json={"allow": True})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["decision"]["status"] == "allowed"
        assert data["decision"]["decided_by"] == "owner"
        assert "allowed" in data["message"].lower()

        # Check client was called
        assert len(fake_client.answered) == 1
        assert fake_client.answered[0] == ("s1", "r1", True)

    def test_answer_deny(self, client, decision_service, fake_client):
        """Test POST /decisions/{id} with allow=false."""
        import asyncio
        decision = asyncio.run(decision_service.create("permission", "s1", "r1", "write", ["f.txt"], "write"))
        decision_id = decision["id"]

        response = client.post(f"/decisions/{decision_id}", json={"allow": False})
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["decision"]["status"] == "denied"
        assert "denied" in data["message"].lower()

        assert len(fake_client.answered) == 1
        assert fake_client.answered[0] == ("s1", "r1", False)

    def test_answer_not_found(self, client):
        """Test POST /decisions/{id} returns 400 for non-existent decision."""
        response = client.post("/decisions/decision:999", json={"allow": True})
        assert response.status_code == 400

    def test_answer_not_pending(self, client, decision_service):
        """Test POST /decisions/{id} returns 400 for already answered decision."""
        import asyncio
        decision = asyncio.run(decision_service.create("permission", "s1", "r1", "bash", ["ls"], "execute"))
        decision_id = decision["id"]
        asyncio.run(decision_service.answer(decision_id, True, "owner"))

        response = client.post(f"/decisions/{decision_id}", json={"allow": False})
        assert response.status_code == 400

    def test_answer_without_client(self, client):
        """Test POST /decisions/{id} returns 503 when no client configured."""
        import asyncio
        from aura.executor.decisions import set_decision_service, DecisionService

        # Create service without client using local FakeDB
        fake_db = FakeDB()
        service = DecisionService(db=fake_db, client=None)
        set_decision_service(service)

        try:
            decision = asyncio.run(service.create("permission", "s1", "r1", "bash", ["ls"], "execute"))
            decision_id = decision["id"]

            response = client.post(f"/decisions/{decision_id}", json={"allow": True})
            assert response.status_code == 503
        finally:
            set_decision_service(None)