"""
Cultural Node models for multi-cultural reasoning architecture.

Implements the data layer for the Cultural RLHF Engine (PRD v2.0 Section 2.2).
Each CulturalNode represents a geopolitical reasoning framework with its own
communication style, value weights, and ethical principles.

Designed for future multi-Aura federation: nodes are self-describing and
serialisable so remote Aura instances can query and sync cultural context.
"""

from datetime import datetime
from typing import Any

from pydantic import Field

from aura.models.base import BaseModel


class CulturalNode(BaseModel):
    """
    A geopolitical reasoning framework node.

    Contains the full value profile for one cultural perspective.
    The router selects a node per turn; LLM integration is deferred
    to a future session — this is data architecture only.
    """

    code: str = Field(..., description="ISO-style short code, e.g. 'JP', 'RU', 'EU'")
    name: str = Field(..., description="Human-readable name, e.g. 'Japan'")

    # Communication & value profile
    communication_style: str = Field(
        ...,
        description="'explicit', 'high_context', 'indirect', 'understated', etc.",
    )
    collective_weight: float = Field(
        ..., ge=0.0, le=1.0,
        description="0 = fully individualist, 1 = fully collectivist",
    )
    restraint_bias: float = Field(
        ..., ge=-1.0, le=1.0,
        description="-1 = action-biased, +1 = restraint-biased",
    )

    # Cultural concepts and principles
    key_concepts: dict[str, str] = Field(
        default_factory=dict,
        description="Concept name → short explanation, e.g. {'kata': 'Form / pattern mastery'}",
    )
    ethical_principles: list[str] = Field(
        default_factory=list,
        description="Core ethical principles of this cultural framework",
    )

    # Metadata
    is_active: bool = Field(default=True)
    confidence_level: float = Field(default=0.5, ge=0.0, le=1.0)


class CulturalRoutingDecision(BaseModel):
    """
    Log entry for a cultural routing decision.

    Captures which node was selected, why, and with what confidence.
    Designed for future audit / federation sync.
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    selected_node: str = Field(..., description="Code of the selected CulturalNode")
    detection_method: str = Field(
        ...,
        description="How context was detected: 'language', 'location', 'explicit', 'default'",
    )
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = Field(default="", description="Human-readable routing rationale")
    user_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
