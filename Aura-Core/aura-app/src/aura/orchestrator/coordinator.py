"""
Meta-Cognitive Orchestrator (Cognitive PRD Section 3).

Coordinates all engines, handles conflicts, maintains coherence.
"""

import json
import logging
import asyncio
from dataclasses import dataclass
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
from aura.engines.recall.models import ContextPacket, RecallRequest
from aura.engines.reflection.engine import ReflectionEngine
from aura.executor.tool_executor import ToolExecutor
from aura.llm.layers import LLMLayers, SynthesisContext
from aura.models.emotion import EmotionInfluence, EmotionState
from aura.models.goal import GoalContext, Goal
from aura.models.learning import LearningContext
from aura.models.messages import EngineMessage
from aura.orchestrator.message_bus import MessageBus

logger = logging.getLogger(__name__)


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


@dataclass
class TurnEvent:
    """One event in the ``_turn_pipeline`` stream (W2-10).

    ``delta`` events carry a text chunk (one character for an early reply,
    one streamed chunk during generation, including the ``"\\n\\n"`` round
    separators). ``done`` carries the full accumulated response.
    """

    kind: Literal["delta", "done"]
    text: str


class SystemState(str, Enum):
    """High-level system state for Sleep/Wake cycle management."""

    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    DREAMING = "DREAMING"
    SLEEPING = "SLEEPING"


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

    async def _resolve_session(self, session_id: str | None) -> None:
        """
        Resolve session → memory namespace + identity overlay (V1PRD §4).

        Caller may pass session_id=None for backward compatibility; that
        routes to MAIN, and namespace stays None → retrieval reads everything.
        """
        session_namespace: str | None = None
        session_overlay = None
        if session_id and session_id != "main":
            try:
                from aura.orchestrator.session_runtime import get_session_runtime
                ctx = await get_session_runtime().context_for(session_id)
                session_namespace = (
                    ctx.memory_namespace if ctx.memory_namespace != "global" else None
                )
                session_overlay = ctx.identity_overlay
            except Exception as e:  # noqa: BLE001
                self.logger.warning(f"Could not resolve session {session_id!r}: {e}")
        self._current_session_namespace = session_namespace
        self._current_identity_overlay = session_overlay

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
        self, user_input: str, user_id: str, stream: bool
    ) -> tuple[dict[str, Any], str, str | None]:
        """
        L1 intent classification, telemetry, keyword fallback, and the
        teaching fast lane. Returns ``(intent_data, intent, teaching_reply)``.
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
            "model": settings.l1_model,
        }
        if stream:
            trace_payload["mode"] = "stream"
        self._publish_trace("L1", "intent_classified", trace_payload)

        # FALLBACK: If intent classification failed or returned empty, try keyword-based detection
        if not intent_data or intent == "CHAT":
            # Check for tool-use keywords as fallback
            tool_keywords = ["search", "stock", "price", "weather", "current", "latest", "now", "today", "find", "look up"]
            user_lower = user_input.lower()
            if any(keyword in user_lower for keyword in tool_keywords):
                self.logger.info(f"[MAG] Fallback: Keyword-based TOOL_USE detection triggered")
                intent = "TOOL_USE"
                intent_data["intent"] = "TOOL_USE"
                intent_data["confidence"] = 0.7
                intent_data["needs_agentic_rag"] = True
                # Try to detect which tool
                if "search" in user_lower or "stock" in user_lower or "price" in user_lower:
                    intent_data["detected_tool"] = "web_search"

        # 1. TEACHING FAST LANE (Existing)
        if intent == "TEACHING":
            self.logger.info("[BRAIN] L1 detected Teaching Intent - Routing to Learning Engine")

            # Create a "Teaching Experience"
            experience_data = {
                "user_id": user_id,
                "task_type": "instruction",  # Matches the fix we made in Learning Engine
                "domain": "coding",  # Or infer from L1
                "context": {"user_query": user_input},
                "metadata": {"intent": "teaching"}
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
        ))

    async def _gather_turn_context(
        self,
        user_input: str,
        user_id: str,
        conversation_history: list[dict[str, str]] | None,
        stream: bool,
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
                ))
            except Exception as e:
                self.logger.warning(f"Recall engine failed (non-critical): {e}")
                packet = None

            cold_start_xml = packet.block_text("cold_start") if packet else None
            latent_intuition_xml = packet.block_text("latent") if packet else None
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
            ))
        except Exception as e:
            self.logger.warning(f"Recall engine failed (non-critical): {e}")
            packet = None

        cold_start_xml = packet.block_text("cold_start") if packet else None
        latent_intuition_xml = packet.block_text("latent") if packet else None
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
        """Run the blocking L3 generation with a bounded tool loop (W2-09).

        Moved verbatim from ``process_query``. Returns the post-processed
        response, including the tool-call stripping and the max-rounds suffix.
        """

        # Step 5: Generate response (L3)
        context_window_size = context_limit if context_limit is not None else 20
        self.logger.info(f"[TARGET] Using context window size: {context_window_size} messages")

        # Step 5: Generate response (L3) with a bounded tool-execution loop.
        # This enables multi-step tool plans (read -> write -> verify) safely.
        self.logger.info(
            f"[MAG] Tool mode check: use_forced_tool_mode={use_forced_tool_mode}, tool_schema_str={'present' if tool_schema_str else 'None'}"
        )

        max_tool_rounds = 5
        tool_history_blocks: list[str] = []

        def _build_loop_input() -> str:
            if not tool_history_blocks:
                return user_input
            return f"{user_input}\n\n[Tool Execution Results]\n" + "\n\n".join(tool_history_blocks)

        # Optional: seed with deterministic tool call when forced mode is available.
        if use_forced_tool_mode and tool_schema_str:
            self.logger.info("[WRENCH] Using FORCED TOOL CALL MODE to seed the tool loop")
            raw_tool_call = await self.llm_layers.l3_tool_call_mode(query=user_input, tool_schema=tool_schema_str)
            self.logger.info(f"[BOX] Raw tool call from forced mode: {raw_tool_call[:300]}...")
            seed_calls = self.tool_executor.extract_tool_calls(raw_tool_call)
            if seed_calls:
                seed_results = await self.tool_executor.execute_and_feedback(seed_calls, requester_role=requester_role)
                if seed_results:
                    tool_history_blocks.append(f"[Seed]\n{seed_results}")
            else:
                self.logger.warning("⚠️ Forced tool call mode produced no valid tool calls; proceeding with normal tool loop")

        response = ""
        for round_idx in range(1, max_tool_rounds + 1):
            loop_context = SynthesisContext(
                user_input=_build_loop_input(),
                conversation_history=conversation_history or [],
                emotional_state=ctx.emotional_state,
                learning_context=ctx.learning_context,
                identity_context=ctx.identity_context,
                goal_context=ctx.goal_context,
                recent_critique=ctx.recent_critique,
                packet=ctx.packet,
            )

            response = await self.llm_layers.l3_synthesis(
                loop_context,
                max_history_messages=context_window_size,
                reasoning_enabled=reasoning_enabled,
            )
            # --- Telemetry: L3 synthesis complete ---
            self._publish_trace("L3", "synthesis_complete", {
                "model": settings.l3_model,
                "round": round_idx,
                "response_len": len(response or ""),
                "reasoning": reasoning_enabled,
            })

            tool_calls = self.tool_executor.extract_tool_calls(response)
            if not tool_calls:
                response = self._remove_tool_calls_from_text(response)
                break

            self.logger.info(f"[WRENCH] Tool loop round {round_idx}: detected {len(tool_calls)} tool call(s)")
            tool_results = await self.tool_executor.execute_and_feedback(tool_calls, requester_role=requester_role)
            if not tool_results:
                response = self._remove_tool_calls_from_text(response)
                break

            tool_history_blocks.append(f"[Round {round_idx}]\n{tool_results}")

        else:
            # Guard: stop after max rounds to avoid infinite loops.
            response = self._remove_tool_calls_from_text(response)
            response += "\n\n(Stopped after max tool rounds; ask me to continue if needed.)"

        return response

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
        """Run the streaming L3 generation with forced-mode/fallback/loop (W2-09).

        Moved verbatim from ``stream_query``. Yields ``(chunk, counts)`` tuples:
        ``counts`` is ``True`` for real response text and ``False`` for the
        ``"\\n\\n"`` separators, so the caller can rebuild today's
        ``full_response`` (which excluded those separators) by accumulating only
        the counted chunks.
        """
        # If forced tool mode is enabled, use it to generate JSON tool call first
        if use_forced_tool_mode and tool_schema_str:
            self.logger.info("[WRENCH] Using FORCED TOOL CALL MODE to generate JSON tool call (streaming)")

            # Generate the tool call JSON using deterministic mode (no persona)
            raw_tool_call = await self.llm_layers.l3_tool_call_mode(
                query=user_input,
                tool_schema=tool_schema_str
            )

            # Parse the raw_tool_call (should be pure JSON)
            tool_calls = self.tool_executor.extract_tool_calls(raw_tool_call)

            if tool_calls:
                self.logger.info(f"✅ Extracted {len(tool_calls)} tool call(s) from forced mode")

                # EXECUTE THE TOOL
                tool_output = await self.tool_executor.execute_and_feedback(tool_calls, requester_role=requester_role)

                # Log the tool output for debugging
                self.logger.info(f"[WRENCH] Tool execution completed. Output length: {len(tool_output) if tool_output else 0} chars")
                if tool_output:
                    self.logger.debug(f"[WRENCH] Tool output (first 500 chars): {tool_output[:500]}")
                else:
                    self.logger.warning("⚠️ Tool output is empty! Tool may have failed silently.")

                # FINAL L3 SYNTHESIS - Now pass the tool output back to L3 (Grok) to synthesize the persona response
                # CRITICAL: Use explicit instructions so L3 knows to use the tool output, not generate its own
                ctx.synthesis_context.user_input = f"""I executed a tool for you. Here are the REAL results from the tool execution:

