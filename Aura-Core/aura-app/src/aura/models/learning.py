"""Learning models (Learning FRD Section 3)."""

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from aura.models.base import BaseModel

# Insight types for categorization
InsightType = Literal[
    "FACT",
    "PREFERENCE", 
    "PATTERN",
    "SKILL_MANUAL",  # For operational insights about learned tools/skills
    "CORRECTION"     # For corrections from the Dreaming Engine
]


class Experience(BaseModel):
    """
    Logged interaction experience with vector embeddings.

    Based on Learning FRD FR-LL-002.
    """

    experience_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    user_id: str
    task_type: str = Field(..., description="e.g., 'code_debugging', 'conversation'")
    domain: str = Field(..., description="e.g., 'javascript', 'philosophy'")

    context: dict[str, Any] = Field(
        ...,
        description="User query, code snippets, tools used, conversation summary",
    )

    aura_response: dict[str, Any] = Field(
        ..., description="Diagnosis, solution, confidence, reasoning strategy"
    )

    outcome: dict[str, Any] = Field(
        ...,
        description="Success status, user feedback, time to resolution, emotional resolution",
    )

    emotional_state: dict[str, Any] = Field(
        ..., description="Pre and post emotional state, dominant emotion"
    )

    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Similar experiences, learned_from flag, importance",
    )

    # Vector embedding for semantic pattern extraction
    embedding: list[float] | None = Field(
        default=None, description="Vector embedding for clustering similar experiences"
    )


class Insight(BaseModel):
    """
    Learned knowledge from interactions (Facts, Preferences, Patterns).
    
    Replaces the rigid Rule system with flexible RAG-based insights.
    Retrieved by semantic similarity for contextual responses.
    """

    insight_id: str
    created: datetime = Field(default_factory=datetime.utcnow)
    updated: datetime = Field(default_factory=datetime.utcnow)

    @classmethod
    def model_validate(cls, obj: Any, *args, **kwargs) -> "Insight":
        # Handle SurrealDB returning 'id' instead of 'insight_id'
        if isinstance(obj, dict):
            if "id" in obj and "insight_id" not in obj:
                obj["insight_id"] = str(obj["id"])
            elif "insight_id" not in obj and "id" not in obj:
                raise ValueError("Record missing both 'id' and 'insight_id' fields")
        return super().model_validate(obj, *args, **kwargs)

    # Core content
    content: str = Field(..., description="The learned fact, preference, or pattern")
    type: InsightType = Field(
        ..., description="Category of insight: FACT, PREFERENCE, PATTERN, SKILL_MANUAL, or CORRECTION"
    )
    
    # Context
    domain: str = Field(..., description="Domain of applicability")
    user_id: str = Field(..., description="User this insight relates to")
    
    # Confidence tracking
    confidence: float = Field(..., ge=0.0, le=1.0)
    confidence_history: list[dict[str, Any]] = Field(default_factory=list)
    
    # Statistics
    application_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    last_used: datetime | None = None
    
    # Provenance
    source_experiences: list[str] = Field(default_factory=list)
    extraction_method: str = Field(default="l2_analysis")
    
    # Emotional context (FR-LE-001: Emotion-Learning Bridge)
    emotional_signature: dict[str, float] = Field(
        default_factory=dict,
        description="Emotional state snapshot at insight creation (27D vector subset)",
    )
    hedonic_score: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Valence tag for future hedonic-gradient rule selection (-1 negative, +1 positive)",
    )

    # Metadata
    deprecated: bool = Field(default=False)
    deprecation_threshold: float = Field(default=0.3, ge=0.0, le=1.0)
    
    # Vector embedding for semantic retrieval
    embedding: list[float] | None = Field(
        default=None,
        description="Vector embedding for RAG semantic similarity search",
    )


class Skill(BaseModel):
    """
    Hierarchical knowledge organization node.

    Based on Learning FRD FR-ST-001.
    """

    skill_id: str
    name: str
    domain: str
    created: datetime = Field(default_factory=datetime.utcnow)

    # Mastery
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)

    # Emotional association
    emotional_signature: dict[str, float] = Field(default_factory=dict)

    # Hierarchy
    parent_skill_id: str | None = None
    sub_skill_ids: list[str] = Field(default_factory=list)
    insight_ids: list[str] = Field(default_factory=list)  # Changed from rule_ids

    # Metadata
    last_practiced: datetime | None = None
    practice_count: int = Field(default=0, ge=0)


class Strategy(BaseModel):
    """
    Reasoning strategy meta-layer.

    Based on Learning FRD FR-RS-001.
    """

    strategy_id: str
    task_type: str = Field(..., description="Type of task this strategy applies to")
    approach: str = Field(..., description="Name of reasoning approach")

    # Performance
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    avg_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    usage_count: int = Field(default=0, ge=0)

    # Emotional prerequisites
    emotional_prerequisites: dict[str, float] = Field(
        default_factory=dict, description="Required emotional state {emotion: min_value}"
    )

    # Guidance
    when_to_use: str = Field(default="", description="Guidance on when to apply")
    examples: list[str] = Field(default_factory=list, description="Example experience IDs")

    # Metadata
    last_updated: datetime = Field(default_factory=datetime.utcnow)


class LearningContext(BaseModel):
    """Learning context for insight retrieval and application."""

    insights: list[Insight] = Field(default_factory=list)  # Changed from rules
    strategy: Strategy | None = None
    confidence_level: float = Field(default=0.0, ge=0.0, le=1.0)
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)
    emotional_alignment: dict[str, float] = Field(default_factory=dict)

