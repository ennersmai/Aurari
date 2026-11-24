"""Behaviour workspace: proposal registry and attention (B2-02, PRD 4.1)."""

import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aura.autonomy import budget as curiosity_budget, controls, drives, registry, trace
from aura.clock import get_clock
from aura.config import settings
from aura.models.messages import EngineMessage, MessageType
from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
from aura.orchestrator.message_bus import MessageBus

logger = logging.getLogger(__name__)

# Proposal kind -> gate kind for may_initiate. `respond` is never autonomous.
KIND_TO_GATE: dict[ProposalKind, str] = {
    ProposalKind.INVESTIGATE: "investigate",
    ProposalKind.PURSUE_GOAL: "pursue_goal",
    ProposalKind.PRACTICE: "practice",
    ProposalKind.SHARE: "share",
    ProposalKind.ASK_USER: "needs_decision",
    ProposalKind.CONSOLIDATE: "consolidate",
}

# Proposal kind -> drives that raise its score (PRD section 5); max is taken.
KIND_TO_DRIVES: dict[ProposalKind, tuple[str, ...]] = {
    ProposalKind.INVESTIGATE: ("curiosity",),
    ProposalKind.PURSUE_GOAL: ("competence",),
    ProposalKind.PRACTICE: ("competence",),
    ProposalKind.SHARE: ("connection",),
    ProposalKind.ASK_USER: ("connection", "coherence"),
    ProposalKind.CONSOLIDATE: ("rest",),
}

# Events that wake the workspace (B2-04). prediction_settled is reserved for B6.
EVENT_NAMES = (
    "user_message", "task_result", "question_resolved",
    "prediction_settled", "dream_completed", "agenda_due",
)
# Workspace event -> drive event (B2-01); events absent here move no drive.
EVENT_TO_DRIVE = {
    "user_message": "exchange_happened",
    "task_result": "task_done",
    "question_resolved": "question_resolved",
    "dream_completed": "dream_completed",
}

Handler = Callable[["Winner"], Awaitable[None]]


# -- B4-04: SHARE and ASK_USER handlers ------------------------------------------

async def _handle_agenda_proposal(winner: "Winner") -> None:
    """Winning SHARE / ASK_USER proposal: wake the B1-05 deliverer.

    The item already exists; the deliverer applies may_initiate, quiet hours
    and interruptibility, so nothing here sends anything itself.
    """
    from aura.autonomy.delivery import get_deliverer

    if any(str(r).startswith("agenda_item:") for r in winner.proposal.refs):
        await get_deliverer().notify()


class PauseToken:
    """Cooperative pause flag for long autonomous work (T12; B4-02 uses it).

    The work calls ``await token.wait_if_paused()`` between steps. The
    workspace pauses every live token when the owner speaks and resumes them
    when the turn ends. Wraps an ``asyncio.Event`` that is set while running.
    """

    def __init__(self) -> None:
        self._running = asyncio.Event()
        self._running.set()

    @property
    def paused(self) -> bool:
        return not self._running.is_set()

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    async def wait_if_paused(self) -> None:
        await self._running.wait()


_RISK_RANK = {RiskLevel.READ: 0.0, RiskLevel.WRITE: 1 / 3, RiskLevel.EXECUTE: 2 / 3, RiskLevel.SEND: 1.0}


@dataclass
class Budget:
    """What the caller can afford right now (rule 4; B4-03 fills it)."""

    tokens: int = 0
    seconds: float = 0.0
    allow_risk: bool = False


@dataclass
class Winner:
    """The proposal attention picked, with its score."""

    proposal: Proposal
    score: float
    cost_score: float
    drive_gain: float


def cost_score(cost: Cost) -> float:
    """Normalised weighted cost in 0..1 (weights and references from config)."""
    wt = settings.workspace_cost_weight_tokens
    ws = settings.workspace_cost_weight_seconds
    wr = settings.workspace_cost_weight_risk
    total = wt + ws + wr
    if total <= 0:
        return 0.0
    tokens = min(1.0, cost.tokens / settings.workspace_cost_ref_tokens)
    seconds = min(1.0, cost.seconds / settings.workspace_cost_ref_seconds)
    return (wt * tokens + ws * seconds + wr * _RISK_RANK[cost.risk]) / total


