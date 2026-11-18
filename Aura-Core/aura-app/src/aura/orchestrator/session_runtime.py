"""SessionRuntime — owns Aura's parallel session state.

The runtime is the single source of truth for which sessions exist, which
agents are attached to which session, and what scope (memory namespace,
identity overlay, model overrides, tool allow/deny list) applies to each
agent's tool calls.

Persistence is delegated to SurrealDB via the existing db client. Live
agent attachments are kept in-memory only — they're rebuilt from running
AgentLoops on restart, not from disk.

**Important invariant:** the MAIN session is a singleton-equivalent
wrapper over the global engines and always exists. Calls without a
`session_id` are routed to MAIN. Aura's EmotionEngine remains shared
across every session unless `emotion_isolated=True` is explicitly set
(see `Session` model docstring for why we made this choice).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows, strip_record_id
from aura.models.session import (
    GLOBAL_NAMESPACE,
    MAIN_SESSION_ID,
    IdentityOverlay,
    Session,
    SessionContext,
    SessionMode,
    SessionStatus,
)

logger = logging.getLogger(__name__)


class SessionRuntimeError(Exception):
    """Domain error from SessionRuntime — routes turn these into 4xx."""


class ConcurrencyLimitError(SessionRuntimeError):
    """Raised when attaching an agent would exceed max_concurrent_agents."""


class SessionRuntime:
    """In-memory + DB-backed registry of Aura's sessions and agent attachments."""

    def __init__(self) -> None:
        self.db = get_db_client()
        self._sessions: dict[str, Session] = {}
        self._agents_by_session: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()
        self._initialised = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialise(self) -> None:
        """Idempotent startup: load persisted sessions and ensure MAIN exists."""
        async with self._lock:
            if self._initialised:
                return
            try:
                rows = await self.db.query(
                    """
                    SELECT * FROM session
                    WHERE status IN ['queued', 'active', 'paused']
                    """
                )
                for row in extract_rows(rows):
                    try:
                        session = Session(**strip_record_id(row))
                        self._sessions[session.session_id] = session
                        self._agents_by_session.setdefault(session.session_id, set())
                    except Exception as e:  # noqa: BLE001
                        logger.error(f"Failed to hydrate session row: {e}; row keys={list(row)}")
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Could not preload sessions (likely first boot): {e}")

            if MAIN_SESSION_ID not in self._sessions:
                main = Session.main()
                await self._persist(main)
                self._sessions[main.session_id] = main
                self._agents_by_session[main.session_id] = set()
                logger.info("Seeded MAIN session")

            self._initialised = True
            logger.info(
                f"SessionRuntime initialised with {len(self._sessions)} session(s) loaded"
            )

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_session(
        self,
        name: str,
        *,
        mode: SessionMode = SessionMode.SCOPED,
        owner: str = "default",
        parent_session_id: str | None = None,
        identity_overlay: IdentityOverlay | None = None,
        model_overrides: dict[str, str] | None = None,
        tool_allowlist: list[str] | None = None,
        tool_denylist: list[str] | None = None,
        max_concurrent_agents: int = 3,
        emotion_isolated: bool = False,
    ) -> Session:
        """Create and persist a new session. Reject MAIN re-creation."""
        if mode is SessionMode.MAIN:
            raise SessionRuntimeError(
                "MAIN session is a singleton; use get_session('main') instead"
            )
        session = Session.new_scoped(
            name=name,
            mode=mode,
            owner=owner,
            parent_session_id=parent_session_id,
            identity_overlay=identity_overlay,
            model_overrides=model_overrides,
            tool_allowlist=tool_allowlist,
            tool_denylist=tool_denylist,
            max_concurrent_agents=max_concurrent_agents,
        )
        if emotion_isolated:
            # Honour explicit override, but log the deviation from default.
            session.emotion_isolated = True
            logger.warning(
                f"Session {session.session_id} created with emotion_isolated=True "
                "— this is unusual; Aura's emotion is normally shared across sessions."
            )
        await self._persist(session)
        async with self._lock:
            self._sessions[session.session_id] = session
            self._agents_by_session[session.session_id] = set()
        logger.info(f"Created session {session.session_id} ({mode.value}) — {name!r}")
        return session

    async def get_session(self, session_id: str) -> Session | None:
        """Fetch a session by ID. Reads in-memory cache first, then DB."""
        async with self._lock:
            cached = self._sessions.get(session_id)
        if cached:
            return cached
        try:
            rows = await self.db.select(self._record_id(session_id))
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to fetch session {session_id}: {e}")
            return None
        for row in extract_rows(rows):
            try:
                session = Session(**strip_record_id(row))
                async with self._lock:
                    self._sessions[session.session_id] = session
                    self._agents_by_session.setdefault(session.session_id, set())
                return session
            except Exception as e:  # noqa: BLE001
                logger.error(f"Failed to hydrate session {session_id}: {e}")
                return None
        return None

    async def list_sessions(
        self,
        *,
        status: SessionStatus | None = None,
        owner: str | None = None,
        limit: int = 50,
    ) -> list[Session]:
        """List sessions ordered by created_at DESC."""
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            clauses.append("status = $status")
            params["status"] = status.value
        if owner is not None:
            clauses.append("owner = $owner")
            params["owner"] = owner
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            rows = await self.db.query(
                f"SELECT * FROM session {where} ORDER BY created_at DESC LIMIT $limit",
                params,
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"list_sessions failed: {e}")
            return []
        out: list[Session] = []
        for row in extract_rows(rows):
            try:
                out.append(Session(**strip_record_id(row)))
            except Exception as e:  # noqa: BLE001
                logger.warning(f"skipping malformed session row: {e}")
        return out

    async def update_session(
        self,
        session_id: str,
        patch: dict[str, Any],
    ) -> Session | None:
        """Apply a partial update. Forbids re-keying core invariants."""
        if session_id == MAIN_SESSION_ID:
            forbidden = {"mode", "memory_namespace", "session_id", "emotion_isolated"}
            if any(k in patch for k in forbidden):
                raise SessionRuntimeError(
                    "Cannot mutate core invariants of the MAIN session"
                )
        try:
            await self.db.merge(self._record_id(session_id), patch)
        except Exception as e:  # noqa: BLE001
            logger.error(f"update_session({session_id}) failed: {e}")
            return None
        async with self._lock:
            self._sessions.pop(session_id, None)  # force re-hydrate
        return await self.get_session(session_id)

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    async def start_session(self, session_id: str) -> Session | None:
        return await self._transition(session_id, SessionStatus.ACTIVE, started=True)

    async def pause_session(self, session_id: str) -> Session | None:
        if session_id == MAIN_SESSION_ID:
            raise SessionRuntimeError("MAIN session cannot be paused")
        return await self._transition(session_id, SessionStatus.PAUSED)

    async def resume_session(self, session_id: str) -> Session | None:
        return await self._transition(session_id, SessionStatus.ACTIVE)

    async def end_session(
        self,
        session_id: str,
        *,
        merge_emotion: bool = False,
        archive_memory: bool = True,
    ) -> Session | None:
        if session_id == MAIN_SESSION_ID:
            raise SessionRuntimeError("MAIN session cannot be ended")

        session = await self.get_session(session_id)
        if session is None:
            return None

        # --- Merge isolated emotion back to global (escape-hatch only) ---
        if merge_emotion and session.emotion_isolated and session.emotion_snapshot:
            try:
                from aura.engines.emotion.engine import EmotionEngine
                engine = EmotionEngine()
                await engine.merge_snapshot(session.emotion_snapshot)
                logger.info(f"Merged isolated emotion from session {session_id} back to global")
            except Exception as e:
                logger.warning(f"Failed to merge emotion for session {session_id}: {e}")

        # --- Archive or delete session-scoped memories ---
        if archive_memory and session.memory_namespace != GLOBAL_NAMESPACE:
            try:
                if session.mode == SessionMode.EPHEMERAL:
                    # Delete ephemeral memories entirely
                    await self.db.query(
                        "DELETE FROM memory WHERE namespace = $ns",
                        {"ns": session.memory_namespace},
                    )
                    logger.info(f"Deleted ephemeral memories for session {session_id} (ns={session.memory_namespace})")
                else:
                    # Mark SCOPED memories as archived
                    await self.db.query(
                        "UPDATE memory SET archived = true WHERE namespace = $ns",
                        {"ns": session.memory_namespace},
                    )
                    logger.info(f"Archived memories for session {session_id} (ns={session.memory_namespace})")
            except Exception as e:
                logger.warning(f"Failed to archive/delete memories for session {session_id}: {e}")

        # Abort any running agent loops in this session (V1PRD §4.7)
        try:
            from aura.api.routes.agent import _active_loops
            async with self._lock:
                attached = set(self._agents_by_session.get(session_id, set()))
            for task_id in list(attached):
                loop = _active_loops.get(task_id)
                if loop is not None:
                    try:
                        loop.abort()
                        logger.info(f"Aborted agent {task_id} during end_session({session_id})")
                    except Exception as e:
                        logger.warning(f"Failed to abort agent {task_id}: {e}")
        except ImportError:
            pass  # agent_routes not loaded yet; non-fatal

        async with self._lock:
            self._agents_by_session.pop(session_id, None)
        return await self._transition(session_id, SessionStatus.ENDED, ended=True)

    async def delete_session(self, session_id: str) -> Session | None:
        """Permanently delete a session after ending it (V1PRD §4.7)."""
        if session_id == MAIN_SESSION_ID:
            raise SessionRuntimeError("MAIN session cannot be deleted")
        # End first to stop any attached agents
        await self.end_session(session_id, archive_memory=False)
        # Remove from SurrealDB
        try:
            await self.db.delete(self._record_id(session_id))
        except Exception as e:
            logger.error(f"delete_session({session_id}) DB delete failed: {e}")
            return None
        async with self._lock:
            self._sessions.pop(session_id, None)
            self._agents_by_session.pop(session_id, None)
        logger.info(f"Deleted session {session_id}")
        # Return a stub so the route can serialize it
        session = await self.get_session(session_id)
        return session

    # ------------------------------------------------------------------
    # Agent attachment (in-memory only — rebuilt from running loops)
    # ------------------------------------------------------------------

    async def attach_agent(self, session_id: str, agent_id: str) -> SessionContext:
        """Register an agent in a session. Enforces max_concurrent_agents.

        Returns the SessionContext the caller should pass to ToolExecutor / AgentLoop.
        """
        session = await self.get_session(session_id)
        if session is None:
            raise SessionRuntimeError(f"unknown session: {session_id}")
        async with self._lock:
            slot = self._agents_by_session.setdefault(session_id, set())
            if agent_id not in slot and len(slot) >= session.max_concurrent_agents:
                raise ConcurrencyLimitError(
                    f"session {session_id} is at its agent cap ({session.max_concurrent_agents})"
                )
            slot.add(agent_id)
        logger.debug(f"Attached agent {agent_id} to session {session_id}")
        return SessionContext.from_session(session)

    async def detach_agent(self, session_id: str, agent_id: str) -> None:
        async with self._lock:
            slot = self._agents_by_session.get(session_id)
            if slot is not None:
                slot.discard(agent_id)

    async def list_attached_agents(self, session_id: str) -> list[str]:
        async with self._lock:
            return sorted(self._agents_by_session.get(session_id, set()))

    # ------------------------------------------------------------------
    # Convenience: derive context with defaults
    # ------------------------------------------------------------------

    async def context_for(self, session_id: str | None) -> SessionContext:
        """Return a SessionContext for the given session_id, defaulting to MAIN."""
        sid = session_id or MAIN_SESSION_ID
        session = await self.get_session(sid)
        if session is None:
            # Don't fabricate — caller passed a bogus id. Fall back to MAIN
            # but log loudly; this usually indicates a missed migration.
            logger.warning(f"context_for: unknown session_id={sid!r}; using MAIN")
            return SessionContext.main()
        return SessionContext.from_session(session)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_id(session_id: str) -> str:
        """Map a logical session_id to the SurrealDB record id."""
        if session_id == MAIN_SESSION_ID:
            return "session:main"
        # Already in `session:abc123` form?
        if session_id.startswith("session:"):
            return session_id
        return f"session:{session_id}"

    async def _persist(self, session: Session) -> None:
        """Insert-or-merge persistence for a Session record."""
        record_id = self._record_id(session.session_id)
        try:
            existing = await self.db.select(record_id)
            if existing:
                await self.db.merge(record_id, session.model_dump(mode="json"))
            else:
                payload = session.model_dump(mode="json")
                # SurrealDB create() takes the explicit record id; pop logical id.
                await self.db.create(record_id, payload)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to persist session {session.session_id}: {e}")

    async def _transition(
        self,
        session_id: str,
        status: SessionStatus,
        *,
        started: bool = False,
        ended: bool = False,
    ) -> Session | None:
        patch: dict[str, Any] = {"status": status.value}
        now = datetime.utcnow().isoformat()
        if started:
            patch["started_at"] = now
        if ended:
            patch["ended_at"] = now
        try:
            await self.db.merge(self._record_id(session_id), patch)
        except Exception as e:  # noqa: BLE001
            logger.error(f"_transition({session_id}, {status}) failed: {e}")
            return None
        async with self._lock:
            self._sessions.pop(session_id, None)
        return await self.get_session(session_id)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_session_runtime: SessionRuntime | None = None


def get_session_runtime() -> SessionRuntime:
    """Get the global SessionRuntime singleton (caller must `await initialise()` once)."""
    global _session_runtime
    if _session_runtime is None:
        _session_runtime = SessionRuntime()
    return _session_runtime
