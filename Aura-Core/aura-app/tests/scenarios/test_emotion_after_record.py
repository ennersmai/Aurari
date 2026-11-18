"""Record the emotion physics baseline after W1-15 (mirrors W0-04).

Same measurements as ``tests/scenarios/test_emotion_baseline_record.py`` but
written to ``docs/metrics/emotion_after.json``. The W1-15 "Done when" requires
this file to show the resting state within 0.01 of the configured baseline.
"""

import json
from pathlib import Path

import pytest

from aura.engines.emotion.physics import EmotionPhysics
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector


class TestEmotionAfterRecord:
    """Record the post-W1-15 emotion physics baseline."""

    def test_record_emotion_after(self):
        """Record 600 ticks from baseline and half-life measurements."""
        config = EmotionPhysicsConfig()
        physics = EmotionPhysics(config)

        baseline = config.baseline
        baseline_dict = baseline.model_dump()

        # Start from baseline.
        current = baseline

        # Run 600 ticks of 1 second each.
        for _ in range(600):
            current = physics.tick(current, dt=1.0, baseline=baseline)

        final_vector = current.model_dump()

        # Measure half-life for specific emotions: how many 1 s ticks for 0.7
        # to fall halfway back to the resting value.
        target_emotions = ["sadness", "anger", "joy", "love"]
        half_life_ticks = {}

        for emotion in target_emotions:
            resting_value = baseline_dict[emotion]
            start_value = 0.7
            target_value = resting_value + (start_value - resting_value) / 2.0

            test_state = EmotionVector(**{**baseline_dict, emotion: start_value})

            ticks = 0
            current_test = test_state
            max_ticks = 100000

            while ticks < max_ticks:
                current_test = physics.tick(current_test, dt=1.0, baseline=baseline)
                current_value = getattr(current_test, emotion)

                if current_value <= target_value:
                    break
                ticks += 1

            half_life_ticks[emotion] = ticks if ticks < max_ticks else max_ticks

        output = {
            "baseline": baseline_dict,
            "after_600_ticks": final_vector,
            "half_life_ticks_from_07": half_life_ticks,
            "half_lives_seconds": physics.half_lives,
            "config": {
                "half_life_startle": config.half_life_startle,
                "half_life_fast": config.half_life_fast,
                "half_life_core": config.half_life_core,
                "half_life_aesthetic": config.half_life_aesthetic,
                "half_life_social": config.half_life_social,
                "half_life_bond": config.half_life_bond,
                "inertia_default": config.inertia_default,
                "tick_rate_seconds": config.tick_rate_seconds,
            },
        }

        output_path = Path("docs/metrics/emotion_after.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2))

        assert output_path.exists()

        print(f"\nPost-W1-15 baseline recorded to {output_path}")
        print(f"Final vector after 600 ticks: {final_vector}")
        print(f"Half-life ticks from 0.7: {half_life_ticks}")

        # "Done when": the resting state (after_600_ticks) is within 0.01 of the
        # configured baseline, since decay from baseline stays at baseline.
        for emotion, value in final_vector.items():
            assert abs(value - baseline_dict[emotion]) < 0.01, (
                f"{emotion} drifted from baseline after 600 ticks: {value} vs "
                f"{baseline_dict[emotion]}"
            )

        assert True
