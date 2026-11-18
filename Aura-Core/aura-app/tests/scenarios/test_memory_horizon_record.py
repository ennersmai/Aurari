"""Record today's memory horizon baseline (W0-05).

This test calls MemoryManager._compute_decay_factor and DreamingEngine._compute_decay
on a row with recall_count=0, emotional_intensity=0.4, not core, not ephemeral,
at ages of 1, 5, 9, 15 and 30 days. Also calls _compute_emotional_intensity on
vectors with 3 dimensions at 0.8, 9 at 0.7 and 14 at 1.0. Writes all results to
docs/metrics/memory_before.json.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from aura.engines.memory.manager import MemoryManager, _compute_emotional_intensity
from aura.engines.dreaming.engine import DreamingEngine
from tests.conftest import write_baseline


class TestMemoryHorizonRecord:
    """Record current memory decay and emotional intensity behavior as baseline."""
    
    def test_record_memory_horizon(self):
        """Record decay factors and emotional intensity calculations."""
        # Create managers without connecting to database
        mm = MemoryManager.__new__(MemoryManager)
        de = DreamingEngine.__new__(DreamingEngine)
        
        # Test _compute_emotional_intensity
        # 3 dimensions at 0.8
        vec_3_08 = {f"dim_{i}": 0.8 for i in range(3)}
        result_3_08 = _compute_emotional_intensity(vec_3_08)
        
        # 9 dimensions at 0.7
        vec_9_07 = {f"dim_{i}": 0.7 for i in range(9)}
        result_9_07 = _compute_emotional_intensity(vec_9_07)
        
        # 14 dimensions at 1.0
        vec_14_10 = {f"dim_{i}": 1.0 for i in range(14)}
        result_14_10 = _compute_emotional_intensity(vec_14_10)
        
        # Test decay at various ages
        ages_days = [1, 5, 9, 15, 30]
        now = datetime.now(timezone.utc)
        
        mm_decay_results = {}
        de_decay_results = {}
        
        for age_days in ages_days:
            # Create a row with the specified age
            timestamp = (now - timedelta(days=age_days)).isoformat()
            row = {
                "timestamp": timestamp,
                "recall_count": 0,
                "emotional_intensity": 0.4,
                "core_memory": False,
                "ephemeral": False,
                "deprecated": False,
            }
            
            # MemoryManager decay
            mm_decay = mm._compute_decay_factor(row)
            mm_decay_results[f"{age_days}_days"] = mm_decay
            
            # DreamingEngine decay
            de_decay = de._compute_decay(row)
            de_decay_results[f"{age_days}_days"] = de_decay
        
        # Write results to JSON
        output = {
            "emotional_intensity": {
                "3_dims_at_0.8": result_3_08,
                "9_dims_at_0.7": result_9_07,
                "14_dims_at_1.0": result_14_10,
            },
            "memory_manager_decay": mm_decay_results,
            "dreaming_engine_decay": de_decay_results,
            "test_parameters": {
                "recall_count": 0,
                "emotional_intensity": 0.4,
                "core_memory": False,
                "ephemeral": False,
                "ages_days_tested": ages_days,
            }
        }
        
        output_path = Path("docs/metrics/memory_before.json")
        written = write_baseline(output_path, output)
        
        # Verify file was created only when RECORD_BASELINE=1
        if written:
            assert output_path.exists()
        else:
            # When RECORD_BASELINE is not set, the file should not be modified
            pass
        
        # Print summary
        print(f"\nMemory horizon recorded to {output_path}")
        print(f"Emotional intensity: 3@0.8={result_3_08:.4f}, 9@0.7={result_9_07:.4f}, 14@1.0={result_14_10:.4f}")
        print(f"MM decay: {mm_decay_results}")
        print(f"DE decay: {de_decay_results}")
        
        # This test passes without asserting specific values - it's a recording test
        assert True