"""Decision Service for managing owner approval decisions.

Handles the lifecycle of permission decisions: create, list pending,
answer (allow/deny), and expire decisions for closed sessions.
"""

from datetime import datetime, timezone
from typing import Any

from aura.clock import get_clock
from aura.db.client import get_db_client


class DecisionService:
    """Service for managing owner approval decisions."""

    def __init__(self, db=None, client=None):
        """Initialize the decision service.

        Args:
            db: Database client (defaults to global get_db_client())
            client: OpenCode client for answering permissions (optional)
        """
        self._db = db or get_db_client()
        self._client = client

    async def create(
        self,
        kind: str,
        session_id: str,
        request_id: str,
        action: str,
        resources: list[str],
        risk: str,
        workspace: str | None = None,
        message: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a pending decision record.

        Args:
            kind: Type of decision (e.g., "permission")
            session_id: OpenCode session ID
            request_id: Permission request ID
            action: Action being requested (e.g., "bash", "write")
            resources: List of resources the action applies to
            risk: Risk level (e.g., "read", "write", "execute", "send")
            workspace: Optional workspace path
            message: Optional message from the permission request
            task_id: Optional task ID this decision belongs to

        Returns:
            The created decision record
        """
        now = get_clock().now()
        
        data = {
            "kind": kind,
            "task_id": task_id,
            "session_id": session_id,
            "request_id": request_id,
            "action": action,
            "resources": resources,
            "risk": risk,
            "workspace": workspace,
            "message": message,
            "status": "pending",
            "created_at": now,
            "decided_at": None,
            "decided_by": None,
        }

        result = await self._db.create("decision", data)
        return result[0] if result else data

    async def pending(self) -> list[dict[str, Any]]:
        """List all pending decisions, newest first.

        Returns:
            List of pending decision records, ordered by created_at DESC
        """
        result = await self._db.query(
            "SELECT * FROM decision WHERE status = 'pending' ORDER BY created_at DESC"
        )
        return result

    async def answer(self, decision_id: str, allow: bool, decided_by: str) -> dict[str, Any]:
        """Answer a pending decision and notify OpenCode.

        Args:
            decision_id: The decision record ID (e.g., "decision:abc123")
            allow: True to allow, False to deny
            decided_by: Identifier of who made the decision (e.g., "owner")

        Returns:
            The updated decision record

        Raises:
            ValueError: If the decision is not pending or doesn't exist
            RuntimeError: If no OpenCode client is configured
        """
        # First, get the decision to verify it's pending and get session/request IDs
        decision = await self._db.select(decision_id)
        if not decision:
            raise ValueError(f"Decision not found: {decision_id}")
        
        decision = decision[0]
        if decision.get("status") != "pending":
            raise ValueError(f"Decision {decision_id} is not pending (status: {decision.get('status')})")

        session_id = decision["session_id"]
        request_id = decision["request_id"]

        now = get_clock().now()
        new_status = "allowed" if allow else "denied"

        # Update the decision record first
        update_data = {
            "status": new_status,
            "decided_at": now,
            "decided_by": decided_by,
        }
        
        await self._db.merge(decision_id, update_data)

        # Then call the OpenCode client to answer the permission
        if decision.get("kind") == "needs_decision":
            # A blocker item (G4-02) has no OpenCode permission request to answer.
            updated = await self._db.select(decision_id)
            return updated[0] if updated else {**decision, **update_data}

        if self._client is None:
            raise RuntimeError("No OpenCode client configured for answering permissions")
        
        await self._client.answer_permission(session_id, request_id, allow)

        # Return the updated decision
        updated = await self._db.select(decision_id)
        return updated[0] if updated else {**decision, **update_data}

    async def get(self, decision_id: Any) -> dict[str, Any] | None:
        """One decision record, or None (P2-10: a code node polls its merge decision)."""
        rows = await self._db.select(decision_id)
        if not rows:
            return None
        return rows[0] if isinstance(rows, list) else rows

    async def reopen(self, decision_id: Any, message: str) -> None:
        """Put an answered decision back to pending with a new message (P2-10).

        Used when an approved merge cannot run yet (main tree not clean).
        """
        await self._db.merge(decision_id, {
            "status": "pending",
            "decided_at": None,
            "decided_by": None,
            "message": message,
        })

    async def expire_for_session(self, session_id: str) -> int:
        """Mark all pending decisions for a session as expired.

        Called when an OpenCode session is closed.

        Args:
            session_id: The OpenCode session ID

        Returns:
            Number of decisions that were expired
        """
        result = await self._db.query(
            "UPDATE decision SET status = 'expired', decided_at = $now WHERE session_id = $sid AND status = 'pending'",
            {"sid": session_id, "now": get_clock().now()}
        )
        # The result format varies; count affected rows
        if result and isinstance(result, list) and len(result) > 0:
            if isinstance(result[0], dict) and "result" in result[0]:
                # Wrapped format
                inner = result[0]["result"]
                if isinstance(inner, list):
                    return len(inner)
        return 0


# Global service instance
_decision_service: DecisionService | None = None


def get_decision_service() -> DecisionService:
    """Get the global decision service instance."""
    global _decision_service
    if _decision_service is None:
        _decision_service = DecisionService()
    return _decision_service


def set_decision_service(service: DecisionService) -> None:
    """Set the global decision service instance (for testing)."""
    global _decision_service
    _decision_service = service