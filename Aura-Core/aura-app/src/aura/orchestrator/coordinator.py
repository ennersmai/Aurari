"""
Meta-Cognitive Orchestrator (Cognitive PRD Section 3).

Coordinates all engines, handles conflicts, maintains coherence.
"""

import json
import logging
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.engines.emotion.engine import EmotionEngine
from aura.engines.goal.engine import GoalEngine
from aura.engines.identity.engine import IdentityEngine
from aura.engines.learning.engine import LearningEngine
from aura.engines.memory.v2.episodes import schedule_extraction, store_episode
from aura.engines.memory.v2.identity import speaker_key
from aura.engines.memory.v2.salience import (
    emotional_intensity,
    interaction_depth,
    salience as compute_salience,
)
from aura.engines.recall.assembly import estimate_tokens
from aura.engines.recall.models import ContextPacket, RecallRequest
from aura.engines.reflection.engine import ReflectionEngine
from aura.executor.tool_executor import ToolExecutor
from aura.executor.tool_registry import get_tool_registry
from aura.llm.layers import LLMLayers, SynthesisContext
from aura.llm.tool_calls import ModelTurn
from aura.models.emotion import EmotionInfluence, EmotionState
from aura.models.goal import GoalContext, Goal
from aura.models.learning import LearningContext
from aura.models.messages import EngineMessage
from aura.orchestrator.message_bus import MessageBus
from aura.orchestrator.tool_loop import NativeCalls, RoundUsage, run_tool_loop
from aura.tiers import (
    TierProfile,
    active_profile,
    gated_tools_denied,
    l2_analysis_allowed,
    l2_reasoning_allowed,
    TIER_NAMES,
    l3_reasoning_allowed,
    note_deprecated_reasoning_controls,
    recall_budget_tokens,
    trim_history,
)
from aura.engines.emotion.system_events import tool_succeeded, tool_failed, self_critique_received, memory_write_failed

logger = logging.getLogger(__name__)


TASK_UNAVAILABLE_NOTE = "Multi-agent work is not available on this tier."


@dataclass
class TurnContext:
    """Gathered context for a single turn (W2-08).

    Holds the engine outputs, resonance score, critique/cold-start/latent-xml
    strings, and the assembled ``SynthesisContext`` produced by
    :meth:`Orchestrator._gather_turn_context`.
    """

    emotional_state: Any
    learning_context: Any
    identity_context: Any
    goal_context: Any
    resonance_score: float
    recent_critique: str | None
    cold_start_xml: str | None
    latent_intuition_xml: str | None
    synthesis_context: SynthesisContext
    packet: ContextPacket | None = None
    offered_tools: list = field(default_factory=list)
    speaker: str = ""
    venue: str = "app"
    session: Any = None  # SessionContext of the turn's session; None for main (G4-04a)
    conversation_id: str | None = None  # reaches plan_task as _conversation_id (P2-11)
    tier_profile: TierProfile | None = None  # set only with tier_profiles_enabled
    route: str | None = None  # L1 route (P2-06); None with l1_routes_enabled off
    stakes: float | None = None  # L1 stakes 0..1 (P2-06)
    prompt_notes: list[str] = field(default_factory=list)
    # Skills chosen for this turn as (skill name or doc id, version); G5-05 fills it,
    # empty until then. ``turn_tools`` collects the tool names the loop ran (G5-04).
    chosen_skills: list = field(default_factory=list)
    turn_tools: list[str] = field(default_factory=list)
    # G5-05: skill index text, the chosen skill's body and name; None when off.
    skill_index: str | None = None
    skill_body: str | None = None
    skill_name: str | None = None


@dataclass
class TurnEvent:
    """One event in the ``_turn_pipeline`` stream (W2-10).

    ``delta`` events carry a text chunk (one character for an early reply,
    one streamed chunk during generation, including the ``"\\n\\n"`` round
    separators). ``done`` carries the response the turn stores.

    During generation the pipeline relays the ``run_tool_loop``
    :class:`~aura.orchestrator.tool_loop.LoopEvent` items: the loop's
    ``delta`` and ``separator`` events become ``delta`` here, and its single
    ``done`` event supplies the stored response.
    """

    kind: Literal["delta", "done"]
    text: str
    # Final done event only: {"deep_reasoning", "tier", "route"} (P2-42).
    meta: dict[str, Any] | None = None


class SystemState(str, Enum):
    """High-level system state for Sleep/Wake cycle management."""

    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    DREAMING = "DREAMING"
    SLEEPING = "SLEEPING"


class _AppraisalHandle:
    """Per-turn state for the parallel appraisal (P2-05)."""

    def __init__(self) -> None:
        self.task: "asyncio.Task | None" = None
        self.handed_off = False


