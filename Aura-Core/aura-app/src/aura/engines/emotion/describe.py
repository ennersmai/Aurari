"""Emotion description helpers (W3-25)."""

from datetime import datetime

from aura.models.emotion import EmotionCause


def cause_phrase(cause: EmotionCause, now: datetime) -> str:
    """
    Build a short plain phrase for an emotion cause.

    Examples:
        "since a tool failed 12 minutes ago"
        "since a message from discord_42 3 minutes ago"
        "since a memory recall 2 hours ago"

    Args:
        cause: The emotion cause to describe
        now: Current time for age calculation

    Returns:
        A human-readable phrase describing the cause
    """
    # Calculate age
    delta = now - cause.at
    total_seconds = delta.total_seconds()

    if total_seconds < 60:
        age_str = f"{int(total_seconds)} seconds ago"
    elif total_seconds < 3600:
        minutes = int(total_seconds / 60)
        age_str = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    else:
        hours = int(total_seconds / 3600)
        age_str = f"{hours} hour{'s' if hours != 1 else ''} ago"

    # Build the phrase based on kind and source
    kind = cause.kind
    source = cause.source
    person_id = cause.person_id

    # Map kind to a human-readable action
    kind_action = {
        "message": "a message",
        "task_result": "a task result",
        "prediction": "a prediction",
        "memory_recall": "a memory recall",
        "memory_write_failed": "a memory write failure",
        "self_critique": "self critique",
        "tool_succeeded": "a tool success",
        "tool_failed": "a tool failure",
    }.get(kind, f"a {kind.replace('_', ' ')}")

    # Build the source description
    if source == "conversation":
        if person_id:
            source_str = f"from {person_id}"
        else:
            source_str = "from conversation"
    elif source == "memory":
        source_str = "from memory"
    elif source == "tool":
        source_str = "from a tool"
    elif source == "orchestrator":
        source_str = "from internal critique"
    elif source == "task_queue":
        source_str = "from a task"
    elif source == "recall_engine":
        source_str = "from recall"
    else:
        source_str = f"from {source}"

    return f"since {kind_action} {source_str} {age_str}"