"""Memory Manager - Multi-signal retrieval with emotional resonance.

Based on PRD Section 5.6 (Memory Engine - The Librarian).

Retrieval signals (scored & weighted):
  1. Semantic similarity  (vector cosine)         — 0.40
  2. Emotional resonance  (27D cosine similarity)  — 0.30
  3. Importance           (stored weight)           — 0.10
  4. Recency              (exponential decay)       — 0.10
  5. Fuzzy text match     (substring hit bonus)     — 0.10

Session 5 enhancements:
  - Formation scoring: novelty, emotional intensity, depth, surprise
  - Nuanced decay: emotional protection, access strengthening, core immunity
  - Spreading activation: multi-hop associative retrieval
  - Cold start context: instant warm-up on new conversations
  - Memory introspection: Aura knows what she remembers
  - FormationContext: memories know where they were born

Session 6 enhancements (AGI Memory Architecture):
  - Thought Clusters: retrieve_for_l3() builds contextual clusters via multi-hop
    graph traversal (chronological + conceptual grounding) in a single pass.
  - Mood-Congruent Retrieval: 27D cosine similarity between live EmotionState
    and memory emotional_signature, weighted at 0.30.
  - L2 Active Recall: traverse_timeline() and fetch_supporting_evidence()
    let the reasoning engine navigate the graph autonomously.

JIT design: retrieve_for_l3() does one DB round-trip and returns
pre-formatted XML context that plugs straight into the L3 system prompt.
"""

import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.db.query_utils import to_record_id
from aura.engines.memory.v2.salience import interaction_depth
from aura.config import settings
from aura.llm.embeddings import get_embeddings_client
from aura.models.memory import (
    ColdStartContext,
    DreamConsolidationReport,
    FormationContext,
    Memory,
    MemoryIntrospection,
)

logger = logging.getLogger(__name__)

# Scoring weights — tuned for mood-congruent conversational recall (Session 6)
W_SEMANTIC   = 0.40
W_EMOTION    = 0.30   # ↑ from 0.25 — mood-congruent retrieval
W_IMPORTANCE = 0.10   # ↓ from 0.15 — freed weight for emotion
W_RECENCY    = 0.10
W_FUZZY      = 0.10

# Recency half-life in hours (memories older than this get halved score)
RECENCY_HALF_LIFE_H = 48.0

# Formation score thresholds
FORMATION_EPHEMERAL_THRESHOLD = 0.25
FORMATION_CORE_THRESHOLD = 0.75

# Decay tuning
EMOTIONAL_PROTECTION_INTENSITY = 0.7   # Memories above this get 4x half-life
EMOTIONAL_HALFLIFE_MULTIPLIER = 4.0
ACCESS_STRENGTHEN_HOURS = 12.0          # Each recall extends half-life by this
EPHEMERAL_DECAY_MULTIPLIER = 4.0       # Ephemeral memories decay 4x faster

# Spreading activation
SPREADING_DECAY = 0.6                  # Neighbor score = seed_score * this
# Nomic nomic-embed-text-v1.5 (768-dim) produces a denser cosine space than
# OpenAI's 1536-dim model.  0.78 prevents over-connected "hairball" graphs by
# ensuring edges form only on highly semantically relevant memory pairs.
RELATED_EDGE_THRESHOLD = 0.78          # Cosine similarity to create related_to edge


def _parse_ts(ts: datetime | str | None) -> datetime | None:
    """Normalize a timestamp to a timezone-aware datetime."""
    if ts is None:
        return None
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


# All 27 emotion dimensions in canonical order (matches EmotionVector model)
_ALL_EMOTION_DIMS = (
    "joy", "love", "interest", "trust", "fear", "sadness", "anger",
    "surprise", "disgust", "awe", "beauty", "wonder", "serenity",
    "melancholy", "nostalgia", "empathy", "gratitude", "pride",
    "shame", "envy", "compassion", "curiosity", "confusion",
    "certainty", "doubt", "fascination", "boredom",
)


def _emotion_resonance(sig_a: dict[str, float], sig_b: dict[str, float]) -> float:
    """
    Full 27-dimensional cosine similarity between two emotion signatures.

    Both vectors are projected into the canonical 27D emotion space; missing
    dimensions are treated as 0.0.  This ensures mood-congruent retrieval:
    when Aura is frustrated she recalls other frustrating memories, even if
    only 3 of the 27 dimensions are non-zero.

    Returns a value in [0.0, 1.0].
    """
    if not sig_a or not sig_b:
        return 0.0
    dot = 0.0
    mag_a = 0.0
    mag_b = 0.0
    for dim in _ALL_EMOTION_DIMS:
        a = sig_a.get(dim, 0.0)
        b = sig_b.get(dim, 0.0)
        dot += a * b
        mag_a += a * a
        mag_b += b * b
    mag_a = math.sqrt(mag_a) or 1.0
    mag_b = math.sqrt(mag_b) or 1.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def _fuzzy_match_score(query: str, content: str) -> float:
    """Simple fuzzy substring match. Returns 0-1."""
    if not query or not content:
        return 0.0
    q_lower = query.lower()
    c_lower = content.lower()
    # Direct substring
    if q_lower in c_lower:
        return 1.0
    # Word overlap ratio
    q_words = set(re.findall(r'\w{3,}', q_lower))
    c_words = set(re.findall(r'\w{3,}', c_lower))
    if not q_words:
        return 0.0
    overlap = len(q_words & c_words)
    return min(1.0, overlap / len(q_words))


def _compute_emotional_intensity(signature: dict[str, float]) -> float:
    """Compute the RMS of active (>0.1) emotion dimensions, clamped to [0,1].

    Unlike the old L2-magnitude-over-27-dims formula, this lets an emotionally
    intense event reach 1.0 instead of being capped well below it.
    """
    if not signature:
        return 0.0
    active = [v for v in signature.values() if v >= 0.1]
    if not active:
        return 0.0
    rms = math.sqrt(sum(v * v for v in active) / len(active))
    return max(0.0, min(1.0, rms))


def _truncate_for_inject(content: str) -> str:
    """Truncate a memory's content to ``settings.memory_inject_max_chars`` for
    injection into L3 prompts, appending ``...`` when it is cut. This only
    affects what is injected — what is stored is never truncated.
    """
    max_chars = settings.memory_inject_max_chars
    if max_chars <= 0 or not content:
        return content or ""
    if len(content) <= max_chars:
        return content
    return content[:max_chars] + "..."


