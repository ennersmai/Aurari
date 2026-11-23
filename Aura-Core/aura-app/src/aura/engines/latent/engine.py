"""
Latent Memory Engine — TITANS-Inspired Neural Long-Term Memory.

Session 7: Third memory pillar complementing Vector RAG and Graph Traversal.

Instead of storing discrete episodes, this engine maintains a continuously
updated, highly compressed LatentState node per user. It provides:

1. Zero-latency intuition injection into L3 (MAC — Memory as Context)
2. Surprise-gated state updates (only novel experiences modify the state)
3. Momentum tracking for drift detection (what is the user trending toward?)
4. Historical emotional centroid (how this user makes Aura feel over time)

Architecture (TITANS-inspired):
- State Vector: 768D EMA of all absorbed experience embeddings
- Momentum Vector: 768D direction of recent state changes
- Surprise Gradient: 1 - cos(new_experience, current_state)
- Adaptive Threshold: mean(surprise) + 1.5 * std(surprise)
- Learning Rate: Decays with experience count, amplified by surprise
"""

import asyncio
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, TYPE_CHECKING

from aura.db.client import get_db_client
from aura.engines.base import BaseEngine
from aura.llm.embeddings import get_embeddings_client

if TYPE_CHECKING:
    from aura.llm.layers import LLMLayers

logger = logging.getLogger(__name__)

# Embedding dimensionality (nomic-embed-text-v1.5)
EMBED_DIM = 768

# Summary regeneration interval (every N state updates)
SUMMARY_REGEN_INTERVAL = 10

# Warm-start: number of experiences to process on first boot
WARM_START_EXPERIENCE_COUNT = 50

# Minimum surprise for graph edge creation (->modulates->)
EDGE_SURPRISE_THRESHOLD = 0.70


@dataclass
class LatentStateCache:
    """In-memory cache of a user's latent state for zero-latency reads."""

    user_id: str
    state_vector: list[float]
    momentum_vector: list[float]
    version: int = 0
    total_experiences_absorbed: int = 0
    avg_surprise: float = 0.5
    surprise_variance: float = 0.1
    emotional_centroid: dict[str, float] = field(default_factory=dict)
    domain_distribution: dict[str, float] = field(default_factory=dict)
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Cached natural-language summary (regenerated periodically)
    summary_text: str = ""
    # Track updates since last summary regen
    updates_since_summary: int = 0


