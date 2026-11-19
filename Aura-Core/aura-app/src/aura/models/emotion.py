"""Emotion models (Emotion FRD Section 4.1)."""

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from aura.models.base import BaseModel


class EmotionVector(BaseModel):
    """
    27-dimensional emotional state vector.

    Based on Emotion FRD FR-EE-001:
    - 9 Primary emotions
    - 18 Secondary emotions (6 aesthetic, 6 social, 6 cognitive)
    """

    # 9 Primary emotions
    love: float = Field(default=0.0, ge=0.0, le=1.0)
    joy: float = Field(default=0.0, ge=0.0, le=1.0)
    interest: float = Field(default=0.0, ge=0.0, le=1.0)
    trust: float = Field(default=0.0, ge=0.0, le=1.0)
    fear: float = Field(default=0.0, ge=0.0, le=1.0)
    sadness: float = Field(default=0.0, ge=0.0, le=1.0)
    anger: float = Field(default=0.0, ge=0.0, le=1.0)
    surprise: float = Field(default=0.0, ge=0.0, le=1.0)
    disgust: float = Field(default=0.0, ge=0.0, le=1.0)

    # 6 Aesthetic emotions
    awe: float = Field(default=0.0, ge=0.0, le=1.0)
    beauty: float = Field(default=0.0, ge=0.0, le=1.0)
    wonder: float = Field(default=0.0, ge=0.0, le=1.0)
    serenity: float = Field(default=0.0, ge=0.0, le=1.0)
    melancholy: float = Field(default=0.0, ge=0.0, le=1.0)
    nostalgia: float = Field(default=0.0, ge=0.0, le=1.0)

    # 6 Social emotions
    empathy: float = Field(default=0.0, ge=0.0, le=1.0)
    gratitude: float = Field(default=0.0, ge=0.0, le=1.0)
    pride: float = Field(default=0.0, ge=0.0, le=1.0)
    shame: float = Field(default=0.0, ge=0.0, le=1.0)
    envy: float = Field(default=0.0, ge=0.0, le=1.0)
    compassion: float = Field(default=0.0, ge=0.0, le=1.0)

    # 6 Cognitive emotions
    curiosity: float = Field(default=0.0, ge=0.0, le=1.0)
    confusion: float = Field(default=0.0, ge=0.0, le=1.0)
    certainty: float = Field(default=0.0, ge=0.0, le=1.0)
    doubt: float = Field(default=0.0, ge=0.0, le=1.0)
    fascination: float = Field(default=0.0, ge=0.0, le=1.0)
    boredom: float = Field(default=0.0, ge=0.0, le=1.0)

    def get_dominant(self) -> tuple[str, float]:
        """Get the dominant emotion (highest value)."""
        emotions = self.model_dump()
        dominant_emotion = max(emotions.items(), key=lambda x: x[1])
        return dominant_emotion

    def get_top_n(self, n: int = 3) -> list[tuple[str, float]]:
        """Get top N emotions by intensity."""
        emotions = self.model_dump()
        sorted_emotions = sorted(emotions.items(), key=lambda x: x[1], reverse=True)
        return sorted_emotions[:n]


class EmotionalSignature(BaseModel):
    """
    Snapshot of emotional state at moment of learning or memory formation.

    Captures the dominant emotion, full vector, valence, and volatility
    so that learned knowledge carries the emotional context of its origin.
    Implements FR-LE-001 from the Emotion-Learning Bridge specification.
    """

    dominant_emotion: str = Field(..., description="Dominant emotion at capture time")
    emotional_vector: dict[str, float] = Field(
        default_factory=dict,
        description="Full 27D emotion vector snapshot",
    )
    valence: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Overall positive/negative sentiment (-1 to +1)",
    )
    volatility: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Emotional stability at capture time",
    )
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class EmotionCause(BaseModel):
    """
    A recorded emotional event that contributed to the current state.

    Based on Emotion FRD Section 9 (EmotionState gains top_causes).
    """

    at: datetime = Field(..., description="When the event occurred")
    kind: str = Field(..., description="Event kind (e.g., message, memory, goal)")
    source: str = Field(..., description="Source of the event (e.g., conversation, memory)")
    ref: str | None = Field(default=None, description="Optional reference ID")
    person_id: str | None = Field(default=None, description="Optional person ID")
    dominant_change: str | None = Field(default=None, description="Emotion with largest deviation change")
    size: float = Field(..., description="Largest absolute deviation change of that event")


