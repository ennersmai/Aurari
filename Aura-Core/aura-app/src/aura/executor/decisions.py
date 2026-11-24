"""Decision Service for managing owner approval decisions.

Handles the lifecycle of permission decisions: create, list pending,
answer (allow/deny), and expire decisions for closed sessions.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from aura.clock import get_clock
from aura.db.client import get_db_client

logger = logging.getLogger(__name__)

# Post-answer hooks for ``needs_decision`` items, keyed by decision ``action``.
# A hook is ``async fn(service, decision, allow, decided_by, trusted)``. Later
# cards register theirs with ``register_answer_hook`` instead of editing answer().
AnswerHook = Callable[["DecisionService", dict, bool, str, bool], Awaitable[None]]
_ANSWER_HOOKS: dict[str, list[AnswerHook]] = {}


def register_answer_hook(action: str, fn: AnswerHook) -> None:
    """Register ``fn`` to run after a ``needs_decision`` item with ``action`` is answered."""
    hooks = _ANSWER_HOOKS.setdefault(action, [])
    if fn not in hooks:
        hooks.append(fn)


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
        if isinstance(result, dict):  # the embedded engine returns the record itself
            return result
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

    async def answer(
        self, decision_id: str, allow: bool, decided_by: str, trusted: bool = False
    ) -> dict[str, Any]:
        """Answer a pending decision and notify OpenCode.

        Args:
            decision_id: The decision record ID (e.g., "decision:abc123")
            allow: True to allow, False to deny
            decided_by: Identifier of who made the decision (e.g., "owner")
            trusted: Passed to post-answer hooks only (G5-02 "approve as trusted")

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

        # B3-05: an allowed pursuit decision is the only way a grant is created.
        # answer() is reached from the owner's decision routes, never from a tool.
        if (decision.get("kind") == "needs_decision" and decision.get("action") == "pursuit"
                and allow and decided_by == "owner"):
            await self._grant_pursuit(decision, now)

        # Then call the OpenCode client to answer the permission
        if decision.get("kind") == "needs_decision":
            # A blocker item (G4-02) has no OpenCode permission request to answer.
            for hook in list(_ANSWER_HOOKS.get(str(decision.get("action")), [])):
                try:
                    await hook(self, decision, allow, decided_by, trusted)
                except Exception:
                    logger.exception("answer hook failed for %s", decision_id)
            updated = await self._db.select(decision_id)
            return updated[0] if updated else {**decision, **update_data}

        if self._client is None:
            raise RuntimeError("No OpenCode client configured for answering permissions")
        
        await self._client.answer_permission(session_id, request_id, allow)

        # Return the updated decision
        updated = await self._db.select(decision_id)
        return updated[0] if updated else {**decision, **update_data}

    async def _grant_pursuit(self, decision: dict[str, Any], now: datetime) -> None:
        """Create the grant the decision describes. Its scope is the stored risk;
        anything malformed creates nothing (fail closed)."""
        from datetime import timedelta

        from aura.autonomy import grants
        from aura.config import settings

        if not settings.goals_v2_enabled:
            return
        resources = list(decision.get("resources") or [])
        scope = decision.get("risk")
        if not resources or scope not in grants.SCOPES or f"scope:{scope}" not in resources:
            logger.warning("pursuit decision malformed, no grant: %s", decision.get("id"))
            return
        budget: dict[str, int] = {}
        for item in resources[1:]:
            key, _, value = str(item).partition(":")
            if key in ("minutes", "tokens") and value.isdigit():
                budget[key] = int(value)
        await grants.create(
            resources[0], scope, now + timedelta(hours=settings.pursuit_grant_hours),
            granted_by="owner", budget=budget, db=self._db,
        )

    async def get(self, decision_id: Any) -> dict[str, Any] | None:
        """One decision record, or None (P2-10: a code node polls its merge decision)."""
        rows = await self._db.select(decision_id)
        if not rows:
            return None
        return rows[0] if isinstance(rows, list) else rows

    async def find_pending(self, action: str, request_id: str | None = None) -> list[dict[str, Any]]:
        """Pending ``needs_decision`` items for ``action`` (optionally one request id)."""
        sql = ("SELECT * FROM decision WHERE kind = 'needs_decision' AND action = $action "
               "AND status = 'pending'")
        params: dict[str, Any] = {"action": action}
        if request_id is not None:
            sql += " AND request_id = $rid"
            params["rid"] = request_id
        return await self._db.query(sql + " ORDER BY created_at ASC", params)

    async def update_pending(self, decision_id: Any, patch: dict[str, Any]) -> None:
        """Change message, request_id or resources of a still-pending decision."""
        await self._db.merge(decision_id, patch)

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