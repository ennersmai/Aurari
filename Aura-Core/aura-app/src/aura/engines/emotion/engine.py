"""
Emotion Engine - Background tick processor for emotional state.

Implements Emotion FRD FR-EE-003 (Real-time Processing).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, TYPE_CHECKING

from aura.config import settings
from aura.clock import get_clock
from aura.db.client import get_db_client
from aura.db.query_utils import to_record_id
from aura.engines.base import BaseEngine
from aura.engines.emotion import mood as mood_math
from aura.engines.emotion import relationship as rel_math
from aura.engines.emotion.physics import EmotionPhysics
from aura.engines.emotion.translator import EmotionTranslator
from aura.models.emotion import (
    EmotionCause,
    EmotionInfluence,
    EmotionalSignature,
    EmotionPhysicsConfig,
    EmotionState,
    EmotionVector,
)
from aura.models.appraisal import AppraisalEvent
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

        # Mood (W4-13): only touched while settings.emotion_mood_enabled
        self._mood: dict[str, float] = {axis: 0.0 for axis in mood_math.AXES}
        self._mood_at = get_clock().now()

        # Relationship baseline (W4-14): love and trust resting points of the last
        # speaker; None until a person's message is appraised.
        self._rel_baseline: dict[str, float] | None = None

        # Timing
        self._last_tick_time = get_clock().now()
        self._last_persistence_time = get_clock().now()

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

    def _effective_baseline(self) -> EmotionVector:
        """Resting point the physics decays toward.

        The configured baseline; with the relationships flag on and a speaker
        known, love and trust come from that person's relationship instead.
        Then (mood flag on) a shift of the positive dimensions by the mood
        valence. The configured baseline is never changed.
        """
        base = self.config.baseline
        if settings.emotion_relationships_enabled and self._rel_baseline is not None:
            base = EmotionVector(**{**base.model_dump(), **self._rel_baseline})
        if not settings.emotion_mood_enabled:
            return base
        shift = mood_math.baseline_shift(
            self._mood["valence"],
            settings.emotion_mood_baseline_gain,
            settings.emotion_mood_baseline_shift_max,
        )
        values = base.model_dump()
        for dim in mood_math.POSITIVE_DIMENSIONS:
            values[dim] = max(0.0, min(1.0, values[dim] + shift))
        return EmotionVector(**values)

    def _advance_mood(self, now: datetime) -> None:
        """Move mood toward the current state's projection by the real time elapsed.

        The projection is measured from the effective baseline, so a state resting
        at a mood-shifted baseline does not feed the mood it came from.
        """
        dt = (now - self._mood_at).total_seconds()
        self._mood_at = now
        target = mood_math.project_mood(
            self.current_vector.model_dump(),
            self._effective_baseline().model_dump(),
            {
                "valence": settings.emotion_mood_valence_weights,
                "arousal": settings.emotion_mood_arousal_weights,
                "control": settings.emotion_mood_control_weights,
            },
        )
        self._mood = mood_math.step(
            self._mood, target, dt, settings.emotion_mood_half_life_hours * 3600.0
        )

    async def tick(self) -> None:
        """Execute one emotion engine cycle."""
        now = get_clock().now()
        dt = (now - self._last_tick_time).total_seconds()

        # Clamp dt: keep the lower bound so a too-small dt uses the tick rate.
        # The 10 s cap is removed (PRD section 4.2 / E7): a restart applies the
        # true elapsed time so a day offline decays the state by a day.
        if dt < 0.1:
            dt = self.tick_rate

        # Apply physics
        self.previous_vector = self.current_vector.model_copy()
        self.current_vector = self.physics.tick(
            self.current_vector, dt, self._effective_baseline()
        )
        self._last_tick_time = now
        if settings.emotion_mood_enabled:
            self._advance_mood(now)

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
        """Get current emotional state with description, deviation, baseline, and top causes."""
        dominant = self.current_vector.get_dominant()
        top_emotions = self.current_vector.get_top_n(n=3)

        secondary = top_emotions[1] if len(top_emotions) > 1 else None

        description = self.translator.translate(self.current_vector)

        stability = self.physics.calculate_stability(self.volatility_history)

        # Compute deviation from baseline
        baseline = self.config.baseline
        current_dict = self.current_vector.model_dump()
        baseline_dict = baseline.model_dump()
        deviation = {
            emotion: current_dict.get(emotion, 0.0) - baseline_dict.get(emotion, 0.0)
            for emotion in current_dict
        }

        # Get top 3 emotion events from the last hour by size
        top_causes = await self._get_top_causes()

        return EmotionState(
            timestamp=get_clock().now(),
            vector=self.current_vector,
            dominant=dominant,
            secondary=secondary,
            volatility=self.volatility_history[-1] if self.volatility_history else 0.0,
            stability=stability,
            description=description,
            deviation=deviation,
            baseline=baseline_dict,
            mood=dict(self._mood) if settings.emotion_mood_enabled else None,
            top_causes=top_causes,
        )

    async def _get_top_causes(self) -> list[EmotionCause]:
        """Get the three largest emotion events of the last hour by size, newest first among equals."""
        try:
            now = get_clock().now()
            one_hour_ago = now - timedelta(hours=1)
            result = await self.db.query(
                """
                SELECT * FROM emotion_event
                WHERE at >= $since
                ORDER BY size DESC, at DESC
                LIMIT 3
                """,
                {"since": one_hour_ago},
            )
            if not result:
                return []
            causes = []
            for row in result:
                cause = EmotionCause(
                    at=row.get("at"),
                    kind=row.get("kind", ""),
                    source=row.get("source", ""),
                    ref=row.get("ref"),
                    person_id=row.get("person_id"),
                    dominant_change=row.get("dominant_change"),
                    size=row.get("size", 0.0),
                )
                causes.append(cause)
            return causes
        except Exception as e:
            self.logger.warning(f"Failed to fetch top causes: {e}")
            return []

    async def get_state(self, person_id: str | None = None) -> EmotionState:
        """
        Get emotional state for a person.

        With the relationships flag on and a ``person_id``, ``love`` and ``trust``
        are read from that person's relationship (scaled into the dimension's
        range); every other dimension is the shared state. Otherwise the global
        state is returned.
        """
        state = await self.get_current_state()
        if not (settings.emotion_relationships_enabled and person_id):
            return state
        rel, _ = await self._load_relationship(person_id)
        values = {**state.vector.model_dump(), **rel_math.baseline_for(rel, settings)}
        vector = EmotionVector(**values)
        top = vector.get_top_n(n=3)
        return state.model_copy(update={
            "vector": vector,
            "dominant": vector.get_dominant(),
            "secondary": top[1] if len(top) > 1 else None,
            "description": self.translator.translate(vector),
        })

    @staticmethod
    def _person_rid(person_id: str) -> Any:
        """Entity RecordID for a speaker key (``"owner"``, ``"discord_42"``).

        The same id ``ensure_person`` builds, ``entity:<key>``; no write.
        """
        thing = person_id if person_id.startswith("entity:") else f"entity:{person_id}"
        return to_record_id(thing.replace("\u27e8", "").replace("\u27e9", ""))

    async def _load_relationship(
        self, person_id: str
    ) -> tuple[dict[str, float], bool]:
        """Read-only lookup: (relationship values, entity exists).

        Missing fields, or a missing entity, read as the starting values
        (the owner's for the key ``"owner"``).
        """
        row = None
        exists = False
        try:
            rows = await self.db.query(
                "SELECT affection, trust, familiarity, tension FROM $rid",
                {"rid": self._person_rid(person_id)},
            )
            if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                row, exists = rows[0], True
        except Exception as e:
            self.logger.warning(f"Failed to read relationship for {person_id}: {e}")
        return rel_math.resolve(row, person_id == "owner", settings), exists

    async def explain(self, since: datetime | None = None) -> list[EmotionCause]:
        """
        Get emotion events since the given time (default: last hour), newest first.

        Args:
            since: Start time for filtering events. Defaults to one hour ago.

        Returns:
            List of EmotionCause objects, newest first.
        """
        if since is None:
            since = get_clock().now() - timedelta(hours=1)

        try:
            result = await self.db.query(
                """
                SELECT * FROM emotion_event
                WHERE at >= $since
                ORDER BY at DESC
                """,
                {"since": since},
            )
            if not result:
                return []
            causes = []
            for row in result:
                cause = EmotionCause(
                    at=row.get("at"),
                    kind=row.get("kind", ""),
                    source=row.get("source", ""),
                    ref=row.get("ref"),
                    person_id=row.get("person_id"),
                    dominant_change=row.get("dominant_change"),
                    size=row.get("size", 0.0),
                )
                causes.append(cause)
            return causes
        except Exception as e:
            self.logger.warning(f"Failed to fetch explanation events: {e}")
            return []

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

    async def appraise(self, event: AppraisalEvent) -> EmotionState:
        """
        Appraise an event and update emotional state accordingly.

        This is the only way emotional state changes (PRD section 9).
        Uses the appraisal table to compute impulses, applies them through
        the same physics as apply_influence (coupling and inertia), writes
        an emotion_event record, and broadcasts the new state.

        Args:
            event: The appraisal event containing appraisal variables

        Returns:
            Updated emotional state (or current state if no impulses matched)
        """
        # Check if appraisal is enabled
        if not settings.emotion_appraisal_enabled:
            self.logger.debug("Appraisal disabled; returning current state")
            return await self.get_current_state()

        # Compute impulses from the appraisal table
        from aura.engines.emotion.appraisal import impulses_for

        # Mood bias (W4-13): an ambiguous event leans with the mood. The unbiased
        # appraisal is what gets recorded.
        appraisal = event.appraisal
        mood_bias = None
        if (
            settings.emotion_mood_enabled
            and settings.emotion_mood_appraisal_bias_enabled
        ):
            mood_bias = 0.0
            if abs(appraisal.congruence) < 0.3:
                mood_bias = max(
                    -0.1,
                    min(0.1, settings.emotion_mood_appraisal_bias * self._mood["valence"]),
                )
                appraisal = appraisal.model_copy(
                    update={
                        "congruence": max(-1.0, min(1.0, appraisal.congruence + mood_bias))
                    }
                )

        impulses = impulses_for(appraisal, event.user_state)

        # Relationship (W4-14): message events from a known person only. System
        # events carry no person (tool events name the tool in person_id).
        rel = None
        rel_exists = False
        if (
            settings.emotion_relationships_enabled
            and event.person_id
            and event.kind == "message"
        ):
            rel, rel_exists = await self._load_relationship(event.person_id)
            self._rel_baseline = rel_math.baseline_for(rel, settings)
            if impulses:
                impulses = rel_math.scale_impulses(
                    impulses, rel, event.appraisal.warmth, settings
                )

        # If no impulses matched, log at DEBUG and return current state
        if not impulses:
            await self._update_relationship(event, rel, rel_exists)
            self.logger.debug(
                f"No appraisal match for event kind={event.kind} source={event.source}; "
                f"appraisal={event.appraisal.model_dump()}"
            )
            return await self.get_current_state()

        # Store baseline before applying influence
        baseline = self.config.baseline
        old_vector = self.current_vector.model_copy()

        # Apply impulses through physics (same as apply_influence)
        # Note: impulses_for already multiplies by appraisal.intensity, so we pass 1.0
        # to avoid squaring the intensity (W3-20 supervisor fix).
        self.previous_vector = self.current_vector.model_copy()
        self.current_vector = self.physics.apply_influence(
            self.current_vector, impulses, 1.0
        )

        # Apply state normalization clamp (same as apply_influence)
        vector_dict = self.current_vector.model_dump()
        clamped_dict = {k: max(0.0, min(1.0, v)) for k, v in vector_dict.items()}
        self.current_vector = EmotionVector(**clamped_dict)
        if settings.emotion_mood_enabled:
            self._advance_mood(get_clock().now())

        # Compute per-dimension deviation change from baseline
        new_vector_dict = self.current_vector.model_dump()
        old_vector_dict = old_vector.model_dump()
        baseline_dict = baseline.model_dump()

        deviation_change = {}
        for emotion in new_vector_dict:
            old_deviation = old_vector_dict.get(emotion, 0.0) - baseline_dict.get(emotion, 0.0)
            new_deviation = new_vector_dict.get(emotion, 0.0) - baseline_dict.get(emotion, 0.0)
            deviation_change[emotion] = new_deviation - old_deviation

        # Find dominant change
        dominant_change = None
        max_change = 0.0
        for emotion, change in deviation_change.items():
            if abs(change) > max_change:
                max_change = abs(change)
                dominant_change = emotion

        # Write emotion_event record
        at = get_clock().now()
        event_record = {
            "at": at,
            "kind": event.kind,
            "source": event.source,
            "ref": event.ref,
            "person_id": event.person_id,
            "venue": event.venue,
            "appraisal": event.appraisal.model_dump(),
            "impulses": impulses,
            "deviation_change": deviation_change,
            "dominant_change": dominant_change,
            "size": max_change,
        }
        if mood_bias is not None:
            event_record["mood_bias"] = mood_bias
        try:
            await self.db.create("emotion_event", event_record)
        except Exception as e:
            # Database failure is logged but does not undo the state change
            self.logger.error(f"Failed to write emotion_event: {e}")

        await self._update_relationship(event, rel, rel_exists)

        # Broadcast state update
        await self._broadcast_state_update(priority=MessagePriority.URGENT)

        return await self.get_current_state()

    async def _update_relationship(
        self, event: AppraisalEvent, rel: dict[str, float] | None, exists: bool
    ) -> None:
        """Step the speaker's relationship and write it: one parameterised UPDATE.

        Nothing is written without a ``person_id`` or when the person has no
        entity yet (an UPDATE would create a nameless record; the entity is
        created by the memory write path).
        """
        if rel is None or not exists or not event.person_id:
            return
        new = rel_math.step(rel, event.appraisal, settings)
        try:
            await self.db.query(
                "UPDATE $rid SET affection = $affection, trust = $trust, "
                "familiarity = $familiarity, tension = $tension, "
                "relationship_updated_at = $at",
                {
                    "rid": self._person_rid(event.person_id),
                    **new,
                    "at": get_clock().now(),
                },
            )
        except Exception as e:
            self.logger.error(f"Failed to write relationship: {e}")

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

            # Convert top_causes to plain JSON-serializable dicts
            top_causes_json = [
                {
                    "at": cause.at.isoformat() if cause.at else None,
                    "kind": cause.kind,
                    "source": cause.source,
                    "ref": cause.ref,
                    "person_id": cause.person_id,
                    "dominant_change": cause.dominant_change,
                    "size": cause.size,
                }
                for cause in state.top_causes
            ]

            emotion_data = {
                **vector_data,
                "current_state": state.description,
                "dominant": state.dominant[0],
                "timestamp": state.timestamp.isoformat(),
                "volatility": state.volatility,
                "valence": valence,
                "arousal": arousal,
                "entropy": state.volatility,
                # New fields from W3-24
                "deviation": state.deviation,
                "baseline": state.baseline,
                "mood": state.mood,
                "top_causes": top_causes_json,
            }
            await broadcast_emotion_update({"data": emotion_data})
        except Exception as e:
            self.logger.error(f"Failed to broadcast emotion websocket update: {e}")

    async def _persist_state(self) -> None:
        """Save current emotional state to database."""
        try:
            state = await self.get_current_state()

            record = {
                "timestamp": state.timestamp,
                "vector": state.vector.model_dump(),
                "dominant": list(state.dominant),
                "volatility": state.volatility,
                "description": state.description,
            }
            if settings.emotion_mood_enabled:
                record["mood"] = dict(self._mood)
                record["mood_at"] = self._mood_at
            await self.db.create("emotion_state", record)

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
                if settings.emotion_mood_enabled and last_state.get("mood"):
                    # No state was lived through while offline: mood decays toward
                    # neutral by the real elapsed time (no cap).
                    now = get_clock().now()
                    saved_at = last_state.get("mood_at") or last_state.get("timestamp")
                    saved = last_state["mood"]
                    self._mood = mood_math.decay(
                        {axis: float(saved.get(axis, 0.0)) for axis in mood_math.AXES},
                        (now - saved_at).total_seconds(),
                        settings.emotion_mood_half_life_hours * 3600.0,
                    )
                    self._mood_at = now
                self.logger.info("Loaded previous emotional state from database")
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")
            raise
