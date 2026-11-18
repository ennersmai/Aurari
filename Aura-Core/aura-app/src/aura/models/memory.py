"""Memory models (PRD Section 8.1)."""

from datetime import datetime
from typing import Any

from pydantic import Field

from aura.models.base import BaseModel


class FormationContext(BaseModel):
    """
    Rich context about where and when a memory was born.

    Enables powerful future queries like "show me memories formed during
    high-resonance conversations" or "what did Aura learn during task X".
    """

    conversation_id: str | None = None
    task_id: str | None = Field(
        default=None, description="If formed during a task, link it",
    )
    active_cultural_node: str | None = Field(
        default=None, description="Cultural routing node active at formation time",
    )
    resonance_score_at_formation: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Resonance field score at the moment this memory was formed",
    )
    step_in_conversation: int = Field(
        default=0, ge=0,
        description="Which turn in the conversation this memory came from",
    )
    triggered_by: str | None = Field(
        default=None,
        description="Retrieval query that surfaced the memories leading to this one",
    )


class Memory(BaseModel):
    """
    Memory node with emotional tagging and vector embeddings.

    Based on PRD Section 8.1.
    """

    memory_id: str
    content: str = Field(..., description="Memory content")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    # Emotional context
    emotional_signature: dict[str, float] = Field(
        default_factory=dict, description="Emotional state during memory formation"
    )

    # Metadata
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    learned_from: bool = Field(default=False, description="Has this memory been learned from?")
    conversation_id: str | None = None
    user_id: str | None = None

    @classmethod
    def model_validate(cls, obj: Any, *args, **kwargs) -> "Memory":
        """Handle SurrealDB ID mapping."""
        if isinstance(obj, dict):
            if "id" in obj and "memory_id" not in obj:
                obj["memory_id"] = str(obj["id"])
        return super().model_validate(obj, *args, **kwargs)

    # Resonance field score at write time (0.0–1.0)
    resonance_score: float | None = Field(
        default=None, ge=0.0, le=1.0,
        description="Resonance field score when this memory was formed",
    )

    # Additional context
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Vector embedding for semantic search (1536 dimensions for OpenAI/OpenRouter)
    embedding: list[float] | None = Field(
        default=None, description="Vector embedding for semantic similarity search"
    )

    # --- Memory Quality Layer (Session 5) ---

    formation_score: float = Field(
        default=0.5, ge=0.0, le=1.0,
        description="Quality score computed at formation: novelty * 0.30 + emotion * 0.30 + depth * 0.20 + surprise * 0.20",
    )
    ephemeral: bool = Field(
        default=False,
        description="Lightweight record excluded from normal retrieval, eligible for aggressive pruning",
    )
    core_memory: bool = Field(
        default=False,
        description="Protected from pruning, infinite half-life, always included in cold-start retrieval",
    )
    deprecated: bool = Field(
        default=False,
        description="Soft-deleted: kept for graph integrity but excluded from retrieval",
    )
    memory_type: str = Field(
        default="episodic",
        description="episodic (default) or semantic (abstracted from multiple episodic memories)",
    )
    emotional_intensity: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Magnitude of emotional state vector at formation time",
    )
    recall_count: int = Field(
        default=0, ge=0,
        description="Number of times this memory has been recalled (Hebbian counter)",
    )
    last_recalled_at: datetime | None = Field(
        default=None,
        description="Timestamp of most recent recall — used for access-strengthened decay",
    )

    # Rich formation context (Session 5)
    formation_context: FormationContext | None = Field(
        default=None,
        description="Where, when, and why this memory was born",
    )


class Conversation(BaseModel):
    """Conversation session."""

    conversation_id: str
    user_id: str
    session_id: str = Field(
        default="main",
        description="Session this conversation belongs to (V1PRD §4)",
    )
    started_at: datetime = Field(default_factory=datetime.utcnow)
    ended_at: datetime | None = None

    # Messages
    message_count: int = Field(default=0, ge=0)

    # Emotional trajectory
    initial_emotion: dict[str, float] = Field(default_factory=dict)
    final_emotion: dict[str, float] = Field(default_factory=dict)

    # Summary
    summary: str = Field(default="")
    key_topics: list[str] = Field(default_factory=list)

    # Learning
    experiences_logged: list[str] = Field(default_factory=list)
    rules_created: list[str] = Field(default_factory=list)


class ColdStartContext(BaseModel):
    """
    Pre-loaded context injected into L3 at conversation start.

    Ensures Aura wakes up knowing who the user is, what just happened,
    and what she's learned — every time, without waiting for the first
    message to trigger retrieval.
    """

    core_memories: list[Memory] = Field(
        default_factory=list,
        description="All core_memory=True records for the user — always loaded",
    )
    recent_memories: list[Memory] = Field(
        default_factory=list,
        description="3 most recent non-ephemeral memories (last session context)",
    )
    top_insights: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Top 3 highest-confidence insights from the learning engine",
    )
    active_cultural_node: str | None = Field(
        default=None,
        description="Currently active cultural routing node code",
    )
    emotional_baseline: dict[str, float] = Field(
        default_factory=dict,
        description="Last known emotional state vector",
    )
    xml_block: str = Field(
        default="",
        description="Pre-formatted XML block ready for L3 system prompt injection",
    )


class DreamConsolidationReport(BaseModel):
    """
    Structured summary of what the dreaming cycle accomplished.

    Stored as a system memory so Aura can reflect on her own cognitive maintenance.
    """

    pruned: int = Field(default=0, description="Ephemeral/faded memories removed")
    abstracted: int = Field(default=0, description="Episodic clusters synthesized into semantic memories")
    reprocessed: int = Field(default=0, description="Negative memories turned into learning insights")
    core_memories: int = Field(default=0, description="Total core memories (untouched)")
    total_active: int = Field(default=0, description="Total active (non-deprecated) memories remaining")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MemoryIntrospection(BaseModel):
    """
    Aura's self-report on the health and shape of her memory.

    Returned by GET /memory/introspect/{user_id}.
    """

    total_memories: int = 0
    core_memories: int = 0
    ephemeral_pending_pruning: int = 0
    semantic_abstractions: int = 0
    oldest_memory: str | None = None
    strongest_memory: dict[str, Any] = Field(default_factory=dict)
    most_emotional_memory: dict[str, Any] = Field(default_factory=dict)
    dominant_domains: list[str] = Field(default_factory=list)
    memory_health_score: float = Field(default=0.0, ge=0.0, le=1.0)
    last_dream_cycle: str | None = None
    insights_count: int = 0
    knowledge_graph_edges: int = 0

