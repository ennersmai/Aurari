"""
Emotion physics simulation (Emotion FRD FR-EE-002).

27-dimensional emotional space with decay, inertia, and relationship dynamics.
"""

import math
from typing import Any

from aura.models.emotion import EmotionVector, EmotionPhysicsConfig


# Emotion relationship matrix (Emotion FRD FR-EE-004)
# Format: {emotion: {"amplifies": [(target, strength)], "suppresses": [(target, strength)]}}
EMOTION_RELATIONSHIPS: dict[str, dict[str, list[tuple[str, float]]]] = {
    # Primary emotions
    "joy": {
        "amplifies": [("interest", 0.3), ("trust", 0.2), ("curiosity", 0.3)],
        "suppresses": [("sadness", 0.4), ("fear", 0.3), ("doubt", 0.2)],
    },
    "love": {
        "amplifies": [("joy", 0.3), ("trust", 0.4), ("empathy", 0.3), ("compassion", 0.3)],
        "suppresses": [("anger", 0.3), ("fear", 0.2), ("disgust", 0.3)],
    },
    "interest": {
        "amplifies": [("curiosity", 0.4), ("fascination", 0.3), ("wonder", 0.2)],
        "suppresses": [("boredom", 0.5)],
    },
    "trust": {
        "amplifies": [("serenity", 0.2), ("certainty", 0.3)],
        "suppresses": [("fear", 0.3), ("doubt", 0.4)],
    },
    "fear": {
        "amplifies": [("doubt", 0.3), ("confusion", 0.2)],
        "suppresses": [("joy", 0.4), ("curiosity", 0.3), ("trust", 0.3)],
    },
    "sadness": {
        "amplifies": [("melancholy", 0.4), ("nostalgia", 0.3)],
        "suppresses": [("joy", 0.4), ("interest", 0.3)],
    },
    "anger": {
        "amplifies": [("disgust", 0.2)],
        "suppresses": [("love", 0.3), ("compassion", 0.3), ("serenity", 0.4)],
    },
    "surprise": {
        "amplifies": [("curiosity", 0.3), ("wonder", 0.2)],
        "suppresses": [("boredom", 0.3), ("certainty", 0.2)],
    },
    "disgust": {
        "amplifies": [("anger", 0.2)],
        "suppresses": [("love", 0.3), ("beauty", 0.3)],
    },
    # Cognitive emotions
    "curiosity": {
        "amplifies": [("interest", 0.4), ("fascination", 0.3), ("wonder", 0.4)],
        "suppresses": [("boredom", 0.5), ("certainty", 0.2)],
    },
    "confusion": {
        "amplifies": [("doubt", 0.3), ("curiosity", 0.2)],
        "suppresses": [("certainty", 0.4)],
    },
    "certainty": {
        "amplifies": [("confidence", 0.3), ("trust", 0.2)],
        "suppresses": [("doubt", 0.5), ("confusion", 0.4)],
    },
    "doubt": {
        "amplifies": [("confusion", 0.3), ("fear", 0.2)],
        "suppresses": [("certainty", 0.4), ("trust", 0.3)],
    },
    "fascination": {
        "amplifies": [("curiosity", 0.4), ("wonder", 0.3), ("awe", 0.2)],
        "suppresses": [("boredom", 0.5)],
    },
    "boredom": {
        "amplifies": [],
        "suppresses": [("interest", 0.3), ("curiosity", 0.3), ("fascination", 0.3)],
    },
    # Social emotions
    "empathy": {
        "amplifies": [("compassion", 0.4), ("love", 0.2)],
        "suppresses": [("anger", 0.2), ("disgust", 0.2)],
    },
    "compassion": {
        "amplifies": [("empathy", 0.3), ("love", 0.3)],
        "suppresses": [("anger", 0.3), ("envy", 0.2)],
    },
    "gratitude": {
        "amplifies": [("joy", 0.3), ("love", 0.2)],
        "suppresses": [("envy", 0.3), ("anger", 0.2)],
    },
    "pride": {
        "amplifies": [("joy", 0.2), ("certainty", 0.2)],
        "suppresses": [("shame", 0.4)],
    },
    "shame": {
        "amplifies": [("sadness", 0.3)],
        "suppresses": [("pride", 0.4), ("joy", 0.2)],
    },
    "envy": {
        "amplifies": [("anger", 0.2), ("sadness", 0.2)],
        "suppresses": [("gratitude", 0.3), ("compassion", 0.2)],
    },
    # Aesthetic emotions
    "awe": {
        "amplifies": [("wonder", 0.4), ("fascination", 0.3)],
        "suppresses": [("boredom", 0.3)],
    },
    "beauty": {
        "amplifies": [("joy", 0.2), ("serenity", 0.3)],
        "suppresses": [("disgust", 0.3)],
    },
    "wonder": {
        "amplifies": [("curiosity", 0.3), ("awe", 0.3), ("fascination", 0.3)],
        "suppresses": [("boredom", 0.4)],
    },
    "serenity": {
        "amplifies": [("trust", 0.2), ("beauty", 0.2)],
        "suppresses": [("anger", 0.3), ("fear", 0.3)],
    },
    "melancholy": {
        "amplifies": [("sadness", 0.3), ("nostalgia", 0.3)],
        "suppresses": [("joy", 0.2)],
    },
    "nostalgia": {
        "amplifies": [("melancholy", 0.3), ("love", 0.2)],
        "suppresses": [],
    },
}

