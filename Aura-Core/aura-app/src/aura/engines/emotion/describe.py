"""Emotion description helpers (W3-25)."""

from datetime import datetime

from aura.models.emotion import EmotionCause


def cause_phrase(cause: EmotionCause, now: datetime) -> str:
    """
    Build a short plain phrase for an emotion cause.

    Examples:
        "since a tool let you down 12 minutes ago"
        "since a message from discord_42 3 minutes ago"
        "since a memory resurfaced 2 hours ago"

    Args:
        cause: The emotion cause to describe
        now: Current time for age calculation

    Returns:
        A human-readable phrase describing the cause
    """
    # Calculate age
    total_seconds = (now - cause.at).total_seconds()

    if total_seconds < 60:
        age_str = "a moment ago"
    elif total_seconds < 3600:
        minutes = int(total_seconds / 60)
        age_str = f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif total_seconds < 86400:
        hours = int(total_seconds / 3600)
        age_str = f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = int(total_seconds / 86400)
        age_str = f"{days} day{'s' if days != 1 else ''} ago"

    kind = cause.kind
    if kind == "message":
        if cause.person_id:
            return f"since a message from {cause.person_id} {age_str}"
        return f"since something said in conversation {age_str}"

    templates = {
        "tool_failed": "a tool let you down",
        "tool_succeeded": "a tool came through for you",
        "task_result": "a task came back",
        "prediction": "a prediction played out",
        "memory_recall": "a memory resurfaced",
        "memory_write_failed": "a memory slipped away before it could be kept",
        "self_critique": "you looked back critically at your own words",
    }
    text = templates.get(kind, kind.replace("_", " "))
    return f"since {text} {age_str}"