class EmotionInfluence(BaseModel):
    """
    External influence on emotional state.

    Based on Emotion FRD FR-EE-005.
    """

    source: Literal[
        "conversation",
        "memory",
        "goal",
        "tool",
        "learning",
        "internal_critique",
        "orchestrator",  # Added for orchestrator-driven updates
    ] = Field(..., description="Source of influence")
    emotions: dict[str, float] = Field(
        ..., description="Emotions to influence {emotion: delta}"
    )
    intensity: float = Field(default=1.0, ge=0.0, le=2.0, description="Multiplier for influence")
    reason: str = Field(..., description="Human-readable reason for influence")
    duration: float = Field(
        default=0.0, ge=0.0, description="Duration in seconds (0 = instant)"
    )
    decay_rate: float | None = Field(
        default=None, description="Custom decay rate (overrides default)"
    )

    @field_validator("emotions")
    @classmethod
    def validate_emotions(cls, v: dict[str, float]) -> dict[str, float]:
        """Validate emotion deltas are in valid range."""
        for emotion, delta in v.items():
            if not -1.0 <= delta <= 1.0:
                raise ValueError(f"Emotion delta for {emotion} must be between -1.0 and 1.0")
        return v


class EmotionState(BaseModel):
    """
    Complete emotional state with metadata.

    Based on Emotion FRD Section 4.1.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    vector: EmotionVector
    dominant: tuple[str, float] = Field(..., description="Dominant emotion (name, intensity)")
    secondary: tuple[str, float] | None = Field(
        default=None, description="Secondary emotion (name, intensity)"
    )
    volatility: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How much emotions are changing"
    )
    stability: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Emotional consistency over time"
    )
    description: str = Field(default="", description="Human-readable emotional description")
    learning_influence: dict[str, float | str | bool] = Field(
        default_factory=dict, description="Learning engine influence context"
    )
    deviation: dict[str, float] | None = Field(
        default=None, description="Per-dimension deviation from baseline (vector - baseline)"
    )
    baseline: dict[str, float] | None = Field(
        default=None, description="Baseline (resting) emotional state"
    )
    mood: dict[str, float] | None = Field(
        default=None, description="Mood state (always None until E4)"
    )
    top_causes: list[EmotionCause] = Field(
        default_factory=list, description="Top 3 emotion events of the last hour by size"
    )


class EmotionPhysicsConfig(BaseModel):
    """Configuration for emotion physics parameters (Emotion FRD FR-EE-002)."""

    # --- Half-lives (seconds) per PRD section 4.2 ---
    # A dimension decays toward its baseline so that the deviation halves every
    # `half_life` seconds: deviation *= 0.5 ** (dt / half_life).
    # These are the starting values; relationships replace love/trust later.
    # love/trust are not decayed by category here; they keep a long half-life
    # until the relationship layer (PRD section 6.3) lands.
    half_life_startle: float = Field(default=45.0, gt=0.0)     # surprise
    half_life_fast: float = Field(default=300.0, gt=0.0)      # confusion, certainty, doubt, boredom, interest, curiosity, fascination (5 min)
    half_life_core: float = Field(default=900.0, gt=0.0)      # joy, sadness, anger, fear, disgust (15 min)
    half_life_aesthetic: float = Field(default=1200.0, gt=0.0)  # awe, beauty, wonder, serenity, melancholy, nostalgia (20 min)
    half_life_social: float = Field(default=1800.0, gt=0.0)   # empathy, gratitude, pride, shame, envy, compassion (30 min)
    half_life_bond: float = Field(default=43200.0, gt=0.0)    # love, trust (12 hours, until relationships land)

    # --- Legacy decay rates (kept so stored configs still load; no longer used) ---
    decay_rate_primary: float = Field(default=0.05, ge=0.0, le=1.0)  # 5% per tick (was 2%)
    decay_rate_aesthetic: float = Field(default=0.02, ge=0.0, le=1.0)  # 2% per tick (was 0.5%)
    decay_rate_social: float = Field(default=0.03, ge=0.0, le=1.0)  # 3% per tick (was 1%)
    decay_rate_cognitive: float = Field(default=0.04, ge=0.0, le=1.0)  # 4% per tick (was 1.5%)

    # Inertia (resistance to change). Applied as a single smoothing factor on
    # the total change produced by apply_influence (PRD section 4.4).
    inertia_default: float = Field(default=0.3, ge=0.0, le=1.0)
    inertia_high_arousal: float = Field(default=0.5, ge=0.0, le=1.0)
    inertia_low_arousal: float = Field(default=0.1, ge=0.0, le=1.0)

    # Tick rate
    tick_rate_seconds: float = Field(default=1.0, gt=0.0)

    # Baseline personality (resting state)
    baseline: EmotionVector = Field(default_factory=lambda: EmotionVector(
        curiosity=0.3,
        trust=0.2,
        joy=0.15,
        interest=0.25,
        serenity=0.2,
        love=0.05,  # Small baseline for love so it doesn't decay to zero
        gratitude=0.05,  # Small baseline for gratitude
        compassion=0.05,  # Small baseline for compassion
    ))

