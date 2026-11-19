"""System event appraisals (W3-23).

Functions that return an AppraisalEvent with computed values for system events.
Each function is documented in one line with its appraisal variables.
"""

from aura.models.appraisal import Appraisal, AppraisalEvent


def memory_write_failed() -> AppraisalEvent:
    """memory_write_failed: congruence -0.6, control 0.3, certainty 0.8, agency circumstance, intensity 0.5"""
    return AppraisalEvent(
        kind="system_event",
        source="memory",
        appraisal=Appraisal(
            congruence=-0.6,
            novelty=0.0,
            certainty=0.8,
            control=0.3,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=0.5,
        ),
        person_id=None,
        venue=None,
    )


def self_critique_received() -> AppraisalEvent:
    """self_critique_received: congruence -0.2, agency self, certainty 0.7, control 0.8, intensity 0.3"""
    return AppraisalEvent(
        kind="system_event",
        source="orchestrator",
        appraisal=Appraisal(
            congruence=-0.2,
            novelty=0.0,
            certainty=0.7,
            control=0.8,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=0.3,
        ),
        person_id=None,
        venue=None,
    )


def tool_succeeded(tool: str) -> AppraisalEvent:
    """tool_succeeded: congruence 0.5, agency self, certainty 0.8, control 0.8, intensity 0.3"""
    return AppraisalEvent(
        kind="system_event",
        source="tool",
        appraisal=Appraisal(
            congruence=0.5,
            novelty=0.0,
            certainty=0.8,
            control=0.8,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=0.3,
        ),
        person_id=tool,
        venue=None,
    )


def tool_failed(tool: str, retryable: bool) -> AppraisalEvent:
    """tool_failed: congruence -0.5, agency circumstance, certainty 0.6, control 0.7 if retryable else 0.2, intensity 0.4"""
    control = 0.7 if retryable else 0.2
    return AppraisalEvent(
        kind="system_event",
        source="tool",
        appraisal=Appraisal(
            congruence=-0.5,
            novelty=0.0,
            certainty=0.6,
            control=control,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=0.4,
        ),
        person_id=tool,
        venue=None,
    )