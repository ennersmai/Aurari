"""Record today's emotion physics baseline (W0-04).

This test builds EmotionPhysics with default config, runs 600 ticks of 1s from
the configured baseline, and writes the resulting vector to
docs/metrics/emotion_before.json. Also records, for sadness, anger, joy and
love, how many 1s ticks a value of 0.7 takes to fall halfway back to the
resting value (cap the loop at 100,000).
"""

import json
from pathlib import Path

import pytest

from aura.engines.emotion.physics import EmotionPhysics
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector
from tests.conftest import write_baseline


class TestEmotionBaselineRecord:
    """Record current emotion physics behavior as baseline."""
    
    def test_record_emotion_baseline(self):
        """Record 600 ticks from baseline and half-life measurements."""
        # Create physics with default config
        config = EmotionPhysicsConfig()
        physics = EmotionPhysics(config)
        
        # Get the baseline (resting state)
        baseline = config.baseline
        baseline_dict = baseline.model_dump()
        
        # Start from baseline
        current = baseline
        
        # Run 600 ticks of 1 second each
        for _ in range(600):
            current = physics.tick(current, dt=1.0, baseline=baseline)
        
        final_vector = current.model_dump()
        
        # Measure half-life for specific emotions: how many ticks for 0.7 to fall
        # halfway back to resting value
        target_emotions = ["sadness", "anger", "joy", "love"]
        half_life_ticks = {}
        
        for emotion in target_emotions:
            resting_value = baseline_dict[emotion]
            start_value = 0.7
            target_value = resting_value + (start_value - resting_value) / 2.0
            
            # Create a state with this emotion at 0.7, others at baseline
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
        
        # Write results to JSON
        output = {
            "baseline": baseline_dict,
            "after_600_ticks": final_vector,
            "half_life_ticks_from_07": half_life_ticks,
            "config": {
                "decay_rate_primary": config.decay_rate_primary,
                "decay_rate_aesthetic": config.decay_rate_aesthetic,
                "decay_rate_social": config.decay_rate_social,
                "decay_rate_cognitive": config.decay_rate_cognitive,
                "inertia_default": config.inertia_default,
                "tick_rate_seconds": config.tick_rate_seconds,
            }
        }
        
        output_path = Path("docs/metrics/emotion_before.json")
        written = write_baseline(output_path, output)
        
        # Verify file was created only when RECORD_BASELINE=1
        if written:
            assert output_path.exists()
        else:
            # When RECORD_BASELINE is not set, the file should not be modified
            # (we don't assert it doesn't exist since it may exist from a previous run)
            pass
        
        # Print summary for visibility
        print(f"\nBaseline recorded to {output_path}")
        print(f"Final vector after 600 ticks: {final_vector}")
        print(f"Half-life ticks from 0.7: {half_life_ticks}")
        
        # This test passes without asserting specific values - it's a recording test
        assert True