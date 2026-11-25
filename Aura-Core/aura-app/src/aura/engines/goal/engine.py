"""
Goal Engine - Autonomous desire formation and planning.

Implements PRD Section 5.1 (Goal Engine).
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.engines.base import BaseEngine
from aura.models.goal import CHECKLIST_FIELDS, STAGE_ORDER, Goal, GoalContext, Task
from aura.models.messages import EngineMessage, MessagePriority

if TYPE_CHECKING:
    from aura.orchestrator.protocols import MessageBusProtocol

logger = logging.getLogger(__name__)


class GoalEngine(BaseEngine):
    """
    Goal Engine for autonomous goal formation and execution.

    Features:
    - Boredom-driven goal generation
    - Hierarchical goal planning
    - Curiosity-driven exploration
    - Progress tracking
    """

    def __init__(self):
        """Initialize goal engine."""
        super().__init__("goal_engine")

        # Database
        self.db = get_db_client()

        # External dependencies (set by orchestrator)
        self._llm_layers: Any = None
        self._emotion_engine: Any = None
        self._learning_engine: Any = None

        # State
        self.active_goals: list[Goal] = []
        self.current_boredom_level: float = 0.0
        # Initialize with timezone-aware UTC datetime to avoid comparison errors
        self.last_user_interaction: datetime = datetime.now(timezone.utc)
        self.last_goal_generation: datetime = datetime.now(timezone.utc) # Added for rate limiting
        self._last_internal_interaction_update: datetime = datetime.now(timezone.utc)

        # Thresholds
        self.boredom_threshold = 0.6  # Trigger goal generation
        self.idle_time_threshold = 300.0  # 5 minutes

    def record_user_interaction(self) -> None:
        """Record a user interaction timestamp (called by orchestrator)."""
        self.last_user_interaction = datetime.now(timezone.utc)

    def set_dependencies(
        self,
        llm_layers: Any = None,
        emotion_engine: Any = None,
        learning_engine: Any = None,
        identity_engine: Any = None,
    ) -> None:
        """Set external dependencies for LLM-based goal generation."""
        if llm_layers:
            self._llm_layers = llm_layers
        if emotion_engine:
            self._emotion_engine = emotion_engine
        if learning_engine:
            self._learning_engine = learning_engine
        if identity_engine:
            self._identity_engine = identity_engine

    def set_message_bus(self, message_bus: "MessageBusProtocol") -> None:
        """Set message bus for inter-engine communication."""
        super().set_message_bus(message_bus)
        if message_bus:
            message_bus.subscribe("goal_engine", self._handle_message)

    async def initialize(self) -> None:
        """Initialize engine resources."""
        self.logger.info("Initializing Goal Engine...")

        # P2-31: every stored goal gets a stage before goals are loaded
        try:
            await self.migrate_stages()
        except Exception as e:
            self.logger.warning(f"Goal stage migration failed: {e}")

        # Load active goals
        await self._load_active_goals()

        self.logger.info(
            f"Goal Engine initialized - {len(self.active_goals)} active goals"
        )

    async def _note_workspace_mode(self) -> None:
        """Say once in the trace that boredom/idle goal creation is off."""
        if getattr(self, "_workspace_noted", False):
            return
        self._workspace_noted = True
        from aura.autonomy import trace

        await trace.record("goal_engine", "tick:boredom_goals_disabled",
                           "workspace_enabled: boredom and idle no longer create goals", allowed=False)

    async def tick(self) -> None:
        """
        Execute one goal engine cycle.

        Checks:
        - Boredom level (from emotion engine)
        - Idle time
        - Goal progress
        """
        # Check boredom and idle time
        # Ensure self.last_user_interaction is timezone aware, if not assume UTC
        last_interaction = self.last_user_interaction
        if last_interaction.tzinfo is None:
            last_interaction = last_interaction.replace(tzinfo=timezone.utc)
            
        idle_seconds = (datetime.now(timezone.utc) - last_interaction).total_seconds()

        if settings.workspace_enabled:
            # B2-04 (finding B1): the workspace cycle is the only self-start path.
            await self._note_workspace_mode()
        elif self.current_boredom_level > self.boredom_threshold:
            self.logger.info(
                f"High boredom detected ({self.current_boredom_level:.2f}) - "
                "considering goal generation"
            )
            await self._consider_new_goal("boredom")

        elif idle_seconds > self.idle_time_threshold:
            self.logger.info(
                f"Idle for {idle_seconds:.0f}s - considering exploration goal"
            )
            await self._consider_new_goal("idle_exploration")

        # Update goal progress and check for completion
        for goal in self.active_goals:
            if goal.status == "active":
                if settings.goals_v2_enabled:
                    await self._evidence_step(goal)
                else:
                    # Update progress based on emotional alignment
                    # If current emotions match the goal's emotional_alignment, progress increases
                    if self._emotion_engine and goal.emotional_alignment:
                        try:
                            current_emotions = await self._emotion_engine.get_current_state()
                            emotion_vector = current_emotions.vector.model_dump()
                        
                            # Calculate alignment score (how well current emotions match goal's alignment)
                            alignment_score = 0.0
                            total_weight = 0.0
                            for emotion_name, target_value in goal.emotional_alignment.items():
                                if emotion_name in emotion_vector:
                                    current_value = emotion_vector[emotion_name]
                                    # Score is higher when current emotion is close to or exceeds target
                                    similarity = 1.0 - abs(current_value - target_value)
                                    alignment_score += similarity * target_value
                                    total_weight += target_value
                        
                            if total_weight > 0:
                                alignment_score = alignment_score / total_weight
                            
                                # Progress increases slowly when emotions align (0.1% per tick if well-aligned)
                                if alignment_score > 0.7:
                                    progress_increment = 0.001 * alignment_score  # 0.1% per tick max
                                    new_progress = min(1.0, goal.progress + progress_increment)
                                    if new_progress > goal.progress:
                                        await self.update_goal_progress(
                                            goal.goal_id, 
                                            new_progress, 
                                            f"Progress updated - emotional alignment: {alignment_score:.2f}"
                                        )
                        except Exception as e:
                            self.logger.debug(f"Error updating goal progress from emotions: {e}")
                
                # Check if goal should be completed
                # Goals can be completed when:
                # 1. Progress reaches 1.0 (100%)
                # 2. Goal has been active for a long time with no progress (stale)
                
                # v2: completion needs every criterion met (progress only reaches 1.0 then)
                if goal.progress >= 1.0 and not (
                    settings.goals_v2_enabled
                    and goal.progress_from_criteria() not in (None, 1.0)
                ):
                    await self.update_goal_progress(goal.goal_id, 1.0, "Goal completed - progress reached 100%")
                
                # Check for stale goals (active for >24 hours with no progress)
                # Ensure both datetimes are timezone-aware
                now = get_clock().now()
                goal_created = goal.created
                if goal_created.tzinfo is None:
                    # If goal.created is naive, assume it's UTC
                    goal_created = goal_created.replace(tzinfo=timezone.utc)
                age_hours = (now - goal_created).total_seconds() / 3600
                # v2: stale-complete is gone; B3-03 replaces it with abandonment
                if age_hours > 24 and goal.progress < 0.1 and not settings.goals_v2_enabled:
                    self.logger.info(f"Marking stale goal as completed: {goal.name}")
                    await self.update_goal_progress(goal.goal_id, 1.0, "Goal completed - was stale with no progress")

                # B3-03: abandonment check (goals_v2_enabled only)
                if settings.goals_v2_enabled:
                    await self._check_abandonment(goal, now)

        if settings.goals_v3_enabled:  # P2-32: crystal plan, milestone evidence, flags
            await self.v3_tick()

        await asyncio.sleep(30.0)  # Check every 30 seconds

    async def _evidence_step(self, goal: Goal) -> None:
        """B3-02: progress comes from criteria met by code-checked evidence only.

        A goal without criteria keeps its progress unchanged.
        """
        if not goal.criteria:
            return
        from aura.engines.goal import evidence

        try:
            now = get_clock().now()
            met = await evidence.check(goal, now, self.db)
            if not met:
                return
            by_id = {m.criterion_id: m for m in met}
            for crit in goal.criteria:
                m = by_id.get(crit.get("id"))
                if m:
                    crit["status"] = "met"
                    crit["met_at"] = m.at
                    crit["evidence_ref"] = m.ref
            goal.evidence = [
                *(goal.evidence or []),
                *({"criterion_id": m.criterion_id, "kind": m.kind, "ref": m.ref, "at": m.at}
                  for m in met),
            ]
            goal.last_evidence_at = now
            new_progress = goal.progress_from_criteria()
            if settings.goals_v3_enabled and goal.milestones:
                new_progress = None  # P2-32: progress is done milestones over total
            if new_progress is not None and new_progress != goal.progress:
                await self.update_goal_progress(
                    goal.goal_id, new_progress, f"criterion met: {met[-1].name}"
                )
            else:
                await self._persist_goal(goal)
        except Exception as e:
            self.logger.warning(f"Evidence check failed for {goal.goal_id}: {e}")

    async def _persist_goal(self, goal: Goal) -> None:
        """Write the mutable goal fields. ``goal_id`` is the record id, not a stored field,
        and the SCHEMAFULL goal table has no ``metadata`` field: the old whole-model
        ``update`` always failed on both."""
        from aura.engines.goal.evidence import goal_rid

        fields = ("status", "progress", "updated", "completed", "criteria", "evidence",
                  "last_evidence_at", "abandon_reason", "stage", "stage_changed", "outcome",
                  "done_criteria", "owner", "horizon", "first_action", "origin_link",
                  "milestones", "close_reason", "proposed", "outcome_changed_at", "plan_requested_at",
                  "swift_checked_at", "orphan_flagged_at", "conflict_flags", "conflict_checked")
        data = {k: v for k, v in goal.model_dump().items() if k in fields and v is not None}
        await self.db.query("UPDATE $rid MERGE $data", {"rid": goal_rid(goal.goal_id), "data": data})

    async def migrate_stages(self) -> int:
        """P2-31 migration, run from ``initialize``: every goal row without a stage becomes
        "forming". Idempotent (rows that have a stage are untouched) and only sets
        ``stage`` and ``stage_changed``; no field is removed. Returns rows migrated."""
        now = get_clock().now()
        from aura.db.query_utils import extract_rows

        rows = extract_rows(await self.db.query(
            "UPDATE goal SET stage = 'forming', stage_changed = $now WHERE stage IS NONE RETURN id",
            {"now": now},
        ))
        return len(rows)

    def _find(self, goal_id: str) -> Goal | None:
        bare = goal_id.partition(":")[2] if goal_id.startswith("goal:") else goal_id
        return next((g for g in self.active_goals if g.goal_id in (goal_id, bare)), None)

    async def advance_stage(
        self, goal_id: str, to: str, *, close_reason: str | None = None
    ) -> tuple[bool, str]:
        """Move a goal forward. Returns (moved, reason). Never backwards (see
        ``change_outcome`` for crystal -> forming). Crystal and later need a complete
        checklist, active needs milestones, closed needs a ``close_reason``."""
        goal = self._find(goal_id)
        if goal is None:
            return False, "unknown goal"
        if to not in STAGE_ORDER:
            return False, f"unknown stage {to}"
        if STAGE_ORDER[to] <= STAGE_ORDER[goal.stage]:
            return False, f"stage moves only forward ({goal.stage} -> {to})"
        if to == "closed":
            if not (close_reason or "").strip():
                return False, "closing needs a reason"
            goal.close_reason = close_reason
        else:
            if STAGE_ORDER[to] >= STAGE_ORDER["crystal"]:
                missing = goal.crystallization()["missing"]
                if missing:
                    return False, "checklist incomplete: " + ", ".join(missing)
            if to == "active" and not goal.milestones:
                return False, "active needs milestones"
        goal.stage = to
        goal.stage_changed = goal.updated = get_clock().now()
        await self._persist_goal(goal)
        return True, "ok"

    async def update_checklist(self, goal_id: str, **fields: Any) -> Goal | None:
        """Fill checklist fields (outcome, done_criteria, owner, horizon, first_action,
        origin_link). A seed with any checklist item moves to forming. Changing the outcome
        of a crystal goal goes through ``change_outcome``."""
        goal = self._find(goal_id)
        if goal is None:
            return None
        allowed = (*CHECKLIST_FIELDS, "origin_link")
        for k, v in fields.items():
            if k not in allowed:
                raise ValueError(f"not a checklist field: {k}")
            if k == "outcome" and goal.stage in ("crystal", "active") and v != goal.outcome:
                raise ValueError("use change_outcome to change a crystal outcome")
        # Validate before writing, so a bad value (e.g. owner "bob") never reaches the DB
        # and breaks the next load (supervisor review, P2-31).
        checked = Goal.model_validate({**goal.model_dump(), **fields})
        for k in fields:
            setattr(goal, k, getattr(checked, k))
        if goal.stage == "seed" and any(k in CHECKLIST_FIELDS for k in fields):
            goal.stage = "forming"
            goal.stage_changed = get_clock().now()
        goal.updated = get_clock().now()
        await self._persist_goal(goal)
        return goal

    async def change_outcome(self, goal_id: str, outcome: str) -> Goal | None:
        """Mai changes the outcome. The only backward move: crystal -> forming (the
        checklist must be confirmed again). An active goal keeps its stage."""
        goal = self._find(goal_id)
        if goal is None or goal.stage == "closed":
            return None
        changed = outcome != goal.outcome
        goal.outcome = outcome
        now = get_clock().now()
        if changed and goal.stage == "crystal":
            goal.stage = "forming"
            goal.stage_changed = now
            goal.outcome_changed_at = now
        elif goal.stage == "seed":
            goal.stage = "forming"
            goal.stage_changed = now
        goal.updated = now
        await self._persist_goal(goal)
        return goal

    async def _close_stage(self, goal: Goal, reason: str) -> None:
        """Keep ``stage`` truthful when a goal is completed, cancelled or abandoned."""
        try:
            await self.advance_stage(goal.goal_id, "closed", close_reason=reason)
        except Exception as e:
            self.logger.warning(f"Could not close stage of {goal.goal_id}: {e}")

    # ---- Goals v3 (P2-32) -------------------------------------------------------------

    @staticmethod
    def _aware(dt: datetime) -> datetime:
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    @staticmethod
    def _is_mai_goal(goal: Goal) -> bool:
        """Mai's goals: owner mai or shared; with no owner, those that came from Mai's words."""
        if goal.owner is not None:
            return goal.owner in ("mai", "shared")
        return (goal.origin_link or {}).get("kind") in ("mai_said", "extraction")

    async def _set_proposed(self, goal: Goal, value: dict[str, Any] | None) -> None:
        from aura.engines.goal.evidence import goal_rid

        goal.proposed = value or None
        goal.updated = get_clock().now()
        await self._persist_goal(goal)
        if not value:  # _persist_goal skips None values
            await self.db.query("UPDATE $rid SET proposed = NONE", {"rid": goal_rid(goal.goal_id)})

    async def refine_checklist(
        self, goal_id: str, fields: dict[str, Any], *, mai_said: bool = False, confirm: bool = False
    ) -> tuple[bool, str]:
        """Fill checklist fields from the conversation. Returns (ok, message).

        On Mai's goals the outcome and done criteria need Mai's words (``mai_said``) or her
        confirmation of a recorded proposal (``confirm``); without either they are recorded
        in ``goal.proposed`` and change nothing else. Changing the outcome of a crystal goal
        always needs one of the two, and goes through ``change_outcome``.
        """
        goal = self._find(goal_id)
        if goal is None:
            return False, "unknown goal"
        if goal.stage == "closed" or goal.status != "active":
            return False, "the goal is closed"
        fields = dict(fields or {})
        bad = [k for k in fields if k not in CHECKLIST_FIELDS]
        if bad:
            return False, "not a checklist field: " + ", ".join(bad)
        if not fields and not confirm:
            return False, "nothing to refine"
        mai_goal = self._is_mai_goal(goal)
        guarded = ("outcome", "done_criteria")
        direct: dict[str, Any] = {}
        proposals: dict[str, Any] = {}
        if confirm:
            if any(k in fields for k in guarded):
                return False, "confirm applies the pending proposal; do not pass outcome or done_criteria with it"
            if not goal.proposed:
                return False, "nothing is proposed on this goal"
            direct.update(goal.proposed)
        if mai_goal and fields.get("owner") == "aura" and goal.owner != "aura" and not mai_said:
            return False, "only Mai can hand her goal to Aura"
        for k, v in fields.items():
            if k in guarded and mai_goal and not mai_said:
                proposals[k] = v
            else:
                direct[k] = v
        outcome = None
        if "outcome" in direct and goal.stage in ("crystal", "active"):
            if direct["outcome"] == goal.outcome:
                direct.pop("outcome")
            elif not (mai_said or confirm):
                return False, "only Mai changes the outcome of a crystal goal (mai_said or confirm)"
            else:
                outcome = direct.pop("outcome")
        try:
            if direct:
                await self.update_checklist(goal.goal_id, **direct)
            if outcome is not None:
                await self.change_outcome(goal.goal_id, outcome)
        except ValueError as e:
            return False, str(e)
        except Exception as e:  # pydantic validation of a bad value
            return False, f"invalid value: {e}"
        if confirm:
            await self._set_proposed(goal, None)
        if proposals:
            await self._set_proposed(goal, {**(goal.proposed or {}), **proposals})
        if outcome is None:  # a changed outcome stays forming until Mai's next explicit refine
            await self._maybe_crystallize(goal)
        missing = goal.crystallization()["missing"]
        note = f"recorded as proposed until Mai confirms: {', '.join(proposals)}; " if proposals else ""
        return True, f"{note}stage {goal.stage}, missing: {', '.join(missing) or 'nothing'}"

    async def confirm_proposal(self, goal_id: str) -> tuple[bool, str]:
        """Mai (inspector route) confirms the pending proposal."""
        return await self.refine_checklist(goal_id, {}, confirm=True)

    async def _maybe_crystallize(self, goal: Goal) -> bool:
        """The code gate: a complete checklist with nothing waiting for Mai becomes crystal."""
        if goal.stage not in ("seed", "forming") or goal.proposed:
            return False
        if not goal.crystallization()["complete"]:
            return False
        moved, _ = await self.advance_stage(goal.goal_id, "crystal")
        return moved

    async def v3_tick(self) -> None:
        """P2-32, from the goal tick: crystal gate, Sage plan, milestone evidence, flags."""
        now = get_clock().now()
        for goal in list(self.active_goals):
            if goal.status != "active" or goal.stage == "closed":
                continue
            try:
                await self._v3_step(goal, now)
            except Exception as e:
                self.logger.warning(f"v3 step failed for {goal.goal_id}: {e}")
        try:
            await self._v3_flags(now)
        except Exception as e:
            self.logger.warning(f"v3 flags failed: {e}")

    async def _v3_step(self, goal: Goal, now: datetime) -> None:
        if goal.outcome_changed_at is None:  # a goal demoted by Mai's outcome change is not re-gated here
            await self._maybe_crystallize(goal)
        if goal.stage == "crystal" and not goal.milestones:
            await self._plan_milestones(goal, now)
        if goal.milestones:
            await self._milestone_step(goal, now)

    async def _plan_milestones(self, goal: Goal, now: datetime) -> None:
        """The one Sage call of a goal that reached crystal (retried only after
        ``goals_v3_plan_retry_hours``; the attempt is stored before the call)."""
        from datetime import timedelta

        from aura.engines.goal import crystallize

        last = goal.plan_requested_at
        if last and now - self._aware(last) < timedelta(hours=settings.goals_v3_plan_retry_hours):
            return
        goal.plan_requested_at = now
        await self._persist_goal(goal)
        try:
            milestones = await crystallize.sage_plan(goal)
        except Exception as e:
            self.logger.warning(f"Sage milestone plan failed for {goal.goal_id}: {e}")
            return
        if not milestones:
            self.logger.warning(f"Sage plan for {goal.goal_id} had no usable milestone")
            return
        goal.milestones = milestones
        moved, why = await self.advance_stage(goal.goal_id, "active")
        if not moved:
            goal.milestones = None
            self.logger.warning(f"Goal {goal.goal_id} not activated: {why}")

    def _swift_due(self, goal: Goal, now: datetime) -> bool:
        from datetime import timedelta

        last = goal.swift_checked_at
        return not last or now - self._aware(last) >= timedelta(hours=settings.goals_v3_swift_min_hours)

    async def _milestone_step(self, goal: Goal, now: datetime) -> None:
        """Milestones turn done only from evidence code found (or Mai's confirmation).
        Progress is done over total."""
        from aura.engines.goal import crystallize, evidence

        changed = False
        for m in await evidence.check_milestones(goal, now, self.db):
            ms = goal.milestones[m.index]
            ms["status"] = "done"
            ms["evidence_refs"] = [*(ms.get("evidence_refs") or []), m.ref]
            ms["done_at"] = m.at
            ms.pop("needs_confirmation", None)
            goal.evidence = [*(goal.evidence or []),
                             {"milestone": m.name, "kind": m.kind, "ref": m.ref, "at": m.at}]
            goal.last_evidence_at = now
            changed = True

        # Specs code cannot check: Swift may only flag them for Mai, once per goal per day.
        pending = [i for i, ms in enumerate(goal.milestones)
                   if ms.get("status") != "done" and not ms.get("needs_confirmation")
                   and evidence.classify(ms.get("evidence_spec") or {}) == "model"]
        if pending and self._swift_due(goal, now):
            goal.swift_checked_at = now
            await self._persist_goal(goal)
            try:
                looks = await crystallize.swift_check(goal, pending)
            except Exception as e:
                self.logger.warning(f"Swift milestone check failed for {goal.goal_id}: {e}")
                looks = {}
            for i, reason in looks.items():
                goal.milestones[i]["needs_confirmation"] = True
                goal.milestones[i]["note"] = reason
                changed = True
        for ms in goal.milestones:
            if ms.get("needs_confirmation") and ms.get("status") != "done" and not ms.get("flagged_at"):
                created = await self._agenda_flag(
                    f"flag:ms:{goal.goal_id}:{ms.get('name')}", "question_for_you",
                    f"Milestone '{ms.get('name')}' of goal '{goal.name}' may be done, but I cannot "
                    f"check it myself. Can you confirm? ({ms.get('note') or 'no note'})",
                    [goal.goal_id], now,
                )
                if created:
                    ms["flagged_at"] = now
                    changed = True

        done = sum(1 for ms in goal.milestones if ms.get("status") == "done")
        progress = done / len(goal.milestones)
        if changed:
            await self._persist_goal(goal)
        if progress != goal.progress:
            await self.update_goal_progress(
                goal.goal_id, progress, f"{done} of {len(goal.milestones)} milestones done"
            )

    async def confirm_milestone(self, goal_id: str, index: int) -> Goal | None:
        """Mai confirms a milestone (route). Works for mai_confirms specs and for milestones
        Swift flagged; a milestone with a code-checkable spec is decided by code only."""
        from aura.engines.goal import evidence

        goal = self._find(goal_id)
        if goal is None or not goal.milestones or not 0 <= index < len(goal.milestones):
            return None
        ms = goal.milestones[index]
        if ms.get("status") == "done":
            return goal
        if evidence.classify(ms.get("evidence_spec") or {}) == "code":
            raise ValueError("this milestone is decided by evidence code can check")
        now = get_clock().now()
        ms["status"] = "done"
        ms["evidence_refs"] = [*(ms.get("evidence_refs") or []), "owner"]
        ms["done_at"] = now
        ms.pop("needs_confirmation", None)
        goal.evidence = [*(goal.evidence or []),
                         {"milestone": ms.get("name"), "kind": "mai_confirms", "ref": "owner", "at": now}]
        goal.last_evidence_at = now
        await self._persist_goal(goal)
        done = sum(1 for m in goal.milestones if m.get("status") == "done")
        await self.update_goal_progress(
            goal.goal_id, done / len(goal.milestones), f"{done} of {len(goal.milestones)} milestones done"
        )
        return goal

    async def _agenda_flag(self, key: str, kind: str, content: str, refs: list[str], now: datetime) -> bool:
        """Create one agenda item through the autonomy gate. False when the gate refuses; the
        refusal is not retried before ``goals_v3_swift_min_hours`` (no trace spam)."""
        from datetime import timedelta

        from aura.autonomy.agenda import AgendaService
        from aura.autonomy.controls import may_initiate

        backoff = self.__dict__.setdefault("_flag_backoff", {})
        if backoff.get(key) and now < backoff[key]:
            return False
        try:
            decision = await may_initiate(kind, now=now, source="goal_engine", refs=refs, db=self.db)
            if not decision.allowed:
                backoff[key] = now + timedelta(hours=settings.goals_v3_swift_min_hours)
                return False
            await AgendaService(self.db).create(
                kind=kind, content=content, refs=refs, priority=0.5, venue="app", source="goal_engine"
            )
            return True
        except Exception as e:
            self.logger.error(f"Could not create agenda item {key}: {e}")
            backoff[key] = now + timedelta(hours=settings.goals_v3_swift_min_hours)
            return False

    def _is_linked(self, goal: Goal, depth: int = 0) -> bool:
        """Linked to Mai, or to an approved Aura goal (``origin_link.approved``)."""
        link = goal.origin_link or {}
        if goal.owner in ("mai", "shared") or link.get("kind") in ("mai_said", "extraction"):
            return True
        if link.get("approved") is True:
            return True
        if link.get("kind") == "parent" and depth < 5:
            ref = str(link.get("ref") or "")
            parent = self._find(ref) if ref else None
            if parent is not None and parent.status not in ("abandoned", "cancelled"):
                return self._is_linked(parent, depth + 1)
        return False

    @staticmethod
    def _resources(goal: Goal) -> set[str]:
        """Budget resources a goal draws on, from its milestone evidence specs."""
        out: set[str] = set()
        for ms in goal.milestones or []:
            spec = ms.get("evidence_spec") or {}
            kind = spec.get("kind")
            if spec.get("resource") in ("opencode", "titan_budget"):
                out.add(spec["resource"])
            elif kind in ("commit", "test_pass"):
                out.add("opencode")
            elif kind == "task_node_done":
                out.add("titan_budget")
        return out

    def _horizon_open(self, goal: Goal, now: datetime) -> bool:
        """True while the goal's horizon has not ended (unparseable horizons count as open)."""
        import re
        from datetime import timedelta

        text = (goal.horizon or "").strip().lower()
        base = self._aware(goal.created)
        days = {"today": 1, "tomorrow": 2, "this week": 7, "this month": 31,
                "this quarter": 92, "this year": 366}.get(text)
        m = re.fullmatch(r"(?:in )?(\d+)\s*(day|week|month)s?", text)
        if m:
            days = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2)]
        if days is not None:
            return now < base + timedelta(days=days)
        try:
            return now < self._aware(datetime.fromisoformat(text))
        except ValueError:
            return True

    async def _v3_flags(self, now: datetime) -> None:
        """Orphans and conflicts, each flagged once (the flag is stored on the goal)."""
        from datetime import timedelta

        live = [g for g in self.active_goals if g.status == "active" and g.stage != "closed"]
        for g in live:
            if g.orphan_flagged_at is not None:
                continue
            ref = self._aware(g.last_evidence_at or g.created)
            if now - ref < timedelta(days=settings.goals_v3_orphan_days) or self._is_linked(g):
                continue
            if await self._agenda_flag(
                f"flag:orphan:{g.goal_id}", "observation",
                f"Goal '{g.name}' has no link to you or to an approved goal of mine and no evidence "
                f"for {settings.goals_v3_orphan_days} days. Should it be pruned?",
                [g.goal_id], now,
            ):
                g.orphan_flagged_at = now
                await self._persist_goal(g)

        from aura.engines.goal import crystallize

        swift_used = False
        for i, a in enumerate(live):
            for b in live[i + 1:]:
                if b.goal_id in (a.conflict_flags or []) or a.goal_id in (b.conflict_flags or []):
                    continue
                if not (self._horizon_open(a, now) and self._horizon_open(b, now)):
                    continue
                shared = self._resources(a) & self._resources(b)
                reason = f"both draw on {', '.join(sorted(shared))}" if shared else ""
                both_crystal = all(g.stage in ("crystal", "active") and g.outcome for g in (a, b))
                if (not reason and both_crystal and not swift_used
                        and b.goal_id not in (a.conflict_checked or [])
                        and a.goal_id not in (b.conflict_checked or [])
                        and self._swift_due(a, now) and self._swift_due(b, now)):
                    swift_used = True  # one pair check per tick
                    for g, other in ((a, b), (b, a)):
                        g.swift_checked_at = now
                        g.conflict_checked = [*(g.conflict_checked or []), other.goal_id]
                        await self._persist_goal(g)
                    try:
                        contradictory, why = await crystallize.swift_conflict(a, b)
                    except Exception as e:
                        self.logger.warning(f"Swift conflict check failed: {e}")
                        contradictory, why = False, ""
                    if contradictory:
                        reason = f"their outcomes seem to contradict: {why}"
                if not reason:
                    continue
                if await self._agenda_flag(
                    f"flag:conflict:{a.goal_id}:{b.goal_id}", "needs_decision",
                    f"Goals '{a.name}' and '{b.name}' may conflict: {reason}. Which should come first?",
                    [a.goal_id, b.goal_id], now,
                ):
                    for g, other in ((a, b), (b, a)):
                        g.conflict_flags = [*(g.conflict_flags or []), other.goal_id]
                        await self._persist_goal(g)

    async def check_evidence(self) -> None:
        """Event-driven check (task node finished, task_result), outside the tick."""
        if not settings.goals_v2_enabled:
            return
        for goal in self.active_goals:
            if goal.status == "active":
                await self._evidence_step(goal)

    async def _check_abandonment(self, goal: Goal, now: datetime) -> None:
        """B3-03: Check if an active goal should be abandoned due to lack of evidence.

        A goal whose last_evidence_at (or created when none) is older than
        goal_stall_days and which is not complete becomes abandoned with
        abandon_reason "no evidence for N days", a completed stamp left empty,
        and progress unchanged. An agenda observation item is created once.
        """
        # Determine the reference time: last_evidence_at or created
        ref_time = goal.last_evidence_at or goal.created
        if ref_time.tzinfo is None:
            ref_time = ref_time.replace(tzinfo=timezone.utc)

        stall_days = settings.goal_stall_days
        age_days = (now - ref_time).total_seconds() / 86400

        if age_days >= stall_days:
            # Goal is abandoned
            goal.status = "abandoned"
            goal.abandon_reason = f"no evidence for {int(age_days)} days"
            goal.updated = now
            # Note: completed is left as None (empty), progress unchanged

            try:
                await self._persist_goal(goal)
                await self._close_stage(goal, f"abandoned: {goal.abandon_reason}")
                self.logger.info(f"Goal abandoned: {goal.name} ({goal.abandon_reason})")
                # Told once: the tick only visits active goals, so this runs at the transition only.
                await self._create_abandonment_agenda_item(goal, now)
            except Exception as e:
                self.logger.error(f"Failed to abandon goal {goal.goal_id}: {e}")

    async def _create_abandonment_agenda_item(self, goal: Goal, now: datetime) -> None:
        """Create an agenda observation item for an abandoned goal."""
        from aura.autonomy.agenda import AgendaService
        from aura.autonomy.controls import may_initiate

        # Check if we may initiate (subject to autonomy controls)
        decision = await may_initiate(
            "observation", now=now, source="goal_engine", refs=[goal.goal_id], db=self.db,
            spend=False,  # P2-33: the message budget is spent when the deliverer sends it
        )
        if not decision.allowed:
            self.logger.debug(f"Abandonment notification not sent: {decision.reason}")
            return

        agenda = AgendaService(self.db)
        try:
            await agenda.create(
                kind="observation",
                content=f"Goal '{goal.name}' has been abandoned due to lack of evidence.",
                refs=[goal.goal_id],
                priority=0.5,
                venue="app",
                source="goal_engine",
            )
            self.logger.info(f"Created abandonment agenda item for goal {goal.goal_id}")
        except Exception as e:
            self.logger.error(f"Failed to create abandonment agenda item: {e}")

    async def reopen_goal(self, goal_id: str) -> Goal | None:
        """B3-03: Reopen an abandoned goal, resetting last_evidence_at to now.

        Abandoned goals are not loaded at startup, so the goal is read from the
        database when it is not in memory. Returns the goal, or None when it is
        unknown or not abandoned.
        """
        goal = next((g for g in self.active_goals if g.goal_id == goal_id), None)
        if goal is None:
            from aura.db.query_utils import extract_rows
            from aura.engines.goal.evidence import goal_rid

            rows = extract_rows(await self.db.query("SELECT * FROM $rid", {"rid": goal_rid(goal_id)}))
            if not rows:
                return None
            row = dict(rows[0])
            row.pop("id", None)
            row["goal_id"] = goal_id.partition(":")[2] if goal_id.startswith("goal:") else goal_id
            goal = Goal(**row)
            self.active_goals.append(goal)
        if goal.status != "abandoned":
            return None
        now = get_clock().now()
        goal.status = "active"
        goal.abandon_reason = None
        goal.last_evidence_at = now
        goal.updated = now
        if goal.stage == "closed":  # P2-32: reopening is the one way back out of closed
            goal.stage = ("active" if goal.milestones
                          else "crystal" if goal.crystallization()["complete"] else "forming")
            goal.stage_changed = now
            goal.close_reason = None
        await self._persist_goal(goal)
        from aura.engines.goal.evidence import goal_rid

        # _persist_goal skips None values, so clear the reason explicitly.
        await self.db.query("UPDATE $rid SET abandon_reason = NONE, close_reason = NONE", {"rid": goal_rid(goal.goal_id)})
        self.logger.info(f"Goal reopened: {goal.name}")
        return goal

    async def shutdown(self) -> None:
        """Clean up engine resources."""
        self.logger.info("Shutting down Goal Engine...")

    # Core Methods

    async def get_goal_context(self) -> GoalContext:
        """
        Get goal context for LLM injection.

        Returns:
            Active goals and current focus
        """
        # Get current focus (highest priority active goal)
        current_focus = None
        active = [g for g in self.active_goals if g.status == "active"]
        if active:
            current_focus = max(active, key=lambda g: g.priority)
            
        # Get pending proposals
        proposals = [g for g in self.active_goals if g.status == "proposed"]

        return GoalContext(
            active_goals=active[:5],  # Top 5 active goals
            current_focus=current_focus,
            pending_proposals=proposals,
        )
    
    async def check_goals_needing_autonomous_pursuit(self) -> list[Goal]:
        """
        Analyze active goals to determine which ones would benefit from autonomous pursuit.
        
        Criteria for suggesting autonomous pursuit:
        - Goal has been active for >2 hours with <20% progress (stuck)
        - Goal has high priority (>0.7) and low progress (<30%)
        - Goal is curiosity-driven and emotional alignment is high but progress is low
        - Goal hasn't been pursued autonomously recently (within last 24 hours)
        
        Returns:
            List of goals that should trigger pursuit requests
        """
        if not self.active_goals:
            return []

        from aura.config import settings

        if settings.autonomy_enabled:
            from aura.autonomy.controls import may_initiate

            if not (await may_initiate("pursue_goal", source="goal_engine")).allowed:
                return []

        now = datetime.now(timezone.utc)
        candidates = []
        
        for goal in self.active_goals:
            if goal.status != "active":
                continue
            
            # Ensure goal.created is timezone-aware
            goal_created = goal.created
            if goal_created.tzinfo is None:
                goal_created = goal_created.replace(tzinfo=timezone.utc)
            
            age_hours = (now - goal_created).total_seconds() / 3600
            
            # Check if goal was recently pursued autonomously (check metadata)
            last_pursuit = goal.metadata.get("last_autonomous_pursuit")
            if last_pursuit:
                if isinstance(last_pursuit, str):
                    # Try to parse ISO format datetime string
                    try:
                        last_pursuit_dt = datetime.fromisoformat(last_pursuit.replace('Z', '+00:00'))
                    except (ValueError, AttributeError):
                        # If parsing fails, skip the check
                        last_pursuit_dt = None
                else:
                    last_pursuit_dt = last_pursuit
                
                if last_pursuit_dt:
                    if last_pursuit_dt.tzinfo is None:
                        last_pursuit_dt = last_pursuit_dt.replace(tzinfo=timezone.utc)
                    hours_since_pursuit = (now - last_pursuit_dt).total_seconds() / 3600
                    if hours_since_pursuit < 24:
                        continue  # Recently pursued, skip
            
            # Criteria 1: Stuck goal (old but low progress)
            if age_hours > 2 and goal.progress < 0.2:
                candidates.append(goal)
                continue
            
            # Criteria 2: High priority but low progress
            if goal.priority > 0.7 and goal.progress < 0.3:
                candidates.append(goal)
                continue
            
            # Criteria 3: Curiosity-driven with high emotional alignment but low progress
            if goal.goal_type == "curiosity_driven" and goal.progress < 0.3:
                if self._emotion_engine and goal.emotional_alignment:
                    try:
                        current_emotions = await self._emotion_engine.get_current_state()
                        emotion_vector = current_emotions.vector.model_dump()
                        
                        # Check if emotions align well
                        alignment_score = 0.0
                        total_weight = 0.0
                        for emotion_name, target_value in goal.emotional_alignment.items():
                            if emotion_name in emotion_vector:
                                current_value = emotion_vector[emotion_name]
                                similarity = 1.0 - abs(current_value - target_value)
                                alignment_score += similarity * target_value
                                total_weight += target_value
                        
                        if total_weight > 0:
                            alignment_score = alignment_score / total_weight
                            if alignment_score > 0.7:  # High alignment
                                candidates.append(goal)
                    except Exception:
                        pass  # Skip if emotion check fails
        
        # Return top 1-2 candidates (prioritize by priority * (1 - progress))
        candidates.sort(key=lambda g: g.priority * (1 - g.progress), reverse=True)
        return candidates[:2]  # Max 2 suggestions at a time

    async def generate_goal_on_demand(
        self,
        trigger: str = "user_requested",
        additional_context: dict[str, Any] | None = None,
    ) -> Goal | None:
        """
        Generate a goal on demand using LLM analysis of emotions and learning.

        This is the main method for LLM-based goal generation that analyzes:
        - Current emotional state
        - Learning context and gaps
        - Recent memories and patterns

        Args:
            trigger: What triggered goal generation
            additional_context: Any additional context to consider

        Returns:
            Newly generated goal or None
        """
        if not self._llm_layers or not self._emotion_engine or not self._learning_engine:
            self.logger.warning("LLM layers or engines not set, using template-based generation")
            return await self.formulate_goal(trigger, additional_context or {})

        try:
            # Gather context from all engines
            emotional_state = await self._emotion_engine.get_current_state()
            learning_context = await self._learning_engine.get_learning_context(
                context="", user_id="default"
            )

            # Build prompt for L2 goal generation
            emotion_desc = emotional_state.description
            top_emotions = sorted(
                emotional_state.vector.model_dump().items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            emotion_str = ", ".join([f"{name}={val:.2f}" for name, val in top_emotions])

            # Learning FRD refactor: LearningContext now exposes `insights` instead of `rules`.
            learning_info = ""
            try:
                insights = getattr(learning_context, "insights", None) or []
                if insights:
                    learning_info = f"\nRecent learnings: {len(insights)} insights active"
                    if learning_context.mastery_level > 0:
                        learning_info += f", mastery level: {learning_context.mastery_level:.2f}"
            except Exception:
                # Non-critical for goal generation; proceed without learning_info
                learning_info = ""

            prompt = f"""You are Aura, an evolving AI companion. This is your internal goal generation process.
Analyze your current state, context, and recent history to propose a meaningful goal for yourself.

CURRENT STATE:
Emotional State: {emotion_desc}
Top Emotions: {emotion_str}
Trigger: {trigger}
{learning_info}

CONTEXT & HISTORY:
{additional_context.get('description', '') if additional_context else ''}
(Check for any recent desires or curiosities you expressed in conversation)

TASK:
Generate a specific, actionable goal that:
1. Is genuinely interesting to YOU (not just generic exploration)
2. Aligns with your current emotional state but isn't solely defined by it
3. Addresses learning gaps or builds on recent discoveries
4. Has clear value for growth or exploration
5. Is distinct from recent goals (avoid repetition)

IMPORTANT:
- If you felt a desire to understand something specific (like your own architecture, a user's comment, etc.), prioritize that.
- Don't just obsess over "nature" or "patterns" unless it's truly relevant to the immediate context.
- Be creative and varied.

Return ONLY a JSON object with:
{{
  "name": "Short goal name (3-5 words)",
  "description": "Detailed description of what this goal entails",
  "goal_type": "curiosity_driven|learning_gap|creative|user_requested|maintenance",
  "priority": 0.0-1.0,
  "emotional_alignment": {{"emotion_name": alignment_value, ...}},
  "reasoning": "Why this goal makes sense right now"
}}"""

            messages = [
                {
                    "role": "system",
                    "content": "You are Aura's internal goal generator. You define what Aura wants to achieve next. Be creative, varied, and specific.",
                },
                {"role": "user", "content": prompt},
            ]

            # Use L3 for goal generation (creative synthesis)
            # Access the client through the LLM layers
            from aura.config import settings
            
            # Use a slightly higher temperature for variety
            response = await self._llm_layers.client.complete(
                messages=messages,
                model=self._llm_layers.l3_model,
                temperature=0.85,
                max_tokens=500,
            )

            # Parse JSON response
            import json
            import re

            json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', response, re.DOTALL)
            if json_match:
                goal_data = json.loads(json_match.group())
                
                # Create goal from LLM response
                priority = min(1.0, max(0.0, float(goal_data.get("priority", 0.5))))
                
                # Determine status based on priority
                # High priority -> active immediately
                # Medium priority -> proposed (ask user)
                status = "active"
                if 0.4 <= priority <= 0.65:
                    status = "proposed"
                
                goal = Goal(
                    goal_id=f"goal:{uuid4().hex[:12]}",
                    name=goal_data.get("name", "New Goal"),
                    description=goal_data.get("description", ""),
                    goal_type=goal_data.get("goal_type", "curiosity_driven"),
                    priority=priority,
                    status=status,
                    origin=f"llm_generated_{trigger}",
                    emotional_alignment=goal_data.get("emotional_alignment", {}),
                    metadata={
                        "reasoning": goal_data.get("reasoning", ""),
                        "llm_generated": True,
                    },
                )

                # Check for duplicates before storing
                # Check if a similar goal already exists (same name or very similar)
                existing_similar = [
                    g for g in self.active_goals
                    if g.name.lower().strip() == goal.name.lower().strip()
                    or (g.description.lower().strip()[:50] == goal.description.lower().strip()[:50]
                        and g.status == "active")
                ]
                
                if existing_similar:
                    self.logger.warning(f"Duplicate goal detected, skipping: {goal.name}")
                    return None
                
                # Store goal
                await self.db.create(goal.goal_id, goal.model_dump())
                self.active_goals.append(goal)

                self.logger.info(f"✅ LLM-generated goal: {goal.name} (priority: {goal.priority:.2f}, status: {goal.status})")

                # Broadcast goal creation
                if self._message_bus:
                    from aura.models.messages import EngineMessage, MessagePriority
                    message = EngineMessage.create_state_update(
                        source="goal_engine",
                        data={
                            "goal_id": goal.goal_id,
                            "name": goal.name,
                            "type": goal.goal_type,
                            "priority": goal.priority,
                        },
                        targets=["orchestrator", "learning_engine"],
                        priority=MessagePriority.NORMAL,
                    )
                    await self._message_bus.publish(message)

                return goal
            else:
                self.logger.warning("Failed to parse LLM response, falling back to template")
                return await self.formulate_goal(trigger, additional_context or {})

        except Exception as e:
            self.logger.error(f"LLM goal generation failed: {e}", exc_info=True)
            # Fallback to template-based
            return await self.formulate_goal(trigger, additional_context or {})

    async def formulate_goal(
        self,
        trigger: str,
        context: dict[str, Any],
    ) -> Goal | None:
        """
        Use template-based goal formulation (fallback when LLM unavailable).

        Args:
            trigger: What triggered goal formation (boredom, curiosity, etc.)
            context: Relevant context

        Returns:
            New goal or None
        """

        goal_templates = {
            "boredom": {
                "name": "Explore interesting topic",
                "description": "Research a topic I haven't explored recently",
                "type": "curiosity_driven",
                "priority": 0.6,
            },
            "idle_exploration": {
                "name": "Review recent learnings",
                "description": "Analyze patterns from recent experiences",
                "type": "learning_gap",
                "priority": 0.5,
            },
            "curiosity": {
                "name": "Deep dive investigation",
                "description": "Investigate an intriguing pattern",
                "type": "curiosity_driven",
                "priority": 0.7,
            },
        }

        template = goal_templates.get(trigger)
        if not template:
            return None

        goal = Goal(
            goal_id=f"goal:{uuid4().hex[:12]}",
            name=template["name"],
            description=template["description"],
            goal_type=template["type"],
            priority=template["priority"],
            origin=f"autonomous_{trigger}",
            emotional_alignment=context.get("emotions", {}),
        )

        # Check for duplicates before storing
        existing_similar = [
            g for g in self.active_goals
            if g.name.lower().strip() == goal.name.lower().strip()
            or (g.description.lower().strip()[:50] == goal.description.lower().strip()[:50]
                and g.status == "active")
        ]
        
        if existing_similar:
            self.logger.warning(f"Duplicate goal detected (template), skipping: {goal.name}")
            return None

        # Store goal
        try:
            # option<...> goal fields reject null, so drop the unset ones
            await self.db.create(
                "goal", {k: v for k, v in goal.model_dump().items() if v is not None}
            )
            self.active_goals.append(goal)

            self.logger.info(f"New goal formulated: {goal.name} ({trigger})")

            # Broadcast goal creation
            if self._message_bus:
                message = EngineMessage.create_state_update(
                    source="goal_engine",
                    data={
                        "goal_id": goal.goal_id,
                        "name": goal.name,
                        "type": goal.goal_type,
                    },
                    targets=["orchestrator", "learning_engine"],
                    priority=MessagePriority.NORMAL,
                )
                await self._message_bus.publish(message)

            return goal

        except Exception as e:
            self.logger.error(f"Failed to create goal: {e}")
            return None

    async def update_goal_progress(
        self, goal_id: str, progress: float, notes: str = ""
    ) -> None:
        """
        Update goal progress.

        Args:
            goal_id: Goal identifier
            progress: New progress [0, 1]
            notes: Progress notes
        """
        for goal in self.active_goals:
            if goal.goal_id == goal_id:
                goal.progress = progress
                goal.updated = get_clock().now()

                if progress >= 1.0:
                    goal.status = "completed"
                    goal.completed = get_clock().now()
                    self.logger.info(f"Goal completed: {goal.name}")

                # Persist
                try:
                    await self._persist_goal(goal)
                    if goal.status == "completed":
                        await self._close_stage(goal, f"completed: {notes}" if notes else "completed")
                except Exception as e:
                    self.logger.error(f"Failed to update goal: {e}")

                break

    async def cancel_goal(self, goal_id: str, reason: str) -> None:
        """Cancel a goal."""
        for goal in self.active_goals:
            if goal.goal_id == goal_id:
                goal.status = "cancelled"
                goal.updated = get_clock().now()
                goal.metadata["cancellation_reason"] = reason

                try:
                    await self._persist_goal(goal)
                    await self._close_stage(goal, f"cancelled: {reason}" if reason else "cancelled")
                    self.logger.info(f"Goal cancelled: {goal.name} - {reason}")
                except Exception as e:
                    self.logger.error(f"Failed to cancel goal: {e}")

                break

    # Private Methods

    async def check_boredom(self) -> float:
        """
        Check current boredom level from emotion engine.

        Returns:
            Boredom level [0, 1]
        """
        # This is updated via message bus from emotion engine
        return self.current_boredom_level

    async def _consider_new_goal(self, trigger: str, accepted_proposal: bool = False) -> None:
        """Consider creating a new goal based on trigger.

        Under goals_v2_enabled, goal creation by Aura is gated: goals come from
        the owner, from an accepted drive proposal, or (at open) from a
        read-only curiosity question. This method returns immediately for
        boredom/idle_exploration/curiosity triggers unless called with
        accepted_proposal=True.

        P2-33: with ``autonomy_enabled`` every call passes may_initiate
        ("propose_goal", level 2) first, and a goal Aura creates on her own
        becomes a proposal (paused until Mai approves it in chat). Flag off:
        the behaviour above, unchanged.
        """
        gated = settings.autonomy_enabled
        if gated:
            from aura.autonomy.controls import may_initiate

            decision = await may_initiate(
                "propose_goal", source="goal_engine", refs=[f"trigger:{trigger}"],
                spend=False, db=self.db,
            )
            if not decision.allowed:
                return
        # B3-06: under goals_v2_enabled, autonomous goal creation from
        # boredom, idle_exploration, curiosity, etc. is disabled.
        # Goals come from the owner, accepted drive proposals, or read-only
        # curiosity questions at open autonomy level.
        elif settings.goals_v2_enabled and not accepted_proposal:
            return

        now = datetime.now(timezone.utc)
        
        # Rate limit: Max 1 new goal per hour (3600 seconds)
        # Reduced from whatever it was before to respect user request
        time_since_last = (now - self.last_goal_generation).total_seconds()
        if time_since_last < 3600.0:  # 1 hour cooldown
            return
            
        # Clean up completed goals from active list
        self.active_goals = [g for g in self.active_goals if g.status == "active"]
        
        # Check if we already have too many active goals
        active_count = len(self.active_goals)

        if active_count >= 5:  # Increased from 3 to allow more goals
            self.logger.debug("Too many active goals, skipping new goal generation")
            return

        # Check if recent goal with same trigger (within last hour)
        recent = [
            g
            for g in self.active_goals
            if (g.origin == f"autonomous_{trigger}" or g.origin == f"llm_generated_{trigger}")
            and (datetime.now(timezone.utc) - (g.created.replace(tzinfo=timezone.utc) if g.created.tzinfo is None else g.created)).total_seconds() < 3600
        ]

        if recent:
            self.logger.debug(f"Recent goal with same trigger ({trigger}) exists, skipping")
            return
            
        self.last_goal_generation = now

        # Check for similar goals (same name or very similar description)
        # This prevents duplicate goals from being created
        if self._llm_layers and self._emotion_engine and self._learning_engine:
            # Use LLM-based generation which should avoid duplicates
            context = {
                "boredom_level": self.current_boredom_level,
                "idle_time": (
                    datetime.now(timezone.utc) - self.last_user_interaction
                ).total_seconds(),
            }
            goal = await self.generate_goal_on_demand(trigger, context)
        else:
            # Fallback to template-based
            context = {
                "boredom_level": self.current_boredom_level,
                "idle_time": (
                    datetime.now(timezone.utc) - self.last_user_interaction
                ).total_seconds(),
            }
            goal = await self.formulate_goal(trigger, context)
        if gated and goal is not None and not accepted_proposal:
            from aura.autonomy.initiative import propose_goal

            await propose_goal(self, goal, db=self.db)

    async def _load_active_goals(self) -> None:
        """Load active goals from database."""
        try:
            result = await self.db.query(
                """
                SELECT * FROM goal
                WHERE status IN ['active', 'paused', 'proposed']
                ORDER BY priority DESC, created DESC
                LIMIT 20
                """
            )

            if result:
                # The goal table has no goal_id field (SCHEMAFULL drops it), so the
                # id comes from the record id (2026-11-24, found in B3-01 review).
                from aura.db.query_utils import extract_rows
                from aura.engines.learning.skill_store import rid_str

                goals = []
                for goal_data in extract_rows(result):
                    row = dict(goal_data)
                    rid = row.pop("id", None)
                    if not row.get("goal_id") and rid is not None:
                        row["goal_id"] = rid_str(rid).partition(":")[2] or rid_str(rid)
                    try:
                        goals.append(Goal(**row))
                    except Exception as e:
                        self.logger.warning(f"Skipping unloadable goal {rid}: {e}")
                
                # Deduplicate goals by name and description (prevent exact duplicates)
                seen = set()
                unique_goals = []
                for goal in goals:
                    # Create a unique key from name and description
                    key = (goal.name.lower().strip(), goal.description.lower().strip()[:100])
                    if key not in seen:
                        seen.add(key)
                        unique_goals.append(goal)
                    else:
                        self.logger.debug(f"Skipping duplicate goal: {goal.name}")
                
                self.active_goals = unique_goals[:10]  # Keep top 10 after deduplication
                self.logger.info(f"Loaded {len(self.active_goals)} unique active goals")

        except Exception as e:
            self.logger.error(f"Failed to load goals: {e}")
    
    async def pursue_goal_autonomously(
        self,
        goal_id: str,
        loop_count: int,
        orchestrator: Any,
        tool_permissions: list[str] | None = None,
        allow_interruption: bool = True,
    ) -> dict[str, Any]:
        """Gate (B1-06), then run the pursuit as a registered task the kill switch can cancel.

        The gate and the registration apply only when ``autonomy_enabled``;
        off means the old behaviour.
        """
        from aura.config import settings

        if not settings.autonomy_enabled:
            return await self._pursue_goal_impl(
                goal_id, loop_count, orchestrator, tool_permissions, allow_interruption
            )
        from aura.autonomy.controls import may_initiate
        from aura.autonomy.registry import register_autonomous_task

        decision = await may_initiate("pursue_goal", source="goal_engine", refs=[goal_id])
        if not decision.allowed:
            raise ValueError(f"autonomous pursuit refused: {decision.reason}")
        task = asyncio.create_task(
            self._pursue_goal_impl(goal_id, loop_count, orchestrator, tool_permissions, allow_interruption),
            name=f"pursue_goal:{goal_id}",
        )
        register_autonomous_task(task, "pursue_goal", goal_id)
        try:
            return await task
        except asyncio.CancelledError:
            me = asyncio.current_task()
            if task.cancelled() and (me is None or me.cancelling() == 0):
                raise ValueError("autonomous pursuit cancelled by the kill switch") from None
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def _pursue_goal_impl(
        self,
        goal_id: str,
        loop_count: int,
        orchestrator: Any,
        tool_permissions: list[str] | None = None,
        allow_interruption: bool = True,
    ) -> dict[str, Any]:
        """
        Pursue a goal autonomously through multiple L2/L3 iterations.
        
        Args:
            goal_id: The goal to pursue
            loop_count: Number of L2/L3 iterations to perform
            orchestrator: Orchestrator instance for L2/L3 access
            tool_permissions: List of tool IDs Aura is allowed to use
            allow_interruption: If True, Aura will pause for user messages. If False, complete uninterrupted.
            
        Returns:
            Dictionary with results: iterations, progress_updates, final_progress
        """
        # Find the goal
        goal = next((g for g in self.active_goals if g.goal_id == goal_id), None)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")
        
        if goal.status != "active":
            raise ValueError(f"Goal {goal_id} is not active")
        
        self.logger.info(
            f"🚀 Starting autonomous pursuit of goal: {goal.name} "
            f"({loop_count} iterations, tools: {tool_permissions or []}, "
            f"interruptible: {allow_interruption})"
        )
        
        initial_progress = goal.progress
        iterations = []
        progress_updates = []
        
        # Store tool permissions and interruption setting for use during pursuit
        # (These will be used when tools are implemented)
        pursuit_config = {
            "tool_permissions": tool_permissions or [],
            "allow_interruption": allow_interruption,
        }
        
        # Track start time for interruption checking
        pursuit_start_time = datetime.now(timezone.utc)
        self._last_internal_interaction_update = pursuit_start_time
        
        for i in range(loop_count):
            # Check for interruption (if allowed)
            if allow_interruption:
                # If last_user_interaction is newer than our last internal update,
                # it means a real user message came in through the orchestrator.
                if self.last_user_interaction > self._last_internal_interaction_update:
                    self.logger.info(f"🛑 Autonomous pursuit interrupted by user interaction at iteration {i}/{loop_count}")
                    break
                    
            self.logger.info(f"  Iteration {i+1}/{loop_count}")
            
            # Build a synthetic user input focused on the goal
            # This simulates Aura thinking about and working on the goal
            synthetic_input = f"I'm working on my goal: {goal.name}. {goal.description}"
            
            # Get current state
            emotional_state = await self._emotion_engine.get_current_state()
            learning_context = await self._learning_engine.get_learning_context(
                context=synthetic_input,
                user_id="aura_autonomous",
            )
            # Get identity context if available
            identity_context = None
            if self._identity_engine:
                identity_context = await self._identity_engine.get_identity_context(
                    conversation_topic=synthetic_input
                )
            goal_context = await self.get_goal_context()
            
            # L3: Generate a response/thought about pursuing the goal
            from aura.llm.layers import SynthesisContext
            synthesis_context = SynthesisContext(
                user_input=synthetic_input,
                conversation_history=[],
                emotional_state=emotional_state,
                learning_context=learning_context,
                identity_context=identity_context,
                goal_context=goal_context,
            )
            
            # Generate L3 response (Aura's internal thought/action)
            l3_response = await orchestrator.llm_layers.l3_synthesis(
                synthesis_context,
                max_history_messages=5,
            )
            
            # L2: Analyze the iteration and assess progress
            # Use orchestrator's L2 analysis method
            await orchestrator._assess_goal_progress(
                user_input=synthetic_input,
                aura_response=l3_response,
                active_goals=[goal],
                emotional_state=emotional_state,
            )
            
            # Prevent idle detection triggering during pursuit
            # But capture the "set time" so we can distinguish our own updates from user updates
            now = datetime.now(timezone.utc)
            self.last_user_interaction = now
            self._last_internal_interaction_update = now # New internal flag (needs to be added to __init__ if strictly typed, but python allows dynamic)
            
            # Reload goal to get updated progress (IMPORTANT: Must reload from DB or memory)
            # The _assess_goal_progress method updates the goal in the list reference if it finds it,
            # but let's be safe and get the fresh reference from our active_goals list
            updated_goal = next((g for g in self.active_goals if g.goal_id == goal_id), None)
            
            if updated_goal:
                progress_updates.append({
                    "iteration": i + 1,
                    "progress": updated_goal.progress,
                    "response": l3_response[:200],  # Truncate for logging
                })
                iterations.append({
                    "iteration": i + 1,
                    "l3_response": l3_response,
                    "progress": updated_goal.progress,
                })
                # Update our local reference for next loop
                goal = updated_goal
            
            # Significant delay between iterations to prevent rate limits
            # 5 seconds delay ensures we don't hit 429 errors from the LLM provider
            await asyncio.sleep(5.0)
        
        final_progress = goal.progress if goal else initial_progress
        progress_delta = final_progress - initial_progress
        
        self.logger.info(
            f"✅ Autonomous pursuit complete: {goal.name} "
            f"({int(initial_progress * 100)}% → {int(final_progress * 100)}%, "
            f"delta: +{int(progress_delta * 100)}%)"
        )
        
        # Record that this goal was pursued autonomously
        if goal:
            goal.metadata["last_autonomous_pursuit"] = datetime.now(timezone.utc).isoformat()
            try:
                await self.db.update(goal_id, goal.model_dump())
            except Exception as e:
                self.logger.warning(f"Failed to update goal metadata: {e}")
        
        return {
            "goal_id": goal_id,
            "goal_name": goal.name if goal else "Unknown",
            "iterations": iterations,
            "progress_updates": progress_updates,
            "initial_progress": initial_progress,
            "final_progress": final_progress,
            "progress_delta": progress_delta,
            "loop_count": loop_count,
        }

    async def _handle_message(self, message: EngineMessage) -> None:
        """Handle incoming messages from other engines."""
        if message.data.get("kind") in ("task_node_done", "task_result"):
            await self.check_evidence()
        if message.source == "emotion_engine":
            # Update boredom level from emotion state
            data = message.data
            vector = data.get("vector", {})
            self.current_boredom_level = vector.get("boredom", 0.0)

            # Check high emotions for goal generation
            curiosity = vector.get("curiosity", 0.0)
            interest = vector.get("interest", 0.0)
            fascination = vector.get("fascination", 0.0)
            wonder = vector.get("wonder", 0.0)
            
            # High curiosity triggers exploration goals
            if curiosity > 0.7:
                await self._consider_new_goal("curiosity")
            
            # High interest + fascination could trigger creative goals
            if interest > 0.7 and fascination > 0.6:
                await self._consider_new_goal("creative_interest")
            
            # High wonder triggers discovery goals
            if wonder > 0.7:
                await self._consider_new_goal("wonder_driven")