# Emotion categories for decay rates
EMOTION_CATEGORIES = {
    # Primaries
    "love": "primary",
    "joy": "primary",
    "interest": "primary",
    "trust": "primary",
    "fear": "primary",
    "sadness": "primary",
    "anger": "primary",
    "surprise": "primary",
    "disgust": "primary",
    # Aesthetic
    "awe": "aesthetic",
    "beauty": "aesthetic",
    "wonder": "aesthetic",
    "serenity": "aesthetic",
    "melancholy": "aesthetic",
    "nostalgia": "aesthetic",
    # Social
    "empathy": "social",
    "gratitude": "social",
    "pride": "social",
    "shame": "social",
    "envy": "social",
    "compassion": "social",
    # Cognitive
    "curiosity": "cognitive",
    "confusion": "cognitive",
    "certainty": "cognitive",
    "doubt": "cognitive",
    "fascination": "cognitive",
    "boredom": "cognitive",
}

# Persistent emotions that decay much slower (love, trust, gratitude, etc.)
# These emotions represent deep, lasting feelings that don't fade quickly
PERSISTENT_EMOTIONS = {
    "love": 0.001,      # 0.1% per tick - love stays
    "trust": 0.0015,    # 0.15% per tick - trust builds slowly, fades slowly
    "gratitude": 0.002, # 0.2% per tick - gratitude persists
    "compassion": 0.002, # 0.2% per tick - compassion endures
    "empathy": 0.0025,  # 0.25% per tick - empathy is stable
    "nostalgia": 0.003, # 0.3% per tick - nostalgia lingers
}