def drive_gain(kind: ProposalKind) -> float:
    """Max gain over the kind's drives; exactly 1.0 when drives are off."""
    if not settings.drives_enabled:
        return 1.0
    names = KIND_TO_DRIVES.get(kind, ())
    if not names:
        return 1.0
    model = drives.current()
    return max(drives.gain(n, model=model) for n in names)


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
        self._user_pending = False
        self._pending_since: datetime | None = None
        self._active_turns = 0
        self._handlers: dict[ProposalKind, Handler] = {}
        self._tokens: "weakref.WeakSet[PauseToken]" = weakref.WeakSet()
        self._bg: set[asyncio.Task] = set()
        self._cycle_lock = asyncio.Lock()
        self._fallback_task: asyncio.Task | None = None
        self.db: Any = None
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

    def note_user_message(self) -> None:
        """A user message is waiting; the next attend pre-empts autonomous work."""
        self._user_pending = True
        self._pending_since = get_clock().now()

    def clear_user_message(self) -> None:
        """The user message was handled."""
        self._user_pending = False
        self._pending_since = None

    # -- B2-04: events, cycle, pre-emption --------------------------------------

    def pause_token(self) -> PauseToken:
        """A token that pauses when the owner speaks (held weakly)."""
        token = PauseToken()
        self._tokens.add(token)
        return token

    def register_handler(self, kind: ProposalKind, handler: Handler) -> None:
        """Handler coroutine for winners of ``kind`` (B4 and B5 register them)."""
        self._handlers[kind] = handler

    def _spawn(self, coro: Any) -> None:
        """create_task with a strong reference and logged exceptions."""
        try:
            task = asyncio.get_running_loop().create_task(coro)
        except RuntimeError:
            coro.close()
            logger.warning("workspace event dropped: no running loop")
            return
        self._bg.add(task)

        def _done(t: asyncio.Task) -> None:
            self._bg.discard(t)
            if not t.cancelled() and t.exception() is not None:
                logger.warning("workspace task failed: %s", t.exception(), exc_info=t.exception())

        task.add_done_callback(_done)

    def on_event(self, name: str, payload: dict[str, Any] | None = None) -> None:
        """Synchronous, non-blocking event hook. Never awaits slow work.

        user_message pre-empts here, before the reply is generated; everything
        else (drives, the cycle) runs in a background task.
        """
        if not settings.workspace_enabled or name not in EVENT_NAMES:
            return
        if name == "user_message":
            self._active_turns += 1
            self.note_user_message()
            for token in list(self._tokens):
                token.pause()
            registry.interrupt_for_user_nowait()
        self._spawn(self._process_event(name, dict(payload or {})))

    def turn_finished(self) -> None:
        """The reply path ended: resume paused work once no turn is active."""
        if self._active_turns > 0:
            self._active_turns -= 1
        if self._active_turns == 0:
            self.clear_user_message()
            for token in list(self._tokens):
                token.resume()

    async def _process_event(self, name: str, payload: dict[str, Any]) -> None:
        drive_event = EVENT_TO_DRIVE.get(name)
        if drive_event is not None:
            try:
                await drives.on_event(drive_event, payload, db=self.db)
            except Exception:
                logger.warning("drive update failed for %s", name, exc_info=True)
        if name == "task_result" and self._bus is not None and "goal_engine" in self._bus._subscribers:
            # Bus messages only reach their targets; the goal engine checks evidence on this.
            await self._bus.publish(EngineMessage(
                source="workspace",
                message_type=MessageType.STATE_UPDATE,
                data={"kind": "task_result", **payload},
                targets=["goal_engine"],
            ))
        await self.run_cycle()

    async def run_cycle(self, budget: Budget | None = None) -> Winner | None:
        """One attention cycle: attend, dispatch the winner. No model call here."""
        if not settings.workspace_enabled:
            return None
        async with self._cycle_lock:
            now = get_clock().now()
            winner = await self.attend(now, budget or Budget(), db=self.db)
            if winner is None:
                return None
            p = winner.proposal
            self._proposals.pop(p.id, None)  # consumed either way
            handler = self._handlers.get(p.kind)
            if handler is None:
                await trace.record(p.source, f"cycle:no_handler:{p.kind.value}", "no handler",
                                   allowed=False, refs=p.refs, db=self.db)
                return winner
            try:
                await handler(winner)
            except Exception:
                logger.warning("handler for %s failed", p.kind.value, exc_info=True)
            return winner

    async def check_stuck(self) -> None:
        """Slow fallback: nothing may stay stuck. Posts nothing, calls no model."""
        if not settings.workspace_enabled:
            return
        now = get_clock().now()
        limit = settings.workspace_fallback_seconds
        if self._user_pending and self._pending_since is not None \
                and (now - self._pending_since).total_seconds() > limit:
            logger.warning("user message flag stuck for over %ss; clearing", limit)
            self._active_turns = 0
            self.turn_finished()
        self.live(now)
        if self._proposals:
            await self.run_cycle()

    async def start(self, db: Any = None) -> None:
        self.db = db
        if self._fallback_task is None:
            self._fallback_task = asyncio.create_task(self._fallback_loop())

    async def stop(self) -> None:
        if self._fallback_task is not None:
            self._fallback_task.cancel()
            await asyncio.gather(self._fallback_task, return_exceptions=True)
            self._fallback_task = None

    async def _fallback_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.workspace_fallback_seconds)
            try:
                await self.check_stuck()
            except Exception:
                logger.warning("workspace fallback failed", exc_info=True)

    async def attend(self, now: datetime, budget: Budget, db: Any = None) -> Winner | None:
        """Pick one proposal to act on, or None. Never reads wall time or config budgets."""
        if not settings.workspace_enabled:
            return None

        if self._user_pending:
            await registry.interrupt_for_user()
            await trace.record("workspace", "attend:preempt", "user message pending", allowed=False, db=db)
            return None

        # Load curiosity daily budget for investigate proposals
        curiosity_budget_obj = None
        if settings.curiosity_enabled:
            curiosity_budget_obj = await curiosity_budget.load_budget(db=db, now=now)

        self.live(now)
        scored: list[tuple[float, datetime, Proposal, float, float]] = []
        for p in list(self._proposals.values()):
            cost = {"tokens": p.cost.tokens, "seconds": p.cost.seconds, "risk": p.cost.risk.value}
            reason = None
            if p.kind not in KIND_TO_GATE:
                reason = "respond_never_autonomous"
            elif p.cost.tokens > budget.tokens or p.cost.seconds > budget.seconds:
                reason = "over_budget"
            elif p.cost.risk != RiskLevel.READ and not budget.allow_risk:
                reason = "risk_not_allowed"
            elif p.kind == ProposalKind.INVESTIGATE and curiosity_budget_obj is not None and (
                exhausted := curiosity_budget_obj.exhausted()
            ):
                # B4-03 (T6). Within budget, the proposal still goes through may_initiate below.
                reason = f"daily budget reached: {exhausted}"
            else:
                d = await controls.may_initiate(
                    KIND_TO_GATE[p.kind], now=now, source=p.source, refs=p.refs, db=db
                )
                if not d.allowed:
                    reason = f"gate_refused:{d.reason}"
            if reason is not None:
                await trace.record(
                    p.source, f"attend:reject:{p.kind.value}", reason,
                    allowed=False, cost=cost, refs=p.refs, db=db,
                )
                continue
            cs = cost_score(p.cost)
            gain = drive_gain(p.kind)
            score = p.urgency * p.value * gain / max(cs, settings.workspace_cost_epsilon)
            scored.append((score, p.created_at, p, cs, gain))

        if not scored:
            return None
        scored.sort(key=lambda t: (-t[0], t[1]))
        score, _, p, cs, gain = scored[0]
        winner = Winner(proposal=p, score=score, cost_score=cs, drive_gain=gain)
        await trace.record(
            p.source, f"attend:winner:{p.kind.value}", f"score={score:.4f} drive_gain={gain:.4f}",
            allowed=True,
            cost={"tokens": p.cost.tokens, "seconds": p.cost.seconds, "risk": p.cost.risk.value},
            refs=p.refs, db=db,
        )
        await self._publish_winner(winner)
        return winner

    async def _publish_winner(self, winner: Winner) -> None:
        """Broadcast the winner to every subscribed engine except the workspace."""
        if self._bus is None:
            return
        targets = [e for e in self._bus._subscribers if e != "workspace"]
        if not targets:
            return
        p = winner.proposal
        await self._bus.publish(EngineMessage(
            source="workspace",
            message_type=MessageType.STATE_UPDATE,
            data={
                "kind": "workspace_winner",
                "proposal_id": p.id,
                "proposal_kind": p.kind.value,
                "source": p.source,
                "summary": p.summary,
                "refs": p.refs,
                "score": winner.score,
            },
            targets=targets,
        ))

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


