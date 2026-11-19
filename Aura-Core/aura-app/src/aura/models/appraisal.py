"""Appraisal models (Emotion PRD Section 5.2, 5.3)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Appraisal(BaseModel):
    """
    Appraisal variables for an event (Emotion PRD Section 5.2).

    Each event is described by a small set of numbers that determine
    the emotional impulse it produces.
    """

    congruence: float = Field(default=0.0, description="Does this help or hinder what she wants (-1 to 1)")
    novelty: float = Field(default=0.0, description="How unexpected it was (0 to 1)")
    certainty: float = Field(default=0.5, description="How sure she is about what it means (0 to 1)")
    control: float = Field(default=0.5, description="Can she do something about it (0 to 1)")
    agency: Literal["self", "other", "circumstance"] = Field(
        default="circumstance", description="Who caused it"
    )
    warmth: float = Field(default=0.0, description="Social tone directed at her (-1 to 1)")
    beauty: float = Field(default=0.0, description="Aesthetic or intellectual elegance (0 to 1)")
    intensity: float = Field(default=0.5, description="Overall size of the event (0 to 1)")

    @field_validator("congruence")
    @classmethod
    def clamp_congruence(cls, v: float) -> float:
        return max(-1.0, min(1.0, v))

    @field_validator("novelty")
    @classmethod
    def clamp_novelty(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("certainty")
    @classmethod
    def clamp_certainty(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("control")
    @classmethod
    def clamp_control(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("warmth")
    @classmethod
    def clamp_warmth(cls, v: float) -> float:
        return max(-1.0, min(1.0, v))

    @field_validator("beauty")
    @classmethod
    def clamp_beauty(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    @field_validator("intensity")
    @classmethod
    def clamp_intensity(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class AppraisalEvent(BaseModel):
    """
    An event that triggers appraisal and emotional response.

    Based on Emotion PRD Section 5.1 and 5.2.
    """

    kind: str = Field(..., description="Type of event (e.g., 'message', 'task_result', 'prediction', 'memory_recall')")
    source: str = Field(..., description="Source of the event (e.g., 'discord', 'task_queue', 'recall_engine')")
    appraisal: Appraisal = Field(..., description="Appraisal variables for this event")
    person_id: str | None = Field(default=None, description="Person involved, if any")
    venue: str | None = Field(default=None, description="Venue/channel where event occurred")
    ref: str | None = Field(default=None, description="Reference ID (e.g., message ID, task ID)")
    user_state: dict[str, float] | None = Field(
        default=None, description="User's emotional state (for empathy matching)"
    )