"""
Dreaming Engine - Deep graph analysis and memory consolidation.

While the user is away, Aura traverses the graph to find "Cause and Effect"
patterns that L2 misses in the heat of the moment.

Session 5 upgrade — the dreaming cycle is now a full cognitive maintenance pass:
- Tiered pruning: ephemeral hard-delete, faded soft-delete, core immunity
- Abstraction: synthesize 5+ similar episodic memories into a single semantic memory
- Emotional reprocessing: turn negative memories into learning insights
- REM Sleep: existing trial-and-error pattern extraction
- Consolidation report: stored as a system memory for self-reflection
"""

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.engines.base import BaseEngine
from aura.models.memory import DreamConsolidationReport

if TYPE_CHECKING:
    from aura.llm.layers import LLMLayers
    from aura.orchestrator.protocols import MessageBusProtocol

logger = logging.getLogger(__name__)

# Decay constant for determining "effectively faded" memories
_DECAY_THRESHOLD = 0.05
_RECENCY_HALF_LIFE_H = 48.0


class DreamingEngine(BaseEngine):
    """
    Dreaming Engine for deep graph analysis and memory consolidation.

    Session 5: upgraded from simple pruning to a full cognitive maintenance pass
    with tiered pruning, abstraction, emotional reprocessing, and self-reporting.
    """

    def __init__(self) -> None:
        """Initialize dreaming engine."""
        super().__init__("dreaming_engine")

        # Database
        self.db = get_db_client()

        # External dependencies (set by orchestrator)
        self._llm_layers: "LLMLayers | None" = None
        self._learning_engine: Any = None

        # State
        self.last_dream_cycle: datetime | None = None
        # Config-driven interval (default: 6 hours)
        self.dream_interval = float(os.getenv("DREAM_INTERVAL", "21600.0"))

    def set_dependencies(
        self,
        llm_layers: "LLMLayers | None" = None,
        learning_engine: Any = None,
    ) -> None:
        """Set external dependencies."""
        if llm_layers:
            self._llm_layers = llm_layers
        if learning_engine:
            self._learning_engine = learning_engine

    async def initialize(self) -> None:
        """Initialize engine resources."""
        self.logger.info("Initializing Dreaming Engine...")
        self.logger.info("Dreaming Engine initialized")

    async def tick(self) -> None:
        """Execute dreaming engine cycles on a timer."""
        while True:
            try:
                now = datetime.now(timezone.utc)

                should_dream = False
                if self.last_dream_cycle is None:
                    should_dream = True
                else:
                    elapsed = (now - self.last_dream_cycle).total_seconds()
                    if elapsed >= self.dream_interval:
                        should_dream = True

                if should_dream:
                    await self.enter_rem_sleep()
                    self.last_dream_cycle = now

                await asyncio.sleep(3600.0)

            except Exception as e:
                self.logger.error(f"Error in dreaming engine tick: {e}", exc_info=True)
                await asyncio.sleep(60.0)

    async def shutdown(self) -> None:
        """Clean up engine resources."""
        self.logger.info("Shutting down Dreaming Engine...")

    # =========================================================================
    # MAIN DREAMING CYCLE
    # =========================================================================

    async def enter_rem_sleep(self) -> DreamConsolidationReport:
        """
        Full cognitive maintenance pass (REM Sleep).

        Phases:
        1. Tiered pruning — dissolve noise, preserve signal
        2. Abstraction — synthesize episodic clusters into semantic memories
        3. Emotional reprocessing — turn negative memories into wisdom
        4. Causal weaving — create next_experience edges for orphaned nodes
        5. Trial-and-error pattern extraction (original REM)
        6. Store consolidation report as system memory
        """
        self.logger.info("[SLEEP] Entering REM Sleep (Full Cognitive Maintenance)...")

        report = DreamConsolidationReport()

        # Phase 1: Tiered Pruning
        try:
            report.pruned = await self._tiered_pruning()
        except Exception as e:
            self.logger.error(f"Tiered pruning failed: {e}", exc_info=True)

        # Phase 2: Abstraction
        if self._llm_layers:
            try:
                report.abstracted = await self._abstract_episodic_clusters()
            except Exception as e:
                self.logger.error(f"Abstraction failed: {e}", exc_info=True)

        # Phase 3: Emotional reprocessing
        if self._llm_layers and self._learning_engine:
            try:
                report.reprocessed = await self._emotional_reprocessing()
            except Exception as e:
                self.logger.error(f"Emotional reprocessing failed: {e}", exc_info=True)

        # Phase 4: Causal weaving — link orphaned experience nodes (Session 6)
        try:
            edges_created = await self._weave_causality()
            if edges_created > 0:
                self.logger.info(f"[LINK] Causal weaving: created {edges_created} next_experience edges")
        except Exception as e:
            self.logger.error(f"Causal weaving failed: {e}", exc_info=True)

        # Phase 5: Original trial-and-error REM
        if self._llm_layers and self._learning_engine:
            try:
                await self._rem_trial_and_error()
            except Exception as e:
                self.logger.error(f"Trial-and-error REM failed: {e}", exc_info=True)

        # Compute summary stats
        try:
            core_result = await self.db.query(
                "SELECT count() FROM memory WHERE core_memory = true AND deprecated = false GROUP ALL"
            )
            report.core_memories = core_result[0].get("count", 0) if core_result else 0

            active_result = await self.db.query(
                "SELECT count() FROM memory WHERE deprecated = false GROUP ALL"
            )
            report.total_active = active_result[0].get("count", 0) if active_result else 0
        except Exception as e:
            self.logger.debug(f"Failed to compute summary stats: {e}")

        # Phase 6: Store report as system memory
        await self._store_dream_report(report)

        self.logger.info(
            f"✨ Dream cycle complete: pruned={report.pruned}, abstracted={report.abstracted}, "
            f"reprocessed={report.reprocessed}, core={report.core_memories}, "
            f"total_active={report.total_active}"
        )
        return report

    # =========================================================================
    # PHASE 1: TIERED PRUNING
    # =========================================================================

    async def _tiered_pruning(self) -> int:
        """Tiered pruning that respects memory hierarchy.

        Rules:
        - ephemeral=True, older than 24h, 0 recalls → hard delete
        - ephemeral=True, older than 7 days regardless → hard delete
        - core_memory=True → never touched

        Non-ephemeral memories are never deleted by age here. Retrieval
        ranking still uses decay (see ``_compute_decay``), so faded
        memories naturally sink out of view without being removed.
        """
        pruned = 0
        now = get_clock().now()
        cutoff_24h = (now - timedelta(hours=24)).isoformat()
        cutoff_7d = (now - timedelta(days=7)).isoformat()

        # Tier 1: ephemeral, >24h, 0 recalls → hard delete
        try:
            tier1 = await self.db.query(
                """
                SELECT id FROM memory
                WHERE ephemeral = true
                  AND timestamp < $cutoff
                  AND recall_count = 0
                  AND deprecated = false
                  AND memory_type != 'semantic'
                LIMIT 200
                """,
                {"cutoff": cutoff_24h},
            )
            for row in (tier1 or []):
                mid = row.get("id")
                if mid:
                    await self.db.delete(str(mid))
                    pruned += 1
        except Exception as e:
            self.logger.warning(f"Tier 1 pruning error: {e}")

        # Tier 2: ephemeral, >7 days → hard delete regardless of recall count
        try:
            tier2 = await self.db.query(
                """
                SELECT id FROM memory
                WHERE ephemeral = true
                  AND timestamp < $cutoff
                  AND deprecated = false
                  AND memory_type != 'semantic'
                LIMIT 200
                """,
                {"cutoff": cutoff_7d},
            )
            for row in (tier2 or []):
                mid = row.get("id")
                if mid:
                    await self.db.delete(str(mid))
                    pruned += 1
        except Exception as e:
            self.logger.warning(f"Tier 2 pruning error: {e}")

        if pruned > 0:
            self.logger.info(f"[CLEAN] Tiered pruning: {pruned} memories dissolved")
        return pruned

    @staticmethod
    def _compute_decay(row: dict[str, Any]) -> float:
        """Lightweight decay computation for pruning decisions."""
        # Semantic memories never fade (memory PRD F4)
        if row.get("memory_type") == "semantic":
            return 1.0
        ts = row.get("timestamp")
        if not ts:
            return 0.0
        if isinstance(ts, str):
            try:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                return 0.0
        if isinstance(ts, datetime) and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        age_hours = max((get_clock().now() - ts).total_seconds() / 3600, 0)
        half_life = _RECENCY_HALF_LIFE_H

        emo = float(row.get("emotional_intensity", 0.0))
        if emo > 0.7:
            half_life *= 4.0

        recalls = int(row.get("recall_count", 0))
        half_life += recalls * 12.0

        if row.get("ephemeral"):
            half_life /= 4.0

        half_life = max(half_life, 0.1)
        return math.exp(-0.693 * age_hours / half_life)

    # =========================================================================
    # PHASE 2: ABSTRACTION — Episodic → Semantic
    # =========================================================================

    async def _abstract_episodic_clusters(self) -> int:
        """Find clusters of 5+ similar episodic memories and synthesize into semantic memories.

        Uses L5 to generate a single general insight from the cluster, then:
        - Creates a new memory with memory_type='semantic' and higher importance
        - Links source memories via ->abstracted_into-> edges
        - Marks source memories as deprecated
        """
        if not self._llm_layers:
            return 0

        abstracted = 0

        try:
            # Fetch non-deprecated episodic memories with embeddings
            candidates = await self.db.query(
                """
                SELECT id, content, embedding, tags, user_id, importance, timestamp
                FROM memory
                WHERE memory_type = 'episodic'
                  AND deprecated = false
                  AND core_memory = false
                  AND embedding != NONE
                ORDER BY timestamp DESC
                LIMIT 200
                """
            )
            if not candidates or len(candidates) < 5:
                return 0

            # Greedy clustering by cosine similarity > 0.80
            processed: set[str] = set()

            for i, primary in enumerate(candidates):
                pid = str(primary.get("id", ""))
                if not pid or pid in processed:
                    continue
                p_emb = primary.get("embedding")
                if not p_emb:
                    continue

                cluster_ids: list[str] = [pid]
                cluster_contents: list[str] = [primary.get("content", "")]
                cluster_user = primary.get("user_id", "default")

                for j, candidate in enumerate(candidates):
                    if i == j:
                        continue
                    cid = str(candidate.get("id", ""))
                    if not cid or cid in processed:
                        continue
                    c_emb = candidate.get("embedding")
                    if not c_emb:
                        continue

                    sim = self._cosine_sim(p_emb, c_emb)
                    if sim > 0.80:
                        cluster_ids.append(cid)
                        cluster_contents.append(candidate.get("content", ""))

                if len(cluster_ids) < 5:
                    continue

                # Synthesize via L5
                content_block = "\n".join(f"- {c[:200]}" for c in cluster_contents[:10])
                prompt = f"""These {len(cluster_ids)} experiences share a common pattern. Synthesize them into a single general insight.

EXPERIENCES:
{content_block}

Return a JSON object:
{{"synthesis": "one-paragraph general insight summarizing the pattern"}}"""

                try:
                    result = await self._llm_layers.l5_structure_analysis(
                        prompt=prompt,
                        system_instruction="You are a memory consolidation engine. Synthesize episodic memories into general semantic knowledge.",
                    )
                    synthesis = result.get("synthesis", "")
                    if not synthesis:
                        continue
                except Exception as e:
                    self.logger.warning(f"L5 abstraction failed: {e}")
                    continue

                # Create semantic memory
                from aura.engines.memory.manager import get_memory_manager
                mm = get_memory_manager()
                sem_id = await mm.store_memory(
                    content=synthesis,
                    user_id=cluster_user,
                    importance=0.8,
                    tags=["semantic", "abstracted"],
                )

                # Mark the new memory as semantic type
                await self.db.merge(sem_id, {"memory_type": "semantic"})

                # Link sources and deprecate them
                for src_id in cluster_ids:
                    try:
                        await self.db.query(
                            "RELATE $from->abstracted_into->$to",
                            {"from": src_id, "to": sem_id},
                        )
                        await self.db.merge(src_id, {"deprecated": True})
                        processed.add(src_id)
                    except Exception:
                        pass

                abstracted += 1
                self.logger.info(
                    f"[DNA] Abstracted {len(cluster_ids)} memories → {sem_id}"
                )

        except Exception as e:
            self.logger.error(f"Abstraction phase error: {e}", exc_info=True)

        return abstracted

    # =========================================================================
    # PHASE 3: EMOTIONAL REPROCESSING — Turning Pain into Wisdom
    # =========================================================================

    async def _emotional_reprocessing(self) -> int:
        """Reprocess negative memories older than 48h into learning insights.

        For memories with high negative valence (frustration, confusion, failure),
        an L2 call asks "what can be learned from this?" and stores the result
        as a PATTERN insight. The source memory's importance is reduced.
        This is how Aura turns bad experiences into wisdom instead of rumination.
        """
        if not self._llm_layers or not self._learning_engine:
            return 0

        reprocessed = 0
        cutoff = (get_clock().now() - timedelta(hours=48)).isoformat()

        # Negative emotions we look for
        negative_emotions = [
            "frustration", "confusion", "anger", "sadness", "fear",
            "shame", "doubt", "disgust",
        ]

        try:
            # Find memories with high negative emotional signatures, older than 48h,
            # that haven't been learned from yet
            neg_memories = await self.db.query(
                """
                SELECT id, content, emotional_signature, importance, user_id
                FROM memory
                WHERE deprecated = false
                  AND learned_from = false
                  AND timestamp < $cutoff
                  AND emotional_intensity > 0.5
                LIMIT 20
                """,
                {"cutoff": cutoff},
            )

            for row in (neg_memories or []):
                emo_sig = row.get("emotional_signature", {})
                if not isinstance(emo_sig, dict):
                    continue

                # Check if this memory has significant negative emotion
                neg_total = sum(emo_sig.get(e, 0.0) for e in negative_emotions)
                if neg_total < 0.4:
                    continue

                content = row.get("content", "")
                mid = str(row.get("id", ""))
                user_id = row.get("user_id", "default")

                # Ask L2: what can be learned?
                try:
                    analysis = await self._llm_layers.l2_reasoning(
                        interaction={
                            "user_input": f"[Dream Reprocessing] This memory carries negative emotions: {content[:300]}",
                            "aura_response": "Reflecting on what can be learned from this difficult experience.",
                            "emotion_before": emo_sig,
                            "emotion_after": {},
                        }
                    )

                    lesson = (analysis.get("analysis") or "").strip()
                    if not lesson or len(lesson) < 20:
                        continue

                    # Store as PATTERN insight
                    await self._learning_engine.create_insight({
                        "content": lesson,
                        "type": "PATTERN",
                        "domain": "emotional_reprocessing",
                        "user_id": user_id,
                        "confidence": 0.65,
                        "source_experiences": [],
                    })

                    # Reduce source memory's importance and mark as learned
                    old_imp = float(row.get("importance", 0.5))
                    await self.db.merge(mid, {
                        "importance": max(0.1, old_imp * 0.6),
                        "learned_from": True,
                    })

                    reprocessed += 1
                    self.logger.info(f"[MOON] Reprocessed negative memory {mid} into wisdom")

                except Exception as e:
                    self.logger.debug(f"Reprocessing failed for {mid}: {e}")
                    continue

        except Exception as e:
            self.logger.error(f"Emotional reprocessing error: {e}", exc_info=True)

        return reprocessed

    # =========================================================================
    # PHASE 4: ORIGINAL REM — Trial-and-Error Pattern Extraction
    # =========================================================================

    async def _rem_trial_and_error(self) -> None:
        """Find trial-and-error patterns and extract insights (original REM logic)."""
        query = """
        SELECT
            id,
            context.user_query as prompt,
            aura_response as failure_response,
            ->next_experience->id as next_id,
            ->next_experience->context.user_query as next_prompt,
            ->next_experience->aura_response as success_response,
            ->next_experience->outcome as next_outcome
        FROM experience
        WHERE outcome.success = false
        AND ->next_experience->outcome.success = true
        LIMIT 10;
        """

        sequences = await self.db.query(query)

        # Filter out error strings returned by DB client for missing tables
        sequences = [s for s in sequences if isinstance(s, dict)]

        if not sequences:
            self.logger.info("No trial-and-error patterns found in this cycle")
            return

        self.logger.info(f"Found {len(sequences)} trial-and-error sequences to analyze")

        for seq in sequences:
            try:
                exp_id = seq.get("id", "")
                next_id = seq.get("next_id", "")
                prompt = seq.get("prompt", "")
                failure_response = seq.get("failure_response", {})
                success_response = seq.get("success_response", {})

                failure_text = str(failure_response.get("response", ""))[:200] if isinstance(failure_response, dict) else str(failure_response)[:200]
                success_text = str(success_response.get("response", ""))[:200] if isinstance(success_response, dict) else str(success_response)[:200]

                dream_prompt = f"""Dream Analysis:
I failed when trying to answer: "{prompt}"
My failure: {failure_text}...
My success (immediately after): {success_text}...

What did I learn? Extract a one-sentence rule or pattern from this trial-and-error sequence."""

                interaction = {
                    "user_input": dream_prompt,
                    "aura_response": f"Failure: {failure_text[:150]}...\nSuccess: {success_text[:150]}...",
                    "emotion_before": {},
                    "emotion_after": {},
                }

                analysis = await self._llm_layers.l2_reasoning(interaction)

                if analysis and analysis.get("analysis"):
                    insight_text = analysis["analysis"].strip()

                    domain_result = await self.db.query(
                        "SELECT domain, user_id FROM experience WHERE id = $id",
                        {"id": exp_id},
                    )
                    domain = "general"
                    user_id = "default"
                    if domain_result:
                        domain = domain_result[0].get("domain", "general")
                        user_id = domain_result[0].get("user_id", "default")

                    await self._learning_engine.create_insight({
                        "content": insight_text,
                        "type": "PATTERN",
                        "domain": domain,
                        "user_id": user_id,
                        "confidence": 0.7,
                        "source_experiences": [str(exp_id), str(next_id)],
                    })
                    self.logger.info(f"✨ Extracted insight: {exp_id} → {next_id}")

            except Exception as e:
                self.logger.error(f"Error processing sequence: {e}", exc_info=True)
                continue

    # =========================================================================
    # CONSOLIDATION REPORT
    # =========================================================================

    async def _store_dream_report(self, report: DreamConsolidationReport) -> None:
        """Store the dream consolidation report as a system memory for self-reflection."""
        try:
            from aura.engines.memory.manager import get_memory_manager
            mm = get_memory_manager()

            summary = (
                f"Dream cycle completed: pruned {report.pruned} faded memories, "
                f"abstracted {report.abstracted} episodic clusters into semantic memories, "
                f"reprocessed {report.reprocessed} negative memories into wisdom. "
                f"{report.core_memories} core memories remain untouched. "
                f"{report.total_active} total active memories."
            )

            await mm.store_memory(
                content=summary,
                user_id="system",
                importance=0.6,
                tags=["dream_report", "system"],
            )
            self.logger.info(f"[MEMO] Dream report stored as system memory")
        except Exception as e:
            self.logger.warning(f"Failed to store dream report: {e}")

    # =========================================================================
    # PHASE 4: CAUSAL WEAVING — Autonomous Edge Generation (Session 6)
    # =========================================================================

    async def _weave_causality(self) -> int:
        """Create next_experience edges between orphaned experience nodes.

        An "orphaned" node is an experience that has NO outgoing next_experience
        edge.  This method finds such nodes from the last 24 hours, groups them
        by user_id, orders them by timestamp, and creates temporal edges between
        consecutive pairs within the same session window (< 30 min gap).

        This ensures the dreaming engine *actively constructs* the causal graph
        that L2's traverse_timeline() tool navigates — the graph doesn't just
        wait for real-time ingestion to build itself.

        Returns:
            Number of edges created.
        """
        edges_created = 0
        cutoff = (get_clock().now() - timedelta(hours=24)).isoformat()

        try:
            # Find experiences from the last 24h that have NO outgoing next_experience edge.
            # A node is "orphaned" if no next_experience edge starts from it.
            orphans = await self.db.query(
                """
                SELECT id, user_id, timestamp
                FROM experience
                WHERE timestamp > $cutoff
                  AND id NOT IN (SELECT in FROM next_experience)
                ORDER BY user_id, timestamp ASC
                LIMIT 500
                """,
                {"cutoff": cutoff},
            )

            if not orphans or len(orphans) < 2:
                return 0

            # Group by user_id
            from collections import defaultdict
            user_groups: dict[str, list[dict]] = defaultdict(list)
            for row in orphans:
                if not isinstance(row, dict):
                    continue
                uid = row.get("user_id", "default")
                user_groups[uid].append(row)

            # For each user, link consecutive experiences if gap < 30 minutes
            max_gap_ms = 30 * 60 * 1000  # 30 minutes in ms

            for uid, exps in user_groups.items():
                if len(exps) < 2:
                    continue

                for i in range(len(exps) - 1):
                    current = exps[i]
                    next_exp = exps[i + 1]

                    cur_id = str(current.get("id", ""))
                    next_id = str(next_exp.get("id", ""))
                    if not cur_id or not next_id:
                        continue

                    # Parse timestamps and compute gap
                    cur_ts = current.get("timestamp")
                    next_ts = next_exp.get("timestamp")

                    if isinstance(cur_ts, str):
                        try:
                            cur_ts = datetime.fromisoformat(cur_ts.replace("Z", "+00:00"))
                        except Exception:
                            continue
                    if isinstance(next_ts, str):
                        try:
                            next_ts = datetime.fromisoformat(next_ts.replace("Z", "+00:00"))
                        except Exception:
                            continue

                    if not isinstance(cur_ts, datetime) or not isinstance(next_ts, datetime):
                        continue

                    # Ensure both are UTC-aware
                    if cur_ts.tzinfo is None:
                        cur_ts = cur_ts.replace(tzinfo=timezone.utc)
                    if next_ts.tzinfo is None:
                        next_ts = next_ts.replace(tzinfo=timezone.utc)

                    elapsed_ms = int((next_ts - cur_ts).total_seconds() * 1000)

                    # Only link if within session window (30 min)
                    if elapsed_ms > max_gap_ms or elapsed_ms < 0:
                        continue

                    # Check if edge already exists (defensive — the NOT IN above
                    # should handle it, but edge creation might race)
                    existing = await self.db.query(
                        """
                        SELECT id FROM next_experience
                        WHERE in = $from AND out = $to
                        LIMIT 1
                        """,
                        {"from": cur_id, "to": next_id},
                    )
                    if existing:
                        continue

                    # Create the temporal edge
                    try:
                        await self.db.query(
                            """
                            RELATE $from->next_experience->$to
                            SET elapsed_ms = $elapsed
                            """,
                            {"from": cur_id, "to": next_id, "elapsed": elapsed_ms},
                        )
                        edges_created += 1
                    except Exception as e:
                        self.logger.debug(f"Failed to create causal edge {cur_id}->{next_id}: {e}")

        except Exception as e:
            self.logger.error(f"_weave_causality error: {e}", exc_info=True)

        return edges_created

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _cosine_sim(v1: list[float], v2: list[float]) -> float:
        """Cosine similarity between two float vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 <= 0 or n2 <= 0:
            return 0.0
        return dot / (n1 * n2)

