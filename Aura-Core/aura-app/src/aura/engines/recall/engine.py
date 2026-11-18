"""Recall Engine — one entry point over today's channels (M2).

This module wires today's four read-path stores into the budgeted assembly step
from :mod:`aura.engines.recall.assembly`. The engine builds :class:`Candidate`
lists from each channel, calls :func:`assemble`, wraps the result blocks into a
:class:`ContextPacket`, and keeps a capped in-memory trace of recent turns.

The engine is the M2 milestone's "one entry point wrapping today's stores ...
no new retrieval logic" (PRD section 6.1): it does not add new queries, scoring,
gating or abstention. A failure in one channel records an entry in
``channel_errors`` and the turn goes on with the other channels, mirroring the
non-critical handlers in today's coordinator.

The engine reads only through the stores it is given — never through the
database directly (PRD 6.1).
"""

from __future__ import annotations

import collections
import logging
import uuid
from typing import Any

from aura.clock import get_clock
from aura.config import settings

from .assembly import assemble, normalise_text
from .models import (
    Block,
    BlockKind,
    Candidate,
    ContextPacket,
    RecallRequest,
    RecallTrace,
)
from .render import render_insights

logger = logging.getLogger(__name__)


class RecallEngine:
    """One entry point over today's memory channels (PRD 6.1, M2).

    Construct with explicit ``memory_manager`` / ``latent_engine`` dependencies,
    or leave them ``None`` to resolve lazily on first use through the module
    singletons (``aura.engines.memory.manager.get_memory_manager`` and
    ``aura.engines.latent.engine.get_latent_engine``). The lazy lookups go
    through the module attributes at call time so tests can monkeypatch them.
    """

    def __init__(self, memory_manager: Any = None, latent_engine: Any = None):
        self._memory_manager = memory_manager
        self._latent_engine = latent_engine
        self._traces: "collections.OrderedDict[str, RecallTrace]" = (
            collections.OrderedDict()
        )

    # ------------------------------------------------------------------
    # Lazy dependency resolution (looked up as module attributes at call time
    # so tests can monkeypatch ``aura.engines.memory.manager.get_memory_manager``
    # and ``aura.engines.latent.engine.get_latent_engine``).
    # ------------------------------------------------------------------

    async def _get_memory_manager(self) -> Any:
        if self._memory_manager is not None:
            return self._memory_manager
        # Looked up as a module attribute at call time so tests can monkeypatch
        # the module-level ``get_memory_manager`` function.
        from aura.engines.memory.manager import get_memory_manager

        self._memory_manager = get_memory_manager()
        return self._memory_manager

    def _get_latent_engine(self) -> Any:
        if self._latent_engine is not None:
            return self._latent_engine
        # Looked up as a module attribute at call time so tests can monkeypatch
        # the module-level ``get_latent_engine`` function.
        from aura.engines.latent.engine import get_latent_engine

        self._latent_engine = get_latent_engine()
        return self._latent_engine

    # ------------------------------------------------------------------
    # Recall — the one entry point
    # ------------------------------------------------------------------

    async def recall(self, request: RecallRequest) -> ContextPacket:
        """Build a :class:`ContextPacket` from today's channels.

        Each channel runs in its own ``try/except``. A failure records
        ``channel_errors[<channel>] = str(e)`` and the turn goes on with the
        other channels, mirroring the non-critical handlers today.
        """
        candidates: list[Candidate] = []
        channel_errors: dict[str, str] = {}

        renderers: dict[BlockKind, Any] = {}

        # --- insights channel ----------------------------------------
        try:
            insights_candidates, insights_renderer = self._build_insights(request)
            candidates.extend(insights_candidates)
            if insights_renderer is not None:
                renderers["insights"] = insights_renderer
        except Exception as e:  # pragma: no cover — defensive, non-critical
            channel_errors["insights"] = str(e)
            logger.debug("Recall insights channel failed (non-critical): %s", e)

        # --- latent channel ------------------------------------------
        try:
            latent_candidates, latent_renderer = self._build_latent(request)
            candidates.extend(latent_candidates)
            if latent_renderer is not None:
                renderers["latent"] = latent_renderer
        except Exception as e:  # pragma: no cover — defensive, non-critical
            channel_errors["latent"] = str(e)
            logger.debug("Recall latent channel failed (non-critical): %s", e)

        # --- cold_start channel --------------------------------------
        try:
            cold_candidates, cold_renderer = await self._build_cold_start(request)
            candidates.extend(cold_candidates)
            if cold_renderer is not None:
                renderers["cold_start"] = cold_renderer
        except Exception as e:  # pragma: no cover — defensive, non-critical
            channel_errors["cold_start"] = str(e)
            logger.debug("Recall cold_start channel failed (non-critical): %s", e)

        # --- memories channel ---------------------------------------
        try:
            memory_candidates, memory_renderer, cluster_data = await self._build_memories(
                request
            )
            candidates.extend(memory_candidates)
            if memory_renderer is not None:
                renderers["memories"] = memory_renderer
        except Exception as e:
            channel_errors["memories"] = str(e)
            logger.debug("Recall memories channel failed (non-critical): %s", e)

        # --- assemble ------------------------------------------------
        budget_tokens = request.token_budget or settings.recall_token_budget
        shares: dict[BlockKind, float] = {
            "insights": settings.recall_share_insights,
            "latent": settings.recall_share_latent,
            "cold_start": settings.recall_share_cold_start,
            "memories": settings.recall_share_memories,
        }

        blocks, trace_items, tokens_before, tokens_after = assemble(
            candidates=candidates,
            renderers=renderers,
            budget_tokens=budget_tokens,
            shares=shares,
            dedup=settings.recall_dedup_enabled,
            budget=settings.recall_budget_enabled,
        )

        stable_blocks: list[Block] = []
        dynamic_blocks: list[Block] = []
        for block in blocks:
            if block.kind == "cold_start":
                stable_blocks.append(block)
            else:
                dynamic_blocks.append(block)

        turn_id = uuid.uuid4().hex
        trace = RecallTrace(
            turn_id=turn_id,
            user_id=request.user_id,
            query=request.user_input,
            created_at=get_clock().now(),
            budget_tokens=budget_tokens,
            tokens_before=tokens_before,
            tokens_after=tokens_after,
            items=trace_items,
            channel_errors=channel_errors,
        )
        self._store_trace(trace)

        return ContextPacket(
            stable_blocks=stable_blocks,
            dynamic_blocks=dynamic_blocks,
            abstain=False,
            trace=trace,
        )

    # ------------------------------------------------------------------
    # Channel builders
    # ------------------------------------------------------------------

    def _build_insights(
        self, request: RecallRequest
    ) -> tuple[list[Candidate], Any]:
        """Insights channel: one candidate per insight in the learning context.

        The renderer is :func:`render_insights`, which does not re-cut the list
        (the caller passes it already cut to ``[:8]``). Returns ``([], None)``
        when the request has no learning context or it has no insights.
        """
        learning_context = request.learning_context
        if learning_context is None:
            return [], None
        insights = getattr(learning_context, "insights", None)
        if not insights:
            return [], None
        mastery_level = getattr(learning_context, "mastery_level", 0.0) or 0.0
        cut = list(insights)[:8]
        candidates: list[Candidate] = []
        for rank, insight in enumerate(cut):
            key = getattr(insight, "insight_id", None) or str(rank)
            content = getattr(insight, "content", "") or ""
            candidates.append(
                Candidate(
                    block="insights",
                    key=key,
                    dedup_keys=("text:" + normalise_text(content),),
                    payload=insight,
                    rank=rank,
                    source="learning.get_learning_context",
                )
            )

        def _renderer(payloads: list[Any]) -> str:
            return render_insights(payloads, mastery_level)

        return candidates, _renderer

    def _build_latent(self, request: RecallRequest) -> tuple[list[Candidate], Any]:
        """Latent channel: one candidate if the latent engine returns XML.

        ``include_latent=False`` skips the channel entirely (the latent engine
        is never called). Returns ``([], None)`` when the latent engine returns
        no XML.
        """
        if not request.include_latent:
            return [], None
        latent_engine = self._get_latent_engine()
        xml = latent_engine.get_intuition_context(request.user_id)
        if not xml:
            return [], None
        candidate = Candidate(
            block="latent",
            key="latent",
            dedup_keys=(),
            payload=xml,
            rank=0,
            source="latent.get_intuition_context",
        )

        def _renderer(payloads: list[Any]) -> str:
            if not payloads:
                return ""
            return payloads[0]

        return [candidate], _renderer

    async def _build_cold_start(
        self, request: RecallRequest
    ) -> tuple[list[Candidate], Any]:
        """Cold-start channel: core, recent and top-insight candidates.

        ``include_cold_start=False`` skips the channel entirely (the memory
        manager's ``get_cold_start_context`` is never awaited). The renderer
        rebuilds the cold-start XML via ``memory_manager._format_cold_start_xml``
        so the wrapper is still present when the lists are empty — today's
        "block present whenever the channel ran".
        """
        if not request.include_cold_start:
            return [], None
        memory_manager = await self._get_memory_manager()
        cold = await memory_manager.get_cold_start_context(request.user_id)

        core_memories = list(getattr(cold, "core_memories", []) or [])
        recent_memories = list(getattr(cold, "recent_memories", []) or [])
        top_insights = list(getattr(cold, "top_insights", []) or [])
        active_cultural_node = getattr(cold, "active_cultural_node", None)

        candidates: list[Candidate] = []
        rank = 0
        for m in core_memories:
            memory_id = getattr(m, "memory_id", None) or f"core:{rank}"
            content = getattr(m, "content", "") or ""
            candidates.append(
                Candidate(
                    block="cold_start",
                    key=memory_id,
                    dedup_keys=("mem:" + memory_id, "text:" + normalise_text(content)),
                    payload=("core", m),
                    rank=rank,
                    source="memory.get_cold_start_context",
                )
            )
            rank += 1
        for m in recent_memories:
            memory_id = getattr(m, "memory_id", None) or f"recent:{rank}"
            content = getattr(m, "content", "") or ""
            candidates.append(
                Candidate(
                    block="cold_start",
                    key=memory_id,
                    dedup_keys=("mem:" + memory_id, "text:" + normalise_text(content)),
                    payload=("recent", m),
                    rank=rank,
                    source="memory.get_cold_start_context",
                )
            )
            rank += 1
        for i, d in enumerate(top_insights):
            content = (d.get("content") if isinstance(d, dict) else "") or ""
            candidates.append(
                Candidate(
                    block="cold_start",
                    key=f"cold_insight:{i}",
                    dedup_keys=("text:" + normalise_text(content),),
                    payload=("insight", d),
                    rank=rank,
                    source="memory.get_cold_start_context",
                )
            )
            rank += 1

        def _renderer(payloads: list[Any]) -> str:
            core: list[Any] = []
            recent: list[Any] = []
            insights: list[Any] = []
            for tag, item in payloads:
                if tag == "core":
                    core.append(item)
                elif tag == "recent":
                    recent.append(item)
                elif tag == "insight":
                    insights.append(item)
            return memory_manager._format_cold_start_xml(
                core, recent, insights, active_cultural_node
            )

        return candidates, _renderer

    async def _build_memories(
        self, request: RecallRequest
    ) -> tuple[list[Candidate], Any, dict[str, dict]]:
        """Memories channel: retrieved memories via ``retrieve_for_l3_parts``.

        The renderer calls ``memory_manager._format_memories_xml`` on the kept
        payloads (in the same order) using the cluster data gathered during
        retrieval. Returns ``([], None, {})`` when no memories are found.
        """
        memory_manager = await self._get_memory_manager()
        emotional_state = request.emotional_state
        current_emotions: dict[str, float] | None = None
        if emotional_state is not None:
            vector = getattr(emotional_state, "vector", None)
            if vector is not None:
                try:
                    current_emotions = vector.model_dump()
                except Exception:
                    current_emotions = None
        memories, cluster_data = await memory_manager.retrieve_for_l3_parts(
            query=request.user_input,
            current_emotions=current_emotions,
            user_id=request.user_id,
            limit=request.limit,
            namespace=request.namespace,
            depth=request.depth,
        )
        if not memories:
            return [], None, {}

        candidates: list[Candidate] = []
        for rank, m in enumerate(memories):
            memory_id = getattr(m, "memory_id", None) or f"memory:{rank}"
            content = getattr(m, "content", "") or ""
            candidates.append(
                Candidate(
                    block="memories",
                    key=memory_id,
                    dedup_keys=("mem:" + memory_id, "text:" + normalise_text(content)),
                    payload=m,
                    rank=rank,
                    source="memory.retrieve_for_l3",
                )
            )

        def _renderer(payloads: list[Any]) -> str:
            if not payloads:
                return ""
            return memory_manager._format_memories_xml(payloads, cluster_data)

        return candidates, _renderer, cluster_data

    # ------------------------------------------------------------------
    # Trace storage
    # ------------------------------------------------------------------

    def _store_trace(self, trace: RecallTrace) -> None:
        """Store a trace, evicting the oldest past ``recall_trace_keep``."""
        keep = settings.recall_trace_keep
        self._traces[trace.turn_id] = trace
        self._traces.move_to_end(trace.turn_id)
        while len(self._traces) > keep:
            self._traces.popitem(last=False)

    def get_trace(self, turn_id: str) -> RecallTrace | None:
        """Return the stored trace for ``turn_id``, or ``None`` if it was
        evicted or never stored."""
        return self._traces.get(turn_id)

    # ------------------------------------------------------------------
    # Recall tools (W2-22): delegate to MemoryManager for L2 internal tools
    # ------------------------------------------------------------------

    async def timeline(
        self,
        experience_id: str,
        steps: int = 3,
        direction: str = "forward",
    ) -> list[dict[str, Any]]:
        """Delegate to MemoryManager.traverse_timeline.

        This is the Recall Engine's entry point for the ``traverse_timeline``
        internal tool (PRD 6.4, M2 fifth injector). It returns the result
        unchanged so the orchestrator's formatting stays the same.
        """
        memory_manager = await self._get_memory_manager()
        return await memory_manager.traverse_timeline(
            experience_id=experience_id,
            steps=steps,
            direction=direction,
        )

    async def evidence(
        self,
        insight_id: str,
    ) -> list[dict[str, Any]]:
        """Delegate to MemoryManager.fetch_supporting_evidence.

        This is the Recall Engine's entry point for the ``fetch_supporting_evidence``
        internal tool (PRD 6.4, M2 fifth injector). It returns the result
        unchanged so the orchestrator's formatting stays the same.
        """
        memory_manager = await self._get_memory_manager()
        return await memory_manager.fetch_supporting_evidence(insight_id=insight_id)


# =============================================================================
# SINGLETON
# =============================================================================

_recall_engine: RecallEngine | None = None


def get_recall_engine() -> RecallEngine:
    """Get the global :class:`RecallEngine` singleton.

    Matches the pattern of :func:`aura.engines.memory.manager.get_memory_manager`.
    """
    global _recall_engine
    if _recall_engine is None:
        _recall_engine = RecallEngine()
    return _recall_engine
