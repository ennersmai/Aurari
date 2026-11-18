"""
Emotion Engine - Background tick processor for emotional state.

Implements Emotion FRD FR-EE-003 (Real-time Processing).
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

from aura.config import settings
from aura.db.client import get_db_client
from aura.engines.base import BaseEngine
from aura.engines.emotion.physics import EmotionPhysics
from aura.engines.emotion.translator import EmotionTranslator
from aura.models.emotion import (
    EmotionInfluence,
    EmotionalSignature,
    EmotionPhysicsConfig,
    EmotionState,
    EmotionVector,
)
from aura.models.messages import EngineMessage, MessagePriority

if TYPE_CHECKING:
    from aura.orchestrator.protocols import MessageBusProtocol

logger = logging.getLogger(__name__)


class EmotionEngine(BaseEngine):
    """
    Emotion Engine with 27D physics simulation and real-time tick processing.

    Based on Emotion FRD Sections 3.1 and 3.2.
    """

    def __init__(
        self,
        config: EmotionPhysicsConfig | None = None,
        tick_rate: float | None = None,
    ):
        """
        Initialize emotion engine.

        Args:
            config: Physics configuration
            tick_rate: Seconds between ticks (default from settings)
        """
        super().__init__("emotion_engine")

        self.config = config or EmotionPhysicsConfig()
        self.tick_rate = tick_rate or settings.emotion_tick_rate
        self.persistence_interval = settings.emotion_persistence_interval

        # Core components
        self.physics = EmotionPhysics(self.config)
        self.translator = EmotionTranslator()

        # State
        self.current_vector = self.config.baseline.model_copy()
        self.previous_vector = self.current_vector.model_copy()
        self.volatility_history: list[float] = []

        # Timing
        self._last_tick_time = datetime.utcnow()
        self._last_persistence_time = datetime.utcnow()

        # Database
        self.db = get_db_client()

    def set_message_bus(self, message_bus: "MessageBusProtocol") -> None:
        """Set message bus for inter-engine communication."""
        super().set_message_bus(message_bus)
        if message_bus:
            message_bus.subscribe("emotion_engine", self._handle_message)

    async def initialize(self) -> None:
        """Initialize engine resources."""
        self.logger.info("Initializing Emotion Engine...")

        # Try to load last saved state
        try:
            await self._load_state()
        except Exception as e:
            self.logger.warning(f"Could not load previous state: {e}")
            self.logger.info("Starting with baseline emotional state")

        # Hydrate per-emotion physics from the SurrealDB emotion table.
        # This resolves the split-brain: physics parameters are now DB-driven,
        # enabling self-modifying physics when values are updated in the DB.
        await self._hydrate_physics_from_db()

        self.logger.info(
            f"Emotion Engine initialized - Tick rate: {self.tick_rate}s, "
            f"Dominant emotion: {self.current_vector.get_dominant()}"
        )

    async def _hydrate_physics_from_db(self) -> None:
        """Fetch physics parameters (decay, inertia) from the 'emotion' table and
        overwrite the hardcoded Pydantic defaults in :attr:`self.config` and the
        resolved rate dict in :attr:`self.physics`.

        Strategy
        --------
        * Query all 27 emotion records for ``name``, ``category``, and ``physics``.
        * Group ``physics.decay`` values by ``category`` and compute the per-category
          mean → write to ``self.config.decay_rate_<category>`` and propagate to
          ``self.physics.decay_rates[category]``.
        * Compute the global mean of all ``physics.inertia`` values → write to
          ``self.config.inertia_default``.

        Failures are swallowed as warnings so a cold DB always falls back to
        the hardcoded Pydantic defaults without crashing the engine.
        """
        try:
            rows = await self.db.query(
                "SELECT name, category, physics FROM emotion"
            )
            if not rows:
                self.logger.debug(
                    "No emotion rows returned — keeping hardcoded physics defaults"
                )
                return

            category_decays: dict[str, list[float]] = {}
            all_inertias: list[float] = []

            for row in rows:
                category  = row.get("category") or ""
                phys      = row.get("physics") or {}
                decay_val   = phys.get("decay")
                inertia_val = phys.get("inertia")

                if decay_val is not None and category:
                    category_decays.setdefault(category, []).append(float(decay_val))
                if inertia_val is not None:
                    all_inertias.append(float(inertia_val))

            # Update config.decay_rate_<category> and physics.decay_rates[category]
            for cat, vals in category_decays.items():
                avg = max(0.0, min(1.0, sum(vals) / len(vals)))
                config_field = f"decay_rate_{cat}"
                if hasattr(self.config, config_field):
                    setattr(self.config, config_field, avg)
                decay_rates = getattr(self.physics, "decay_rates", None)
                if isinstance(decay_rates, dict):
                    decay_rates[cat] = avg

            # Update global inertia_default from the mean across all emotions
            if all_inertias:
                self.config.inertia_default = max(
                    0.0, min(1.0, sum(all_inertias) / len(all_inertias))
                )

            self.logger.info(
                "Physics hydrated from DB: categories=%s avg_inertia=%.3f",
                sorted(category_decays.keys()),
                self.config.inertia_default,
            )
        except Exception as exc:
            self.logger.warning("Physics DB hydration failed (non-fatal): %s", exc)

    async def tick(self) -> None:
        """Execute one emotion engine cycle."""
        now = datetime.utcnow()
        dt = (now - self._last_tick_time).total_seconds()
        
        # Clamp dt to prevent issues with very large or very small values
        # If dt is too large (e.g., server was down), cap it at 10 seconds
        # If dt is too small (e.g., processing delay), use the intended tick rate
        if dt > 10.0:
            dt = 10.0
        elif dt < 0.1:
            dt = self.tick_rate

        # Apply physics
        self.previous_vector = self.current_vector.model_copy()
        self.current_vector = self.physics.tick(
            self.current_vector, dt, self.config.baseline
        )
        self._last_tick_time = now

        # Calculate volatility
        volatility = self.physics.calculate_volatility(
            self.current_vector, self.previous_vector
        )
        self.volatility_history.append(volatility)
        if len(self.volatility_history) > 20:  # Keep last 20 samples
            self.volatility_history.pop(0)

        # Check if significant change occurred (>0.3 in any emotion)
        significant_change = self._detect_significant_change()

        if significant_change:
            # Broadcast state update
            await self._broadcast_state_update(priority=MessagePriority.URGENT)

        # Periodic persistence
        time_since_save = (now - self._last_persistence_time).total_seconds()
        if time_since_save >= self.persistence_interval:
            await self._persist_state()
            self._last_persistence_time = now

        # Sleep until next tick
        await asyncio.sleep(self.tick_rate)

    async def shutdown(self) -> None:
        """Clean up engine resources."""
        self.logger.info("Shutting down Emotion Engine...")
        await self._persist_state()
        self.logger.info("Emotion Engine shut down")

    async def get_current_state(self) -> EmotionState:
        """Get current emotional state with description."""
        dominant = self.current_vector.get_dominant()
        top_emotions = self.current_vector.get_top_n(n=3)

        secondary = top_emotions[1] if len(top_emotions) > 1 else None

        description = self.translator.translate(self.current_vector)

        stability = self.physics.calculate_stability(self.volatility_history)

        return EmotionState(
            timestamp=datetime.utcnow(),
            vector=self.current_vector,
            dominant=dominant,
            secondary=secondary,
            volatility=self.volatility_history[-1] if self.volatility_history else 0.0,
            stability=stability,
            description=description,
        )

    async def apply_influence(self, influence: EmotionInfluence) -> EmotionState:
        """
        Apply external emotional influence.

        Args:
            influence: Influence specification

        Returns:
            Updated emotional state
        """
        self.logger.info(
            f"Applying influence from {influence.source}: {influence.reason}"
        )

        self.previous_vector = self.current_vector.model_copy()
        self.current_vector = self.physics.apply_influence(
            self.current_vector, influence.emotions, influence.intensity
        )

        # Apply state_normalization clamp
        vector_dict = self.current_vector.model_dump()
        clamped_dict = {k: max(0.0, min(1.0, v)) for k, v in vector_dict.items()}
        self.current_vector = EmotionVector(**clamped_dict)

        # Broadcast immediate state update
        await self._broadcast_state_update(priority=MessagePriority.URGENT)

        return await self.get_current_state()

    async def configure_physics(self, config: EmotionPhysicsConfig) -> None:
        """Update physics configuration."""
        self.config = config
        self.physics = EmotionPhysics(config)
        self.logger.info("Physics configuration updated")

    async def capture_learning_event(self) -> EmotionalSignature:
        """
        Capture current emotional state as an EmotionalSignature snapshot.

        Called by the learning engine when an insight/rule is created so the
        learned knowledge carries the emotional context of its origin.
        Implements FR-LE-001 (Emotional Tagging on Rules).

        Returns:
            EmotionalSignature frozen at this moment.
        """
        state = await self.get_current_state()
        vector_dict = state.vector.model_dump()
        dominant_name, _ = state.dominant

        # Compute valence: weighted sum of positive vs negative emotions
        valence = self._compute_valence(vector_dict)

        signature = EmotionalSignature(
            dominant_emotion=dominant_name,
            emotional_vector=vector_dict,
            valence=valence,
            volatility=state.volatility,
            timestamp=state.timestamp,
        )

        self.logger.info(
            f"Captured learning event signature: dominant={dominant_name}, "
            f"valence={valence:.2f}, volatility={state.volatility:.2f}"
        )
        return signature

    @staticmethod
    def _compute_valence(vector: dict[str, float]) -> float:
        """
        Derive scalar valence from 27D vector.

        Positive emotions contribute positively, negative emotions negatively.
        Returns a value in [-1.0, 1.0].
        """
        positive = (
            "joy", "love", "interest", "trust", "curiosity", "fascination",
            "wonder", "awe", "beauty", "serenity", "empathy", "compassion",
            "gratitude", "pride", "certainty",
        )
        negative = (
            "fear", "sadness", "anger", "disgust", "shame", "envy",
            "doubt", "confusion", "boredom", "melancholy",
        )
        # nostalgia and surprise are neutral/ambivalent — excluded from both

        pos_sum = sum(vector.get(e, 0.0) for e in positive)
        neg_sum = sum(vector.get(e, 0.0) for e in negative)
        total = pos_sum + neg_sum
        if total == 0:
            return 0.0
        return max(-1.0, min(1.0, (pos_sum - neg_sum) / total))

    async def get_history(
        self, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get emotional state history from database."""
        try:
            result = await self.db.query(
                """
                SELECT * FROM emotion_state
                ORDER BY timestamp DESC
                LIMIT $limit
                """,
                {"limit": limit},
            )
            return result if result else []
        except Exception as e:
            self.logger.error(f"Failed to retrieve history: {e}")
            return []

    async def _handle_message(self, message: EngineMessage) -> None:
        """Handle incoming messages from other engines."""
        # For now, we just log that we received it.
        # Future: React to rule learning or other engine events
        self.logger.debug(f"Emotion Engine received message from {message.source}: {message.message_type}")

    # Private methods

    def _detect_significant_change(self) -> bool:
        """Detect if a significant emotional change occurred."""
        curr = self.current_vector.model_dump()
        prev = self.previous_vector.model_dump()

        for emotion in curr.keys():
            change = abs(curr[emotion] - prev[emotion])
            if change > 0.3:
                return True

        return False

    async def _broadcast_state_update(
        self, priority: MessagePriority = MessagePriority.NORMAL
    ) -> None:
        """Broadcast emotional state update via message bus and websocket."""
        state = await self.get_current_state()

        if self._message_bus:
            message = EngineMessage.create_state_update(
                source="emotion_engine",
                data={
                    "vector": state.vector.model_dump(),
                    "dominant": state.dominant,
                    "description": state.description,
                    "volatility": state.volatility,
                },
                targets=["orchestrator", "learning_engine", "goal_engine"],
                priority=priority,
            )

            await self._message_bus.publish(message)

        # Fire websocket update to Mission Control
        try:
            from aura.api.websocket import broadcast_emotion_update
            vector_data = state.vector.model_dump()
            positive_emotions = vector_data.get('joy', 0) + vector_data.get('love', 0) + vector_data.get('trust', 0) + vector_data.get('interest', 0)
            negative_emotions = vector_data.get('fear', 0) + vector_data.get('sadness', 0) + vector_data.get('anger', 0) + vector_data.get('disgust', 0)
            valence = (positive_emotions - negative_emotions) / 4.0
            arousal = (vector_data.get('surprise', 0) + vector_data.get('fear', 0) + vector_data.get('anger', 0) + vector_data.get('joy', 0)) / 4.0

            emotion_data = {
                **vector_data,
                "current_state": state.description,
                "dominant": state.dominant[0],
                "timestamp": state.timestamp.isoformat(),
                "volatility": state.volatility,
                "valence": valence,
                "arousal": arousal,
                "entropy": state.volatility,
            }
            await broadcast_emotion_update({"data": emotion_data})
        except Exception as e:
            self.logger.error(f"Failed to broadcast emotion websocket update: {e}")

    async def _persist_state(self) -> None:
        """Save current emotional state to database."""
        try:
            state = await self.get_current_state()

            await self.db.create(
                "emotion_state",
                {
                    "timestamp": state.timestamp,
                    "vector": state.vector.model_dump(),
                    "dominant": list(state.dominant),
                    "volatility": state.volatility,
                    "description": state.description,
                },
            )

            self.logger.debug("Emotional state persisted to database")
        except Exception as e:
            self.logger.error(f"Failed to persist state: {e}")

    async def _load_state(self) -> None:
        """Load last saved emotional state from database."""
        try:
            result = await self.db.query(
                """
                SELECT * FROM emotion_state
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )

            if result:
                last_state = result[0]
                vector_data = last_state.get("vector", {})
                loaded_vector = EmotionVector(**vector_data)
                
                # Safety check: if any emotion is extremely high (>0.95), reset to baseline
                # This prevents corrupted or extreme values from persisting
                needs_reset = False
                for emotion, value in loaded_vector.model_dump().items():
                    if value > 0.95:
                        self.logger.warning(
                            f"Detected extreme emotion value: {emotion}={value:.2f}. "
                            "Resetting to baseline to prevent stuck states."
                        )
                        needs_reset = True
                        break
                
                if needs_reset:
                    self.current_vector = self.config.baseline.model_copy()
                    self.logger.info("Reset to baseline due to extreme values")
                else:
                    self.current_vector = loaded_vector
                
                self.previous_vector = self.current_vector.model_copy()
                self.logger.info("Loaded previous emotional state from database")
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
            raise