def _register_finding_handlers(workspace: Workspace) -> None:
    """Register SHARE and ASK_USER handlers (B4-04)."""
    from aura.models.proposal import ProposalKind
    workspace.register_handler(ProposalKind.SHARE, _handle_agenda_proposal)
    workspace.register_handler(ProposalKind.ASK_USER, _handle_agenda_proposal)


def get_workspace(bus: MessageBus | None = None) -> Workspace:
    """Get or create the global workspace instance."""
    global _workspace
    if _workspace is None:
        _workspace = Workspace(bus)
        _register_finding_handlers(_workspace)
    elif bus is not None and _workspace._bus is None:
        _workspace._bus = bus
    return _workspace


def set_workspace(workspace: Workspace | None) -> None:
    """Replace the global workspace (for testing)."""
    global _workspace
    _workspace = workspace


def fire_event(name: str, payload: dict[str, Any] | None = None) -> None:
    """Hook for callers: sync, cheap, never raises. No-op when workspace is off."""
    if not settings.workspace_enabled:
        return
    try:
        get_workspace().on_event(name, payload)
    except Exception:
        logger.warning("workspace event %s failed", name, exc_info=True)


def turn_finished() -> None:
    """Hook for the end of a turn (resumes paused autonomous work)."""
    if not settings.workspace_enabled:
        return
    try:
        get_workspace().turn_finished()
    except Exception:
        logger.warning("workspace turn_finished failed", exc_info=True)
