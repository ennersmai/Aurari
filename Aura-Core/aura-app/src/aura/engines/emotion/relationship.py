"""Relationships on person entities (W4-14, Emotion PRD 6.3).

Pure maths only. A relationship is four numbers in [0, 1] (affection, trust,
familiarity, tension) held on the person's entity. The engine owns the reads,
the writes and the clock. There is no time decay.
"""

from typing import Any

FIELDS = ("affection", "trust", "familiarity", "tension")

# Negative-valence dimensions (the negative set of EmotionEngine._compute_valence).
# The table's impulses are all magnitudes, so "negative impulse" means an impulse
# on one of these dimensions.
NEGATIVE_DIMENSIONS = (
    "fear", "sadness", "anger", "disgust", "shame", "envy",
    "doubt", "confusion", "boredom", "melancholy",
)
POSITIVE_DIMENSIONS = (
    "joy", "love", "interest", "trust", "curiosity", "fascination",
    "wonder", "awe", "beauty", "serenity", "empathy", "compassion",
    "gratitude", "pride", "certainty",
)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def starting_values(is_owner: bool, settings: Any) -> dict[str, float]:
    """Values for a person whose relationship fields are NONE."""
    prefix = "emotion_relationship_owner_" if is_owner else "emotion_relationship_stranger_"
    return {
        "affection": getattr(settings, prefix + "affection"),
        "trust": getattr(settings, prefix + "trust"),
        "familiarity": getattr(settings, prefix + "familiarity"),
        "tension": settings.emotion_relationship_stranger_tension,
    }


def resolve(row: dict[str, Any] | None, is_owner: bool, settings: Any) -> dict[str, float]:
    """Stored values, with any missing (NONE) field read as its starting value."""
    start = starting_values(is_owner, settings)
    row = row or {}
    return {
        name: (start[name] if row.get(name) is None else _clamp(float(row[name])))
        for name in FIELDS
    }


def baseline_for(rel: dict[str, float], settings: Any) -> dict[str, float]:
    """Resting points of love and trust, scaled into the dimension's range."""
    return {
        "love": _clamp(rel["affection"] * settings.emotion_relationship_love_scale),
        "trust": _clamp(rel["trust"] * settings.emotion_relationship_trust_scale),
    }


def is_stranger(rel: dict[str, float], settings: Any) -> bool:
    return rel["familiarity"] < settings.emotion_stranger_familiarity


def scale_impulses(
    impulses: dict[str, float], rel: dict[str, float], warmth: float, settings: Any
) -> dict[str, float]:
    """Scale a message's impulses by the relationship.

    With positive warmth, impulses on positive dimensions are multiplied by
    ``1 + warmth_gain * (affection + familiarity) / 2``. For a stranger, each
    impulse on a negative dimension is capped at ``emotion_stranger_hostility_cap``.
    """
    out = dict(impulses)
    if warmth > 0.0:
        factor = 1.0 + settings.emotion_relationship_warmth_gain * (
            rel["affection"] + rel["familiarity"]
        ) / 2.0
        for dim in out:
            if dim in POSITIVE_DIMENSIONS:
                out[dim] = out[dim] * factor
    if is_stranger(rel, settings):
        cap = settings.emotion_stranger_hostility_cap
        for dim in out:
            if dim in NEGATIVE_DIMENSIONS:
                out[dim] = min(out[dim], cap)
    return out


def step(rel: dict[str, float], appraisal: Any, settings: Any) -> dict[str, float]:
    """One event's change to a relationship; every field clamped to [0, 1].

    - familiarity: every exchange adds ``step * (1 - familiarity)`` (diminishing returns).
    - affection: rises by ``gain * (warmth + congruence) / 2`` when warmth and
      congruence are both positive and the agency is the other person; falls by
      ``loss * -warmth`` with negative warmth.
    - tension: rises by ``rise * max(-congruence, -warmth)`` when the other
      person is the agent of a negative congruence or warmth; eases by
      ``ease * warmth`` with later positive warmth (repair).
    - trust: the appraisal's ``certainty`` and ``congruence`` with agency other
      are the proxy for expectations. Positive congruence is a confirmed
      expectation (``+gain * congruence * certainty``); negative congruence is a
      broken one (``-loss * -congruence * certainty``).
    """
    warmth = appraisal.warmth
    congruence = appraisal.congruence
    other = appraisal.agency == "other"
    out = dict(rel)

    out["familiarity"] = _clamp(
        rel["familiarity"]
        + settings.emotion_relationship_familiarity_step * (1.0 - rel["familiarity"])
    )

    aff = rel["affection"]
    if other and warmth > 0.0 and congruence > 0.0:
        aff += settings.emotion_relationship_affection_gain * (warmth + congruence) / 2.0
    if warmth < 0.0:
        aff -= settings.emotion_relationship_affection_loss * -warmth
    out["affection"] = _clamp(aff)

    tension = rel["tension"]
    if other and (congruence < 0.0 or warmth < 0.0):
        tension += settings.emotion_relationship_tension_rise * max(-congruence, -warmth)
    elif warmth > 0.0:
        tension -= settings.emotion_relationship_tension_ease * warmth
    out["tension"] = _clamp(tension)

    trust = rel["trust"]
    if other:
        if congruence > 0.0:
            trust += settings.emotion_relationship_trust_gain * congruence * appraisal.certainty
        elif congruence < 0.0:
            trust -= settings.emotion_relationship_trust_loss * -congruence * appraisal.certainty
    out["trust"] = _clamp(trust)
    return out