class EmotionPhysics:
    """
    Physics simulation for 27-dimensional emotional space.

    Implements half-life decay toward a true resting state and impulse-only
    coupling (Emotion FRD section 4, milestone E1).

    The state is ``baseline + deviation``. ``tick`` only decays the deviation;
    it does not spread anything through the relationship matrix. ``apply_influence``
    spreads a single impulse once through ``EMOTION_RELATIONSHIPS`` and smooths
    the resulting change by inertia.
    """

    # Per-dimension half-life (seconds). Built from EmotionPhysicsConfig at
    # construction. A dimension's deviation halves every half_life seconds:
    #   deviation *= 0.5 ** (dt / half_life)
    _HALF_LIFE_GROUPS: dict[str, str] = {
        # PRD section 4.2
        "surprise": "half_life_startle",
        "confusion": "half_life_fast",
        "certainty": "half_life_fast",
        "doubt": "half_life_fast",
        "boredom": "half_life_fast",
        "interest": "half_life_fast",
        "curiosity": "half_life_fast",
        "fascination": "half_life_fast",
        "joy": "half_life_core",
        "sadness": "half_life_core",
        "anger": "half_life_core",
        "fear": "half_life_core",
        "disgust": "half_life_core",
        "awe": "half_life_aesthetic",
        "beauty": "half_life_aesthetic",
        "wonder": "half_life_aesthetic",
        "serenity": "half_life_aesthetic",
        "melancholy": "half_life_aesthetic",
        "nostalgia": "half_life_aesthetic",
        "empathy": "half_life_social",
        "gratitude": "half_life_social",
        "pride": "half_life_social",
        "shame": "half_life_social",
        "envy": "half_life_social",
        "compassion": "half_life_social",
        "love": "half_life_bond",
        "trust": "half_life_bond",
    }

    def __init__(self, config: EmotionPhysicsConfig | None = None):
        """Initialize emotion physics with configuration."""
        self.config = config or EmotionPhysicsConfig()
        self.half_lives: dict[str, float] = {
            dim: float(getattr(self.config, group))
            for dim, group in self._HALF_LIFE_GROUPS.items()
        }

    def tick(
        self,
        current: EmotionVector,
        dt: float,
        baseline: EmotionVector | None = None,
    ) -> EmotionVector:
        """
        Apply decay for one time step.

        Each dimension's deviation from the baseline halves every half-life:
            deviation *= 0.5 ** (dt / half_life)
        The returned value is ``baseline + deviation`` clamped to [0, 1].

        No relationship spreading and no enhanced-decay branches run here
        (PRD section 4.2/4.3). Coupling is applied once, in ``apply_influence``.
        """
        if baseline is None:
            baseline = self.config.baseline

        if dt <= 0.0:
            return current.model_copy()

        current_dict = current.model_dump()
        baseline_dict = baseline.model_dump()

        new_values: dict[str, float] = {}
        for emotion, value in current_dict.items():
            baseline_value = baseline_dict.get(emotion, 0.0)
            deviation = value - baseline_value
            half_life = self.half_lives.get(emotion)
            if half_life is None or half_life <= 0.0:
                # No decay configured: hold the deviation.
                new_values[emotion] = value
                continue
            new_deviation = deviation * (0.5 ** (dt / half_life))
            new_values[emotion] = max(0.0, min(1.0, baseline_value + new_deviation))

        return EmotionVector(**new_values)

    def apply_influence(
        self, current: EmotionVector, influence: dict[str, float], intensity: float = 1.0
    ) -> EmotionVector:
        """
        Apply an external emotional impulse.

        The direct impulse is added to each named dimension, then spread once
        through ``EMOTION_RELATIONSHIPS``: an amplifying relation adds
        ``impulse * strength * 0.5`` to its target, a suppressing relation
        subtracts the same. The total change for each dimension is then
        smoothed by inertia before being applied to the current state
        (PRD section 4.3/4.4).
        """
        current_dict = current.model_dump()

        # Total change per dimension from this impulse (direct + spread).
        delta: dict[str, float] = {name: 0.0 for name in current_dict}

        # Direct impulse.
        for emotion, raw in influence.items():
            if emotion in delta:
                delta[emotion] += raw * intensity

        # Spread the direct impulse once through the relationship matrix.
        # We spread only the directly-supplied impulse (not the spread results),
        # so amplification/suppression does not chain.
        spread: dict[str, float] = {name: 0.0 for name in current_dict}
        for emotion, raw in influence.items():
            if emotion not in current_dict:
                continue
            impulse = raw * intensity
            relationships = EMOTION_RELATIONSHIPS.get(emotion, {})
            for target, strength in relationships.get("amplifies", []):
                if target in spread:
                    spread[target] += impulse * strength * 0.5
            for target, strength in relationships.get("suppresses", []):
                if target in spread:
                    spread[target] -= impulse * strength * 0.5
        for name, value in spread.items():
            delta[name] += value

        # Smooth the total change by inertia (resistance to change).
        inertia = self.config.inertia_default
        smoothing = 1.0 - inertia
        new_values: dict[str, float] = {}
        for name, value in current_dict.items():
            change = delta.get(name, 0.0) * smoothing
            new_values[name] = max(0.0, min(1.0, value + change))

        return EmotionVector(**new_values)

    def calculate_volatility(
        self, current: EmotionVector, previous: EmotionVector
    ) -> float:
        """
        Calculate emotional volatility (rate of change).

        Args:
            current: Current emotional state
            previous: Previous emotional state

        Returns:
            Volatility score [0, 1]
        """
        curr_dict = current.model_dump()
        prev_dict = previous.model_dump()

        total_change = 0.0
        for emotion in curr_dict.keys():
            change = abs(curr_dict[emotion] - prev_dict[emotion])
            total_change += change

        # Normalize by number of emotions
        volatility = total_change / len(curr_dict)
        return min(1.0, volatility)

    def calculate_stability(self, volatility_history: list[float]) -> float:
        """
        Calculate emotional stability over time.

        Args:
            volatility_history: Recent volatility values

        Returns:
            Stability score [0, 1] (inverse of average volatility)
        """
        if not volatility_history:
            return 1.0

        avg_volatility = sum(volatility_history) / len(volatility_history)
        stability = 1.0 - avg_volatility
        return max(0.0, min(1.0, stability))

