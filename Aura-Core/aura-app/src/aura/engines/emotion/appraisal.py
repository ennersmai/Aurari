"""Appraisal engine (Emotion PRD Section 5.3)."""

import json
from pathlib import Path
from typing import Any

from aura.models.emotion import EmotionVector
from aura.models.appraisal import Appraisal


class Pattern:
    """A single appraisal table pattern."""

    def __init__(self, data: dict[str, Any]):
        self.name = data["name"]
        self.when = data["when"]
        self.impulse = data.get("impulse", {})
        self.note = data.get("note")

    def matches(self, appraisal: Appraisal, user_state: dict[str, float] | None = None) -> bool:
        """Check if this pattern matches the given appraisal and user_state."""
        for key, condition in self.when.items():
            if key == "user_state":
                if not user_state:
                    return False
                for emotion, range_spec in condition.items():
                    if emotion not in user_state:
                        return False
                    value = user_state[emotion]
                    if isinstance(range_spec, list):
                        min_val, max_val = range_spec
                        if not (min_val <= value <= max_val):
                            return False
                    else:
                        if value != range_spec:
                            return False
            elif key == "agency":
                if appraisal.agency != condition:
                    return False
            else:
                # Check numeric range
                value = getattr(appraisal, key)
                if isinstance(condition, list):
                    min_val, max_val = condition
                    if not (min_val <= value <= max_val):
                        return False
                else:
                    if value != condition:
                        return False
        return True


def load_table(path: str | Path | None = None) -> list[Pattern]:
    """
    Load the appraisal table from a JSON file.

    Args:
        path: Path to the JSON file. If None, uses the default location.

    Returns:
        List of Pattern objects.

    Raises:
        ValueError: If an impulse dimension name is not a valid EmotionVector field.
        FileNotFoundError: If the file doesn't exist.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    if path is None:
        path = Path(__file__).parent / "appraisal_table.json"

    with open(path) as f:
        data = json.load(f)

    # Validate all impulse dimension names against EmotionVector.model_fields
    valid_fields = set(EmotionVector.model_fields.keys())
    patterns = []
    for row in data:
        pattern = Pattern(row)
        for dim in pattern.impulse.keys():
            if dim not in valid_fields:
                raise ValueError(
                    f"Unknown emotion dimension '{dim}' in pattern '{pattern.name}'. "
                    f"Valid dimensions: {sorted(valid_fields)}"
                )
        patterns.append(pattern)

    return patterns


def impulses_for(
    appraisal: Appraisal,
    user_state: dict[str, float] | None = None,
    table: list[Pattern] | None = None,
) -> dict[str, float]:
    """
    Calculate the emotional impulses for an appraisal.

    Sums the impulses of every matching row, then multiplies by appraisal.intensity.
    Values are capped at 1.0.

    Args:
        appraisal: The appraisal variables for the event.
        user_state: Optional user emotional state (for empathy matching).
        table: Optional pre-loaded table. If None, loads the default table.

    Returns:
        Dictionary mapping emotion dimension to impulse value [0, 1].
    """
    if table is None:
        table = load_table()

    total_impulse: dict[str, float] = {}

    for pattern in table:
        if pattern.matches(appraisal, user_state):
            for dim, weight in pattern.impulse.items():
                total_impulse[dim] = total_impulse.get(dim, 0.0) + weight

    # Scale by intensity and cap at 1.0
    intensity = appraisal.intensity
    if intensity == 0.0:
        return {}

    result = {}
    for dim, value in total_impulse.items():
        scaled = value * intensity
        result[dim] = min(1.0, scaled)

    return result