class MemoryManager:
    """
    Memory management with multi-signal hybrid search.

    Not just a DB — a living cognitive substrate.
    Uses SurrealDB's vector index (MTREE COSINE) for semantic search,
    then re-ranks with emotional resonance, nuanced decay, importance,
    and fuzzy match.  Formation scoring gates what enters long-term memory.
    Spreading activation enables associative recall.
    """

    def __init__(self) -> None:
        self.db = get_db_client()
        self.embeddings = get_embeddings_client()

    # =========================================================================
    # FORMATION SCORING — Stop Storing Noise
    # =========================================================================

    async def _compute_formation_score(
        self,
        content: str,
        embedding: list[float],
        emotional_signature: dict[str, float],
        user_id: str | None,
        response_length: int = 0,
        reasoning_steps: int = 0,
        tool_calls: int = 0,
        pre_retrieval_ids: list[str] | None = None,
    ) -> float:
        """
        Compute how worthy this interaction is of becoming a lasting memory.

        Combines four signals:
        - **Novelty** (0.30): cosine distance from 5 most recent memories.
          If similarity > 0.88 with any, score is heavily penalized.
        - **Emotional intensity** (0.30): magnitude of the emotional state
          vector at formation time. Flat moments → weak memories.
        - **Interaction depth** (0.20): derived from response length,
          reasoning steps, tool calls. Shallow exchanges score low.
        - **Surprise** (0.20): distance between pre-retrieval set and
          actual outcome. High surprise → high formation score.

        Returns:
            formation_score in [0.0, 1.0]
        """
        # --- Novelty ---
        novelty = 1.0
        try:
            conditions = ["deprecated = false"]
            params: dict[str, Any] = {"emb": embedding}
            if user_id:
                conditions.append("user_id = $user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)
            recent = await self.db.query(
                f"""
                SELECT embedding,
                       vector::similarity::cosine(embedding, $emb) AS sim
                FROM memory
                WHERE {where}
                ORDER BY sim DESC
                LIMIT 5
                """,
                params,
            )
            if recent and embedding:
                for row in recent:
                    sim = row.get("sim")
                    if sim is None:
                        continue
                    sim = float(sim)
                    if sim > 0.88:
                        novelty = max(0.0, novelty - 0.4)  # heavy penalty
                    elif sim > 0.75:
                        novelty = max(0.0, novelty - 0.15)
        except Exception as e:
            logger.debug(f"Novelty scoring failed (non-critical): {e}")

        # --- Emotional intensity ---
        emo_intensity = _compute_emotional_intensity(emotional_signature)

        # --- Interaction depth ---
        depth = interaction_depth(response_length, reasoning_steps, tool_calls)

        # --- Surprise ---
        surprise = 0.5  # default neutral
        if pre_retrieval_ids and embedding:
            try:
                # Fetch embeddings of pre-retrieval memories
                id_list = pre_retrieval_ids[:5]
                placeholders = ", ".join(f"$id{i}" for i in range(len(id_list)))
                params = {f"id{i}": rid for i, rid in enumerate(id_list)}
                pre_mems = await self.db.query(
                    f"SELECT embedding FROM memory WHERE id IN [{placeholders}]",
                    params,
                )
                if pre_mems:
                    # Average cosine similarity of pre-retrieval set to new content
                    sims = []
                    for row in pre_mems:
                        oe = row.get("embedding")
                        if oe:
                            sims.append(self._cosine_similarity(embedding, oe))
                    if sims:
                        avg_sim = sum(sims) / len(sims)
                        # High distance from predictions → high surprise
                        surprise = max(0.0, min(1.0, 1.0 - avg_sim))
            except Exception as e:
                logger.debug(f"Surprise scoring failed (non-critical): {e}")

        score = (
            novelty * 0.30
            + emo_intensity * 0.30
            + depth * 0.20
            + surprise * 0.20
        )
        return max(0.0, min(1.0, score))

    # =========================================================================
    # STORE
    # =========================================================================

    async def store_memory(
        self,
        content: str,
        user_id: str | None = None,
        conversation_id: str | None = None,
        emotional_signature: dict[str, float] | None = None,
        importance: float = 0.5,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        resonance_score: float | None = None,
        namespace: str | None = None,
        formation_context: FormationContext | None = None,
        response_length: int = 0,
        reasoning_steps: int = 0,
        tool_calls: int = 0,
        pre_retrieval_ids: list[str] | None = None,
    ) -> str:
        """Store a memory with formation quality scoring and rich context.

        Formation scoring determines whether the memory is ephemeral (noise),
        normal, or a core memory (signal).  Rich FormationContext tracks
        exactly where and why this memory was born.

        Args:
            namespace: Optional task namespace for scoped memories.
            formation_context: Rich context about formation circumstances.
            response_length: Length of Aura's response (for depth scoring).
            reasoning_steps: Number of reasoning steps taken.
            tool_calls: Number of tool calls made.
            pre_retrieval_ids: Memory IDs from pre-interaction retrieval (for surprise scoring).
        """
        memory_id = f"memory:{uuid4().hex[:12]}"
        emo_sig = emotional_signature or {}
        
        # Filter out noise from emotional signature to preserve cosine similarity math
        emo_sig = {k: v for k, v in emo_sig.items() if v >= 0.1}

        try:
            embedding = await self.embeddings.embed(content)

            # Compute formation score
            formation_score = await self._compute_formation_score(
                content=content,
                embedding=embedding,
                emotional_signature=emo_sig,
                user_id=user_id,
                response_length=response_length,
                reasoning_steps=reasoning_steps,
                tool_calls=tool_calls,
                pre_retrieval_ids=pre_retrieval_ids,
            )

            # Classify memory tier
            is_ephemeral = formation_score < FORMATION_EPHEMERAL_THRESHOLD
            is_core = formation_score > FORMATION_CORE_THRESHOLD

            # Boost importance for core memories
            final_importance = importance
            if is_core:
                final_importance = max(importance, 0.85)
            elif is_ephemeral:
                final_importance = min(importance, 0.3)

            emo_intensity = _compute_emotional_intensity(emo_sig)

            data = Memory(
                memory_id=memory_id,
                content=content,
                user_id=user_id,
                conversation_id=conversation_id,
                emotional_signature=emo_sig,
                importance=final_importance,
                tags=tags or [],
                metadata=metadata or {},
                embedding=embedding,
                resonance_score=resonance_score,
                formation_score=formation_score,
                ephemeral=is_ephemeral,
                core_memory=is_core,
                emotional_intensity=emo_intensity,
                formation_context=formation_context,
            ).model_dump()

            # Attach namespace outside the Pydantic model (schema-optional field)
            if namespace:
                data["namespace"] = namespace

            # CRITICAL FIX: SurrealDB 2.x create() requires the specific record ID
            data.pop("memory_id", None)
            create_res = await self.db.create(memory_id, data)
            from aura.logging_config import sanitize_log_payload
            logger.info(f"Database create returned: {sanitize_log_payload(create_res)}")

            # Create related_to edges to similar recent memories
            asyncio.create_task(self._create_related_edges(memory_id, embedding, user_id))

            tier_label = "CORE" if is_core else ("ephemeral" if is_ephemeral else "normal")
            ns_label = f", namespace={namespace}" if namespace else ""
            logger.info(
                f"Memory stored: {memory_id} (formation={formation_score:.2f}, "
                f"tier={tier_label}, importance={final_importance:.2f}{ns_label})"
            )
            return memory_id

        except Exception as e:
            logger.error(f"Failed to store memory: {e}", exc_info=True)
            return None

    async def _create_related_edges(
        self, memory_id: str, embedding: list[float], user_id: str | None,
    ) -> None:
        """Create ->related_to-> edges to semantically similar memories at formation time."""
        try:
            conditions = ["id != $memory_id", "deprecated = false"]
            params: dict[str, Any] = {"memory_id": memory_id, "emb": embedding}
            if user_id:
                conditions.append("user_id = $user_id")
                params["user_id"] = user_id
            where = " AND ".join(conditions)

            neighbors = await self.db.query(
                f"""
                SELECT id,
                       vector::similarity::cosine(embedding, $emb) AS sim
                FROM memory
                WHERE {where}
                ORDER BY sim DESC
                LIMIT 5
                """,
                params,
            )
            for row in (neighbors or []):
                sim = float(row.get("sim", 0.0))
                if sim >= RELATED_EDGE_THRESHOLD:
                    neighbor_id = row.get("id")
                    if neighbor_id:
                        await self.db.query(
                            "RELATE $from->related_to->$to SET similarity = $sim",
                            {"from": memory_id, "to": str(neighbor_id), "sim": sim},
                        )
        except Exception as e:
            logger.debug(f"_create_related_edges failed (non-critical): {e}")

    # =========================================================================
    # NUANCED DECAY — Memory Decay That Feels Real
    # =========================================================================

    def _compute_decay_factor(self, row: dict[str, Any]) -> float:
        """Compute a nuanced decay factor for a memory at read time.

        Unlike the old flat exponential, this respects:
        - **Emotional protection**: memories with emotional_intensity > 0.7
          have their half-life multiplied by 4x.
        - **Access strengthening**: each recall extends effective half-life by 12h.
        - **Core memory immunity**: core_memory=True → infinite half-life (returns 1.0).
        - **Ephemeral acceleration**: ephemeral=True → 4x faster decay.

        Returns:
            Decay factor in [0.0, 1.0] (replaces flat recency score).
        """
        # Core memories never decay
        if row.get("core_memory"):
            return 1.0

        # Semantic memories never fade (memory PRD F4)
        if row.get("memory_type") == "semantic":
            return 1.0

        ts = _parse_ts(row.get("timestamp"))
        if ts is None:
            return 0.0

        now = get_clock().now()
        age_hours = max((now - ts).total_seconds() / 3600, 0)

        # Start with base half-life
        half_life = RECENCY_HALF_LIFE_H

        # Emotional protection
        emo_intensity = float(row.get("emotional_intensity", 0.0))
        if emo_intensity > EMOTIONAL_PROTECTION_INTENSITY:
            half_life *= EMOTIONAL_HALFLIFE_MULTIPLIER

        # Access strengthening: each recall extends half-life
        recall_count = int(row.get("recall_count", 0))
        half_life += recall_count * ACCESS_STRENGTHEN_HOURS

        # Ephemeral acceleration
        if row.get("ephemeral"):
            half_life /= EPHEMERAL_DECAY_MULTIPLIER

        # Prevent division by zero
        half_life = max(half_life, 0.1)

        return math.exp(-0.693 * age_hours / half_life)

    # =========================================================================
    # MULTI-SIGNAL RETRIEVAL (core)
    # =========================================================================

    async def retrieve_memories(
        self,
        query: str,
        limit: int = 8,
        emotional_filter: dict[str, float] | None = None,
        importance_min: float = 0.0,
        user_id: str | None = None,
        current_emotions: dict[str, float] | None = None,
        namespace: str | None = None,
    ) -> list[Memory]:
        """
        Multi-signal memory retrieval with nuanced decay.

        1. Fetch candidate pool via vector similarity (over-fetch 3x limit)
        2. Score each candidate across all 5 signals (using nuanced decay for recency)
        3. Return top-K by composite score

        Args:
            namespace: If supplied, candidates are restricted to memories whose
                namespace is either NULL/"global" (the main session) OR equals
                this namespace. Pass `None` (or "global") for unrestricted reads.
        """
        try:
            # Phase 1: Candidate retrieval (vector + importance filter)
            candidates = await self._fetch_candidates(
                query=query,
                pool_size=limit * 3,
                importance_min=importance_min,
                user_id=user_id,
                namespace=namespace,
            )

            if not candidates:
                return []

            # Phase 2: Multi-signal scoring
            scored = []
            for row in candidates:
                mem = Memory.model_validate(row)
                semantic = float(row.get("relevance", 0.0))
                # Use nuanced decay instead of flat recency
                recency = self._compute_decay_factor(row)
                emotion = _emotion_resonance(
                    current_emotions or {},
                    mem.emotional_signature,
                )
                fuzzy = _fuzzy_match_score(query, mem.content)
                imp = mem.importance

                composite = (
                    W_SEMANTIC   * semantic
                    + W_EMOTION  * emotion
                    + W_IMPORTANCE * imp
                    + W_RECENCY  * recency
                    + W_FUZZY    * fuzzy
                )

                # Attach score metadata for debugging / L3 formatting
                mem.metadata = mem.metadata or {}
                mem.metadata["_score"] = round(composite, 4)
                mem.metadata["_semantic"] = round(semantic, 3)
                mem.metadata["_emotion_resonance"] = round(emotion, 3)
                mem.metadata["_recency"] = round(recency, 3)

                scored.append((composite, mem))

            # Phase 3: Rank and return top-K
            scored.sort(key=lambda x: x[0], reverse=True)
            results = [mem for _, mem in scored[:limit]]

            logger.debug(
                f"Retrieved {len(results)} memories "
                f"(candidates={len(candidates)}, top_score={scored[0][0]:.3f})"
            )
            return results

        except Exception as e:
            logger.error(f"Failed to retrieve memories: {e}")
            return []

    async def _fetch_candidates(
        self,
        query: str,
        pool_size: int = 24,
        importance_min: float = 0.0,
        user_id: str | None = None,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch raw candidate rows from SurrealDB, excluding deprecated and ephemeral.

        Args:
            namespace: When supplied (and not "global"), candidates are filtered
                to `namespace = $ns OR namespace = "global" OR namespace IS NONE`.
                This implements the V1PRD §4.4 rule: scoped sessions see their
                own memories *and* global ones, never another session's memories.
        """
        conditions = [
            "importance >= $importance_min",
            "deprecated = false",
            "ephemeral = false",
        ]
        params: dict[str, Any] = {"importance_min": importance_min}
        if user_id:
            conditions.append("user_id = $user_id")
            params["user_id"] = user_id

        # "global" / None / "" all mean "no scope filter — read everything"
        if namespace and namespace != "global":
            conditions.append('(namespace = $ns OR namespace = "global" OR namespace IS NONE)')
            params["ns"] = namespace

        where = " AND ".join(conditions)

        query_embedding = None
        if query and query.strip():
            query_embedding = await self.embeddings.embed(query)

        if query_embedding:
            params["query_embedding"] = query_embedding
            result = await self.db.query(
                f"""
                SELECT *,
                       vector::similarity::cosine(embedding, $query_embedding) AS relevance
                FROM memory
                WHERE {where}
                ORDER BY relevance DESC
                LIMIT {pool_size}
                """,
                params,
            )
        else:
            result = await self.db.query(
                f"""
                SELECT *, 0.0 AS relevance
                FROM memory
                WHERE {where}
                ORDER BY importance DESC, timestamp DESC
                LIMIT {pool_size}
                """,
                params if params else None,
            )
        return result or []

    # =========================================================================
    # JIT: PRE-FORMATTED L3 CONTEXT
    # =========================================================================

    async def retrieve_for_l3(
        self,
        query: str,
        current_emotions: dict[str, float] | None = None,
        user_id: str | None = None,
        limit: int = 5,
        namespace: str | None = None,
        depth: int = 1,
    ) -> tuple[list[Memory], str]:
        """
        JIT retrieval that returns memories AND pre-formatted XML for the L3 prompt.

        Session 6 upgrade: each seed memory is expanded into a **Thought Cluster**
        by traversing graph edges in a single batched SurQL call:
          - ``->related_to->``      (semantic neighbours)
          - ``->abstracted_into->``  (what Aura learned from this)
          - ``<-abstracted_into<-``  (source episodes of a semantic memory)

        For the top seed, a lightweight chronological context is fetched from
        the ``experience`` table via ``->next_experience`` / ``<-next_experience``
        edges so L3 sees causality, not isolated facts.

        Args:
            depth: 1 = standard retrieval, 2 = spreading activation (richer context).

        Returns:
            (memories, xml_block) — the xml_block is ready to paste into the system prompt.
        """
        memories, cluster_data = await self.retrieve_for_l3_parts(
            query=query,
            current_emotions=current_emotions,
            user_id=user_id,
            limit=limit,
            namespace=namespace,
            depth=depth,
        )
        if not memories:
            return [], ""
        return memories, self._format_memories_xml(memories, cluster_data)

    async def retrieve_for_l3_parts(
        self,
        query: str,
        current_emotions: dict[str, float] | None = None,
        user_id: str | None = None,
        limit: int = 5,
        namespace: str | None = None,
        depth: int = 1,
    ) -> tuple[list[Memory], dict[str, dict]]:
        """Retrieve memories and their thought-cluster data, without formatting.

        This is the pure retrieval + cluster-enrichment half of
        :meth:`retrieve_for_l3`. It returns ``(memories, cluster_data)`` ready for
        :meth:`_format_memories_xml`, so the Recall Engine can deduplicate and
        budget the items before they are formatted (PRD M2).

        Returns:
            (memories, cluster_data). When no memories are found, returns
            ``([], {})``.
        """
        if depth >= 2:
            memories = await self.retrieve_with_spreading_activation(
                query=query,
                current_emotions=current_emotions,
                user_id=user_id,
                seed_limit=5,
                final_limit=limit,
                namespace=namespace,
            )
        else:
            memories = await self.retrieve_memories(
                query=query,
                limit=limit,
                current_emotions=current_emotions,
                user_id=user_id,
                importance_min=0.2,
                namespace=namespace,
            )

        # If a task namespace is active, also retrieve scoped memories
        if namespace:
            task_memories = await self._fetch_namespace_memories(
                namespace=namespace, query=query, limit=limit,
            )
            seen_ids = {m.memory_id for m in task_memories}
            merged = list(task_memories)
            for m in memories:
                if m.memory_id not in seen_ids:
                    merged.append(m)
            memories = merged[:limit]

        if not memories:
            return [], {}

        # Boost recalled memories (Hebbian reinforcement)
        boost_ids = [m.memory_id for m in memories]
        asyncio.create_task(self._batch_boost_on_recall(boost_ids))

        # ── Session 6: Build Thought Clusters for top seeds ──────────────
        # For the top 3 seeds, fetch graph context in parallel.
        cluster_data: dict[str, dict] = {}
        try:
            cluster_coros = [
                self._fetch_thought_cluster(m.memory_id)
                for m in memories[:3]
            ]
            cluster_results = await asyncio.gather(*cluster_coros, return_exceptions=True)
            for mem, result in zip(memories[:3], cluster_results):
                if isinstance(result, dict):
                    cluster_data[mem.memory_id] = result
        except Exception as e:
            logger.debug(f"Thought cluster enrichment failed (non-critical): {e}")

        return memories, cluster_data

    # =========================================================================
    # THOUGHT CLUSTER — Multi-hop Graph Traversal (Session 6)
    # =========================================================================

    async def _fetch_thought_cluster(self, memory_id: str) -> dict:
        """Fetch a single memory's graph context in one batched DB call.

        Returns a dict with optional keys:
            - ``abstractions``: list[dict] — memories this was abstracted into
            - ``sources``:      list[dict] — if semantic, the episodic sources
            - ``timeline_before``: list[dict] — chronologically preceding experiences
            - ``timeline_after``:  list[dict] — chronologically following experiences
        """
        cluster: dict = {}
        try:
            # 1. Conceptual grounding: abstracted_into edges (both directions)
            abs_out = await self.db.query(
                """
                SELECT out.content AS content, out.memory_type AS memory_type,
                       out.importance AS importance
                FROM abstracted_into
                WHERE in = $mid
                FETCH out
                LIMIT 3
                """,
                {"mid": memory_id},
            )
            if abs_out:
                cluster["abstractions"] = [
                    r for r in abs_out if isinstance(r, dict) and r.get("content")
                ]

            abs_in = await self.db.query(
                """
                SELECT in.content AS content, in.timestamp AS timestamp
                FROM abstracted_into
                WHERE out = $mid
                LIMIT 5
                FETCH in
                """,
                {"mid": memory_id},
            )
            if abs_in:
                cluster["sources"] = [
                    r for r in abs_in if isinstance(r, dict) and r.get("content")
                ]

            # 2. Chronological context: find the experience node closest to this
            #    memory's conversation_id, then traverse next_experience edges.
            mem_row = await self.db.query(
                "SELECT conversation_id, timestamp FROM memory WHERE id = $mid LIMIT 1",
                {"mid": memory_id},
            )
            if mem_row:
                conv_id = (mem_row[0] or {}).get("conversation_id")
                mem_ts = (mem_row[0] or {}).get("timestamp")
                if conv_id:
                    # Find the experience in this conversation whose timestamp is
                    # not later than the memory's own, so the chronology lines up
                    # with when the memory was actually formed.
                    exp_match = await self.db.query(
                        """
                        SELECT id FROM experience
                        WHERE context.conversation_id = $cid
                           OR metadata.conversation_id = $cid
                        AND timestamp <= $ts
                        ORDER BY timestamp DESC
                        LIMIT 1
                        """,
                        {"cid": conv_id, "ts": mem_ts},
                    )

                    if exp_match:
                        exp_id = str((exp_match[0] or {}).get("id", ""))
                        if exp_id:
                            # Traverse ->next_experience (what happened after)
                            after = await self.db.query(
                                """
                                SELECT out.context.user_query AS prompt,
                                       out.domain AS domain,
                                       out.timestamp AS timestamp
                                FROM next_experience
                                WHERE in = $eid
                                LIMIT 2
                                FETCH out
                                """,
                                {"eid": exp_id},
                            )
                            if after:
                                cluster["timeline_after"] = [
                                    r for r in after
                                    if isinstance(r, dict) and r.get("prompt")
                                ]

                            # Traverse <-next_experience (what happened before)
                            before = await self.db.query(
                                """
                                SELECT in.context.user_query AS prompt,
                                       in.domain AS domain,
                                       in.timestamp AS timestamp
                                FROM next_experience
                                WHERE out = $eid
                                LIMIT 2
                                FETCH in
                                """,
                                {"eid": exp_id},
                            )
                            if before:
                                cluster["timeline_before"] = [
                                    r for r in before
                                    if isinstance(r, dict) and r.get("prompt")
                                ]
        except Exception as e:
            logger.debug(f"_fetch_thought_cluster({memory_id}) failed: {e}")

        return cluster

    def _format_memories_xml(
        self,
        memories: list[Memory],
        cluster_data: dict[str, dict] | None = None,
    ) -> str:
        """Format memories as XML Thought Clusters for L3 injection.

        When ``cluster_data`` is provided, each seed memory is wrapped in a
        ``<thought_cluster>`` element that exposes chronological and conceptual
        context so L3 reasons over causal sequences, not isolated text chunks.
        """
        cluster_data = cluster_data or {}
        xml = "<relevant_memories>\n"

        for mem in memories:
            ts = self._format_ts(mem.timestamp)
            emo_res = mem.metadata.get("_emotion_resonance", 0) if mem.metadata else 0

            top_emo = ""
            if mem.emotional_signature:
                top_k = sorted(mem.emotional_signature.items(), key=lambda x: x[1], reverse=True)[:2]
                top_emo = ", ".join(f"{k}={v:.2f}" for k, v in top_k if v > 0.1)

            attrs = f"timestamp='{ts}' importance='{mem.importance:.2f}'"
            if mem.core_memory:
                attrs += " core='true'"
            if mem.memory_type == "semantic":
                attrs += " type='semantic'"
            if top_emo:
                attrs += f" emotional_context='{top_emo}'"
            if emo_res > 0.3:
                attrs += f" resonance='{emo_res:.2f}'"

            cluster = cluster_data.get(mem.memory_id)
            if cluster:
                xml += f"  <thought_cluster {attrs}>\n"
                xml += f"    <core_memory>{_truncate_for_inject(mem.content)}</core_memory>\n"

                # Chronological context
                before = cluster.get("timeline_before", [])
                after = cluster.get("timeline_after", [])
                if before or after:
                    xml += "    <chronology>\n"
                    for b in before:
                        xml += f"      <before>{b.get('prompt', '')[:200]}</before>\n"
                    xml += "      <current>THIS MEMORY</current>\n"
                    for a in after:
                        xml += f"      <after>{a.get('prompt', '')[:200]}</after>\n"
                    xml += "    </chronology>\n"

                # Conceptual grounding
                abstractions = cluster.get("abstractions", [])
                if abstractions:
                    xml += "    <insights_derived>\n"
                    for ab in abstractions:
                        xml += f"      <insight>{ab.get('content', '')[:300]}</insight>\n"
                    xml += "    </insights_derived>\n"

                sources = cluster.get("sources", [])
                if sources:
                    xml += "    <evidence_base>\n"
                    for src in sources:
                        xml += f"      <source_memory>{src.get('content', '')[:200]}</source_memory>\n"
                    xml += "    </evidence_base>\n"

                xml += "  </thought_cluster>\n"
            else:
                xml += f"  <memory {attrs}>{_truncate_for_inject(mem.content)}</memory>\n"

        xml += "</relevant_memories>"
        return xml

    # =========================================================================
    # NAMESPACE-SCOPED RETRIEVAL (task memories)
    # =========================================================================

    async def _fetch_namespace_memories(
        self,
        namespace: str,
        query: str,
        limit: int = 5,
    ) -> list[Memory]:
        """Fetch memories scoped to a specific task namespace."""
        try:
            query_embedding = None
            if query and query.strip():
                query_embedding = await self.embeddings.embed(query)

            if query_embedding:
                result = await self.db.query(
                    """
                    SELECT *,
                           vector::similarity::cosine(embedding, $qe) AS relevance
                    FROM memory
                    WHERE namespace = $ns AND deprecated = false
                    ORDER BY relevance DESC
                    LIMIT $lim
                    """,
                    {"qe": query_embedding, "ns": namespace, "lim": limit},
                )
            else:
                result = await self.db.query(
                    """
                    SELECT *, 0.0 AS relevance
                    FROM memory
                    WHERE namespace = $ns AND deprecated = false
                    ORDER BY timestamp DESC
                    LIMIT $lim
                    """,
                    {"ns": namespace, "lim": limit},
                )
            return [Memory.model_validate(r) for r in (result or [])]
        except Exception as e:
            logger.error(f"_fetch_namespace_memories failed: {e}")
            return []

    # =========================================================================
    # SPREADING ACTIVATION — Associative Memory Chains
    # =========================================================================

    async def retrieve_with_spreading_activation(
        self,
        query: str,
        current_emotions: dict[str, float] | None = None,
        user_id: str | None = None,
        seed_limit: int = 5,
        final_limit: int = 10,
        namespace: str | None = None,
    ) -> list[Memory]:
        """
        Multi-pass associative retrieval with spreading activation.

        Pass 1: standard 5-signal retrieval → top seeds.
        Pass 2: traverse ->related_to-> edges from each seed; score neighbors
                with diminished relevance (seed_score * 0.6).
        Pass 3: deduplicate, re-rank by combined score, return top N.

        The result: Aura doesn't just remember what you asked about —
        she remembers the web of things connected to it.

        Args:
            namespace: Session-scoped retrieval. Seeds are filtered to
                `namespace = $ns OR namespace = "global"`. Edge-traversed
                neighbours are not re-filtered (the seed already lives in
                the right scope, so its neighbours are reachable by design).
        """
        # Pass 1: Seeds
        seeds = await self.retrieve_memories(
            query=query,
            limit=seed_limit,
            current_emotions=current_emotions,
            user_id=user_id,
            importance_min=0.2,
            namespace=namespace,
        )
        if not seeds:
            return []

        scored: dict[str, tuple[float, Memory]] = {}
        for mem in seeds:
            score = float((mem.metadata or {}).get("_score", 0.5))
            scored[mem.memory_id] = (score, mem)

        # Pass 2: Spread activation via a single batched graph traversal.
        #
        # Old approach: 2 × len(seeds) separate queries (N+1 bottleneck).
        # New approach: one query covering forward AND reverse edges for ALL
        # seeds simultaneously.  FETCH materialises the full memory records
        # inline so we never need a follow-up lookup.
        seed_ids = [m.memory_id for m in seeds]
        seed_score_map = {
            m.memory_id: float((m.metadata or {}).get("_score", 0.5))
            for m in seeds
        }
        seed_id_set = set(seed_ids)
        try:
            all_edges = await self.db.query(
                """
                SELECT in, out, similarity
                FROM related_to
                WHERE in IN $sids OR out IN $sids
                LIMIT 50
                FETCH in, out
                """,
                {"sids": seed_ids},
            )
            for row in (all_edges or []):
                in_rec  = row.get("in")
                out_rec = row.get("out")
                in_id   = str(
                    in_rec.get("id",  "") if isinstance(in_rec,  dict) else in_rec  or ""
                )
                out_id  = str(
                    out_rec.get("id", "") if isinstance(out_rec, dict) else out_rec or ""
                )
                edge_sim = float(row.get("similarity", 0.6))

                # Identify which end is the seed and which is the neighbor
                if in_id in seed_id_set:
                    seed_id, n_id, n_data = in_id, out_id, out_rec
                elif out_id in seed_id_set:
                    seed_id, n_id, n_data = out_id, in_id, in_rec
                else:
                    continue

                if not n_data or not isinstance(n_data, dict):
                    continue
                # Skip seeds themselves and unusable records
                if n_id in seed_id_set or n_data.get("deprecated") or n_data.get("ephemeral"):
                    continue

                seed_score     = seed_score_map.get(seed_id, 0.5)
                neighbor_score = seed_score * SPREADING_DECAY * edge_sim

                if n_id in scored:
                    if neighbor_score > scored[n_id][0]:
                        try:
                            scored[n_id] = (neighbor_score, Memory.model_validate(n_data))
                        except Exception:
                            pass
                else:
                    try:
                        scored[n_id] = (neighbor_score, Memory.model_validate(n_data))
                    except Exception:
                        pass
        except Exception as e:
            logger.debug(f"Spreading activation pass 2 failed (non-critical): {e}")

        # Pass 3: Deduplicate, re-rank, return top N
        ranked = sorted(scored.values(), key=lambda x: x[0], reverse=True)
        return [mem for _, mem in ranked[:final_limit]]

    # =========================================================================
    # GRAPH TRAVERSAL: Related memories
    # =========================================================================

    async def find_related(self, memory_id: str, limit: int = 5) -> list[Memory]:
        """
        Find memories related via graph edges (related_to, same conversation,
        or embedding similarity fallback).
        """
        try:
            # 1. Graph edges (related_to)
            result = await self.db.query(
                """
                SELECT out.* FROM related_to
                WHERE in = $mid
                ORDER BY similarity DESC
                LIMIT $lim
                """,
                {"mid": memory_id, "lim": limit},
            )
            if result:
                mems = []
                for r in result:
                    data = r.get("out") if isinstance(r.get("out"), dict) else r
                    if data:
                        try:
                            mems.append(Memory.model_validate(data))
                        except Exception:
                            continue
                if mems:
                    return mems

            # 2. Same conversation
            result = await self.db.query(
                """
                SELECT * FROM memory
                WHERE conversation_id = (SELECT conversation_id FROM $mid)
                  AND id != $mid AND deprecated = false
                ORDER BY timestamp ASC
                LIMIT $lim
                """,
                {"mid": memory_id, "lim": limit},
            )

            if result:
                return [Memory.model_validate(r) for r in result]

            # 3. Fallback: closest by embedding
            source = await self.db.query(
                "SELECT embedding FROM memory WHERE id = $mid LIMIT 1",
                {"mid": memory_id},
            )
            if source and source[0].get("embedding"):
                result = await self.db.query(
                    """
                    SELECT *,
                           vector::similarity::cosine(embedding, $emb) AS sim
                    FROM memory
                    WHERE id != $mid AND deprecated = false
                    ORDER BY sim DESC
                    LIMIT $lim
                    """,
                    {"emb": source[0]["embedding"], "mid": memory_id, "lim": limit},
                )
                if result:
                    return [Memory.model_validate(r) for r in result]

            return []
        except Exception as e:
            logger.error(f"find_related failed: {e}")
            return []

    # =========================================================================
    # EMOTION-BASED RETRIEVAL
    # =========================================================================

    async def find_by_emotion(
        self, emotion_name: str, threshold: float = 0.3, limit: int = 10
    ) -> list[Memory]:
        """Find memories linked to a specific emotion above threshold."""
        try:
            result = await self.db.query(
                f"""
                SELECT * FROM memory
                WHERE emotional_signature.{emotion_name} >= {threshold}
                  AND deprecated = false
                ORDER BY emotional_signature.{emotion_name} DESC
                LIMIT {limit}
                """
            )
            if not result:
                return []
            return [Memory.model_validate(r) for r in result]
        except Exception as e:
            logger.error(f"find_by_emotion failed: {e}")
            return []

    # =========================================================================
    # MUTATIONS
    # =========================================================================

    async def update_memory_importance(self, memory_id: str, new_importance: float) -> None:
        """Boost or decay importance (called on recall or by reflection engine)."""
        try:
            await self.db.merge(memory_id, {"importance": min(1.0, max(0.0, new_importance))})
        except Exception as e:
            logger.error(f"Failed to update memory importance: {e}")

    async def boost_on_recall(self, memory_id: str, boost: float = 0.05) -> None:
        """Strengthen a memory each time it's recalled (Hebbian reinforcement).

        Also increments recall_count and updates last_recalled_at so the
        nuanced decay engine can extend this memory's effective half-life.

        Done as a single UPDATE so concurrent boosts on the same memory cannot
        read the same importance and lose one of the increments.
        """
        try:
            await self.db.query(
                "UPDATE $mid SET "
                "importance = math::min([1.0, importance + $boost]), "
                "recall_count += 1, "
                "last_recalled_at = $now",
                {"mid": to_record_id(memory_id), "boost": boost, "now": get_clock().now()},
            )
        except Exception as e:
            logger.error(f"boost_on_recall failed: {e}")

    async def _batch_boost_on_recall(self, memory_ids: list[str]) -> None:
        """Boost multiple memories in parallel after retrieval."""
        try:
            await asyncio.gather(
                *(self.boost_on_recall(mid) for mid in memory_ids),
                return_exceptions=True,
            )
        except Exception as e:
            logger.debug(f"_batch_boost_on_recall failed: {e}")

    async def mark_as_learned(self, memory_id: str) -> None:
        try:
            await self.db.merge(memory_id, {"learned_from": True})
        except Exception as e:
            logger.error(f"Failed to mark memory as learned: {e}")

    async def set_core(self, memory_id: str, core: bool) -> None:
        """Pin a memory as core, or unpin it.

        When ``core`` is true the memory is marked core and is no longer
        ephemeral (core memories must persist). When false only the core flag
        is cleared.
        """
        try:
            if core:
                await self.db.merge(memory_id, {"core_memory": True, "ephemeral": False})
            else:
                await self.db.merge(memory_id, {"core_memory": False})
        except Exception as e:
            logger.error(f"Failed to set core flag: {e}")
            raise

    # =========================================================================
    # COLD START — First Impression on Every Conversation
    # =========================================================================

    def _format_cold_start_xml(
        self,
        core_memories: list[Memory],
        recent_memories: list[Memory],
        top_insights: list[dict[str, Any]],
        active_cultural_node: str | None,
    ) -> str:
        """Format the cold-start context block as XML for L3 injection.

        Renders the wrapper even when every list is empty, so the block stays
        present whenever the channel ran (PRD M2).
        """
        xml = "<cold_start_context>\n"
        if core_memories:
            xml += "  <core_memories>\n"
            for m in core_memories:
                xml += f"    <memory importance='{m.importance:.2f}'>{_truncate_for_inject(m.content)}</memory>\n"
            xml += "  </core_memories>\n"
        if recent_memories:
            xml += "  <recent_context>\n"
            for m in recent_memories:
                ts = self._format_ts(m.timestamp)
                xml += f"    <memory timestamp='{ts}'>{_truncate_for_inject(m.content)}</memory>\n"
            xml += "  </recent_context>\n"
        if top_insights:
            xml += "  <key_insights>\n"
            for ins in top_insights:
                xml += f"    <insight type='{ins.get('type', 'PATTERN')}' confidence='{ins.get('confidence', 0.5):.2f}'>{ins.get('content', '')}</insight>\n"
            xml += "  </key_insights>\n"
        if active_cultural_node:
            xml += f"  <cultural_node>{active_cultural_node}</cultural_node>\n"
        xml += "</cold_start_context>"
        return xml

    async def get_cold_start_context(self, user_id: str) -> ColdStartContext:
        """Load warm context for a new conversation before any retrieval happens.

        Fetches:
        - All core_memory=True records for the user.
        - 3 most recent non-ephemeral memories (last session context).
        - Top 3 highest-confidence insights from the learning engine.
        - Active cultural node.
        - Last known emotional state baseline.

        Returns a ColdStartContext with a pre-formatted XML block for L3 injection.
        """
        core_task = self.db.query(
            """
            SELECT * FROM memory
            WHERE user_id = $uid AND core_memory = true AND deprecated = false
            ORDER BY importance DESC
            LIMIT 10
            """,
            {"uid": user_id},
        )

        recent_task = self.db.query(
            """
            SELECT * FROM memory
            WHERE user_id = $uid AND ephemeral = false AND deprecated = false
            ORDER BY timestamp DESC
            LIMIT 3
            """,
            {"uid": user_id},
        )

        insights_task = self.db.query(
            """
            SELECT content, type, confidence, domain
            FROM insight
            WHERE user_id = $uid AND deprecated = false
            ORDER BY confidence DESC
            LIMIT 3
            """,
            {"uid": user_id},
        )

        cultural_task = self.db.query(
            "SELECT code FROM cultural_node WHERE active = true LIMIT 1"
        )

        emotion_task = self.db.query(
            """
            SELECT vector FROM emotion_state
            ORDER BY timestamp DESC
            LIMIT 1
            """
        )

        core_rows, recent_rows, insight_rows, cultural_rows, emotion_rows = (
            await asyncio.gather(
                core_task, recent_task, insights_task, cultural_task, emotion_task,
                return_exceptions=True,
            )
        )

        # Parse results (handle exceptions from gather)
        core_memories: list[Memory] = []
        if isinstance(core_rows, list):
            for r in core_rows:
                try:
                    core_memories.append(Memory.model_validate(r))
                except Exception:
                    pass

        recent_memories: list[Memory] = []
        if isinstance(recent_rows, list):
            for r in recent_rows:
                try:
                    recent_memories.append(Memory.model_validate(r))
                except Exception:
                    pass

        top_insights: list[dict[str, Any]] = []
        if isinstance(insight_rows, list):
            top_insights = insight_rows[:3]

        active_cultural_node: str | None = None
        if isinstance(cultural_rows, list) and cultural_rows:
            active_cultural_node = cultural_rows[0].get("code")

        emotional_baseline: dict[str, float] = {}
        if isinstance(emotion_rows, list) and emotion_rows:
            emotional_baseline = emotion_rows[0].get("vector", {})

        # Build XML block
        xml = self._format_cold_start_xml(
            core_memories, recent_memories, top_insights, active_cultural_node
        )

        ctx = ColdStartContext(
            core_memories=core_memories,
            recent_memories=recent_memories,
            top_insights=top_insights,
            active_cultural_node=active_cultural_node,
            emotional_baseline=emotional_baseline,
            xml_block=xml,
        )
        logger.info(
            f"Cold start context loaded: {len(core_memories)} core, "
            f"{len(recent_memories)} recent, {len(top_insights)} insights"
        )
        return ctx

    # =========================================================================
    # MEMORY INTROSPECTION — Aura Knows What She Remembers
    # =========================================================================

    async def introspect(self, user_id: str) -> MemoryIntrospection:
        """Build a self-report on the health and shape of Aura's memory."""
        queries = {
            "total": "SELECT count() FROM memory WHERE deprecated = false GROUP ALL",
            "core": "SELECT count() FROM memory WHERE core_memory = true AND deprecated = false GROUP ALL",
            "ephemeral": "SELECT count() FROM memory WHERE ephemeral = true AND deprecated = false GROUP ALL",
            "semantic": "SELECT count() FROM memory WHERE memory_type = 'semantic' AND deprecated = false GROUP ALL",
            "oldest": "SELECT timestamp FROM memory WHERE deprecated = false ORDER BY timestamp ASC LIMIT 1",
            "strongest": "SELECT content, importance, recall_count FROM memory WHERE deprecated = false ORDER BY importance DESC LIMIT 1",
            "emotional": "SELECT content, emotional_signature, emotional_intensity FROM memory WHERE deprecated = false ORDER BY emotional_intensity DESC LIMIT 1",
            "insights": "SELECT count() FROM insight WHERE deprecated = false GROUP ALL",
            "edges": "SELECT count() FROM related_to GROUP ALL",
            "dream": "SELECT timestamp FROM memory WHERE tags CONTAINS 'dream_report' ORDER BY timestamp DESC LIMIT 1",
            "domains": "SELECT tags, count() AS cnt FROM memory WHERE deprecated = false GROUP BY tags ORDER BY cnt DESC LIMIT 5",
        }

        results: dict[str, Any] = {}
        tasks = {k: self.db.query(v) for k, v in queries.items()}
        raw = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for key, result in zip(tasks.keys(), raw):
            results[key] = result if not isinstance(result, Exception) else []

        total = results["total"][0].get("count", 0) if results["total"] else 0
        core = results["core"][0].get("count", 0) if results["core"] else 0
        ephemeral = results["ephemeral"][0].get("count", 0) if results["ephemeral"] else 0
        semantic = results["semantic"][0].get("count", 0) if results["semantic"] else 0
        insights_count = results["insights"][0].get("count", 0) if results["insights"] else 0
        edges = results["edges"][0].get("count", 0) if results["edges"] else 0

        oldest_ts = results["oldest"][0].get("timestamp") if results["oldest"] else None
        strongest_row = results["strongest"][0] if results["strongest"] else {}
        emotional_row = results["emotional"][0] if results["emotional"] else {}
        dream_row = results["dream"][0] if results["dream"] else {}

        # Memory health score
        ephemeral_ratio = ephemeral / max(total, 1)
        abstraction_ratio = semantic / max(total, 1)
        core_density = core / max(total, 1)
        health = (1.0 - ephemeral_ratio) * 0.4 + abstraction_ratio * 0.3 + core_density * 0.3
        health = max(0.0, min(1.0, health))

        # Dominant domains from tags
        domain_list: list[str] = []
        if results.get("domains"):
            for row in results["domains"]:
                t = row.get("tags")
                if isinstance(t, list):
                    domain_list.extend(t)

        return MemoryIntrospection(
            total_memories=total,
            core_memories=core,
            ephemeral_pending_pruning=ephemeral,
            semantic_abstractions=semantic,
            oldest_memory=str(oldest_ts) if oldest_ts else None,
            strongest_memory={
                "content": strongest_row.get("content", ""),
                "importance": strongest_row.get("importance", 0),
                "recall_count": strongest_row.get("recall_count", 0),
            },
            most_emotional_memory={
                "content": emotional_row.get("content", ""),
                "emotional_intensity": emotional_row.get("emotional_intensity", 0),
            },
            dominant_domains=domain_list[:5],
            memory_health_score=health,
            last_dream_cycle=str(dream_row.get("timestamp")) if dream_row else None,
            insights_count=insights_count,
            knowledge_graph_edges=edges,
        )

    # =========================================================================
    # L2 ACTIVE RECALL TOOLS (Session 6)
    # =========================================================================

    async def traverse_timeline(
        self,
        experience_id: str,
        steps: int = 3,
        direction: str = "forward",
    ) -> list[dict[str, Any]]:
        """Let L2 sequentially read a past conversation by traversing next_experience edges.

        This is an *internal tool* callable by the L2 reasoning engine during its
        analysis loop.  It answers: "What happened before/after this event?"

        Args:
            experience_id: Starting experience node (e.g. ``experience:abc123``).
            steps: Number of hops to traverse (max 10 for safety).
            direction: ``"forward"`` (->next_experience) or ``"backward"`` (<-next_experience).

        Returns:
            Ordered list of experience summaries with timestamps.
        """
        steps = min(steps, 10)
        results: list[dict[str, Any]] = []
        current_id = experience_id

        try:
            for _ in range(steps):
                if direction == "forward":
                    row = await self.db.query(
                        """
                        SELECT out.id AS id,
                               out.context.user_query AS prompt,
                               out.aura_response.response AS response,
                               out.domain AS domain,
                               out.timestamp AS timestamp,
                               elapsed_ms
                        FROM next_experience
                        WHERE in = $eid
                        FETCH out
                        LIMIT 1
                        """,
                        {"eid": current_id},
                    )
                else:
                    row = await self.db.query(
                        """
                        SELECT in.id AS id,
                               in.context.user_query AS prompt,
                               in.aura_response.response AS response,
                               in.domain AS domain,
                               in.timestamp AS timestamp,
                               elapsed_ms
                        FROM next_experience
                        WHERE out = $eid
                        LIMIT 1
                        FETCH in
                        """,
                        {"eid": current_id},
                    )

                if not row:
                    break

                entry = row[0]
                if not isinstance(entry, dict):
                    break

                next_id = str(entry.get("id", ""))
                if not next_id:
                    break

                results.append({
                    "experience_id": next_id,
                    "prompt": (entry.get("prompt") or "")[:300],
                    "response": (entry.get("response") or "")[:300],
                    "domain": entry.get("domain", ""),
                    "timestamp": str(entry.get("timestamp", "")),
                    "elapsed_ms": entry.get("elapsed_ms"),
                })
                current_id = next_id

        except Exception as e:
            logger.error(f"traverse_timeline failed: {e}")

        return results

    async def fetch_supporting_evidence(
        self,
        insight_id: str,
    ) -> list[dict[str, Any]]:
        """Let L2 pull the raw episodic memories that formed a belief/insight.

        Traverses ``<-abstracted_into<-`` from the target insight (semantic memory
        or insight node) to retrieve the original episodic memories that were
        synthesized into it.  This prevents hallucination by grounding abstract
        beliefs in concrete experience.

        Args:
            insight_id: The insight or semantic memory record ID
                        (e.g. ``insight:abc123`` or ``memory:xyz789``).

        Returns:
            List of source memory/experience summaries.
        """
        evidence: list[dict[str, Any]] = []
        try:
            # Path 1: If this is a memory (semantic), look for abstracted_into edges
            if insight_id.startswith("memory:"):
                rows = await self.db.query(
                    """
                    SELECT in.content AS content,
                           in.timestamp AS timestamp,
                           in.emotional_signature AS emotional_signature,
                           in.importance AS importance
                    FROM abstracted_into
                    WHERE out = $iid
                    LIMIT 10
                    FETCH in
                    """,
                    {"iid": insight_id},
                )
                for r in (rows or []):
                    if isinstance(r, dict) and r.get("content"):
                        evidence.append({
                            "content": r["content"][:500],
                            "timestamp": str(r.get("timestamp", "")),
                            "importance": r.get("importance", 0.0),
                        })

            # Path 2: If this is an insight record, use source_experiences field
            if insight_id.startswith("insight:"):
                ins_row = await self.db.query(
                    "SELECT source_experiences, content, confidence FROM insight WHERE id = $iid LIMIT 1",
                    {"iid": insight_id},
                )
                if ins_row:
                    insight_data = ins_row[0] if isinstance(ins_row[0], dict) else {}
                    src_ids = insight_data.get("source_experiences", [])
                    if src_ids:
                        # Fetch the actual experience content
                        exp_rows = await self.db.query(
                            """
                            SELECT id, context.user_query AS prompt,
                                   aura_response.response AS response,
                                   domain, timestamp
                            FROM experience
                            WHERE id IN $ids
                            LIMIT 10
                            """,
                            {"ids": [str(s) for s in src_ids[:10]]},
                        )
                        for r in (exp_rows or []):
                            if isinstance(r, dict):
                                evidence.append({
                                    "experience_id": str(r.get("id", "")),
                                    "prompt": (r.get("prompt") or "")[:300],
                                    "response": (r.get("response") or "")[:300],
                                    "domain": r.get("domain", ""),
                                    "timestamp": str(r.get("timestamp", "")),
                                })

        except Exception as e:
            logger.error(f"fetch_supporting_evidence({insight_id}) failed: {e}")

        return evidence

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _format_ts(ts: datetime | str | None) -> str:
        if ts is None:
            return "unknown"
        if isinstance(ts, str):
            return ts[:19]
        return ts.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
        """Cosine similarity between two float vectors."""
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 <= 0 or n2 <= 0:
            return 0.0
        return dot / (n1 * n2)


# Global singleton
_memory_manager: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        _memory_manager = MemoryManager()
    return _memory_manager