class LatentEngine(BaseEngine):
    """
    TITANS-inspired Latent Memory Engine.

    Maintains a compressed neural state vector that represents the holistic
    "gist" of all past interactions with each user. Provides zero-latency
    intuition injection into L3 context (MAC — Memory as Context).

    Update Lifecycle:
    1. Every experience triggers surprise_gradient calculation
    2. If surprise > adaptive_threshold → state update
    3. Every SUMMARY_REGEN_INTERVAL updates → regenerate text summary via L5
    4. L3 reads cached state on every query (no DB round-trip)
    """

    def __init__(self):
        super().__init__("latent_engine")
        self.db = get_db_client()
        self.embeddings = get_embeddings_client()
        self.llm_layers: "LLMLayers | None" = None

        # In-memory cache: user_id → LatentStateCache
        self._state_cache: dict[str, LatentStateCache] = {}
        self._lock = asyncio.Lock()

    def set_llm_layers(self, llm_layers: "LLMLayers") -> None:
        """Set LLM layers for summary generation."""
        self.llm_layers = llm_layers

    # =========================================================================
    # LIFECYCLE
    # =========================================================================

    async def initialize(self) -> None:
        """Load existing latent states from DB into memory cache."""
        self.logger.info("Initializing Latent Engine (TITANS)...")
        try:
            rows = await self.db.query(
                "SELECT * FROM latent_state"
            )
            loaded = 0
            for row in (rows or []):
                user_id = row.get("user_id")
                if not user_id:
                    continue
                cache = LatentStateCache(
                    user_id=user_id,
                    state_vector=row.get("state_vector") or [0.0] * EMBED_DIM,
                    momentum_vector=row.get("momentum_vector") or [0.0] * EMBED_DIM,
                    version=row.get("version", 0),
                    total_experiences_absorbed=row.get("total_experiences_absorbed", 0),
                    avg_surprise=row.get("avg_surprise", 0.5),
                    surprise_variance=row.get("surprise_variance", 0.1),
                    emotional_centroid=row.get("emotional_centroid") or {},
                    domain_distribution=row.get("domain_distribution") or {},
                    summary_text=row.get("summary_text") or "",
                )
                ts = row.get("last_updated")
                if isinstance(ts, str):
                    try:
                        cache.last_updated = datetime.fromisoformat(
                            ts.replace("Z", "+00:00")
                        )
                    except Exception:
                        pass
                elif isinstance(ts, datetime):
                    cache.last_updated = ts

                self._state_cache[user_id] = cache
                loaded += 1

            self.logger.info(
                f"Latent Engine initialized — loaded {loaded} user state(s)"
            )
        except Exception as e:
            self.logger.warning(f"Latent Engine init (non-critical): {e}")

    async def tick(self) -> None:
        """No background processing needed — state updates are event-driven."""
        while True:
            await asyncio.sleep(60)

    async def shutdown(self) -> None:
        """Persist all cached states on shutdown."""
        self.logger.info("Shutting down Latent Engine — persisting states...")
        for user_id, cache in self._state_cache.items():
            try:
                await self._persist_state(cache)
            except Exception as e:
                self.logger.error(f"Failed to persist latent state for {user_id}: {e}")

    # =========================================================================
    # CORE TITANS LOOP
    # =========================================================================

    async def absorb_experience(
        self,
        user_id: str,
        experience_embedding: list[float],
        emotional_state: dict[str, float] | None = None,
        domain: str = "general",
        experience_id: str | None = None,
    ) -> float:
        """
        Core TITANS loop: compute surprise → conditionally update state.

        Called by the Orchestrator/LearningEngine after every experience is logged.

        Args:
            user_id: User identifier
            experience_embedding: 768D embedding of the experience
            emotional_state: Current 27D emotion vector (for centroid tracking)
            domain: Domain label of the experience
            experience_id: Optional experience ID (for graph edge creation)

        Returns:
            The surprise gradient (for telemetry/logging). Range [0.0, 1.0].
        """
        if not experience_embedding or len(experience_embedding) != EMBED_DIM:
            return 0.0

        async with self._lock:
            # Get or create state
            cache = await self._get_or_create_state(user_id)

            # 1. Compute Surprise Gradient
            surprise = self._compute_surprise_gradient(
                new_embedding=experience_embedding,
                current_state=cache.state_vector,
                momentum=cache.momentum_vector,
            )

            # 2. Compute Adaptive Threshold
            threshold = self._compute_adaptive_threshold(
                avg_surprise=cache.avg_surprise,
                surprise_variance=cache.surprise_variance,
                total_experiences=cache.total_experiences_absorbed,
            )

            # 3. Update running surprise statistics (always, even if below threshold)
            cache = self._update_surprise_stats(cache, surprise)
            cache.total_experiences_absorbed += 1

            # 4. Update domain distribution (always)
            total = cache.total_experiences_absorbed
            dist = cache.domain_distribution
            for d in dist:
                dist[d] = dist[d] * ((total - 1) / total)
            dist[domain] = dist.get(domain, 0.0) + (1.0 / total)

            # 5. Conditionally update state vector (surprise-gated)
            if surprise > threshold:
                cache.state_vector, cache.momentum_vector = self._update_state(
                    current_state=cache.state_vector,
                    current_momentum=cache.momentum_vector,
                    new_embedding=experience_embedding,
                    surprise=surprise,
                    total_experiences=cache.total_experiences_absorbed,
                )
                cache.version += 1
                cache.last_updated = datetime.now(timezone.utc)
                cache.updates_since_summary += 1

                # Update emotional centroid (EMA of emotional responses)
                if emotional_state:
                    cache.emotional_centroid = self._update_emotional_centroid(
                        cache.emotional_centroid,
                        emotional_state,
                        cache.total_experiences_absorbed,
                    )

                # Create graph edge for surprising experiences
                if surprise > EDGE_SURPRISE_THRESHOLD and experience_id:
                    asyncio.create_task(
                        self._create_modulates_edge(user_id, experience_id, surprise)
                    )

                # Regenerate summary periodically
                if cache.updates_since_summary >= SUMMARY_REGEN_INTERVAL:
                    asyncio.create_task(self._regenerate_summary(user_id))
                    cache.updates_since_summary = 0

                self.logger.info(
                    f"🧠 Latent state updated: user={user_id}, v={cache.version}, "
                    f"surprise={surprise:.3f} > threshold={threshold:.3f}"
                )
            else:
                self.logger.debug(
                    f"Latent state unchanged: surprise={surprise:.3f} <= threshold={threshold:.3f}"
                )

            # 6. Persist to DB (async, non-blocking on every update)
            # Only persist every 5 version bumps or if this was a significant update
            if cache.version % 5 == 0 or surprise > EDGE_SURPRISE_THRESHOLD:
                asyncio.create_task(self._persist_state(cache))

        return surprise

    # =========================================================================
    # ZERO-LATENCY MAC RETRIEVAL
    # =========================================================================

    def get_intuition_context(self, user_id: str) -> str:
        """
        ZERO-LATENCY: Returns cached XML block for L3 injection.

        No DB query. No embedding computation. Pure memory read.
        This is the MAC (Memory as Context) output.

        Returns:
            XML string ready for injection into L3 system prompt.
            Returns empty string if no state exists for user.
        """
        cache = self._state_cache.get(user_id)
        if not cache or cache.total_experiences_absorbed < 3:
            return ""

        # Build XML block
        xml = "<latent_intuition>\n"

        # Summary (natural language interpretation)
        if cache.summary_text:
            confidence = min(1.0, cache.total_experiences_absorbed / 100)
            xml += (
                f"  <state_summary confidence='{confidence:.2f}' "
                f"experiences_absorbed='{cache.total_experiences_absorbed}'>\n"
                f"    {cache.summary_text}\n"
                f"  </state_summary>\n"
            )

        # Emotional centroid (how this user makes Aura feel)
        if cache.emotional_centroid:
            top_emotions = sorted(
                cache.emotional_centroid.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            emo_str = ", ".join(f"{k}={v:.2f}" for k, v in top_emotions if v > 0.05)
            if emo_str:
                xml += f"  <emotional_centroid>{emo_str}</emotional_centroid>\n"

        # Domain affinity
        if cache.domain_distribution:
            top_domains = sorted(
                cache.domain_distribution.items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5]
            domain_str = ", ".join(f"{k}={v:.2f}" for k, v in top_domains if v > 0.03)
            if domain_str:
                xml += f"  <domain_affinity>{domain_str}</domain_affinity>\n"

        # Momentum / drift detection
        momentum_magnitude = math.sqrt(
            sum(x * x for x in cache.momentum_vector)
        ) if cache.momentum_vector else 0.0
        if momentum_magnitude > 0.05 and cache.domain_distribution:
            # Find which domain the momentum is trending toward
            top_domain = max(
                cache.domain_distribution.items(), key=lambda x: x[1]
            )[0]
            xml += (
                f"  <recent_drift direction='toward {top_domain}' "
                f"magnitude='{momentum_magnitude:.3f}'/>\n"
            )

        xml += "</latent_intuition>"
        return xml

    # =========================================================================
    # WARM START
    # =========================================================================

    async def warm_start(self, user_id: str) -> None:
        """
        Warm start: process the last N experiences to rapidly anneal
        an initial baseline state for a new user.

        Called on first boot when no latent_state record exists.
        """
        self.logger.info(f"🔥 Warm start for user {user_id}: processing last {WARM_START_EXPERIENCE_COUNT} experiences...")
        try:
            experiences = await self.db.query(
                """
                SELECT id, embedding, domain, emotional_state, timestamp
                FROM experience
                WHERE user_id = $uid AND embedding != NONE
                ORDER BY timestamp ASC
                LIMIT $lim
                """,
                {"uid": user_id, "lim": WARM_START_EXPERIENCE_COUNT},
            )

            if not experiences:
                self.logger.info(f"No experiences found for warm start (user={user_id})")
                return

            count = 0
            for exp in experiences:
                embedding = exp.get("embedding")
                if not embedding or len(embedding) != EMBED_DIM:
                    continue
                domain = exp.get("domain", "general")
                emo = exp.get("emotional_state") or {}
                exp_id = str(exp.get("id", ""))

                await self.absorb_experience(
                    user_id=user_id,
                    experience_embedding=embedding,
                    emotional_state=emo,
                    domain=domain,
                    experience_id=exp_id,
                )
                count += 1

            self.logger.info(
                f"✅ Warm start complete: absorbed {count} experiences for user {user_id}"
            )

            # Generate initial summary after warm start
            if count > 5:
                await self._regenerate_summary(user_id)

        except Exception as e:
            self.logger.error(f"Warm start failed for {user_id}: {e}", exc_info=True)

    # =========================================================================
    # MATHEMATICAL CORE
    # =========================================================================

    @staticmethod
    def _compute_surprise_gradient(
        new_embedding: list[float],
        current_state: list[float],
        momentum: list[float],
    ) -> float:
        """
        Compute surprise gradient between new experience and current latent state.

        Surprise = 1 - cosine_similarity(new_experience, latent_state)
        Adjusted by momentum alignment to detect sustained vs. noise surprise.

        Returns value in [0.0, 1.0]:
            0.0 = perfectly expected
            1.0 = completely novel
        """
        # Base surprise: distance from current state
        base_surprise = 1.0 - _cosine_similarity(new_embedding, current_state)

        # Momentum alignment: are we already drifting toward this?
        momentum_alignment = _cosine_similarity(new_embedding, momentum)

        # If momentum is already aligned, reduce surprise (we're adapting)
        # If momentum is opposed, amplify surprise (unexpected shift)
        momentum_factor = 1.0 - (0.3 * max(0.0, momentum_alignment))

        effective_surprise = base_surprise * momentum_factor
        return max(0.0, min(1.0, effective_surprise))

    @staticmethod
    def _compute_adaptive_threshold(
        avg_surprise: float,
        surprise_variance: float,
        total_experiences: int,
    ) -> float:
        """
        Adaptive gating threshold based on running surprise distribution.

        Formula: τ = mean + 1.5 * std
        With maturity scaling:
        - Early life (< 50 experiences): k=0.5 (aggressive learning)
        - Mature (50-500): k=1.0 (moderate gating)
        - Stable (500+): k=1.5 (conservative — only outliers)

        Returns threshold in [0.05, 0.80].
        """
        if total_experiences < 50:
            k = 0.5
        elif total_experiences < 500:
            k = 1.0
        else:
            k = 1.5

        threshold = avg_surprise + k * math.sqrt(max(surprise_variance, 0.001))
        return max(0.05, min(0.80, threshold))

    @staticmethod
    def _update_state(
        current_state: list[float],
        current_momentum: list[float],
        new_embedding: list[float],
        surprise: float,
        total_experiences: int,
    ) -> tuple[list[float], list[float]]:
        """
        TITANS-inspired state update with momentum.

        Learning rates:
        - α (state): How much the new experience moves the state
        - β (momentum): How much the new experience influences drift direction

        Both modulated by surprise: higher surprise → larger update.
        Both decay with experience count (annealing).
        """
        # Learning rate decays with experience count (annealing)
        base_alpha = 0.1 / (1 + math.log(1 + total_experiences / 100))
        base_beta = 0.3 / (1 + math.log(1 + total_experiences / 200))

        # Surprise amplification: more surprise = larger step
        alpha = base_alpha * (1 + 2 * surprise)  # Range: [α, 3α]
        beta = base_beta * (1 + surprise)  # Range: [β, 2β]

        # State update: exponential moving average
        new_state = [
            (1 - alpha) * s + alpha * e
            for s, e in zip(current_state, new_embedding)
        ]

        # Momentum update: tracks direction of recent changes
        delta = [e - s for e, s in zip(new_embedding, current_state)]
        new_momentum = [
            (1 - beta) * m + beta * d
            for m, d in zip(current_momentum, delta)
        ]

        # Normalize state to unit sphere (maintains cosine similarity semantics)
        magnitude = math.sqrt(sum(x * x for x in new_state)) or 1.0
        new_state = [x / magnitude for x in new_state]

        # Normalize momentum
        m_mag = math.sqrt(sum(x * x for x in new_momentum)) or 1.0
        new_momentum = [x / m_mag for x in new_momentum]

        return new_state, new_momentum

    @staticmethod
    def _update_surprise_stats(
        cache: LatentStateCache, surprise: float
    ) -> LatentStateCache:
        """Update running mean and variance of surprise (Welford's algorithm)."""
        n = cache.total_experiences_absorbed + 1
        old_mean = cache.avg_surprise
        new_mean = old_mean + (surprise - old_mean) / n
        # Online variance update
        new_variance = cache.surprise_variance + (
            (surprise - old_mean) * (surprise - new_mean) - cache.surprise_variance
        ) / n
        cache.avg_surprise = new_mean
        cache.surprise_variance = max(0.001, new_variance)
        return cache

    @staticmethod
    def _update_emotional_centroid(
        current_centroid: dict[str, float],
        new_emotions: dict[str, float],
        total_experiences: int,
    ) -> dict[str, float]:
        """
        Update emotional centroid using exponential moving average.

        The centroid represents HOW THIS USER MAKES AURA FEEL over time,
        providing a historical emotional baseline for the relationship.
        """
        # Use a slow-updating EMA to track long-term emotional patterns
        alpha = 0.05 / (1 + math.log(1 + total_experiences / 200))
        alpha = max(0.01, min(0.2, alpha))

        updated = dict(current_centroid)
        for emotion, value in new_emotions.items():
            if abs(value) < 0.05:
                continue  # Filter noise
            old_val = updated.get(emotion, 0.0)
            updated[emotion] = (1 - alpha) * old_val + alpha * value

        # Prune near-zero entries
        updated = {k: v for k, v in updated.items() if abs(v) > 0.02}
        return updated

    # =========================================================================
    # PERSISTENCE
    # =========================================================================

    async def _get_or_create_state(self, user_id: str) -> LatentStateCache:
        """Get cached state or create a new one (with optional warm start)."""
        if user_id in self._state_cache:
            return self._state_cache[user_id]

        # Try loading from DB
        try:
            rows = await self.db.query(
                "SELECT * FROM latent_state WHERE user_id = $uid LIMIT 1",
                {"uid": user_id},
            )
            if rows and isinstance(rows[0], dict):
                row = rows[0]
                cache = LatentStateCache(
                    user_id=user_id,
                    state_vector=row.get("state_vector") or [0.0] * EMBED_DIM,
                    momentum_vector=row.get("momentum_vector") or [0.0] * EMBED_DIM,
                    version=row.get("version", 0),
                    total_experiences_absorbed=row.get("total_experiences_absorbed", 0),
                    avg_surprise=row.get("avg_surprise", 0.5),
                    surprise_variance=row.get("surprise_variance", 0.1),
                    emotional_centroid=row.get("emotional_centroid") or {},
                    domain_distribution=row.get("domain_distribution") or {},
                    summary_text=row.get("summary_text") or "",
                )
                self._state_cache[user_id] = cache
                return cache
        except Exception as e:
            self.logger.debug(f"Failed to load latent state from DB: {e}")

        # Create fresh state
        cache = LatentStateCache(
            user_id=user_id,
            state_vector=[0.0] * EMBED_DIM,
            momentum_vector=[0.0] * EMBED_DIM,
        )
        self._state_cache[user_id] = cache

        # Schedule warm start in background (don't block the first query)
        asyncio.create_task(self.warm_start(user_id))
        return cache

    async def _persist_state(self, cache: LatentStateCache) -> None:
        """Persist latent state to SurrealDB (upsert via SurrealQL)."""
        try:
            # Use raw SurrealQL UPSERT to avoid SDK-level issues with
            # record IDs containing dots (e.g., discord_zoot.augur).
            await self.db.query(
                """
                UPSERT latent_state
                CONTENT {
                    user_id: $uid,
                    state_vector: $state_vector,
                    momentum_vector: $momentum_vector,
                    version: $version,
                    total_experiences_absorbed: $total_experiences_absorbed,
                    avg_surprise: $avg_surprise,
                    surprise_variance: $surprise_variance,
                    emotional_centroid: $emotional_centroid,
                    domain_distribution: $domain_distribution,
                    last_updated: $last_updated,
                    summary_text: $summary_text
                }
                WHERE user_id = $uid
                """,
                {
                    "uid": cache.user_id,
                    "state_vector": cache.state_vector,
                    "momentum_vector": cache.momentum_vector,
                    "version": cache.version,
                    "total_experiences_absorbed": cache.total_experiences_absorbed,
                    "avg_surprise": cache.avg_surprise,
                    "surprise_variance": cache.surprise_variance,
                    "emotional_centroid": cache.emotional_centroid,
                    "domain_distribution": cache.domain_distribution,
                    "last_updated": datetime.now(timezone.utc),
                    "summary_text": cache.summary_text,
                },
            )
        except Exception as e:
            self.logger.error(f"Failed to persist latent state: {e}")

    async def _create_modulates_edge(
        self, user_id: str, experience_id: str, surprise: float
    ) -> None:
        """Create a ->modulates-> graph edge for surprising experiences."""
        try:
            # Find the latent_state record ID
            state_rows = await self.db.query(
                "SELECT id FROM latent_state WHERE user_id = $uid LIMIT 1",
                {"uid": user_id},
            )
            if not state_rows:
                return

            state_id = str(state_rows[0].get("id", ""))
            if not state_id:
                return

            await self.db.query(
                """
                RELATE $exp->modulates->$state
                SET surprise_gradient = $surprise,
                    timestamp = time::now()
                """,
                {
                    "exp": experience_id,
                    "state": state_id,
                    "surprise": surprise,
                },
            )
            self.logger.debug(
                f"Created modulates edge: {experience_id} -> {state_id} (surprise={surprise:.3f})"
            )
        except Exception as e:
            self.logger.debug(f"Failed to create modulates edge (non-critical): {e}")

    # =========================================================================
    # SUMMARY GENERATION (L5)
    # =========================================================================

    async def _regenerate_summary(self, user_id: str) -> None:
        """
        Use L5 to generate a natural-language interpretation of the latent state.
        Called every N updates, not on every query.
        """
        if not self.llm_layers:
            return

        cache = self._state_cache.get(user_id)
        if not cache:
            return

        try:
            # Build a compact representation for L5
            top_emotions = sorted(
                cache.emotional_centroid.items(), key=lambda x: x[1], reverse=True
            )[:7]
            emo_str = ", ".join(f"{k}: {v:.2f}" for k, v in top_emotions) if top_emotions else "neutral"

            top_domains = sorted(
                cache.domain_distribution.items(), key=lambda x: x[1], reverse=True
            )[:5]
            domain_str = ", ".join(f"{k}: {v:.1%}" for k, v in top_domains) if top_domains else "general"

            prompt = f"""Generate a brief 2-3 sentence intuition summary about a user based on their interaction patterns.

Emotional centroid (how they make me feel): {emo_str}
Domain distribution (what they care about): {domain_str}
Total interactions absorbed: {cache.total_experiences_absorbed}
Average surprise level: {cache.avg_surprise:.3f}

Write a concise summary of what I intuitively sense about this user's interests, communication style, and how our interactions tend to feel. Be specific, not generic. Write in first person as Aura."""

            messages = [
                {"role": "system", "content": "You are Aura's latent memory summarizer. Output 2-3 concise sentences. No preamble."},
                {"role": "user", "content": prompt},
            ]

            from aura.config import settings
            summary = await self.llm_layers.client.complete(
                messages=messages,
                model=settings.active_l5_model,
                temperature=0.4,
                max_tokens=150,
            )

            if summary and isinstance(summary, str) and len(summary.strip()) > 10:
                cache.summary_text = summary.strip()
                self.logger.info(f"🧠 Latent summary regenerated for {user_id}: {cache.summary_text[:80]}...")
            else:
                self.logger.debug("Summary generation returned empty result")

        except Exception as e:
            self.logger.warning(f"Failed to regenerate latent summary: {e}")

    # =========================================================================
    # DIAGNOSTICS
    # =========================================================================

    def get_state_diagnostics(self, user_id: str) -> dict[str, Any]:
        """Get diagnostic info about a user's latent state (for debug API)."""
        cache = self._state_cache.get(user_id)
        if not cache:
            return {"status": "no_state", "user_id": user_id}

        momentum_magnitude = math.sqrt(
            sum(x * x for x in cache.momentum_vector)
        ) if cache.momentum_vector else 0.0

        return {
            "user_id": user_id,
            "version": cache.version,
            "total_experiences_absorbed": cache.total_experiences_absorbed,
            "avg_surprise": round(cache.avg_surprise, 4),
            "surprise_variance": round(cache.surprise_variance, 4),
            "adaptive_threshold": round(
                self._compute_adaptive_threshold(
                    cache.avg_surprise, cache.surprise_variance,
                    cache.total_experiences_absorbed
                ), 4
            ),
            "momentum_magnitude": round(momentum_magnitude, 4),
            "emotional_centroid": {
                k: round(v, 3) for k, v in sorted(
                    cache.emotional_centroid.items(),
                    key=lambda x: x[1], reverse=True
                )[:5]
            },
            "domain_distribution": {
                k: round(v, 3) for k, v in sorted(
                    cache.domain_distribution.items(),
                    key=lambda x: x[1], reverse=True
                )[:5]
            },
            "summary": cache.summary_text[:200] if cache.summary_text else None,
            "last_updated": cache.last_updated.isoformat(),
            "updates_since_summary": cache.updates_since_summary,
        }


# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Fast cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 <= 0 or n2 <= 0:
        return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))


# =============================================================================
# SINGLETON
# =============================================================================

_latent_engine: LatentEngine | None = None


def get_latent_engine() -> LatentEngine:
    """Get the global LatentEngine singleton."""
    global _latent_engine
    if _latent_engine is None:
        _latent_engine = LatentEngine()
    return _latent_engine