{tool_output}

Your task: Synthesize a natural, persona-driven response based on these ACTUAL tool results. Do NOT generate fake tool output or simulate tool execution. Use ONLY the results provided above.

Original user query: {user_input}"""

                self.logger.info(f"[WRENCH] Passing tool output to L3 synthesis. Updated user_input length: {len(ctx.synthesis_context.user_input)} chars")
                self.logger.debug(f"[WRENCH] Tool output being passed to L3 (first 300 chars): {tool_output[:300] if tool_output else 'EMPTY'}")

                # Stream the final persona-driven response with tool results
                async for chunk in self.llm_layers.stream_l3_synthesis(ctx.synthesis_context, reasoning_enabled=reasoning_enabled):
                    yield chunk, True
            else:
                # Fallback: if forced mode failed, try regular streaming
                self.logger.warning("⚠️ Forced tool call mode failed to generate valid JSON, falling back to regular L3 streaming")
                full_response = ""
                async for chunk in self.llm_layers.stream_l3_synthesis(ctx.synthesis_context, reasoning_enabled=reasoning_enabled):
                    full_response += chunk
                    yield chunk, True

                # Still try to extract tool calls from regular response as fallback
                tool_calls = self.tool_executor.extract_tool_calls(full_response)
                if tool_calls:
                    self.logger.info(f"[WRENCH] Detected {len(tool_calls)} tool call(s) in fallback streamed response")
                    tool_results = await self.tool_executor.execute_and_feedback(tool_calls, requester_role=requester_role)

                    if tool_results:
                        follow_up_input = f"{user_input}\n\n[Tool Execution Results]\n{tool_results}"
                        follow_up_context = SynthesisContext(
                            user_input=follow_up_input,
                            conversation_history=conversation_history or [],
                            emotional_state=ctx.emotional_state,
                            learning_context=ctx.learning_context,
                            identity_context=ctx.identity_context,
                            goal_context=ctx.goal_context,
                            packet=ctx.packet,
                        )

                        yield "\n\n", False
                        async for chunk in self.llm_layers.stream_l3_synthesis(follow_up_context, reasoning_enabled=reasoning_enabled):
                            yield chunk, True
        else:
            # Regular flow: multi-round streaming tool loop (read -> write -> verify)
            max_tool_rounds = 5
            tool_history_blocks: list[str] = []

            def _build_loop_input() -> str:
                if not tool_history_blocks:
                    return user_input
                return f"{user_input}\n\n[Tool Execution Results]\n" + "\n\n".join(tool_history_blocks)

            for round_idx in range(1, max_tool_rounds + 1):
                loop_context = SynthesisContext(
                    user_input=_build_loop_input(),
                    conversation_history=conversation_history or [],
                    emotional_state=ctx.emotional_state,
                    learning_context=ctx.learning_context,
                    identity_context=ctx.identity_context,
                    goal_context=ctx.goal_context,
                    packet=ctx.packet,
                )

                round_response = ""
                async for chunk in self.llm_layers.stream_l3_synthesis(
                    loop_context, reasoning_enabled=reasoning_enabled
                ):
                    round_response += chunk
                    yield chunk, True

                tool_calls = self.tool_executor.extract_tool_calls(round_response)
                if not tool_calls:
                    break

                self.logger.info(
                    f"[WRENCH] Tool loop round {round_idx} (streaming): detected {len(tool_calls)} tool call(s)"
                )
                tool_results = await self.tool_executor.execute_and_feedback(tool_calls, requester_role=requester_role)
                if not tool_results:
                    break

                tool_history_blocks.append(f"[Round {round_idx}]\n{tool_results}")
                yield "\n\n", False

    async def _turn_pipeline(
        self,
        user_input: str,
        user_id: str,
        conversation_history: list[dict[str, str]] | None,
        *,
        stream: bool,
        context_limit: int | None,
        enable_l2: bool,
        conversation_id: str | None,
        reasoning_enabled: bool,
        l2_reasoning_enabled: bool,
        session_id: str | None,
        context_mode: str,
        requester_role: str,
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

        During streaming generation every chunk is yielded as a ``delta``
        (separators included); the post-response chain is scheduled before the
        ``done`` event so it still runs only after the last delta has been
        consumed, as today.
        """
        # Stage 1: set the LLM router context mode.
        self.llm_layers.context_mode = context_mode  # type: ignore[assignment]

        # Stage 2: resolve the session namespace and identity overlay.
        await self._resolve_session(session_id)

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

        # Stage 4: L1 intent classification, telemetry, keyword fallback, teaching lane.
        intent_data, intent, teaching_reply = await self._classify_intent(
            user_input, user_id, stream=stream
        )
        if teaching_reply is not None:
            if stream:
                for char in teaching_reply:
                    yield TurnEvent("delta", char)
                yield TurnEvent("done", teaching_reply)
            else:
                yield TurnEvent("done", teaching_reply)
            return

        # Stage 5: forced-tool resolution (tool reflex fast lane).
        use_forced_tool_mode, tool_schema_str = await self._resolve_forced_tool(intent, intent_data)

        # Stage 6: gather engine context (emotion/learning/identity/goal + memory).
        ctx = await self._gather_turn_context(user_input, user_id, conversation_history, stream=stream)

        # Stage 7: cache the system prompt for debugging (before synthesis).
        await self._cache_system_prompt(ctx.synthesis_context, user_input, user_id)

        # Stage 8: generation (streaming or blocking).
        if stream:
            full_response = ""
            async for chunk, counts in self._generate_streaming(
                user_input,
                conversation_history,
                ctx,
                reasoning_enabled,
                use_forced_tool_mode,
                tool_schema_str,
                requester_role,
            ):
                # Yield every chunk as a delta (separators included); accumulate
                # only the counted chunks so ``full_response`` matches today.
                yield TurnEvent("delta", chunk)
                if counts:
                    full_response += chunk
            response = full_response
        else:
            response = await self._generate_blocking(
                user_input,
                conversation_history,
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
        )

        # Stage 10: yield the final done event with the accumulated response.
        yield TurnEvent("done", response)

    async def process_query(
        self,
        user_input: str,
        user_id: str = "default",
        conversation_history: list[dict[str, str]] | None = None,
        context_limit: int | None = None,
        enable_l2_analysis: bool | None = None,
        conversation_id: str | None = None,
        reasoning_enabled: bool = False,
        l2_reasoning_enabled: bool = False,
        deep_analysis_enabled: bool = True,
        session_id: str | None = None,
        context_mode: str = "deep_work",
        requester_role: str = "owner",
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
        """
        self.logger.info(f"Processing query from user {user_id} (session={session_id or 'main'})")

        # Use deep_analysis_enabled if provided, otherwise fall back to
        # enable_l2_analysis for backward compatibility.
        final_l2_enabled = deep_analysis_enabled if enable_l2_analysis is None else enable_l2_analysis

        response = ""
        async for ev in self._turn_pipeline(
            user_input,
            user_id,
            conversation_history,
            stream=False,
            context_limit=context_limit,
            enable_l2=final_l2_enabled,
            conversation_id=conversation_id,
            reasoning_enabled=reasoning_enabled,
            l2_reasoning_enabled=l2_reasoning_enabled,
            session_id=session_id,
            context_mode=context_mode,
            requester_role=requester_role,
        ):
            if ev.kind == "done":
                response = ev.text
        return response

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
    ) -> None:
        """
        Execute post-response tasks in correct dependency order.
        
        Order:
        1. L4 Emotion Analysis (Must complete first)
        2. Log Experience
        3. L2 Deep Analysis (Needs updated emotional state)
        """

        # 1. Apply L4 Emotion Analysis (Critical for state update)
        # Respects layer_l4_enabled toggle from inference cockpit.
        if settings.layer_l4_enabled:
            await self._apply_l4_emotion_analysis(
                user_input=user_input,
                aura_response=response,
                current_emotions=emotional_before.vector.model_dump(),
            )
        
        # 2. Log Experience (Now captured with potential new emotional state)
        # We need to get the FRESH state
        emotional_current = await self.emotion_engine.get_current_state()
        
        await self._log_interaction_experience(
            user_id=user_id,
            user_input=user_input,
            aura_response=response,
            emotional_state=emotional_current,
            learning_context=learning_context,
        )
        
        # 3. Run L2 Analysis (if enabled AND L2 layer not bypassed via inference cockpit)
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
                "model": settings.l2_model,
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
        reasoning_enabled: bool = False,
        l2_reasoning_enabled: bool = False,
        deep_analysis_enabled: bool = True,
        session_id: str | None = None,
        context_mode: str = "deep_work",
        requester_role: str = "owner",
    ):
        """
        Stream orchestrated response generation.

        This is the streaming entry point over :meth:`_turn_pipeline` (W2-10).
        It drives the pipeline with ``stream=True`` and yields the text of each
        ``delta`` event as it is produced; the final ``done`` event is ignored.

        Yields text chunks as they're generated.
        """
        async for ev in self._turn_pipeline(
            user_input,
            user_id,
            conversation_history,
            stream=True,
            context_limit=None,
            enable_l2=deep_analysis_enabled,
            conversation_id=conversation_id,
            reasoning_enabled=reasoning_enabled,
            l2_reasoning_enabled=l2_reasoning_enabled,
            session_id=session_id,
            context_mode=context_mode,
            requester_role=requester_role,
        ):
            if ev.kind == "delta":
                yield ev.text

    async def _apply_l4_emotion_analysis(
        self,
        user_input: str,
        aura_response: str,
        current_emotions: dict[str, float],
    ) -> None:
        """
        Apply emotional influence using L4 emotion analysis (async).
        
        Uses LLM to analyze conversation and detect emotions, replacing heuristic detection.
        Includes retry logic for robustness.
        """
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                self.logger.info(f"Starting L4 emotion analysis (attempt {attempt+1})...")
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
                    return # Success
                else:
                    self.logger.warning(f"⚠️ L4 emotion analysis returned no emotion deltas (attempt {attempt+1})")
                    if attempt == max_retries:
                         # Fallback to heuristic detection if L4 returns nothing after retries
                         await self._apply_conversation_influence_fallback(user_input, aura_response)
                    
            except Exception as e:
                self.logger.error(f"❌ L4 emotion analysis failed (attempt {attempt+1}): {e}")
                if attempt == max_retries:
                    # Fallback to heuristic detection if L4 fails
                    await self._apply_conversation_influence_fallback(user_input, aura_response)

    async def _apply_conversation_influence_fallback(
        self, user_input: str, aura_response: str
    ) -> None:
        """
        Fallback heuristic emotion detection (used if L4 fails).
        
        Kept as backup for reliability.
        """
        emotions = {}
        user_lower = user_input.lower()
        response_lower = aura_response.lower()

        # Positive words increase joy/interest
        positive_words = ["happy", "great", "love", "wonderful", "excited", "thank", "yes", "absolutely"]
        if any(word in user_lower for word in positive_words):
            emotions["joy"] = 0.15
            emotions["interest"] = 0.1

        # Surprise triggers
        surprise_words = ["wow", "amazing", "incredible", "unexpected", "show me", "reveal", "discover"]
        surprise_phrases = ["i want to see", "i want to understand", "show me", "let me see"]
        if any(word in user_lower for word in surprise_words) or any(phrase in user_lower for phrase in surprise_phrases):
            emotions["surprise"] = 0.2
            emotions["curiosity"] = 0.15

        # Anticipation triggers (use interest + curiosity instead of anticipation)
        anticipation_words = ["waiting", "expect", "anticipate", "eager", "excited", "ready", "want to"]
        anticipation_phrases = ["i want", "i need", "can't wait", "looking forward"]
        if any(word in user_lower for word in anticipation_words) or any(phrase in user_lower for phrase in anticipation_phrases):
            emotions["interest"] = max(emotions.get("interest", 0), 0.2)
            emotions["curiosity"] = max(emotions.get("curiosity", 0), 0.15)

        # Questions increase curiosity
        if "?" in user_input:
            emotions["curiosity"] = max(emotions.get("curiosity", 0), 0.12)

        # Intensity/excitement in response
        intensity_words = ["electric", "sharpens", "crystallizing", "vast", "blueprint", "architecture"]
        if any(word in response_lower for word in intensity_words):
            emotions["interest"] = max(emotions.get("interest", 0), 0.15)
            emotions["fascination"] = max(emotions.get("fascination", 0), 0.1)

        # Apply if we detected any emotions
        if emotions:
            emotion_str = ", ".join([f"{k}={v:.2f}" for k, v in emotions.items()])
            self.logger.info(f"Fallback heuristic detection: {emotion_str}")
            influence = EmotionInfluence(
                source="conversation",
                emotions=emotions,
                intensity=0.4,
                reason="Fallback heuristic detection",
            )
            await self.emotion_engine.apply_influence(influence)
            self.logger.info(f"✅ Fallback emotion influence applied: {len(emotions)} emotions")
        else:
            self.logger.debug("Fallback heuristic detection found no emotions")
    
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

    def _remove_tool_calls_from_text(self, text: str) -> str:
        """
        Remove tool call JSON blocks from text to clean up the response.
        
        Args:
            text: Text that may contain tool call JSON blocks
            
        Returns:
            Text with tool call blocks removed
        """
        import re
        
        # Remove JSON code blocks that look like tool calls
        text = re.sub(r'```(?:json)?\s*\{[^{}]*"tool"[^{}]*\}\s*```', '', text, flags=re.DOTALL)
        
        # Remove inline tool call JSON objects
        text = re.sub(r'\{[^{}]*"tool"[^{}]*\}', '', text, flags=re.DOTALL)
        
        # Clean up extra whitespace
        text = re.sub(r'\n\s*\n\s*\n', '\n\n', text)
        
        return text.strip()
    
    async def _log_interaction_experience(
        self,
        user_id: str,
        user_input: str,
        aura_response: str,
        emotional_state: EmotionState,
        learning_context: LearningContext | None,
    ) -> None:
        """Log interaction as experience for learning."""
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
                "outcome": {"success": True},  # Assume success if no error
                "emotional_state": {
                    "pre": emotional_state.vector.model_dump(),
                    "dominant": emotional_state.dominant[0],
                },
            }

            await self.learning_engine.log_experience(experience_data)

        except Exception as e:
            self.logger.error(f"Failed to log experience: {e}")

