"""Behaviour workspace: proposal registry and attention (B2-02, PRD 4.1)."""

import logging
from datetime import datetime
from typing import Any

from aura.clock import get_clock
from aura.config import settings
from aura.models.messages import EngineMessage, MessageType
from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
from aura.orchestrator.message_bus import MessageBus

logger = logging.getLogger(__name__)


class Workspace:
    """
    In-memory registry for proposals.
    
    Proposals can be posted directly or via the message bus (PROPOSAL type).
    The workspace subscribes to the bus once and converts messages.
    Bounded by workspace_max_proposals (default 50), evicting oldest expired first.
    """

    def __init__(self, bus: MessageBus | None = None) -> None:
        self._bus = bus
        self._proposals: dict[str, Proposal] = {}
        self._subscribed = False
        if bus is not None:
            self._ensure_subscribed()

    def _ensure_subscribed(self) -> None:
        """Subscribe to the message bus for PROPOSAL messages."""
        if not settings.workspace_enabled:
            return
        if self._bus is not None and not self._subscribed:
            self._bus.subscribe("workspace", self._on_bus_message)
            self._subscribed = True
            logger.info("Workspace subscribed to message bus")

    async def _on_bus_message(self, message: EngineMessage) -> None:
        """Handle incoming PROPOSAL messages from the bus."""
        if message.message_type != MessageType.PROPOSAL:
            return

        # Convert bus message data to Proposal
        data = message.data or {}
        try:
            extra: dict[str, Any] = {}
            if data.get("id"):
                extra["id"] = str(data["id"])
            if data.get("created_at"):
                extra["created_at"] = data["created_at"]
            proposal = Proposal(
                **extra,
                source=data.get("source", message.source),
                kind=ProposalKind(data["kind"]),
                summary=data["summary"],
                refs=data.get("refs", []),
                urgency=float(data.get("urgency", 0.5)),
                value=float(data.get("value", 0.5)),
                cost=Cost(
                    tokens=int(data.get("cost", {}).get("tokens", 0)),
                    seconds=float(data.get("cost", {}).get("seconds", 0.0)),
                    risk=RiskLevel(data.get("cost", {}).get("risk", "read")),
                ),
                expires_at=data.get("expires_at"),
            )
            # Post directly (bypasses bus to avoid loops)
            self._post_internal(proposal)
        except Exception as e:
            logger.warning(f"Failed to convert bus message to proposal: {e}")

    def _post_internal(self, proposal: Proposal) -> str | None:
        """Internal post without bus publishing."""
        # Check for duplicate: same source, kind, and sorted refs
        dup_key = proposal.duplicate_key()
        for existing_id, existing in list(self._proposals.items()):
            if existing.duplicate_key() == dup_key:
                # Replace older one
                logger.debug(f"Replacing duplicate proposal {existing_id} with {proposal.id}")
                del self._proposals[existing_id]
                break

        # Enforce bound: remove oldest expired first, then oldest overall
        max_proposals = settings.workspace_max_proposals
        if len(self._proposals) >= max_proposals:
            self._evict_to_fit(max_proposals)

        self._proposals[proposal.id] = proposal
        logger.debug(f"Posted proposal {proposal.id} (kind={proposal.kind.value}, source={proposal.source})")
        return proposal.id

    def _evict_to_fit(self, max_proposals: int) -> None:
        """Evict proposals to fit within max_proposals. Oldest expired first, then oldest overall."""
        now = get_clock().now()

        # First pass: collect expired
        expired = [(pid, p) for pid, p in self._proposals.items() if p.is_expired(now)]
        expired.sort(key=lambda x: x[1].created_at)  # oldest first

        # Remove expired until we have space or run out
        for pid, _ in expired:
            if len(self._proposals) < max_proposals:
                break
            del self._proposals[pid]
            logger.debug(f"Evicted expired proposal {pid}")

        # Second pass: if still over limit, remove oldest overall
        if len(self._proposals) >= max_proposals:
            sorted_by_age = sorted(self._proposals.items(), key=lambda x: x[1].created_at)
            to_remove = len(self._proposals) - max_proposals + 1
            for pid, _ in sorted_by_age[:to_remove]:
                del self._proposals[pid]
                logger.debug(f"Evicted oldest proposal {pid}")

    def post(self, proposal: Proposal) -> str | None:
        """
        Post a proposal to the workspace.
        
        Validates the proposal, stores it in the bounded in-memory dict,
        and returns the proposal id. Returns None if workspace is disabled.
        """
        if not settings.workspace_enabled:
            return None

        self._ensure_subscribed()
        return self._post_internal(proposal)

    def live(self, now: datetime | None = None) -> list[str]:
        """
        Drop expired proposals.
        
        Returns list of evicted proposal ids.
        """
        if not settings.workspace_enabled:
            return []

        now = now or get_clock().now()
        evicted = []

        for pid, proposal in list(self._proposals.items()):
            if proposal.is_expired(now):
                del self._proposals[pid]
                evicted.append(pid)
                logger.debug(f"Dropped expired proposal {pid}")

        return evicted

    def get(self, proposal_id: str) -> Proposal | None:
        """Get a proposal by id."""
        return self._proposals.get(proposal_id)

    def all(self) -> list[Proposal]:
        """Get all current proposals."""
        return list(self._proposals.values())

    def clear(self) -> None:
        """Clear all proposals (for testing)."""
        self._proposals.clear()


# Global workspace instance
_workspace: Workspace | None = None


def get_workspace(bus: MessageBus | None = None) -> Workspace:
    """Get or create the global workspace instance."""
    global _workspace
    if _workspace is None:
        _workspace = Workspace(bus)
    elif bus is not None and _workspace._bus is None:
        _workspace._bus = bus
    return _workspace


def set_workspace(workspace: Workspace | None) -> None:
    """Replace the global workspace (for testing)."""
    global _workspace
    _workspace = workspace