class Orchestrator:
    """
    Meta-cognitive orchestrator coordinating all cognitive engines.

    Based on Cognitive PRD OR-001 through OR-004.
    """

    def __init__(
        self,
        emotion_engine: EmotionEngine,
        learning_engine: LearningEngine,
        identity_engine: IdentityEngine,
        goal_engine: GoalEngine,
        reflection_engine: ReflectionEngine,
        message_bus: MessageBus,
        llm_layers: LLMLayers,
    ):
        """
        Initialize orchestrator.

        Args:
            emotion_engine: Emotion engine instance
            learning_engine: Learning engine instance
            identity_engine: Identity engine instance
            goal_engine: Goal engine instance
            reflection_engine: Reflection engine instance
            message_bus: Message bus for inter-engine communication
            llm_layers: LLM layer manager
        """
        self.emotion_engine = emotion_engine
        self.learning_engine = learning_engine
        self.identity_engine = identity_engine
        self.goal_engine = goal_engine
        self.reflection_engine = reflection_engine
        self.message_bus = message_bus
        self.llm_layers = llm_layers

        # Database (for system journal persistence)
        self.db = get_db_client()
        
        # Tool executor for executing tool calls
        self.tool_executor = ToolExecutor()
        self.tool_executor.set_llm_layers(self.llm_layers)  # L5 self-healing
        
        # Critique buffer for self-correction
        self.critique_buffer: dict[str, list[str]] = {} # user_id -> [critiques]
        
        # Cache for last system prompt per user (for debugging)
        self._last_system_prompt: dict[str, str] = {}  # user_id -> system_prompt

        self.logger = logging.getLogger("aura.orchestrator")

        # =========================================================================
        # System State Machine (Sleep/Wake Cycle)
        # =========================================================================
        self.system_state: SystemState = SystemState.ACTIVE
        self.state_updated_at: datetime = datetime.utcnow()
        self.last_user_interaction: datetime = datetime.utcnow()
        self.last_active_user_id: str = "default"
        self.session_started_at: datetime = datetime.utcnow()

        self._state_lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._idle_loop_task: asyncio.Task | None = None
        self._dream_task: asyncio.Task | None = None

        # Start the idle checker loop if we're running inside an event loop (normal FastAPI lifespan).
        # If constructed in a non-async context (e.g., tests), the caller can start it manually.
        try:
            asyncio.get_running_loop()
            self._idle_loop_task = asyncio.create_task(
                self._check_idle_state_loop(),
                name="orchestrator:check_idle_state",
            )
            self.logger.info(
                "System State Machine initialized (idle_after=%sm, dream_after=%sm, wake_word=%r, auto_wake=%s)",
                settings.system_idle_after_minutes,
                settings.system_dream_after_minutes,
                settings.system_wake_word,
                settings.system_auto_wake_on_query,
            )
        except RuntimeError:
            self.logger.warning(
                "System State Machine not started (no running event loop). "
                "If needed, call `await orchestrator.start_state_machine()`."
            )

    # =========================================================================
    # System State Machine API
    # =========================================================================

    async def start_state_machine(self) -> None:
        """Start the background idle checker loop (if not already running)."""
        async with self._state_lock:
            if self._idle_loop_task and not self._idle_loop_task.done():
                return
            self._shutdown_event.clear()
            self._idle_loop_task = asyncio.create_task(
                self._check_idle_state_loop(),
                name="orchestrator:check_idle_state",
            )

    async def stop_state_machine(self) -> None:
        """Stop background tasks related to the state machine."""
        self._shutdown_event.set()

        # Cancel idle loop
        if self._idle_loop_task and not self._idle_loop_task.done():
            self._idle_loop_task.cancel()
            try:
                await self._idle_loop_task
            except asyncio.CancelledError:
                pass

        # Cancel dreaming task
        if self._dream_task and not self._dream_task.done():
            self._dream_task.cancel()
            try:
                await self._dream_task
            except asyncio.CancelledError:
                pass

    async def get_system_state(self) -> dict[str, Any]:
        """Get current system state (safe for API responses)."""
        async with self._state_lock:
            return {
                "state": self.system_state.value,
                "state_updated_at": self.state_updated_at.isoformat(),
                "last_user_interaction": self.last_user_interaction.isoformat(),
                "last_active_user_id": self.last_active_user_id,
                "session_started_at": self.session_started_at.isoformat(),
                "idle_after_minutes": settings.system_idle_after_minutes,
                "dream_after_minutes": settings.system_dream_after_minutes,
                "wake_word": settings.system_wake_word,
                "auto_wake_on_query": settings.system_auto_wake_on_query,
                "dreaming_task_running": bool(
                    self._dream_task and not self._dream_task.done()
                ),
            }

    async def enter_sleep_mode(self, user_id: str | None = None, forced: bool = False) -> dict[str, Any]:
        """
        Trigger DREAMING -> SLEEPING sequence.

        This runs:
        A) learning_engine.consolidate_memory(user_id)
        B) L2 Journal entry generation
        C) Persist journal entry to SurrealDB (system_journal)
        D) Transition to SLEEPING
        """
        target_user = user_id or self.last_active_user_id or "default"
        dream_task = await self._begin_dreaming_sequence(target_user, forced=forced)
        if dream_task:
            await dream_task
        return await self.get_system_state()

    async def wake_up(self, user_id: str | None = None, forced: bool = False) -> str:
        """
        Wake the system to ACTIVE and generate a greeting based on last journal entry.
        """
        target_user = user_id or self.last_active_user_id or "default"

        now = datetime.utcnow()
        async with self._state_lock:
            # Cancel any in-progress dream task if we are forced awake
            if forced and self._dream_task and not self._dream_task.done():
                self._dream_task.cancel()

            self.system_state = SystemState.ACTIVE
            self.state_updated_at = now
            self.session_started_at = now
            self.last_user_interaction = now
            self.last_active_user_id = target_user

        last_journal = await self._fetch_last_journal_entry(target_user)
        greeting = await self._generate_wake_greeting(target_user, last_journal)
        return greeting

    # =========================================================================
    # Internals: state transitions / loops
    # =========================================================================

    async def _check_idle_state_loop(self) -> None:
        """Background loop that checks idle time every minute."""
        try:
            while not self._shutdown_event.is_set():
                await asyncio.sleep(60)
                await self.check_idle_state()
        except asyncio.CancelledError:
            return
        except Exception as e:
            self.logger.error(f"Idle state loop crashed: {e}", exc_info=True)

    async def check_idle_state(self) -> None:
        """
        Check last_user_interaction and transition:
        - ACTIVE -> IDLE after idle_after_minutes
        - (ACTIVE/IDLE) -> DREAMING -> SLEEPING after dream_after_minutes
        """
        now = datetime.utcnow()
        elapsed_minutes = (now - self.last_user_interaction).total_seconds() / 60.0

        # Snapshot state under lock to avoid races with wake/sleep triggers
        async with self._state_lock:
            current_state = self.system_state

        # Don't auto-transition further while sleeping/dreaming (explicit wake required).
        if current_state in (SystemState.SLEEPING, SystemState.DREAMING):
            return

        if elapsed_minutes >= settings.system_dream_after_minutes:
            # Enter dreaming in the background to keep the idle loop responsive.
            await self._begin_dreaming_sequence(self.last_active_user_id or "default", forced=False)
            return

        if elapsed_minutes >= settings.system_idle_after_minutes and current_state == SystemState.ACTIVE:
            async with self._state_lock:
                # Re-check inside lock
                if self.system_state == SystemState.ACTIVE:
                    self.system_state = SystemState.IDLE
                    self.state_updated_at = now
                    self.logger.info(
                        "System transitioned to IDLE (elapsed=%.1fm, threshold=%sm)",
                        elapsed_minutes,
                        settings.system_idle_after_minutes,
                    )

    async def _begin_dreaming_sequence(self, user_id: str, forced: bool) -> asyncio.Task | None:
        """Ensure a single dreaming task is running; return it."""
        async with self._state_lock:
            if self.system_state == SystemState.SLEEPING:
                return None

            if self._dream_task and not self._dream_task.done():
                return self._dream_task

            # Transition to DREAMING immediately
            self.system_state = SystemState.DREAMING
            self.state_updated_at = datetime.utcnow()
            self.last_active_user_id = user_id

            self._dream_task = asyncio.create_task(
                self._dreaming_sequence(user_id=user_id, forced=forced),
                name="orchestrator:dreaming_sequence",
            )
            self.logger.info("System entered DREAMING (user_id=%s, forced=%s)", user_id, forced)
            return self._dream_task

    async def _dreaming_sequence(self, user_id: str, forced: bool) -> None:
        """Implements DREAMING -> SLEEPING sequence."""
        session_end = datetime.utcnow()
        # Snapshot session_started_at under lock to avoid race with wake_up()
        async with self._state_lock:
            session_start_snapshot = self.session_started_at
        journal_id: str | None = None
        was_cancelled = False
        try:
            # Step A: consolidate memory
            await self.learning_engine.consolidate_memory(user_id)

            # Step B: generate journal (L2)
            journal_text, journal_meta = await self._generate_journal_entry(user_id=user_id)

            # Step C: persist journal
            journal_id = await self._store_journal_entry(
                user_id=user_id,
                entry=journal_text,
                session_start=session_start_snapshot,
                session_end=session_end,
                metadata=journal_meta,
            )
            from aura.orchestrator import workspace as _workspace

            _workspace.fire_event("dream_completed", {"journal_id": str(journal_id)})

        except asyncio.CancelledError:
            was_cancelled = True
            self.logger.info("Dreaming sequence cancelled (user_id=%s)", user_id)
            raise
        except Exception as e:
            self.logger.error(f"Dreaming sequence failed: {e}", exc_info=True)
        finally:
            # If the dream task was cancelled (e.g., forced wake), do NOT override state.
            # Guard with was_cancelled flag instead of 'return' (forbidden in finally blocks).
            if not was_cancelled:
                # Step D: transition to SLEEPING (even if dreaming failed; sleeping is the low-power goal)
                async with self._state_lock:
                    self.system_state = SystemState.SLEEPING
                    self.state_updated_at = datetime.utcnow()
                self.logger.info(
                    "System entered SLEEPING (user_id=%s, journal_id=%s)",
                    user_id,
                    journal_id,
                )

    async def _record_user_interaction(self, user_id: str) -> None:
        """Update timestamps and ensure ACTIVE when user interacts."""
        now = datetime.utcnow()
        async with self._state_lock:
            self.last_user_interaction = now
            self.last_active_user_id = user_id
            if self.system_state == SystemState.IDLE:
                self.system_state = SystemState.ACTIVE
                self.state_updated_at = now

        # Keep GoalEngine's interaction timestamp updated (it drives boredom/autonomy logic).
        try:
            self.goal_engine.record_user_interaction()
        except Exception:
            # Non-critical: do not break query processing if goal engine is unavailable.
            pass

    async def _sleep_gate(self, user_input: str, user_id: str) -> tuple[bool, str | None]:
        """
        Enforce SLEEPING/DREAMING behavior:
        - If sleeping: reject unless wake-word present OR auto-wake enabled.
        - If dreaming: reject unless wake-word present OR auto-wake enabled (forced wake cancels dreaming).
        """
        text = (user_input or "").lower()
        wake_word = (settings.system_wake_word or "").strip().lower()
        has_wake_word = bool(wake_word) and wake_word in text

        async with self._state_lock:
            current_state = self.system_state

        if current_state == SystemState.SLEEPING:
            if settings.system_auto_wake_on_query or has_wake_word:
                await self.wake_up(user_id=user_id, forced=True)
                return True, None
            return False, "System is sleeping (zero-inference mode). Send the wake word or use the Wake button."

        if current_state == SystemState.DREAMING:
            if settings.system_auto_wake_on_query or has_wake_word:
                await self.wake_up(user_id=user_id, forced=True)
                return True, None
            return False, "System is dreaming (consolidating memory). Please wait or wake the system."

        return True, None

    # =========================================================================
    # Internals: journal generation / persistence
    # =========================================================================

    async def _generate_journal_entry(self, user_id: str) -> tuple[str, dict[str, Any]]:
        """Use L2 to generate a 1-paragraph introspective journal entry."""
        # Pull a compact view of recent insights and experiences as journal inputs
        insights = await self.db.query(
            """
            SELECT id, content, type, confidence, user_id, created_at
            FROM insight
            WHERE user_id = $user_id
            ORDER BY created_at DESC
            LIMIT 10
            """,
            {"user_id": user_id},
        )

        experiences = await self.db.query(
            """
            SELECT id, timestamp, task_type, domain, context
            FROM experience
            WHERE user_id = $user_id
            ORDER BY timestamp DESC
            LIMIT 10
            """,
            {"user_id": user_id},
        )

        insight_lines: list[str] = []
        insight_ids: list[str] = []
        for row in insights or []:
            rid = row.get("id")
            if rid is not None:
                insight_ids.append(str(rid))
            content = (row.get("content") or "").strip()
            itype = row.get("type") or "PATTERN"
            conf = row.get("confidence", 0.5)
            if content:
                insight_lines.append(f"- [{itype} | {conf:.2f}] {content}")

        exp_lines: list[str] = []
        exp_ids: list[str] = []
        for row in experiences or []:
            rid = row.get("id")
            if rid is not None:
                exp_ids.append(str(rid))
            ts = row.get("timestamp")
            task_type = row.get("task_type", "conversation")
            domain = row.get("domain", "general")
            ctx = row.get("context") or {}
            user_query = ""
            if isinstance(ctx, dict):
                user_query = (ctx.get("user_query") or ctx.get("source") or ctx.get("prompt") or "")[:200]
            if user_query:
                exp_lines.append(f"- [{task_type}/{domain}] {user_query}")

        prompt = f"""Review the new insights created this session. Write a short 1-paragraph internal journal entry summarizing what you learned about the user and the world. Be introspective.

RECENT INSIGHTS (most recent first):
{chr(10).join(insight_lines) if insight_lines else "- (none)"}

RECENT INTERACTIONS (most recent first):
{chr(10).join(exp_lines) if exp_lines else "- (none)"}

Write only the journal entry paragraph (no title, no bullets).
"""

        messages = [
            {
                "role": "system",
                "content": "You are Aura's internal journaling module. Output a single concise paragraph.",
            },
            {"role": "user", "content": prompt},
        ]

        # Use active_l2_model (stack-aware) — journal should follow the active stack
        journal = await self.llm_layers.client.complete(
            messages=messages,
            model=settings.active_l2_model,
            temperature=0.5,
            max_tokens=220,
        )

        journal_text = (journal or "").strip()
        if not journal_text:
            journal_text = "Quiet session. I reviewed recent signals and prepared to continue learning on next wake."

        meta = {
            "insight_ids": insight_ids,
            "experience_ids": exp_ids,
            "insight_count": len(insight_ids),
            "experience_count": len(exp_ids),
        }
        return journal_text, meta

    async def _store_journal_entry(
        self,
        user_id: str,
        entry: str,
        session_start: datetime,
        session_end: datetime,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Persist journal entry to SurrealDB `system_journal` table."""
        journal_id = f"system_journal:{uuid4().hex[:12]}"
        data = {
            "user_id": user_id,
            "created": datetime.utcnow(),
            "entry": entry,
            "session_start": session_start,
            "session_end": session_end,
            "metadata": metadata or {},
        }
        await self.db.create(journal_id, data)
        return journal_id

    async def _fetch_last_journal_entry(self, user_id: str) -> dict[str, Any] | None:
        """Fetch most recent journal entry for a user."""
        result = await self.db.query(
            """
            SELECT *
            FROM system_journal
            WHERE user_id = $user_id
            ORDER BY created DESC
            LIMIT 1
            """,
            {"user_id": user_id},
        )
        if result and len(result) > 0:
            return result[0]
        return None

    async def _generate_wake_greeting(self, user_id: str, last_journal: dict[str, Any] | None) -> str:
        """Generate a wake greeting based on the last journal entry."""
        if not last_journal:
            return "System online. Ready for the next phase."

        entry = (last_journal.get("entry") or "").strip()
        if not entry:
            return "System online. Ready for the next phase."

        prompt = f"""You are waking up. Based on the internal journal entry below, generate a short greeting in 1 sentence.

JOURNAL ENTRY:
{entry}

Constraints:
- One sentence.
- Confident, system-like tone.
- Mention one concrete thing you integrated or noticed.
"""
        messages = [
            {"role": "system", "content": "You are Aura's system boot greeter."},
            {"role": "user", "content": prompt},
        ]
        # Use active_l2_model (stack-aware) so wake greeting uses the active stack
        greeting = await self.llm_layers.client.complete(
            messages=messages,
            model=settings.active_l2_model,
            temperature=0.6,
            max_tokens=80,
        )
        greeting_text = (greeting or "").strip()
        return greeting_text or "System online. Ready for the next phase."

    # =========================================================================
    # Internals: turn preamble (session resolution + pre-intent commands)
    # =========================================================================

    async def _resolve_session(self, session_id: str | None) -> Any:
        """
        Resolve session → memory namespace + identity overlay (V1PRD §4).

        Caller may pass session_id=None for backward compatibility; that
        routes to MAIN, and namespace stays None → retrieval reads everything.
        """
        session_namespace: str | None = None
        session_overlay = None
        session_ctx = None
        if session_id and session_id != "main":
            try:
                from aura.orchestrator.session_runtime import get_session_runtime
                ctx = await get_session_runtime().context_for(session_id)
                session_namespace = (
                    ctx.memory_namespace if ctx.memory_namespace != "global" else None
                )
                session_overlay = ctx.identity_overlay
                session_ctx = ctx
            except Exception as e:  # noqa: BLE001
                self.logger.warning(f"Could not resolve session {session_id!r}: {e}")
        self._current_session_namespace = session_namespace
        self._current_identity_overlay = session_overlay
        self._current_session_context = session_ctx
        # Returned so a turn keeps its own context: the attributes above are
        # shared by concurrent turns and may be overwritten across awaits.
        return session_ctx

    @staticmethod
    def _session_excluded_tools(session: Any) -> set[str]:
        """Names of registered tools the session does not allow (G4-04a)."""
        if session is None or (session.tool_allowlist is None and not session.tool_denylist):
            return set()
        return {
            r.name for r in get_tool_registry().all()
            if not session.is_tool_allowed(r.name)[0]
        }

    async def _select_skills(
        self, ctx: "TurnContext", user_input: str, requester_role: str, profile: Any
    ) -> None:
        """Fill ``ctx.skill_*`` and ``ctx.chosen_skills`` (G5-05). Never fails the turn.

        The recall engine keeps its embedding private, so the request is embedded
        once here (timeout ``skill_embed_timeout_ms``; on timeout no skill). The
        tool filter is the tier's gated tools plus the session's allow/denylist.
        """
        from aura.engines.learning.skill_index import select_for_turn, selection_enabled

        if not selection_enabled() or requester_role != "owner":
            return
        try:
            import random

            from aura.engines.learning.skill_store import SkillStore
            from aura.llm.embeddings import get_embeddings_client

            denied = gated_tools_denied(profile) if profile else set()
            session = ctx.session

            def tool_allowed(name: str) -> bool:
                if name in denied:
                    return False
                return session is None or session.is_tool_allowed(name)[0]

            result = await select_for_turn(
                SkillStore(self.db),
                user_input,
                requester_role,
                random.Random(),
                embed=get_embeddings_client().embed,
                tool_allowed=tool_allowed,
            )
            ctx.skill_index = result.index_text or None
            ctx.skill_body = result.body or None
            ctx.skill_name = result.chosen_name
            if result.chosen is not None:
                ctx.chosen_skills.append(result.chosen)
            sc = ctx.synthesis_context
            sc.skill_index, sc.skill_body, sc.skill_name = (
                ctx.skill_index, ctx.skill_body, ctx.skill_name,
            )
        except Exception as e:
            self.logger.warning(f"Skill selection failed (non-critical): {e}")

    async def _pre_intent_reply(self, user_input: str, user_id: str) -> str | None:
        """
        Handle sleep gating and system commands that bypass intent classification.

        Returns the reply string when the turn should end here, or None when the
        turn should continue to intent classification.
        """
        # Enforce system sleep/dreaming gating before any LLM work.
        allowed, blocked_msg = await self._sleep_gate(user_input=user_input, user_id=user_id)
        if not allowed:
            return blocked_msg or "System unavailable."

        # Record interaction (updates last_user_interaction and exits IDLE if needed).
        await self._record_user_interaction(user_id)

        # --- PRIORITY 0: System Commands (bypass intent classification) ---
        # Check for system command: "System: Connect MCP <server_name> <url|command...>"
        # This must happen BEFORE intent classification to ensure it's always detected
        import re
        connect_match = re.search(
            r"system:\s*connect\s+mcp\s+(\w+)\s+(.+)",
            user_input,
            re.IGNORECASE,
        )
        if connect_match:
            server_name = connect_match.group(1)
            target = (connect_match.group(2) or "").strip()
            if not target:
                return "❌ Usage: `System: Connect MCP <server_name> <url|command...>`"

            # Build connection config (stored into skills for reconnects)
            connection_config: dict[str, Any]
            if target.lower().startswith(("http://", "https://")):
                # Prefer streamable HTTP; allow SSE paths by hinting transport.
                transport = "sse" if "/sse" in target.lower() else "streamable_http"
                connection_config = {"transport": transport, "url": target, "timeout_s": 15, "server": server_name}
            else:
                import os
                import shlex

                # Prefer Windows-safe parsing on Windows; POSIX parsing elsewhere.
                posix_default = os.name != "nt"
                try:
                    parts = shlex.split(target, posix=posix_default)
                except Exception:
                    parts = shlex.split(target, posix=(not posix_default))

                if not parts:
                    return "❌ Could not parse command. Try quoting paths with spaces."
                connection_config = {
                    "transport": "stdio",
                    "command": parts[0],
                    "args": parts[1:],
                    "timeout_s": 15,
                    "server": server_name,
                }

            self.logger.info(f"[PLUG] System command detected: Connect MCP '{server_name}'")
            try:
                result = await self.learning_engine.ingest_mcp_server(server_name, connection_config)
                return f"✅ {result}"
            except Exception as e:
                self.logger.error(f"Failed to connect MCP server '{server_name}': {e}", exc_info=True)
                return f"❌ Failed to connect MCP server '{server_name}': {str(e)}"

        # Check for system command: "System: Ingest tool <name>"
        # This must happen BEFORE intent classification to ensure it's always detected
        ingest_match = re.search(r'system:\s*ingest\s+tool\s+(\w+)', user_input, re.IGNORECASE)
        if ingest_match:
            tool_name = ingest_match.group(1)
            self.logger.info(f"[WRENCH] System command detected: Ingest tool '{tool_name}'")
            try:
                result = await self.learning_engine.ingest_local_tool_module(tool_name)
                return f"✅ {result} The tool is now registered and available for use (semantic triggers will be ready shortly)."
            except Exception as e:
                self.logger.error(f"Failed to ingest tool '{tool_name}': {e}", exc_info=True)
                return f"❌ Failed to ingest tool '{tool_name}': {str(e)}"

        # --- PRIORITY 0.5: Direct Learning Command (God Mode) ---
        # Intercept "Aura learn: ..." / "learn this: ..." to force Fact ingestion instead of Skill compilation.
        # This must happen BEFORE intent classification to ensure it's always detected.
        learn_match = re.search(
            r'(?:aura\s+)?learn(?:\s+this)?\s*:\s*(.+)',
            user_input,
            re.IGNORECASE,
        )
        if learn_match:
            content_to_learn = (learn_match.group(1) or "").strip()
            if not content_to_learn:
                return "❌ I didn’t find any content after `learn:`. Try: `Aura learn: <fact>`."

            self.logger.info(
                "[BRAIN] Direct learning command detected: forcing direct_instruction (content_len=%s)",
                len(content_to_learn),
            )
            try:
                await self.learning_engine.log_experience(
                    {
                        "user_id": user_id,
                        "task_type": "direct_instruction",  # CRITICAL: triggers Route A in Learning Engine
                        "domain": "user_defined",
                        "context": {"user_query": user_input, "source": content_to_learn},
                        "metadata": {
                            "forced_insight": {
                                "content": content_to_learn,
                                "type": "FACT",
                                "confidence": 1.0,
                            }
                        },
                    }
                )

                return (
                    f"✅ Understood. I have committed this to memory as a Fact: '{content_to_learn}'."
                )
            except Exception as e:
                self.logger.error(
                    f"Failed to execute direct learning: {e}", exc_info=True
                )
                return f"❌ Memory write failed: {str(e)}"

        return None

    async def _classify_intent(
        self, user_input: str, user_id: str, stream: bool, speaker: str = "owner"
    ) -> tuple[dict[str, Any], str, str | None]:
        """
        L1 intent classification, telemetry, and the teaching fast lane.
        Returns ``(intent_data, intent, teaching_reply)``.
        ``teaching_reply`` is the teaching string when L1 routes to TEACHING
        (and ``log_experience`` has been called), otherwise ``None``.
        ``stream`` controls only whether the L1 trace payload carries
        ``"mode": "stream"``; both entry points share the rest verbatim.
        """
        # --- CHANGE 1: THE GATEKEEPER ---
        # Call the new L1 classifier
        intent_data = await self.llm_layers.l1_classify_intent(user_input)
        intent = intent_data.get("intent", "CHAT")
        # --- Telemetry: L1 routing decision ---
        trace_payload: dict[str, Any] = {
            "intent": intent,
            "confidence": round(float(intent_data.get("confidence") or 0), 3),
            "model": settings.active_l1_model,
        }
        if settings.l1_routes_enabled:
            trace_payload["route"] = intent_data.get("route", "chat")
            trace_payload["stakes"] = intent_data.get("stakes", 0.0)
        if stream:
            trace_payload["mode"] = "stream"
        self._publish_trace("L1", "intent_classified", trace_payload)

        # 1. TEACHING FAST LANE (Existing)
        if intent == "TEACHING":
            self.logger.info("[BRAIN] L1 detected Teaching Intent - Routing to Learning Engine")

            # Create a "Teaching Experience"
            experience_data = {
                "user_id": user_id,
                "task_type": "instruction",  # Matches the fix we made in Learning Engine
                "domain": "coding",  # Or infer from L1
                "context": {"user_query": user_input},
                "metadata": {"intent": "teaching", "speaker": speaker},
            }

            # Send directly to Learning Engine (The "Fast Lane" we discussed)
            await self.learning_engine.log_experience(experience_data)

            return intent_data, intent, "I've processed that instruction. I'm analyzing the schema and adding it to my skills now."

        return intent_data, intent, None

    async def _resolve_forced_tool(
        self, intent: str, intent_data: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """
        Tool-reflex fast lane: resolve a TOOL_USE intent to a forced tool
        schema. Returns ``(use_forced_tool_mode, tool_schema_str)``.

        Looks the skill up by ``target_skill_id`` first, then by
        ``detected_tool`` name (three parameterised ``SELECT * FROM skill``
        queries), then falls back to loading the tool definition from a file
        and registering it via ``ingest_local_tool_module``.
        """
        if intent_data.get("routing_method") != "vector_search":
            return False, None

        target_skill_id = intent_data.get("target_action")
        # L1/L5 sometimes returns a descriptive label here (e.g. "stock_price_analysis")
        # instead of an actual Surreal record id. Only treat it as an id if it looks like one.
        if isinstance(target_skill_id, str) and ":" not in target_skill_id:
            target_skill_id = None

        # Track if we need to use forced tool call mode
        use_forced_tool_mode = False
        tool_schema_str = None

        self.logger.info(f"[MAG] Intent detection result: intent={intent}, target_skill_id={target_skill_id}, detected_tool={intent_data.get('detected_tool')}, confidence={intent_data.get('confidence', 'N/A')}")

        if intent == "TOOL_USE":
            # Try target_skill_id first, but if it fails or doesn't exist, use detected_tool
            skill_found = False

            if target_skill_id:
                self.logger.info(f"⚡ L1 detected TOOL_USE intent with target_skill_id: {target_skill_id}")

                # Fetch the specific skill definition for forced tool call mode
                try:
                    skill_record = await self.learning_engine.get_skill(target_skill_id)
                    if skill_record:
                        self.logger.info(f"[CLIPBOARD] Found skill record: {skill_record.name}")
                        # Get the full skill record from database
                        skill_data = await self.learning_engine.db.select(target_skill_id)
                        if skill_data and len(skill_data) > 0:
                            skill_full = skill_data[0]

                            # Build tool definition for forced JSON mode
                            tool_definition = skill_full.get("definition")

                            # Check if definition exists and is not empty
                            has_definition = tool_definition is not None and (
                                (isinstance(tool_definition, dict) and len(tool_definition) > 0) or
                                (isinstance(tool_definition, list) and len(tool_definition) > 0) or
                                (not isinstance(tool_definition, (dict, list)) and tool_definition)
                            )

                            if has_definition:
                                # Format as JSON string for tool schema
                                tool_schema_str = json.dumps(tool_definition, indent=2)

                                use_forced_tool_mode = True
                                skill_found = True
                                self.logger.info(f"✅ Prepared forced tool call mode for {skill_record.name}")
                                self.logger.debug(f"Tool schema: {tool_schema_str[:200]}...")
                            else:
                                self.logger.warning(
                                    f"⚠️ Skill {target_skill_id} has no valid definition field "
                                    f"(got: {type(tool_definition).__name__}, value: {tool_definition})"
                                )
                        else:
                            self.logger.warning(f"⚠️ Skill {target_skill_id} found but no full data available in database")
                    else:
                        self.logger.warning(f"⚠️ Skill record not found for ID: {target_skill_id}")
                except Exception as e:
                    self.logger.warning(f"⚠️ Failed to fetch skill by ID '{target_skill_id}': {e}")

            # FALLBACK: If target_skill_id lookup failed or doesn't exist, try detected_tool
            if not skill_found:
                detected_tool = intent_data.get("detected_tool")
                if detected_tool:
                    self.logger.info(f"[MAG] Fallback: Attempting to find skill by name: {detected_tool}")
                    try:
                        # Try to find skill by name (case-insensitive, handle spaces/underscores)
                        # Normalize: "web_search" -> "web search", "Web Search" -> "web search"
                        normalized_tool = detected_tool.replace("_", " ").lower()

                        # Try exact match first
                        skill_query = await self.learning_engine.db.query(
                            "SELECT * FROM skill WHERE name = $name LIMIT 1",
                            {"name": detected_tool}
                        )

                        # If not found, try case-insensitive match
                        if not skill_query or len(skill_query) == 0:
                            skill_query = await self.learning_engine.db.query(
                                "SELECT * FROM skill WHERE string::lowercase(name) = $normalized LIMIT 1",
                                {"normalized": normalized_tool}
                            )

                        # If still not found, try matching with spaces/underscores normalized
                        if not skill_query or len(skill_query) == 0:
                            # Try replacing spaces with underscores and vice versa
                            alt_name1 = detected_tool.replace("_", " ")
                            alt_name2 = detected_tool.replace(" ", "_")
                            skill_query = await self.learning_engine.db.query(
                                "SELECT * FROM skill WHERE string::lowercase(name) = string::lowercase($alt1) OR string::lowercase(name) = string::lowercase($alt2) LIMIT 1",
                                {"alt1": alt_name1, "alt2": alt_name2}
                            )
                        if skill_query and len(skill_query) > 0:
                            skill_record = skill_query[0]
                            target_skill_id = skill_record.get("id")
                            skill_name = skill_record.get("name", "unknown")
                            self.logger.info(f"✅ Found skill by name: '{detected_tool}' matched '{skill_name}' -> {target_skill_id}")

                            if len(skill_query) > 1:
                                self.logger.warning(f"⚠️ Multiple skills found for '{detected_tool}', using first match: {skill_name}")

                            # Now fetch full skill data
                            skill_data = await self.learning_engine.db.select(target_skill_id)
                            if skill_data and len(skill_data) > 0:
                                skill_full = skill_data[0]
                                tool_definition = skill_full.get("definition")

                                # Check if definition exists and is not empty (could be dict, list, or other truthy value)
                                # An empty dict {} is falsy, so we need to check explicitly
                                has_definition = tool_definition is not None and (
                                    (isinstance(tool_definition, dict) and len(tool_definition) > 0) or
                                    (isinstance(tool_definition, list) and len(tool_definition) > 0) or
                                    (not isinstance(tool_definition, (dict, list)) and tool_definition)
                                )

                                if has_definition:
                                    tool_schema_str = json.dumps(tool_definition, indent=2)
                                    use_forced_tool_mode = True
                                    skill_found = True  # CRITICAL: Mark as found so we don't try file fallback
                                    self.logger.info(f"✅ Prepared forced tool call mode for {detected_tool} (found by name, has definition)")
                                else:
                                    # Skill exists but has no definition - might be abstract skill
                                    # Log what we actually got for debugging
                                    self.logger.warning(
                                        f"⚠️ Skill '{detected_tool}' found but has no valid definition field "
                                        f"(got: {type(tool_definition).__name__}, value: {tool_definition}) - will try file fallback"
                                    )
                    except Exception as e:
                        self.logger.warning(f"⚠️ Failed to find skill by name '{detected_tool}': {e}")

                # FINAL FALLBACK: If skill not in DB, try to load tool definition directly from file
                if not skill_found and detected_tool:
                    self.logger.info(f"[WRENCH] Final fallback: Loading tool definition directly from file: {detected_tool}")
                    try:
                        import importlib.util
                        import os

                        # Find the tool file - try multiple paths
                        # In Docker: /app/src/aura/tools/web_search.py
                        # Local dev: relative from coordinator.py
                        possible_paths = [
                            os.path.join("/app", "src", "aura", "tools", f"{detected_tool}.py"),  # Docker path
                        ]

                        # Also try relative path
                        current_file_dir = os.path.dirname(os.path.abspath(__file__))
                        aura_root = os.path.dirname(os.path.dirname(current_file_dir))
                        tools_dir = os.path.join(aura_root, "tools")
                        possible_paths.append(os.path.join(tools_dir, f"{detected_tool}.py"))

                        file_path = None
                        for path in possible_paths:
                            if os.path.exists(path):
                                file_path = path
                                self.logger.info(f"✅ Found tool file at: {file_path}")
                                break

                        if file_path and os.path.exists(file_path):
                            spec = importlib.util.spec_from_file_location(
                                f"aura.tools.{detected_tool}",
                                file_path
                            )
                            module = importlib.util.module_from_spec(spec)
                            spec.loader.exec_module(module)

                            if hasattr(module, "TOOL_DEFINITION"):
                                tool_def = module.TOOL_DEFINITION
                                # Convert to the format expected by forced tool mode
                                tool_definition = {
                                    "name": tool_def.get("name"),
                                    "description": tool_def.get("description"),
                                    "parameters": tool_def.get("parameters", {})
                                }

                                tool_schema_str = json.dumps(tool_definition, indent=2)
                                use_forced_tool_mode = True
                                skill_found = True
                                self.logger.info(f"✅ Loaded tool definition directly from file: {detected_tool}")

                                # Optionally register it as a skill for future use (async, non-blocking)
                                try:
                                    await self.learning_engine.ingest_local_tool_module(detected_tool)
                                    self.logger.info(f"✅ Registered {detected_tool} as skill for future use")
                                except Exception as reg_error:
                                    self.logger.warning(f"⚠️ Failed to register {detected_tool} as skill (non-critical): {reg_error}")
                            else:
                                self.logger.warning(f"⚠️ Tool file {file_path} exists but has no TOOL_DEFINITION")
                        else:
                            self.logger.warning(f"⚠️ Tool file not found: {file_path}")
                    except Exception as e:
                        self.logger.error(f"❌ Failed to load tool definition from file '{detected_tool}': {e}", exc_info=True)
                elif not detected_tool:
                    # Only warn when detected_tool is actually missing; don't warn when we already found a skill.
                    self.logger.warning(f"⚠️ TOOL_USE intent detected but no detected_tool provided. Intent data: {intent_data}")

        return use_forced_tool_mode, tool_schema_str

    async def _cache_system_prompt(
        self,
        synthesis_context: SynthesisContext,
        user_input: str,
        user_id: str,
    ) -> None:
        """Build and cache the L3 system prompt for debugging (before calling synthesis)."""
        try:
            # W2-20: the cached prompt shows the Recall packet's memories.
            relevant_memories = (
                synthesis_context.packet.block_text("memories")
                if getattr(synthesis_context, "packet", None)
                else None
            )

            # Build and cache the system prompt
            system_prompt = self.llm_layers.build_l3_system_prompt(
                synthesis_context,
                relevant_memories=relevant_memories
            )
            self._last_system_prompt[user_id] = system_prompt
        except Exception as e:
            self.logger.warning(f"Failed to cache system prompt: {e}")

    def _schedule_post_response(
        self,
        *,
        user_input: str,
        response: str,
        emotional_before: EmotionState,
        user_id: str,
        conversation_id: str | None,
        goal_context: Any,
        learning_context: Any,
        enable_l2: bool,
        l2_reasoning_enabled: bool,
        resonance_score: float,
        conversation_history: list[dict[str, str]] | None = None,
        venue: str = "app",
        speaker: str = "owner",
        packet: ContextPacket | None = None,
        appraisal_task: "asyncio.Task | None" = None,
        chosen_skills: list | None = None,
        turn_tools: list[str] | None = None,
    ) -> None:
        """Schedule the post-response chain in the background (never awaited here)."""
        asyncio.create_task(self._post_response_chain(
            user_input=user_input,
            response=response,
            emotional_before=emotional_before,
            user_id=user_id,
            conversation_id=conversation_id,
            goal_context=goal_context,
            learning_context=learning_context,
            enable_l2=enable_l2,
            l2_reasoning_enabled=l2_reasoning_enabled,
            resonance_score=resonance_score,
            conversation_history=conversation_history,
            venue=venue,
            speaker=speaker,
            packet=packet,
            # Only passed when a parallel appraisal exists; flag off is unchanged.
            **({"appraisal_task": appraisal_task} if appraisal_task is not None else {}),
            # Only passed when a skill was chosen for the turn (G5-04).
            **(
                {"chosen_skills": list(chosen_skills), "turn_tools": list(turn_tools or [])}
                if chosen_skills
                else {}
            ),
        ))

    def _parallel_appraisal_active(self) -> bool:
        return bool(
            settings.appraisal_parallel_enabled
            and settings.emotion_appraisal_enabled
            and settings.layer_l4_enabled
        )

    def _start_background_appraisal(self, **kwargs: Any) -> "asyncio.Task":
        """Start one appraisal task and keep a strong reference until it ends (P2-05)."""
        tasks = self.__dict__.setdefault("_appraisal_tasks", set())
        task = asyncio.create_task(self._appraise_message(**kwargs))
        tasks.add(task)

        def _done(t: "asyncio.Task") -> None:
            tasks.discard(t)
            if not t.cancelled() and t.exception() is not None:
                self.logger.warning(f"Parallel appraisal task failed: {t.exception()}")

        task.add_done_callback(_done)
        return task

    async def _working_set_offer(
        self, user_id: str, user_input: str, requester_role: str, venue: str
    ) -> list[tuple[str, str]]:
        """B5-04: pending agenda items to offer inside this owner reply. Cheap, no
        model call; never raises into the turn."""
        from aura.autonomy import offer

        if not offer.enabled():
            return []
        try:
            return await offer.working_set_for_turn(user_id, user_input, requester_role, venue)
        except Exception as e:  # noqa: BLE001
            self.logger.debug(f"Working-set offer failed (non-critical): {e}")
            return []

    async def _gather_turn_context(
        self,
        user_input: str,
        user_id: str,
        conversation_history: list[dict[str, str]] | None,
        stream: bool,
        venue: str = "app",
        recall_token_budget: int | None = None,
        requester_role: str = "guest",
    ) -> TurnContext:
        """Gather engine context and assemble the L3 ``SynthesisContext`` (W2-08).

        ``stream=False`` mirrors ``process_query``'s sequential context
        gathering; ``stream=True`` mirrors ``stream_query``'s parallel
        ``asyncio.gather`` with a 10 s timeout and per-result fallbacks.
        """
        if not stream:
            # Step 1: Parallel engine queries
            emotional_state = await self.emotion_engine.get_current_state()

            learning_context = await self.learning_engine.get_learning_context(
                context=user_input,
                user_id=user_id,
            )

            identity_context = await self.identity_engine.get_identity_context(
                conversation_topic=user_input,
                overlay=getattr(self, "_current_identity_overlay", None),
            )

            goal_context = await self.goal_engine.get_goal_context()

            # Check if any goals would benefit from autonomous pursuit
            goals_needing_pursuit = await self.goal_engine.check_goals_needing_autonomous_pursuit()

            # If there are goals that need pursuit, add a hint to the goal context
            if goals_needing_pursuit:
                # Add pursuit suggestions to goal context
                pursuit_suggestions = []
                for goal in goals_needing_pursuit:
                    goal_created = goal.created
                    if goal_created.tzinfo is None:
                        goal_created = goal_created.replace(tzinfo=timezone.utc)
                    age_hours = (get_clock().now() - goal_created).total_seconds() / 3600

                    pursuit_suggestions.append({
                        "goal_id": goal.goal_id,
                        "goal_name": goal.name,
                        "reason": f"Priority: {goal.priority:.2f}, Progress: {goal.progress:.1%}, Age: {age_hours:.1f}h"
                    })

                # Update goal context with pursuit suggestions
                goal_context.pursuit_suggestions = pursuit_suggestions

            # Step 1.5: Compute Resonance Score (Emotion-Learning Bridge)
            resonance_score = self._compute_resonance_score(emotional_state)
            self.logger.info(f"[WAVE] Resonance score: {resonance_score:.2f}")

            # Step 2 & 3: Detect and resolve conflicts
            # For now, skip conflict detection (no competing signals yet)

            # Step 4: Synthesize context for L3
            history_count = len(conversation_history) if conversation_history else 0
            self.logger.info(f"[MEMO] Conversation history: {history_count} messages")
            if conversation_history and len(conversation_history) > 0:
                # Log last few messages for debugging
                last_messages = conversation_history[-3:]
                for i, msg in enumerate(last_messages):
                    role = msg.get('role', 'unknown')
                    content_preview = msg.get('content', '')[:60]
                    self.logger.debug(f"  [{i+1}] {role}: {content_preview}...")

            # Check buffer for recent critique (under lock to avoid race with L2 background task)
            async with self._state_lock:
                recent_critiques = self.critique_buffer.pop(user_id, [])
            recent_critique = "\n\n".join(recent_critiques) if recent_critiques else None

            # Recall Engine (M2, W2-20): one call assembles the insights, latent,
            # cold-start and memories blocks. Replaces the separate cold-start
            # and latent-intuition blocks and the per-round retrieval in L3.
            from aura.engines.recall.engine import get_recall_engine
            packet: ContextPacket | None = None
            working_set = await self._working_set_offer(user_id, user_input, requester_role, venue)
            try:
                packet = await get_recall_engine().recall(RecallRequest(
                    user_id=user_id,
                    user_input=user_input,
                    recent_turns=(conversation_history or [])[-6:],
                    emotional_state=emotional_state,
                    learning_context=learning_context,
                    depth=2,
                    limit=5,
                    namespace=None,
                    include_cold_start=True,
                    include_latent=True,
                    venue=venue,
                    token_budget=recall_token_budget,
                    working_set=working_set,
                ))
            except Exception as e:
                self.logger.warning(f"Recall engine failed (non-critical): {e}")
                packet = None

            cold_start_xml = packet.block_text("cold_start") if packet else None
            latent_intuition_xml = packet.block_text("latent") if packet else None
            ws = packet.block_text("working_set") if packet else None
            if ws:
                latent_intuition_xml = (
                    "\n".join([latent_intuition_xml, ws]) if latent_intuition_xml else ws
                )
            if packet is not None:
                self.logger.info(
                    f"[ICE] Recall packet: {packet.trace.tokens_after} tokens "
                    f"(before {packet.trace.tokens_before})"
                )
                self.logger.debug(
                    f"[BRAIN] MAC injected ({len(latent_intuition_xml or '')} chars)"
                )
                duplicate_count = sum(
                    1 for item in packet.trace.items if item.fate == "duplicate"
                )
                over_budget_count = sum(
                    1 for item in packet.trace.items if item.fate == "over_budget"
                )
                self._publish_trace("RECALL", "packet_built", {
                    "turn_id": packet.trace.turn_id,
                    "tokens_before": packet.trace.tokens_before,
                    "tokens_after": packet.trace.tokens_after,
                    "duplicates": duplicate_count,
                    "over_budget": over_budget_count,
                })

            synthesis_context = SynthesisContext(
                user_input=user_input,
                user_id=user_id,
                conversation_history=conversation_history or [],
                emotional_state=emotional_state,
                learning_context=learning_context,
                identity_context=identity_context,
                goal_context=goal_context,
                recent_critique=recent_critique,
                resonance_score=resonance_score,
                cold_start_xml=cold_start_xml,
                latent_intuition_xml=latent_intuition_xml,
                packet=packet,
                venue=venue,
            )

            return TurnContext(
                emotional_state=emotional_state,
                learning_context=learning_context,
                identity_context=identity_context,
                goal_context=goal_context,
                resonance_score=resonance_score,
                recent_critique=recent_critique,
                cold_start_xml=cold_start_xml,
                latent_intuition_xml=latent_intuition_xml,
                synthesis_context=synthesis_context,
                packet=packet,
            )

        # stream == True
        # Parallel engine queries with timeout protection
        import asyncio

        # Execute context retrievals in parallel with 10s timeout per engine
        try:
            results = await asyncio.wait_for(
                asyncio.gather(
                    self.emotion_engine.get_current_state(),
                    self.learning_engine.get_learning_context(context=user_input, user_id=user_id),
                    self.identity_engine.get_identity_context(
                        conversation_topic=user_input,
                        overlay=getattr(self, "_current_identity_overlay", None),
                    ),
                    self.goal_engine.get_goal_context(),
                    return_exceptions=True
                ),
                timeout=10.0  # 10 second total timeout for all parallel queries
            )
        except asyncio.TimeoutError:
            self.logger.error("Context retrieval timed out! Using fallback empty contexts.")
            # Use fallback empty contexts
            from aura.models.emotion import EmotionState, EmotionVector
            from aura.models.learning import LearningContext
            from aura.models.identity import IdentityContext
            from aura.models.goal import GoalContext

            results = [
                EmotionState(timestamp=get_clock().now().replace(tzinfo=None), vector=EmotionVector(), dominant=("neutral", 0.0), description="Neutral"),
                LearningContext(),
                IdentityContext(narrative="I am Aura.", core_values={}),
                GoalContext()
            ]

        # Unpack results, handling potential errors gracefully
        emotional_state = results[0] if not isinstance(results[0], Exception) else await self.emotion_engine.get_current_state() # fallback/retry?
        if isinstance(emotional_state, Exception): # Should not happen with get_current_state
             # Absolute fallback if emotion engine fails
             from aura.models.emotion import EmotionState, EmotionVector
             emotional_state = EmotionState(
                 timestamp=get_clock().now().replace(tzinfo=None),
                 vector=EmotionVector(),
                 dominant=("neutral", 0.0),
                 description="Neutral"
             )

        learning_context = results[1]
        if isinstance(learning_context, Exception):
            self.logger.error(f"Failed to get learning context: {learning_context}")
            # Fallback empty context
            from aura.models.learning import LearningContext
            learning_context = LearningContext()

        identity_context = results[2]
        if isinstance(identity_context, Exception):
            self.logger.error(f"Failed to get identity context: {identity_context}")
            from aura.models.identity import IdentityContext
            identity_context = IdentityContext(narrative="I am Aura.", core_values={})

        goal_context = results[3]
        if isinstance(goal_context, Exception):
            self.logger.error(f"Failed to get goal context: {goal_context}")
            from aura.models.goal import GoalContext
            goal_context = GoalContext()

        # Note: interaction time is tracked in the orchestrator state machine.

        # Compute Resonance Score (Emotion-Learning Bridge) for streaming path
        resonance_score = self._compute_resonance_score(emotional_state)
        self.logger.info(f"[WAVE] Resonance score (stream): {resonance_score:.2f}")

        # Recall Engine (M2, W2-20): one call assembles the insights, latent,
        # cold-start and memories blocks for the streaming path.
        from aura.engines.recall.engine import get_recall_engine
        packet: ContextPacket | None = None
        working_set = await self._working_set_offer(user_id, user_input, requester_role, venue)
        try:
            packet = await get_recall_engine().recall(RecallRequest(
                user_id=user_id,
                user_input=user_input,
                recent_turns=(conversation_history or [])[-6:],
                emotional_state=emotional_state,
                learning_context=learning_context,
                depth=1,
                limit=5,
                namespace=None,
                include_cold_start=False,
                include_latent=True,
                venue=venue,
                token_budget=recall_token_budget,
                working_set=working_set,
            ))
        except Exception as e:
            self.logger.warning(f"Recall engine failed (non-critical): {e}")
            packet = None

        cold_start_xml = packet.block_text("cold_start") if packet else None
        latent_intuition_xml = packet.block_text("latent") if packet else None
        ws = packet.block_text("working_set") if packet else None
        if ws:
            latent_intuition_xml = (
                "\n".join([latent_intuition_xml, ws]) if latent_intuition_xml else ws
            )
        if packet is not None:
            self.logger.info(
                f"[ICE] Recall packet (stream): {packet.trace.tokens_after} tokens "
                f"(before {packet.trace.tokens_before})"
            )
            self.logger.debug(f"[BRAIN] MAC injected ({len(latent_intuition_xml or '')} chars)")
            duplicate_count = sum(
                1 for item in packet.trace.items if item.fate == "duplicate"
            )
            over_budget_count = sum(
                1 for item in packet.trace.items if item.fate == "over_budget"
            )
            self._publish_trace("RECALL", "packet_built", {
                "turn_id": packet.trace.turn_id,
                "tokens_before": packet.trace.tokens_before,
                "tokens_after": packet.trace.tokens_after,
                "duplicates": duplicate_count,
                "over_budget": over_budget_count,
            })

        # Synthesis context
        synthesis_context = SynthesisContext(
            user_input=user_input,
            conversation_history=conversation_history or [],
            emotional_state=emotional_state,
            learning_context=learning_context,
            identity_context=identity_context,
            goal_context=goal_context,
            latent_intuition_xml=latent_intuition_xml,
            packet=packet,
            venue=venue,
        )

        return TurnContext(
            emotional_state=emotional_state,
            learning_context=learning_context,
            identity_context=identity_context,
            goal_context=goal_context,
            resonance_score=resonance_score,
            recent_critique=None,
            cold_start_xml=cold_start_xml,
            latent_intuition_xml=latent_intuition_xml,
            synthesis_context=synthesis_context,
            packet=packet,
        )

    async def _generate_blocking(
        self,
        user_input: str,
        conversation_history: list[dict[str, str]] | None,
        ctx: TurnContext,
        context_limit: int | None,
        reasoning_enabled: bool,
        use_forced_tool_mode: bool,
        tool_schema_str: str | None,
        requester_role: str,
    ) -> str:
        """Run the blocking L3 generation through ``run_tool_loop``.

        Returns the post-processed response from the loop's ``done`` event,
        including the tool-call stripping and the max-rounds suffix.
        """

        # Step 5: Generate response (L3)
        context_window_size = context_limit if context_limit is not None else 20
        self.logger.info(f"[TARGET] Using context window size: {context_window_size} messages")

        # Step 5: Generate response (L3) with a bounded tool-execution loop.
        # This enables multi-step tool plans (read -> write -> verify) safely.
        self.logger.info(
            f"[MAG] Tool mode check: use_forced_tool_mode={use_forced_tool_mode}, tool_schema_str={'present' if tool_schema_str else 'None'}"
        )

        # Emit reasoning_started event for avatar state machine
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.reasoning_started()
        except Exception:
            pass

        seed = await self._forced_seed(user_input, tool_schema_str, requester_role, ctx.venue, ctx.session) if use_forced_tool_mode and tool_schema_str else None

        async def _round(loop_input, round_idx, final=False):
            # final: the closing call after a guard stopped the loop; no tools (P2-41).
            loop_context = SynthesisContext(
                user_input=loop_input,
                conversation_history=conversation_history or [],
                emotional_state=ctx.emotional_state,
                learning_context=ctx.learning_context,
                identity_context=ctx.identity_context,
                goal_context=ctx.goal_context,
                recent_critique=ctx.recent_critique,
                packet=ctx.packet,
                offered_tools=None if final else ctx.offered_tools,
                venue=ctx.venue,
                prompt_notes=ctx.prompt_notes,
                skill_index=ctx.skill_index,
                skill_body=ctx.skill_body,
                skill_name=ctx.skill_name,
            )

            round_response = await self.llm_layers.l3_synthesis(
                loop_context,
                max_history_messages=context_window_size,
                reasoning_enabled=reasoning_enabled,
                tools=None if final else ctx.offered_tools,
            )
            # --- Telemetry: L3 synthesis complete ---
            if isinstance(round_response, ModelTurn):
                round_text = round_response.text or ""
            else:
                round_text = round_response
            self._publish_trace("L3", "synthesis_complete", {
                "model": settings.active_l3_model,
                "round": round_idx,
                "response_len": len(round_text or ""),
                "reasoning": reasoning_enabled,
            })
            # Native tools: text first, then the calls the model returned (W2-37).
            if isinstance(round_response, ModelTurn):
                if round_text:
                    yield round_text
                if round_response.tool_calls:
                    yield NativeCalls(round_response.tool_calls)
                if round_response.cost:
                    yield RoundUsage(round_response.cost)
            else:
                yield round_text

        async def _final(loop_input, round_idx):
            async for item in _round(loop_input, round_idx, final=True):
                yield item

        response = ""

        # Define on_tool_result callback for emotion appraisal when enabled
        async def _on_tool_result(tool_name: str, success: bool) -> None:
            ctx.turn_tools.append(tool_name)
            if settings.emotion_appraisal_enabled:
                if success:
                    event = tool_succeeded(tool_name)
                else:
                    # The executor doesn't tell us if it's retryable; assume not retryable for now
                    event = tool_failed(tool_name, retryable=False)
                await self.emotion_engine.appraise(event)

        async for event in run_tool_loop(
            user_input=user_input,
            generate_round=_round,
            tool_executor=self.tool_executor,
            requester_role=requester_role,
            venue=ctx.venue,
            session=ctx.session,
            conversation_id=ctx.conversation_id,
            seed_results=seed,
            on_tool_result=(
                _on_tool_result
                if settings.emotion_appraisal_enabled or ctx.chosen_skills
                else None
            ),
            turn_budget_seconds=ctx.tier_profile.turn_budget_seconds if ctx.tier_profile else None,
            turn_budget_usd=ctx.tier_profile.turn_budget_usd if ctx.tier_profile else None,
            generate_final=_final,
            allow_task_graph=bool(ctx.tier_profile and ctx.tier_profile.allow_task_graph),
        ):
            if event.kind == "done":
                response = event.text
                if event.stats is not None:
                    self._publish_trace("L3", "tool_loop_done", event.stats)

        # Emit reasoning_finished event for avatar state machine
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.reasoning_finished()
        except Exception:
            pass

        return response

    async def _forced_seed(
        self,
        user_input: str,
        tool_schema_str: str,
        requester_role: str,
        venue: str = "app",
        session: Any = None,
    ) -> str | None:
        """Seed the tool loop with a deterministic forced tool call."""
        self.logger.info("[WRENCH] Using FORCED TOOL CALL MODE to seed the tool loop")
        raw_tool_call = await self.llm_layers.l3_tool_call_mode(query=user_input, tool_schema=tool_schema_str)
        self.logger.info(f"[BOX] Raw tool call from forced mode: {raw_tool_call[:300]}...")
        seed_calls = self.tool_executor.extract_tool_calls(raw_tool_call)
        if seed_calls:
            seed_results = await self.tool_executor.execute_and_feedback(
                seed_calls, requester_role=requester_role, venue=venue,
                **({"session": session} if session is not None else {}),
            )
            if seed_results:
                return seed_results
        self.logger.warning("⚠️ Forced tool call mode produced no valid tool calls; proceeding with normal tool loop")
        return None

    async def _generate_streaming(
        self,
        user_input: str,
        conversation_history: list[dict[str, str]] | None,
        ctx: TurnContext,
        reasoning_enabled: bool,
        use_forced_tool_mode: bool,
        tool_schema_str: str | None,
        requester_role: str,
    ):
        """Run the streaming L3 generation through ``run_tool_loop``.

        Yields the loop's :class:`~aura.orchestrator.tool_loop.LoopEvent`
        items unchanged: ``delta`` for each streamed chunk, ``separator``
        between rounds, and one final ``done`` carrying the post-processed
        response (tool-call JSON stripped, max-rounds suffix included when
        applicable). Forced tool mode seeds the loop with a deterministic
        tool call instead of its own prompt.
        """
        # Emit reasoning_started event for avatar state machine
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.reasoning_started()
        except Exception:
            pass

        seed = await self._forced_seed(user_input, tool_schema_str, requester_role, ctx.venue, ctx.session) if use_forced_tool_mode and tool_schema_str else None

        async def _round(loop_input, round_idx, final=False):
            # final: the closing call after a guard stopped the loop; no tools (P2-41).
            loop_context = SynthesisContext(
                user_input=loop_input,
                conversation_history=conversation_history or [],
                emotional_state=ctx.emotional_state,
                learning_context=ctx.learning_context,
                identity_context=ctx.identity_context,
                goal_context=ctx.goal_context,
                recent_critique=ctx.recent_critique,
                packet=ctx.packet,
                offered_tools=None if final else ctx.offered_tools,
                venue=ctx.venue,
                prompt_notes=ctx.prompt_notes,
                skill_index=ctx.skill_index,
                skill_body=ctx.skill_body,
                skill_name=ctx.skill_name,
            )

            round_response = ""
            async for chunk in self.llm_layers.stream_l3_synthesis(
                loop_context,
                reasoning_enabled=reasoning_enabled,
                tools=None if final else ctx.offered_tools,
            ):
                if isinstance(chunk, str):
                    round_response += chunk
                yield chunk
            # --- Telemetry: L3 synthesis complete ---
            self._publish_trace("L3", "synthesis_complete", {
                "model": settings.active_l3_model,
                "round": round_idx,
                "response_len": len(round_response or ""),
                "reasoning": reasoning_enabled,
                "mode": "stream",
            })

        # Define on_tool_result callback for emotion appraisal when enabled
        async def _on_tool_result(tool_name: str, success: bool) -> None:
            ctx.turn_tools.append(tool_name)
            if settings.emotion_appraisal_enabled:
                if success:
                    event = tool_succeeded(tool_name)
                else:
                    # The executor doesn't tell us if it's retryable; assume not retryable for now
                    event = tool_failed(tool_name, retryable=False)
                await self.emotion_engine.appraise(event)

        async def _final(loop_input, round_idx):
            async for item in _round(loop_input, round_idx, final=True):
                yield item

        async for event in run_tool_loop(
            user_input=user_input,
            generate_round=_round,
            generate_final=_final,
            tool_executor=self.tool_executor,
            requester_role=requester_role,
            venue=ctx.venue,
            session=ctx.session,
            conversation_id=ctx.conversation_id,
            seed_results=seed,
            on_tool_result=(
                _on_tool_result
                if settings.emotion_appraisal_enabled or ctx.chosen_skills
                else None
            ),
            turn_budget_seconds=ctx.tier_profile.turn_budget_seconds if ctx.tier_profile else None,
            turn_budget_usd=ctx.tier_profile.turn_budget_usd if ctx.tier_profile else None,
            allow_task_graph=bool(ctx.tier_profile and ctx.tier_profile.allow_task_graph),
        ):
            if event.kind == "done" and event.stats is not None:
                self._publish_trace("L3", "tool_loop_done", event.stats)
            yield event

        # Emit reasoning_finished event for avatar state machine
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.reasoning_finished()
        except Exception:
            pass

    async def _turn_pipeline(self, *args, **kwargs):
        """Drive :meth:`_turn_stages` and clean up a parallel appraisal (P2-05).

        The appraisal task is started inside the stages, after the pre-intent
        reply. Any exit that did not hand it to the post-response chain (the
        teaching reply, an exception, the consumer closing the stream) cancels
        it, so a turn that never reaches the chain never appraises.
        """
        handle = _AppraisalHandle()
        stages = self._turn_stages(*args, appraisal=handle, **kwargs)
        # B2-04: the one place both entry points pass. Sync, no await; pre-empts autonomous work.
        from aura.orchestrator import workspace as _workspace

        _workspace.fire_event("user_message")
        from aura.autonomy import channel as _channel

        _channel.note_owner_message()
        try:
            async for ev in stages:
                yield ev
        finally:
            _workspace.turn_finished()
            if handle.task is not None and not handle.handed_off:
                handle.task.cancel()
            await stages.aclose()

    async def _turn_stages(
        self,
        user_input: str,
        user_id: str,
        conversation_history: list[dict[str, str]] | None,
        *,
        stream: bool,
        context_limit: int | None,
        enable_l2: bool | None = None,
        conversation_id: str | None = None,
        reasoning_enabled: bool | None = None,
        l2_reasoning_enabled: bool | None = None,
        session_id: str | None = None,
        context_mode: str = "deep_work",
        requester_role: str = "owner",
        venue: str = "app",
        appraisal: "_AppraisalHandle | None" = None,
    ):
        """Run one turn end-to-end and yield :class:`TurnEvent` items (W2-10).

        This is the single pipeline that both ``process_query`` (``stream=False``)
        and ``stream_query`` (``stream=True``) drive. It runs the stages in
        order: context-mode set, session resolution, pre-intent reply, intent
        classification, forced-tool resolution, context gathering, system-prompt
        caching, generation, and post-response scheduling; then it yields a
        final ``done`` event carrying the accumulated response.

        Early replies (stage 3 pre-intent, or the teaching reply from stage 4)
        are returned without scheduling the post-response chain, as today:
        when ``stream`` is true one ``delta`` is yielded per character then a
        ``done`` with the full reply; when ``stream`` is false only the ``done``
        event is yielded.

        During streaming generation the ``run_tool_loop``
        :class:`~aura.orchestrator.tool_loop.LoopEvent` items are relayed as
        ``delta`` events (both its ``delta`` and ``separator`` kinds), and its
        ``done`` event supplies the response; the post-response chain is
        scheduled before the ``done`` event so it still runs only after the
        last delta has been consumed, as today.

        Reasoning controls (P2-42): ``enable_l2``, ``reasoning_enabled`` and
        ``l2_reasoning_enabled`` are accepted for old callers and IGNORED (one
        deprecation log line per process). Effective values:

        * ``tier_profiles_enabled`` ON: ``enable_l2 = l2_analysis_allowed(profile)``,
          ``l2_reasoning = l2_reasoning_allowed(profile)``,
          ``reasoning = l3_reasoning_allowed(profile, route, stakes)``.
        * ``tier_profiles_enabled`` OFF: fixed values equal to the old frontend
          default request: reasoning False, l2_reasoning False, deep analysis
          (enable_l2) True; L2 still needs ``settings.layer_l2_enabled``.
        """
        note_deprecated_reasoning_controls([
            n for n, v in (
                ("enable_l2", enable_l2),
                ("reasoning_enabled", reasoning_enabled),
                ("l2_reasoning_enabled", l2_reasoning_enabled),
            ) if v is not None
        ])
        # Stage 1: set the LLM router context mode.
        self.llm_layers.context_mode = context_mode  # type: ignore[assignment]

        # Emit message_received event for avatar state machine
        try:
            from aura.main import avatar_state_machine
            if avatar_state_machine is not None:
                avatar_state_machine.message_received()
        except Exception:
            pass

        # Stage 2: resolve the session namespace and identity overlay.
        turn_session = await self._resolve_session(session_id)

        # Stage 3: sleep gating + system commands (bypass intent classification).
        reply = await self._pre_intent_reply(user_input, user_id)
        if reply is not None:
            if stream:
                for char in reply:
                    yield TurnEvent("delta", char)
                yield TurnEvent("done", reply)
            else:
                yield TurnEvent("done", reply)
            return

        # P2-05: start the L4 appraisal now, in parallel with L1. It needs only the
        # message, the history, the venue and the speaker (never Aura's reply).
        # Started after the pre-intent reply so that path never appraises.
        speaker = speaker_key(user_id, requester_role)
        if appraisal is not None and self._parallel_appraisal_active():
            appraisal.task = self._start_background_appraisal(
                user_input=user_input,
                conversation_history=conversation_history,
                venue=venue,
                speaker=speaker,
            )

        # Stage 4: L1 intent classification, telemetry, teaching lane.
        intent_data, intent, teaching_reply = await self._classify_intent(
            user_input, user_id, stream=stream, speaker=speaker
        )
        if teaching_reply is not None:
            if stream:
                for char in teaching_reply:
                    yield TurnEvent("delta", char)
                yield TurnEvent("done", teaching_reply)
            else:
                yield TurnEvent("done", teaching_reply)
            return

        route: str | None = None
        stakes: float | None = None
        if settings.l1_routes_enabled:
            route = intent_data.get("route", "chat")
            stakes = intent_data.get("stakes", 0.0)

        # Stage 5: forced-tool resolution (tool reflex fast lane).
        use_forced_tool_mode, tool_schema_str = await self._resolve_forced_tool(intent, intent_data)

        # Stage 6: gather engine context (emotion/learning/identity/goal + memory).
        profile = active_profile() if settings.tier_profiles_enabled else None
        history_for_turn = conversation_history
        # P2-42: client values are ignored; the profile and route decide alone.
        enable_l2, l2_reasoning_enabled, reasoning_enabled = True, False, False
        if profile is not None:
            enable_l2 = l2_analysis_allowed(profile)
            l2_reasoning_enabled = l2_reasoning_allowed(profile)
            # Route and stakes are None unless l1_routes_enabled (P2-06).
            reasoning_enabled = l3_reasoning_allowed(profile, route, stakes)
            if conversation_history:
                history_for_turn = trim_history(conversation_history, profile, estimate_tokens)
            self._publish_trace("TIER", "profile_applied", {
                "tier_name": profile.name,
                **profile.model_dump(),
            })
        if appraisal is not None and appraisal.task is not None:
            # Wait for the appraisal up to the deadline, before any emotion state is
            # read for this turn. If it is not done it is NOT cancelled: it finishes
            # in the background and applies to the next turn.
            await asyncio.wait(
                {appraisal.task}, timeout=settings.appraisal_turn_deadline_ms / 1000
            )
            self._publish_trace("L4", "appraisal_timing", {
                "appraisal": "this_turn" if appraisal.task.done() else "next_turn",
            })
        ctx = await self._gather_turn_context(
            user_input,
            user_id,
            history_for_turn,
            stream=stream,
            venue=venue,
            recall_token_budget=recall_budget_tokens(profile) if profile else None,
            requester_role=requester_role,
        )
        ctx.tier_profile = profile
        ctx.route = route
        ctx.stakes = stakes
        # Record who is speaking and where this turn happens (W3-10).
        ctx.speaker = speaker
        ctx.venue = venue
        # The session scope travels like the venue (G4-04a); None for main.
        ctx.session = turn_session
        ctx.conversation_id = conversation_id
        if settings.consult_enabled:
            # P2-27: fresh consult limits and trace for this turn (no model call).
            from aura.tools.consult import begin_turn as begin_consult_turn

            begin_consult_turn()
        # Stage 6.5: select the tools to offer the model this turn (W2-35).
        try:
            tier_args = (
                {"top_k": profile.tools_offered_max, "exclude": gated_tools_denied(profile)}
                if profile else {}
            )
            session_excluded = self._session_excluded_tools(ctx.session)
            if session_excluded:
                tier_args["exclude"] = set(tier_args.get("exclude", ())) | session_excluded
            ctx.offered_tools = await get_tool_registry().select_tools(
                user_input, requester_role=requester_role, **tier_args
            )
            if route == "task" and profile is not None:
                if profile.allow_task_graph:
                    # Titan: offer plan_task first when it is registered and offered.
                    tools = list(ctx.offered_tools)
                    tools.sort(key=lambda t: getattr(t, "name", None) != "plan_task")
                    ctx.offered_tools = tools
                else:
                    ctx.prompt_notes.append(TASK_UNAVAILABLE_NOTE)
        except Exception as e:
            self.logger.warning(f"Tool selection failed (non-critical): {e}")
            ctx.offered_tools = []

        # Stage 6.6: skill index and the chosen skill's body (G5-05). No model call.
        await self._select_skills(ctx, user_input, requester_role, profile)

        # Stage 7: cache the system prompt for debugging (before synthesis).
        await self._cache_system_prompt(ctx.synthesis_context, user_input, user_id)

        # Stage 8: generation (streaming or blocking).
        if stream:
            response = ""
            async for event in self._generate_streaming(
                user_input,
                history_for_turn,
                ctx,
                reasoning_enabled,
                use_forced_tool_mode,
                tool_schema_str,
                requester_role,
            ):
                if event.kind in ("delta", "separator"):
                    yield TurnEvent("delta", event.text)
                elif event.kind == "done":
                    response = event.text
        else:
            response = await self._generate_blocking(
                user_input,
                history_for_turn,
                ctx,
                context_limit,
                reasoning_enabled,
                use_forced_tool_mode,
                tool_schema_str,
                requester_role,
            )

        # Stage 9: schedule the post-response chain (L4/L2/etc.) in the background.
        self._schedule_post_response(
            user_input=user_input,
            response=response,
            emotional_before=ctx.emotional_state,
            user_id=user_id,
            conversation_id=conversation_id,
            goal_context=ctx.goal_context,
            learning_context=ctx.learning_context,
            enable_l2=enable_l2,
            l2_reasoning_enabled=l2_reasoning_enabled,
            resonance_score=ctx.resonance_score,
            conversation_history=conversation_history,
            venue=ctx.venue,
            speaker=ctx.speaker,
            packet=ctx.packet,
            appraisal_task=appraisal.task if appraisal is not None else None,
            chosen_skills=ctx.chosen_skills,
            turn_tools=ctx.turn_tools,
        )
        if appraisal is not None:
            appraisal.handed_off = True

        # Stage 10: yield the final done event with the accumulated response.
        yield TurnEvent("done", response, meta={
            "deep_reasoning": bool(reasoning_enabled),
            "tier": TIER_NAMES.get(settings.model_stack_index, "lean"),
            "route": route,
        })

    async def process_query(
        self,
        user_input: str,
        user_id: str = "default",
        conversation_history: list[dict[str, str]] | None = None,
        context_limit: int | None = None,
        enable_l2_analysis: bool | None = None,
        conversation_id: str | None = None,
        reasoning_enabled: bool | None = None,
        l2_reasoning_enabled: bool | None = None,
        deep_analysis_enabled: bool | None = None,
        session_id: str | None = None,
        context_mode: str = "deep_work",
        requester_role: str = "owner",
        venue: str = "app",
        turn_meta: dict[str, Any] | None = None,
    ) -> str:
        """
        Full orchestrated query processing.

        This is the non-streaming entry point over :meth:`_turn_pipeline`
        (W2-10). It drives the pipeline with ``stream=False`` and returns the
        ``done`` text.

        Args:
            user_input: User's message
            user_id: User identifier
            conversation_history: Previous messages

        Returns:
            Generated response

        ``reasoning_enabled``, ``l2_reasoning_enabled``, ``deep_analysis_enabled``
        and ``enable_l2_analysis`` are deprecated and ignored (P2-42): see
        :meth:`_turn_stages` for the effective values. If ``turn_meta`` is a
        dict it is filled with ``deep_reasoning``, ``tier`` and ``route``.
        """
        self.logger.info(f"Processing query from user {user_id} (session={session_id or 'main'})")

        note_deprecated_reasoning_controls([
            n for n, v in (
                ("reasoning_enabled", reasoning_enabled),
                ("l2_reasoning_enabled", l2_reasoning_enabled),
                ("deep_analysis_enabled", deep_analysis_enabled),
                ("enable_l2_analysis", enable_l2_analysis),
            ) if v is not None
        ])
        if turn_meta is not None:
            turn_meta.update(self._default_turn_meta())

        response = ""
        async for ev in self._turn_pipeline(
            user_input,
            user_id,
            conversation_history,
            stream=False,
            context_limit=context_limit,
            conversation_id=conversation_id,
            session_id=session_id,
            context_mode=context_mode,
            requester_role=requester_role,
            venue=venue,
        ):
            if ev.kind == "done":
                response = ev.text
                if turn_meta is not None and ev.meta:
                    turn_meta.update(ev.meta)
        return response

    @staticmethod
    def _default_turn_meta() -> dict[str, Any]:
        """Turn metadata for replies that never reach generation (P2-42)."""
        return {
            "deep_reasoning": False,
            "tier": TIER_NAMES.get(settings.model_stack_index, "lean"),
            "route": None,
        }

    def _compute_resonance_score(self, emotional_state: EmotionState) -> float:
        """
        Compute the Resonance Field Score for the current turn.

        Formula: resonance = (user_contentment * 0.5) + (aura_alignment * 0.5)

        - user_contentment: derived from recent emotional valence trend.
          Positive-trending emotions → high, negative → low.
        - aura_alignment: dot-product between current emotional vector and
          baseline personality vector — how "herself" Aura feels right now.

        Returns a float in [0.0, 1.0].
        """
        vector_dict = emotional_state.vector.model_dump()

        # --- user_contentment: valence mapped to [0, 1] ---
        from aura.engines.emotion.engine import EmotionEngine
        raw_valence = EmotionEngine._compute_valence(vector_dict)  # [-1, 1]
        user_contentment = (raw_valence + 1.0) / 2.0  # map to [0, 1]

        # --- aura_alignment: cosine similarity with baseline personality ---
        baseline_dict = self.emotion_engine.config.baseline.model_dump()
        dot = 0.0
        mag_current = 0.0
        mag_baseline = 0.0
        for key in vector_dict:
            c = vector_dict[key]
            b = baseline_dict.get(key, 0.0)
            dot += c * b
            mag_current += c * c
            mag_baseline += b * b

        import math
        mag_current = math.sqrt(mag_current) or 1.0
        mag_baseline = math.sqrt(mag_baseline) or 1.0
        cosine_sim = dot / (mag_current * mag_baseline)
        # Cosine similarity is in [-1, 1]; map to [0, 1]
        aura_alignment = max(0.0, min(1.0, (cosine_sim + 1.0) / 2.0))

        resonance = (user_contentment * 0.5) + (aura_alignment * 0.5)
        return max(0.0, min(1.0, resonance))

    async def _handle_message(self, message: EngineMessage) -> None:
        """
        Handle incoming messages from other engines.
        
        The orchestrator monitors state updates and alerts from all engines
        to maintain global coherence and detect conflicts.
        """
        self.logger.debug(f"Orchestrator received message from {message.source}: {message.message_type}")
        
        # In the future, this is where conflict detection logic will reside
        # e.g. if Emotion Engine says "fear" but Goal Engine says "explore",
        # the orchestrator will intervene.
        
        # For now, we just log significant events
        if message.message_type == "state_update":
            self.logger.debug(f"State update from {message.source}: {message.data}")

    # =========================================================================
    # Telemetry helper — non-blocking trace publisher
    # =========================================================================

    def _publish_trace(self, layer: str, event: str, data: dict) -> None:
        """
        Fire-and-forget trace event to all connected Telemetry Widget clients.

        Wraps the async broadcast in an asyncio.create_task so it never blocks
        the main cognitive pipeline.  Failures are silently swallowed — the
        trace stream is purely observability and must never affect responses.
        """
        try:
            from aura.api.trace_socket_manager import get_trace_manager
            from datetime import timezone as _tz
            payload: dict = {
                "layer": layer,
                "event": event,
                "ts": datetime.now(_tz.utc).isoformat(),
            }
            # Only include JSON-serialisable scalars to avoid payload blowup
            for k, v in data.items():
                if isinstance(v, (str, int, float, bool, type(None))):
                    payload[k] = v
            asyncio.create_task(get_trace_manager().broadcast(payload))
        except Exception:
            pass  # Trace is strictly non-critical

    # =========================================================================
    # L2 INTERNAL COGNITIVE TOOLS (Session 6 — Active Recall)
    # =========================================================================

    # Tool definitions exposed to L2 during reasoning. These let L2 autonomously
    # navigate Aura's memory graph without relying solely on what manager.py injects.
    L2_INTERNAL_TOOLS = [
        {
            "name": "traverse_timeline",
            "description": (
                "Read a past conversation sequentially by following temporal "
                "(next_experience) edges in the experience graph. Use this when "
                "you need to understand 'what happened before/after' a specific event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "experience_id": {
                        "type": "string",
                        "description": "The experience record ID to start from (e.g. experience:abc123)",
                    },
                    "steps": {
                        "type": "integer",
                        "description": "Number of steps to traverse (1-10)",
                        "default": 3,
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["forward", "backward"],
                        "description": "forward = what happened after, backward = what happened before",
                        "default": "forward",
                    },
                },
                "required": ["experience_id"],
            },
        },
        {
            "name": "fetch_supporting_evidence",
            "description": (
                "Retrieve the raw episodic memories or experiences that formed a "
                "belief/insight. Use this to ground abstract knowledge in concrete "
                "evidence, preventing hallucination about past events."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "insight_id": {
                        "type": "string",
                        "description": (
                            "The insight or semantic memory ID to trace back "
                            "(e.g. insight:abc123 or memory:xyz789)"
                        ),
                    },
                },
                "required": ["insight_id"],
            },
        },
    ]

    async def execute_l2_internal_tool(self, tool_name: str, arguments: dict) -> str:
        """Execute an internal cognitive tool called by L2 during reasoning.

        Routes tool calls to the appropriate RecallEngine method and returns
        the result as a formatted string for re-injection into L2's context.

        Args:
            tool_name: One of the L2_INTERNAL_TOOLS names.
            arguments: Parsed arguments dict from L2's tool call.

        Returns:
            Formatted string result for L2 consumption.
        """
        from aura.engines.recall.engine import get_recall_engine
        recall = get_recall_engine()

        try:
            if tool_name == "traverse_timeline":
                experience_id = arguments.get("experience_id", "")
                steps = int(arguments.get("steps", 3))
                direction = arguments.get("direction", "forward")

                timeline = await recall.timeline(
                    experience_id=experience_id,
                    steps=steps,
                    direction=direction,
                )

                if not timeline:
                    return f"[traverse_timeline] No {direction} events found from {experience_id}."

                lines = [f"[traverse_timeline] {len(timeline)} events ({direction} from {experience_id}):"]
                for i, entry in enumerate(timeline, 1):
                    ts = entry.get("timestamp", "?")
                    prompt = entry.get("prompt", "(no prompt)")
                    lines.append(f"  {i}. [{ts}] User: {prompt}")
                    resp = entry.get("response", "")
                    if resp:
                        lines.append(f"     Aura: {resp[:150]}...")
                return "\n".join(lines)

            elif tool_name == "fetch_supporting_evidence":
                insight_id = arguments.get("insight_id", "")

                evidence = await recall.evidence(insight_id=insight_id)

                if not evidence:
                    return f"[fetch_supporting_evidence] No evidence found for {insight_id}."

                lines = [f"[fetch_supporting_evidence] {len(evidence)} source(s) for {insight_id}:"]
                for i, item in enumerate(evidence, 1):
                    content = item.get("content") or item.get("prompt") or "(empty)"
                    ts = item.get("timestamp", "?")
                    lines.append(f"  {i}. [{ts}] {content[:250]}")
                return "\n".join(lines)

            else:
                return f"[error] Unknown internal tool: {tool_name}"

        except Exception as e:
            self.logger.error(f"L2 internal tool execution failed ({tool_name}): {e}")
            return f"[error] Tool execution failed: {e}"

    def get_l2_tools_prompt_block(self) -> str:
        """Generate the XML tool availability block injected into L2's system prompt.

        This teaches L2 that it can autonomously navigate its own memory graph
        by emitting tool calls in JSON format during analysis.
        """
        block = "\n<available_internal_tools>\n"
        block += "You may call these tools during your analysis by outputting a JSON block:\n"
        block += '```json\n{"tool": "<name>", "arguments": {...}}\n```\n\n'
        for tool in self.L2_INTERNAL_TOOLS:
            params = tool["parameters"]["properties"]
            param_desc = ", ".join(
                f"{k}: {v.get('description', '')}" for k, v in params.items()
            )
            block += f"• {tool['name']}: {tool['description']}\n"
            block += f"  Parameters: {param_desc}\n\n"
        block += "</available_internal_tools>\n"
        return block

    async def _post_response_chain(
        self,
        user_input: str,
        response: str,
        emotional_before: EmotionState,
        user_id: str,
        conversation_id: str | None,
        goal_context: GoalContext,
        learning_context: LearningContext | None,
        enable_l2: bool,
        l2_reasoning_enabled: bool = False,
        resonance_score: float | None = None,
        conversation_history: list[dict[str, str]] | None = None,
        venue: str = "app",
        speaker: str = "owner",
        packet: ContextPacket | None = None,
        appraisal_task: "asyncio.Task | None" = None,
        chosen_skills: list | None = None,
        turn_tools: list[str] | None = None,
    ) -> None:
        """
        Execute post-response tasks in correct dependency order.
        
        Order:
        1. Emotion Appraisal (when enabled) or L4 Emotion Analysis
        2. Log Experience
        3. Store the memory v2 episode (only when the write flag is on)
        4. L2 Deep Analysis (Needs updated emotional state)
        """

        # 1. Apply Emotion Appraisal (when enabled) or L4 Emotion Analysis (legacy)
        # Respects layer_l4_enabled toggle from inference cockpit.
        # Appraisal is an L4 model call, so it must respect the L4 switch:
        # call _appraise_message only when both flags are true.
        if appraisal_task is not None:
            # P2-05: already started at turn start; never appraise the message again.
            # Wait for it (if the deadline passed it is still running) so the
            # experience log and L2 below see the fresh state, as they do today.
            await asyncio.wait({appraisal_task})
        elif settings.emotion_appraisal_enabled and settings.layer_l4_enabled:
            await self._appraise_message(
                user_input=user_input,
                conversation_history=conversation_history,
                venue=venue,
                speaker=speaker,
            )
        elif settings.layer_l4_enabled:
            await self._apply_l4_emotion_analysis(
                user_input=user_input,
                aura_response=response,
                current_emotions=emotional_before.vector.model_dump(),
            )
        
        # 2. Log Experience (Now captured with potential new emotional state)
        # We need to get the FRESH state
        emotional_current = await self.emotion_engine.get_current_state()
        
        experience_id = await self._log_interaction_experience(
            user_id=user_id,
            user_input=user_input,
            aura_response=response,
            emotional_state=emotional_current,
            learning_context=learning_context,
            speaker=speaker,
        )

        # 2b. Real outcome signal for the earlier owner turns (G5-03). Logs its
        #     own failures; the ring is keyed by conversation id, or by user id
        #     when the turn has none.
        if settings.outcome_signals_enabled:
            from aura.engines.learning.outcomes import track_turn_outcome
            from aura.llm.embeddings import get_embeddings_client

            on_outcome = None
            if settings.skills_v2_enabled and settings.skill_attribution_enabled:
                # G5-04: a patched turn outcome counts that turn's skill uses.
                async def on_outcome(eid: str, signal: str) -> None:
                    from aura.engines.learning.skill_stats import apply_outcome_for_turn
                    from aura.engines.learning.skill_store import SkillStore

                    await apply_outcome_for_turn(SkillStore(self.db), eid, signal)

            await track_turn_outcome(
                self.learning_engine,
                get_embeddings_client(),
                key=conversation_id or f"user:{user_id}",
                speaker=speaker,
                text=user_input,
                experience_id=experience_id if isinstance(experience_id, str) else None,
                **({"on_outcome": on_outcome} if on_outcome is not None else {}),
            )

        # 3. Store the memory v2 episode (only when the write flag is on).
        #    A failure here must never affect the turn, which has already been
        #    answered and had its experience logged.
        if settings.memory_v2_write_enabled:
            try:
                from aura.llm.embeddings import get_embeddings_client

                baseline = self.emotion_engine.config.baseline.model_dump()
                intensity = emotional_intensity(
                    emotional_current.vector.model_dump(), baseline
                )
                depth = interaction_depth(len(response), None, None)
                salience_value = compute_salience(intensity, None, depth)
                # When the owner speaks in the app, pass their user_id as the display
                # name so the owner's entity accumulates the owner's name as an alias.
                # (The app sends the owner's name, e.g. "Mai".)
                display_name = None
                if speaker == "owner" and venue == "app":
                    if user_id and user_id != "default":
                        display_name = user_id

                episode_id = await store_episode(
                    self.db,
                    get_embeddings_client(),
                    user_text=user_input,
                    aura_text=response,
                    speaker=speaker,
                    venue=venue,
                    conversation_id=conversation_id,
                    emotional_signature=emotional_current.vector.model_dump(),
                    salience=salience_value,
                    display_name=display_name,
                )
                # Extraction runs after the turn, in the background, never on
                # the reply path. The task reference is kept by
                # ``schedule_extraction`` until it finishes.
                client = getattr(getattr(self, "llm_layers", None), "client", None)
                if client is not None:
                    schedule_extraction(self.db, client, episode_id)
            except Exception as e:
                self.logger.warning(f"Failed to store memory v2 episode: {e}")

        # 3b. Feedback on the recalled facts (W4-06). Logs its own failures.
        used_fact_ids: list[str] = []
        if settings.recall_feedback_enabled and packet is not None:
            from aura.engines.recall.feedback import record_feedback
            from aura.llm.embeddings import get_embeddings_client

            used_fact_ids = await record_feedback(
                self.db, get_embeddings_client(), packet, response
            )

        # 3c. Attribution (G5-04): one skill_use per skill chosen for this turn.
        #     The outcome arrives with a later turn. Never affects the turn.
        if chosen_skills and settings.skills_v2_enabled and settings.skill_attribution_enabled:
            try:
                from aura.engines.learning.skill_stats import record_skill_use
                from aura.engines.learning.skill_store import SkillStore

                skill_store = SkillStore(self.db)
                for skill, version in chosen_skills:
                    await record_skill_use(
                        skill_store,
                        skill,
                        version,
                        turn_id=experience_id if isinstance(experience_id, str) else None,
                        task_id=None,
                        requester_role="owner" if speaker == "owner" else "guest",
                        tools=list(turn_tools or []),
                        fact_ids=list(used_fact_ids),
                    )
            except Exception as exc:
                self.logger.warning(f"Skill attribution failed (non-critical): {exc}")

        # 4. Run L2 Analysis (if enabled AND L2 layer not bypassed via inference cockpit)
        if enable_l2 and settings.layer_l2_enabled:
            await self._async_l2_analysis(
                user_input=user_input,
                aura_response=response,
                emotional_before=emotional_before,
                emotional_after=emotional_current,
                user_id=user_id,
                conversation_id=conversation_id,
                goal_context=goal_context,
                learning_context=learning_context,
                l2_reasoning_enabled=l2_reasoning_enabled,
                resonance_score=resonance_score,
            )

    async def _async_l2_analysis(
        self,
        user_input: str,
        aura_response: str,
        emotional_before: EmotionState,
        emotional_after: EmotionState,
        user_id: str = "default",
        conversation_id: str | None = None,
        goal_context: GoalContext | None = None,
        learning_context: LearningContext | None = None,
        l2_reasoning_enabled: bool = False,
        resonance_score: float | None = None,
    ) -> None:
        """
        Run L2 post-response analysis in background.
        
        Non-blocking metacognitive analysis for learning and improvement.
        Also stores important memories from the interaction.
        """
        try:
            # --- CHANGE 2: PREPARE MEMORY ---
            # Extract the content strings from the context
            known_insights_list = []
            if learning_context and learning_context.insights:
                # Limit to top 5 to save tokens (The "Context Cap")
                known_insights_list = [i.content for i in learning_context.insights[:5]]

            # Run L2 deep analysis WITH MEMORY
            analysis = await self.llm_layers.l2_reasoning(
                interaction={
                    'user_input': user_input,
                    'aura_response': aura_response,
                    'emotion_before': emotional_before.vector.model_dump(),
                    'emotion_after': emotional_after.vector.model_dump(),
                },
                known_insights=known_insights_list,  # <--- PASS NEW ARGUMENT
                l2_reasoning_enabled=l2_reasoning_enabled,
            )
            # --- Telemetry: L2 post-response analysis ---
            self._publish_trace("L2", "post_analysis_complete", {
                "model": settings.active_l2_model,
                "patterns": len(analysis.get("patterns_found", [])),
                "insights": len(analysis.get("insights", [])),
                "has_critique": bool(analysis.get("critique")),
            })

            self.logger.info(f"L2 post-analysis complete: {analysis.get('analysis', '')[:100]}...")
            
            # Store critique in buffer for next turn (under lock to avoid race with process_query)
            critique = analysis.get("critique")
            if critique and len(critique) > 10:
                async with self._state_lock:
                    if user_id not in self.critique_buffer:
                        self.critique_buffer[user_id] = []
                    
                    # Append new critique
                    self.critique_buffer[user_id].append(critique)
                    
                    # Enforce buffer size limit (keep last 5)
                    MAX_CRITIQUE_BUFFER_SIZE = 5
                    if len(self.critique_buffer[user_id]) > MAX_CRITIQUE_BUFFER_SIZE:
                        self.critique_buffer[user_id] = self.critique_buffer[user_id][-MAX_CRITIQUE_BUFFER_SIZE:]
                    
                self.logger.info(f"Buffered L2 critique for next turn: {critique[:50]}...")
                
                # Apply emotional impact of critique - "Self-Reflection"
                # Aura should feel "concern" or "determination" based on critique
                if settings.emotion_appraisal_enabled:
                    await self.emotion_engine.appraise(self_critique_received())
                else:
                    await self.emotion_engine.apply_influence(
                        EmotionInfluence(
                            source="internal_critique",
                            emotions={"interest": 0.1, "determination": 0.1}, 
                            reason="Self-critique received"
                        )
                    )
                
                # Send to Learning Engine for pattern extraction/integration
                from aura.models.messages import EngineMessage, MessagePriority, MessageType
                msg = EngineMessage(
                    source="orchestrator",
                    targets=["learning_engine"],
                    message_type=MessageType.PROPOSAL,
                    data={
                        "type": "rule",
                        "condition": "self_critique_feedback",
                        "action": "internalize_critique",
                        "rationale": f"Self-Critique: {critique}",
                        "domain": "meta_cognition",
                        "confidence": 0.6,
                        "task_type": "critique_integration"
                    },
                    priority=MessagePriority.NORMAL
                )
                await self.message_bus.publish(msg)
            
            # Store memory from this interaction
            try:
                from aura.engines.memory.manager import get_memory_manager
                from aura.models.memory import FormationContext
                memory_manager = get_memory_manager()
                
                # Create memory content combining user input and Aura's response
                memory_content = f"User: {user_input}\nAura: {aura_response}"
                
                # Determine importance based on emotional change and response length
                emotional_change = sum(
                    abs(emotional_after.vector.model_dump().get(emotion, 0) - 
                        emotional_before.vector.model_dump().get(emotion, 0))
                    for emotion in emotional_after.vector.model_dump().keys()
                ) / len(emotional_after.vector.model_dump())
                
                # Importance: higher if emotional change is significant or response is substantial
                importance = min(1.0, 0.3 + (emotional_change * 0.3) + (min(len(aura_response), 200) / 200 * 0.4))

                # Build rich formation context (Session 5)
                active_cultural = None
                try:
                    from aura.engines.cultural.router import CulturalRouter
                    cr = CulturalRouter()
                    active_node = cr.get_active()
                    if active_node:
                        active_cultural = active_node.code
                except Exception:
                    pass

                formation_ctx = FormationContext(
                    conversation_id=conversation_id,
                    active_cultural_node=active_cultural,
                    resonance_score_at_formation=resonance_score or 0.0,
                    triggered_by=user_input[:200] if user_input else None,
                )
                
                # Store memory with formation scoring and rich context
                await memory_manager.store_memory(
                    content=memory_content,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    emotional_signature=emotional_after.vector.model_dump(),
                    importance=importance,
                    tags=["conversation", "interaction"],
                    resonance_score=resonance_score,
                    formation_context=formation_ctx,
                    response_length=len(aura_response),
                )
                
                self.logger.info(
                    f"Memory stored from interaction (user_id: {user_id}, "
                    f"conversation_id: {conversation_id}, importance: {importance:.2f})"
                )

                # Session 7: Feed experience to TITANS Latent Engine
                try:
                    from aura.engines.latent.engine import get_latent_engine
                    from aura.llm.embeddings import get_embeddings_client
                    embeddings_client = get_embeddings_client()
                    # Embed the interaction content for the latent state
                    experience_text = f"{user_input} {aura_response[:200]}"
                    exp_embedding = await embeddings_client.embed(experience_text)
                    if exp_embedding:
                        surprise = await get_latent_engine().absorb_experience(
                            user_id=user_id,
                            experience_embedding=exp_embedding,
                            emotional_state=emotional_after.vector.model_dump(),
                            domain="conversation",
                        )
                        self.logger.debug(f"[BRAIN] Latent absorption: surprise={surprise:.3f}")
                except Exception as latent_err:
                    self.logger.debug(f"Latent engine absorption failed (non-critical): {latent_err}")

            except Exception as mem_error:
                self.logger.error(f"CRITICAL: Failed to store memory: {mem_error}")
                # Apply emotional impact - Aura should feel "loss" or "distress"
                # Memory failure is a significant cognitive event
                try:
                    if settings.emotion_appraisal_enabled:
                        await self.emotion_engine.appraise(memory_write_failed())
                    else:
                        await self.emotion_engine.apply_influence(
                            EmotionInfluence(
                                source="system_error",
                                emotions={"confusion": 0.3, "doubt": 0.2},
                                reason="Memory storage failure (cognitive distress)"
                            )
                        )
                except Exception as e:
                    self.logger.error(f"Failed to apply emotional distress for memory error: {e}")
            
            # Assess goal progress if goals are active
            if goal_context and goal_context.active_goals:
                await self._assess_goal_progress(
                    user_input=user_input,
                    aura_response=aura_response,
                    active_goals=goal_context.active_goals,
                    emotional_state=emotional_after,
                )
            
            # Extract patterns and send to learning engine
            patterns = analysis.get("patterns_found", [])
            insights = analysis.get("insights", [])  # L2 might also return insights directly
            
            # Deduplicate patterns/insights before sending
            import re
            seen_content = set()
            unique_patterns = []
            unique_insights = []
            
            # Process patterns
            if patterns:
                for pattern in patterns:
                    # Check if pattern has content field (might be insight-like)
                    content = pattern.get("content") or pattern.get("condition") or str(pattern)
                    normalized = re.sub(r'[^\w\s]', '', content.lower().strip())
                    
                    if normalized not in seen_content:
                        seen_content.add(normalized)
                        unique_patterns.append(pattern)
            
            # Process insights (if L2 returns them directly)
            if insights:
                for insight in insights:
                    content = insight.get("content") or str(insight)
                    normalized = re.sub(r'[^\w\s]', '', content.lower().strip())
                    
                    if normalized not in seen_content:
                        seen_content.add(normalized)
                        unique_insights.append(insight)
            
            # Send unique patterns as rules
            if unique_patterns:
                self.logger.info(f"L2 detected {len(unique_patterns)} unique patterns (deduplicated from {len(patterns)}) - sending to Learning Engine")
                
                from aura.models.messages import EngineMessage, MessagePriority, MessageType
                
                for pattern in unique_patterns:
                    # Validate pattern structure
                    if not isinstance(pattern, dict) or "condition" not in pattern or "action" not in pattern:
                        continue
                        
                    # Create message for Learning Engine
                    message = EngineMessage(
                        source="orchestrator",
                        targets=["learning_engine"],
                        message_type=MessageType.PROPOSAL,
                        data={
                            "type": "rule",
                            "condition": pattern.get("condition"),
                            "action": pattern.get("action"),
                            "confidence": pattern.get("confidence", 0.5),
                            "domain": pattern.get("domain", "general"),
                            "rationale": f"Detected by L2 analysis (User: {user_id})"
                        },
                        priority=MessagePriority.NORMAL
                    )
                    await self.message_bus.publish(message)
            
            # Send unique insights directly
            if unique_insights:
                self.logger.info(f"L2 detected {len(unique_insights)} unique insights (deduplicated from {len(insights)}) - sending to Learning Engine")
                
                from aura.models.messages import EngineMessage, MessagePriority, MessageType
                
                for insight in unique_insights:
                    if not isinstance(insight, dict) or not insight.get("content"):
                        continue
                    
                    message = EngineMessage(
                        source="orchestrator",
                        targets=["learning_engine"],
                        message_type=MessageType.PROPOSAL,
                        data={
                            "type": "insight",
                            "content": insight.get("content"),
                            "insight_type": insight.get("type", "PATTERN"),
                            "confidence": insight.get("confidence", 0.5),
                            "domain": insight.get("domain", "general"),
                            "user_id": user_id,
                        },
                        priority=MessagePriority.NORMAL
                    )
                    await self.message_bus.publish(message)

        except Exception as e:
            self.logger.error(f"L2 analysis failed: {e}")

    async def stream_query(
        self,
        user_input: str,
        user_id: str = "default",
        conversation_history: list[dict[str, str]] | None = None,
        conversation_id: str | None = None,
        reasoning_enabled: bool | None = None,
        l2_reasoning_enabled: bool | None = None,
        deep_analysis_enabled: bool | None = None,
        session_id: str | None = None,
        context_mode: str = "deep_work",
        requester_role: str = "owner",
        venue: str = "app",
        turn_meta: dict[str, Any] | None = None,
    ):
        """
        Stream orchestrated response generation.

        This is the streaming entry point over :meth:`_turn_pipeline` (W2-10).
        It drives the pipeline with ``stream=True`` and yields the text of each
        ``delta`` event as it is produced; the final ``done`` event is ignored.

        Yields text chunks as they're generated. The three reasoning keyword
        args are deprecated and ignored (P2-42). If ``turn_meta`` is a dict it
        is filled with ``deep_reasoning``, ``tier`` and ``route`` before the
        stream ends.
        """
        note_deprecated_reasoning_controls([
            n for n, v in (
                ("reasoning_enabled", reasoning_enabled),
                ("l2_reasoning_enabled", l2_reasoning_enabled),
                ("deep_analysis_enabled", deep_analysis_enabled),
            ) if v is not None
        ])
        if turn_meta is not None:
            turn_meta.update(self._default_turn_meta())
        async for ev in self._turn_pipeline(
            user_input,
            user_id,
            conversation_history,
            stream=True,
            context_limit=None,
            conversation_id=conversation_id,
            session_id=session_id,
            context_mode=context_mode,
            requester_role=requester_role,
            venue=venue,
        ):
            if ev.kind == "delta":
                yield ev.text
            elif ev.kind == "done" and turn_meta is not None and ev.meta:
                turn_meta.update(ev.meta)

    async def _appraise_message(
        self,
        user_input: str,
        conversation_history: list[dict[str, str]] | None,
        venue: str,
        speaker: str,
    ) -> None:
        """
        Appraise the user's message using the new L4 appraisal pathway (W3-21, W3-22).
        
        Calls l4_appraise_message with history up to and including the user's message
        (not Aura's reply), then passes the result to emotion_engine.appraise.
        On failure: one warning log, no impulse, no fallback. No retry loop.
        """
        try:
            self.logger.info("Starting L4 message appraisal...")
            # Use L4 to appraise the user's message (history excludes Aura's reply)
            appraisal, user_state = await self.llm_layers.l4_appraise_message(
                user_input=user_input,
                recent_history=conversation_history or [],
                speaker=speaker,
            )
            
            # Create and send the appraisal event
            from aura.models.appraisal import AppraisalEvent
            event = AppraisalEvent(
                kind="message",
                source="conversation",
                appraisal=appraisal,
                user_state=user_state,
                person_id=speaker,
                venue=venue,
            )
            
            await self.emotion_engine.appraise(event)
            self.logger.info("✅ L4 message appraisal applied successfully")
            
        except Exception as e:
            # On failure: one warning log, no impulse, no fallback, no retry
            self.logger.warning(f"⚠️ L4 message appraisal failed: {e}")

    async def _apply_l4_emotion_analysis(
        self,
        user_input: str,
        aura_response: str,
        current_emotions: dict[str, float],
    ) -> None:
        """
        Apply emotional influence using L4 emotion analysis (legacy path).
        
        Uses LLM to analyze conversation and detect emotions, replacing heuristic detection.
        On failure: one warning log, no impulse, no fallback. No retry loop.
        """
        try:
            self.logger.info("Starting L4 emotion analysis...")
            # Use L4 to analyze emotions
            emotion_deltas = await self.llm_layers.l4_emotion_analysis(
                user_input=user_input,
                aura_response=aura_response,
                current_emotions=current_emotions,
            )
            
            if emotion_deltas:
                # Log what emotions were detected
                emotion_str = ", ".join([f"{k}={v:.2f}" for k, v in emotion_deltas.items()])
                self.logger.info(f"L4 detected emotions: {emotion_str}")
                
                # Apply detected emotions with appropriate intensity
                influence = EmotionInfluence(
                    source="conversation",
                    emotions=emotion_deltas,
                    intensity=0.6,
                    reason="L4 emotion analysis from conversation",
                )
                await self.emotion_engine.apply_influence(influence)
                self.logger.info(
                    f"✅ L4 emotion analysis applied: {len(emotion_deltas)} emotions influenced"
                )
            else:
                # When L4 returns nothing: log warning, apply nothing (T14 on the old path)
                self.logger.warning("⚠️ L4 emotion analysis returned no emotion deltas")
                
        except Exception as e:
            # On failure: one warning log, no impulse, no fallback
            self.logger.warning(f"⚠️ L4 emotion analysis failed: {e}")

    async def _assess_goal_progress(
        self,
        user_input: str,
        aura_response: str,
        active_goals: list[Goal],
        emotional_state: EmotionState,
    ) -> None:
        """
        Assess if the interaction made progress on any active goals.
        
        Uses L2 to analyze if Aura's response or the conversation topic
        relates to any active goals and updates progress accordingly.
        """
        if not active_goals:
            return
        
        try:
            # Build prompt for goal progress assessment
            goals_text = "\n".join([
                f"- {g.name} (ID: {g.goal_id}): {g.description} (type: {g.goal_type}, progress: {int(g.progress * 100)}%)"
                for g in active_goals[:5]
            ])
            
            prompt = f"""Analyze if this conversation interaction made progress toward any of Aura's active goals.

ACTIVE GOALS:
{goals_text}

CONVERSATION:
User: {user_input}
Aura: {aura_response}

CURRENT EMOTIONAL STATE:
{emotional_state.description}

TASK:
Determine if Aura's response or the conversation topic relates to any active goals.
For each relevant goal, assess if progress was made (even small progress counts).

Return ONLY a JSON object with this structure:
{{
  "goals_progress": [
    {{
      "goal_name": "exact goal name from list above",
      "relevance_score": 0.0-1.0,
      "progress_made": 0.0-0.1,
      "reasoning": "brief explanation of how this interaction relates to the goal"
    }}
  ]
}}

Only include goals where relevance_score > 0.5. Progress_made should be small (0.01-0.1) per interaction.
"""
            
            # Use L2 model directly via the structure layer (bypassing the specific "Reasoning" prompt)
            # We use the L2 model (Smart) but with the generic structure extractor
            goal_analysis = await self.llm_layers.l5_structure_analysis(
                prompt=prompt,
                system_instruction="Goal Progress Assessor",
                model=settings.active_l2_model  # Stack-aware, hot-swap safe
            )
            
            # The result is already a dict, so we don't need regex parsing anymore!
            if goal_analysis:
                progress_data = goal_analysis
                
                # Update goal progress
                for goal_progress in progress_data.get("goals_progress", []):
                    goal_name = goal_progress.get("goal_name", "")
                    goal_id_ref = goal_progress.get("goal_id", None) # Try to get ID if provided
                    progress_made = goal_progress.get("progress_made", 0.0)
                    reasoning = goal_progress.get("reasoning", "")
                    
                    # Find matching goal - prioritizing ID match, fallback to name
                    matching_goal = None
                    for goal in active_goals:
                        if goal_id_ref and goal.goal_id == goal_id_ref:
                            matching_goal = goal
                            break
                        if goal.name.lower() == goal_name.lower(): # Case-insensitive name match
                            matching_goal = goal
                            break
                    
                    if matching_goal:
                         # Ensure progress is always applied, even if small
                        # But cap max progress per interaction to prevent jumping to 100% too fast
                        actual_progress = max(0.01, min(progress_made, 0.2)) # Min 1%, max 20%
                        
                        new_progress = min(1.0, matching_goal.progress + actual_progress)
                        
                        await self.goal_engine.update_goal_progress(
                            matching_goal.goal_id,
                            new_progress,
                            f"Progress from conversation: {reasoning}"
                        )
                        self.logger.info(
                            f"[TARGET] Goal progress updated: {matching_goal.name} "
                            f"({int(matching_goal.progress * 100)}% → {int(new_progress * 100)}%)"
                        )
            
        except Exception as e:
            self.logger.debug(f"Goal progress assessment failed: {e}")

    async def _log_interaction_experience(
        self,
        user_id: str,
        user_input: str,
        aura_response: str,
        emotional_state: EmotionState,
        learning_context: LearningContext | None,
        speaker: str = "owner",
    ) -> str | None:
        """Log interaction as experience for learning. Returns the experience id."""
        try:
            # Include active rules in context if available
            context_data = {"user_query": user_input}
            if learning_context and learning_context.insights:
                context_data["active_insights"] = [i.insight_id for i in learning_context.insights]

            experience_data = {
                "user_id": user_id,
                "task_type": "conversation",
                "domain": "general",
                "context": context_data,
                "aura_response": {"response": aura_response},
                # Flag off: assume success. Flag on (G5-03): unknown until a later
                # owner turn shows otherwise; silence is never positive.
                "outcome": (
                    {"signal": "unknown", "success": None}
                    if settings.outcome_signals_enabled
                    else {"success": True}
                ),
                "emotional_state": {
                    "pre": emotional_state.vector.model_dump(),
                    "dominant": emotional_state.dominant[0],
                },
            }

            return await self.learning_engine.log_experience(experience_data)

        except Exception as e:
            self.logger.error(f"Failed to log experience: {e}")
            return None

