"""
Cognitive State Models — Structural Learning Engine

Pydantic models for the sovereign cognitive architecture that map
cleanly to SurrealDB's graph-oriented data model.

These models represent the *structural* layer of Aura's mind:
  - Pattern:  Recurring interaction templates extracted by L2 analysis.
  - Abstraction:  Compressed, generalized knowledge nodes.
  - SkillTree:  Hierarchical competency graph with emotional tagging.

All models use SurrealDB record IDs (table:id) as primary keys and
support graph edges via RELATE statements.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import Field

from aura.models.base import BaseModel, TimestampedModel


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class PatternDomain(str, Enum):
    """Domains a pattern can belong to."""
    CONVERSATION = "conversation"
    CODING = "coding"
    EMOTIONAL = "emotional"
    TOOL_USE = "tool_use"
    LEARNING = "learning"
    GENERAL = "general"


class AbstractionLevel(str, Enum):
    """Level of abstraction in the knowledge hierarchy."""
    RAW = "raw"           # Direct observation
    PATTERN = "pattern"   # Recognized recurrence
    CONCEPT = "concept"   # Generalized idea
    PRINCIPLE = "principle"  # Universal rule
    META = "meta"         # Knowledge about knowledge


class SkillNodeType(str, Enum):
    """Type of node in the skill tree."""
    ROOT = "root"
    CATEGORY = "category"
    SKILL = "skill"
    SUB_SKILL = "sub_skill"
    TECHNIQUE = "technique"


# ---------------------------------------------------------------------------
# Pattern  (L2-extracted interaction template)
# ---------------------------------------------------------------------------

class PatternCondition(BaseModel):
    """Trigger condition for a pattern."""
    field: str = Field(..., description="Which field to check (e.g., 'user_input', 'emotion')")
    operator: Literal["contains", "equals", "matches", "gt", "lt", "in"] = "contains"
    value: Any = Field(..., description="Value to compare against")


class PatternAction(BaseModel):
    """Action to take when a pattern matches."""
    type: Literal["respond", "tool_call", "emotion_update", "memory_store", "goal_trigger"] = "respond"
    payload: dict[str, Any] = Field(default_factory=dict)


class Pattern(BaseModel):
    """
    A recurring interaction pattern extracted by L2 analysis.

    Maps to SurrealDB table: ``pattern``
    Graph edges:
      - ``pattern→abstraction`` (generalizes_to)
      - ``pattern→experience`` (extracted_from)
      - ``pattern→skill`` (belongs_to)
    """

    pattern_id: str = Field(..., description="SurrealDB record ID (pattern:<ulid>)")
    name: str = Field(..., description="Human-readable pattern name")
    domain: PatternDomain = Field(default=PatternDomain.GENERAL)

    # Trigger
    conditions: list[PatternCondition] = Field(
        default_factory=list,
        description="Conditions that trigger this pattern",
    )

    # Response
    actions: list[PatternAction] = Field(
        default_factory=list,
        description="Actions to execute when triggered",
    )

    # Confidence & statistics
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    activation_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    last_activated: datetime | None = None

    # Emotional context
    emotional_signature: dict[str, float] = Field(
        default_factory=dict,
        description="Typical emotional state when this pattern activates",
    )
    hedonic_tag: float = Field(
        default=0.0, ge=-1.0, le=1.0,
        description="Valence association (-1 negative, +1 positive)",
    )

    # Provenance
    source_experiences: list[str] = Field(default_factory=list)
    extraction_method: str = "l2_analysis"

    # Graph edges (SurrealDB RELATE)
    generalizes_to: list[str] = Field(
        default_factory=list,
        description="Abstraction IDs this pattern feeds into",
    )
    belongs_to_skill: str | None = Field(
        default=None,
        description="Skill ID this pattern is part of",
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    deprecated: bool = False


# ---------------------------------------------------------------------------
# Abstraction  (compressed knowledge node)
# ---------------------------------------------------------------------------

class Abstraction(BaseModel):
    """
    A compressed, generalized knowledge node in the cognitive hierarchy.

    Abstractions are formed by clustering related patterns and insights.
    They represent higher-level understanding that transcends individual
    experiences.

    Maps to SurrealDB table: ``abstraction``
    Graph edges:
      - ``abstraction→pattern`` (composed_of)
      - ``abstraction→abstraction`` (parent_of / child_of)
      - ``abstraction→skill`` (applied_in)
    """

    abstraction_id: str = Field(..., description="SurrealDB record ID (abstraction:<ulid>)")
    name: str = Field(..., description="Concept name")
    description: str = Field(default="", description="Natural language description")

    level: AbstractionLevel = Field(default=AbstractionLevel.PATTERN)

    # Composition
    source_patterns: list[str] = Field(
        default_factory=list,
        description="Pattern IDs that compose this abstraction",
    )
    source_insights: list[str] = Field(
        default_factory=list,
        description="Insight IDs that contributed to this abstraction",
    )

    # Hierarchy
    parent_abstraction_id: str | None = None
    child_abstraction_ids: list[str] = Field(default_factory=list)

    # Confidence
    coherence_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="How internally consistent this abstraction is",
    )
    evidence_count: int = Field(default=0, ge=0)

    # Emotional
    emotional_valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    emotional_activation: dict[str, float] = Field(default_factory=dict)

    # Application
    applied_in_skills: list[str] = Field(default_factory=list)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_reinforced: datetime | None = None
    version: int = Field(default=1, ge=1)


# ---------------------------------------------------------------------------
# Skill Tree  (hierarchical competency graph)
# ---------------------------------------------------------------------------

class SkillTreeNode(BaseModel):
    """
    A node in the hierarchical skill tree.

    Each node represents a competency at some level of granularity,
    from broad categories down to specific techniques.

    Maps to SurrealDB table: ``skill``
    Graph edges:
      - ``skill→skill`` (parent_of / child_of)
      - ``skill→pattern`` (uses)
      - ``skill→abstraction`` (understands)
      - ``skill→insight`` (knows)
    """

    skill_id: str = Field(..., description="SurrealDB record ID (skill:<ulid>)")
    name: str
    node_type: SkillNodeType = SkillNodeType.SKILL
    domain: str = "general"

    # Mastery
    mastery_level: float = Field(default=0.0, ge=0.0, le=1.0)
    mastery_history: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Time-series of mastery changes [{timestamp, level}]",
    )

    # Hierarchy
    parent_skill_id: str | None = None
    child_skill_ids: list[str] = Field(default_factory=list)

    # Associated knowledge
    pattern_ids: list[str] = Field(default_factory=list)
    abstraction_ids: list[str] = Field(default_factory=list)
    insight_ids: list[str] = Field(default_factory=list)

    # Emotional
    emotional_signature: dict[str, float] = Field(default_factory=dict)
    emotional_prerequisites: dict[str, float] = Field(
        default_factory=dict,
        description="Minimum emotional state needed to practice this skill",
    )

    # Practice
    practice_count: int = Field(default=0, ge=0)
    last_practiced: datetime | None = None
    practice_interval_days: float = Field(
        default=1.0, gt=0,
        description="Recommended days between practice sessions",
    )

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SkillTree(BaseModel):
    """
    Complete skill tree — the root container for the competency graph.

    Maps to SurrealDB table: ``skill_tree``
    """

    tree_id: str = Field(default="skill_tree:main")
    name: str = "Aura Skill Tree"
    root_skill_ids: list[str] = Field(default_factory=list)

    # Statistics
    total_nodes: int = Field(default=0, ge=0)
    average_mastery: float = Field(default=0.0, ge=0.0, le=1.0)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Cognitive State  (aggregate snapshot)
# ---------------------------------------------------------------------------

class CognitiveState(BaseModel):
    """
    Aggregate snapshot of the structural learning engine's state.

    Used by the /v1/cognition/* endpoints to provide a holistic view
    of Aura's cognitive architecture.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Counts
    pattern_count: int = 0
    abstraction_count: int = 0
    skill_count: int = 0

    # Top-level metrics
    average_pattern_confidence: float = 0.0
    average_abstraction_coherence: float = 0.0
    overall_mastery: float = 0.0

    # Active patterns (recently triggered)
    active_patterns: list[str] = Field(default_factory=list)

    # Recent abstractions
    recent_abstractions: list[str] = Field(default_factory=list)

    # Skill tree summary
    skill_tree_summary: dict[str, Any] = Field(default_factory=dict)