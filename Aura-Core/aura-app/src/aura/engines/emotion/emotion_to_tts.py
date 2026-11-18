"""
Emotion → Qwen3-TTS Instruction Generator (NLG).

Converts the 27-dimensional emotion vector into a natural-language
instruction string compatible with Qwen3-TTS's `instruct` parameter.
Also computes TTS temperature/top_p based on emotional energy (arousal).
"""

from __future__ import annotations

import math
from typing import Any


# ---- Emotion-to-instruction phrase templates ----

# Primary emotion → instruction fragments
EMOTION_INSTRUCT_TEMPLATES: dict[str, str] = {
    "joy": "with a cheerful and bright tone",
    "love": "with a warm and affectionate voice",
    "interest": "with an engaged and inquisitive tone",
    "trust": "with a calm and reassuring voice",
    "fear": "with a trembling and hesitant tone",
    "sadness": "with a soft and melancholic voice",
    "anger": "with a firm and intense tone",
    "surprise": "with a tone of astonishment",
    "disgust": "with a curt and dismissive tone",
    "awe": "with a tone of wonder and reverence",
    "beauty": "with an appreciative and gentle voice",
    "wonder": "with a tone of curiosity and amazement",
    "serenity": "with a peaceful and soothing voice",
    "melancholy": "with a wistful and reflective tone",
    "nostalgia": "with a fond and reminiscent voice",
    "empathy": "with a compassionate and understanding tone",
    "gratitude": "with a thankful and sincere voice",
    "pride": "with a confident and proud tone",
    "shame": "with a quiet and self-conscious voice",
    "envy": "with a slightly bitter tone",
    "compassion": "with a gentle and caring voice",
    "curiosity": "with an eager and questioning tone",
    "confusion": "with a puzzled and uncertain voice",
    "certainty": "with a confident and assured tone",
    "doubt": "with a hesitant and questioning voice",
    "fascination": "with a captivated and intrigued tone",
    "boredom": "with a flat and disinterested voice",
}

# Energy level → pacing modifiers
ENERGY_PACING: dict[str, str] = {
    "high": "Speak quickly and energetically.",
    "medium": "Speak at a natural, conversational pace.",
    "low": "Speak slowly and deliberately.",
}

# Valence → emotional coloring
VALENCE_COLORING: dict[str, str] = {
    "positive": "The overall mood is positive and warm.",
    "neutral": "The overall mood is balanced and neutral.",
    "negative": "The overall mood is somber and heavy.",
}


def emotion_to_tts_instruction(
    vector: dict[str, float],
    top_n: int = 3,
) -> str:
    """
    Generate a Qwen3-TTS instruction string from a 27D emotion vector.

    Args:
        vector: 27D emotion values {name: intensity 0..1}
        top_n: Number of dominant emotions to include

    Returns:
        Natural-language instruction string for TTS `instruct` parameter.
    """
    # Get top N dominant emotions
    sorted_emotions = sorted(vector.items(), key=lambda x: x[1], reverse=True)
    dominant = [(name, val) for name, val in sorted_emotions[:top_n] if val > 0.15]

    if not dominant:
        return "Speak in a neutral, natural voice."

    # Build instruction fragments
    fragments: list[str] = []
    for name, intensity in dominant:
        template = EMOTION_INSTRUCT_TEMPLATES.get(name)
        if template:
            if intensity > 0.7:
                fragments.append(f"{template}, very pronounced")
            elif intensity > 0.4:
                fragments.append(template)
            else:
                fragments.append(f"{template}, subtly")

    # Compute energy (arousal) for pacing
    high_arousal_emotions = [
        vector.get("joy", 0), vector.get("anger", 0),
        vector.get("surprise", 0), vector.get("fear", 0),
        vector.get("awe", 0), vector.get("wonder", 0),
        vector.get("fascination", 0), vector.get("curiosity", 0),
    ]
    energy = sum(high_arousal_emotions) / len(high_arousal_emotions)

    if energy > 0.5:
        pacing = ENERGY_PACING["high"]
    elif energy > 0.25:
        pacing = ENERGY_PACING["medium"]
    else:
        pacing = ENERGY_PACING["low"]

    # Compute valence
    pos = sum(vector.get(e, 0) for e in [
        "joy", "love", "trust", "interest", "serenity", "gratitude",
        "beauty", "compassion",
    ])
    neg = sum(vector.get(e, 0) for e in [
        "fear", "sadness", "anger", "disgust", "shame", "envy",
        "boredom", "melancholy",
    ])
    valence = (pos - neg) / 8

    if valence > 0.15:
        coloring = VALENCE_COLORING["positive"]
    elif valence < -0.15:
        coloring = VALENCE_COLORING["negative"]
    else:
        coloring = VALENCE_COLORING["neutral"]

    # Assemble final instruction
    emotion_part = " ".join(fragments)
    instruction = f"{pacing} Speak {emotion_part}. {coloring}"

    return instruction


def emotion_to_tts_params(
    vector: dict[str, float],
) -> dict[str, Any]:
    """
    Compute TTS generation parameters from emotion vector.

    Returns dict with:
      - instruction: NLG instruction string
      - temperature: 0.6–1.1 scaled by energy
      - top_p: 0.85–0.98 scaled by energy
      - speaker: best-matching speaker (default "serena")
    """
    instruction = emotion_to_tts_instruction(vector)

    # Energy → temperature (higher energy = more expressive = higher temp)
    high_arousal = [
        vector.get("joy", 0), vector.get("anger", 0),
        vector.get("surprise", 0), vector.get("fear", 0),
        vector.get("awe", 0), vector.get("wonder", 0),
        vector.get("fascination", 0), vector.get("curiosity", 0),
    ]
    energy = sum(high_arousal) / len(high_arousal)

    # Map energy (0..1) to temperature (0.6..1.1) using sigmoid
    temperature = 0.6 + energy * 0.5
    # Map energy to top_p (0.85..0.98)
    top_p = 0.85 + energy * 0.13

    # Speaker selection based on dominant emotion
    speaker = "serena"  # default
    sorted_emotions = sorted(vector.items(), key=lambda x: x[1], reverse=True)
    dominant_name = sorted_emotions[0][0] if sorted_emotions else "neutral"

    # Map dominant emotion to speaker personality
    speaker_map = {
        "joy": "serena",
        "sadness": "vivian",
        "anger": "ryan",
        "surprise": "aiden",
        "love": "serena",
        "serenity": "ono_anna",
        "curiosity": "sohee",
        "certainty": "eric",
        "melancholy": "vivian",
    }
    speaker = speaker_map.get(dominant_name, "serena")

    return {
        "instruction": instruction,
        "temperature": round(temperature, 2),
        "top_p": round(top_p, 3),
        "speaker": speaker,
        "energy": round(energy, 3),
    }
