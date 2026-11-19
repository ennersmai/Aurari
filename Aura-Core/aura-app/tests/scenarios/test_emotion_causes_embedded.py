"""Test that emotion_event size field is stored and top_causes is ordered by size (supervisor fix for W3-24).

This test uses the runner's embedded SurrealDB with the real schema.
"""

import pytest
from datetime import datetime, timezone

from aura.clock import FakeClock, set_clock
from aura.engines.emotion.engine import EmotionEngine
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig


class TestEmotionCausesEmbedded:
    """Test emotion_event size field and top_causes ordering with real embedded DB."""

    @pytest.fixture
    def clock(self):
        clock = FakeClock(datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
        set_clock(clock)
        yield clock
        # Reset clock after test
        from aura.clock import Clock, set_clock as _set_clock
        _set_clock(Clock())

    @pytest.fixture
    async def engine(self, clock):
        """Create EmotionEngine wired to embedded SurrealDB with real schema."""
        from tests.scenarios.runner import EmbeddedSurrealDB
        
        db = EmbeddedSurrealDB()
        await db.connect()
        
        config = EmotionPhysicsConfig()
        engine = EmotionEngine(config=config)
        engine.db = db
        engine._message_bus = None
        
        # Initialize to baseline
        engine.current_vector = config.baseline.model_copy()
        engine.previous_vector = config.baseline.model_copy()
        
        # Mock websocket broadcast
        from unittest.mock import AsyncMock, patch
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            yield engine
        
        await db.close()

    @pytest.mark.asyncio
    async def test_top_causes_ordered_by_size(self, engine, clock):
        """Three emotion_event rows with different intensities -> top_causes ordered by size desc."""
        from aura.config import settings
        from unittest.mock import AsyncMock, patch
        
        # Enable appraisal
        with patch.object(settings, "emotion_appraisal_enabled", True):
            # Event 1: Low intensity (small size) - congruence=0.2 matches pattern
            event1 = AppraisalEvent(
                kind="message",
                source="conversation",
                appraisal=Appraisal(congruence=0.2, agency="self", intensity=0.2),
            )
            with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
                await engine.appraise(event1)
            
            # Advance clock a bit
            clock.advance(10)
            
            # Event 2: Medium intensity (medium size)
            event2 = AppraisalEvent(
                kind="message",
                source="conversation",
                appraisal=Appraisal(congruence=0.5, agency="self", intensity=0.5),
            )
            with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
                await engine.appraise(event2)
            
            # Advance clock a bit
            clock.advance(10)
            
            # Event 3: High intensity (large size)
            event3 = AppraisalEvent(
                kind="message",
                source="conversation",
                appraisal=Appraisal(congruence=0.9, agency="self", intensity=1.0),
            )
            with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
                await engine.appraise(event3)
        
        # Get current state with top_causes
        state = await engine.get_current_state()
        
        # Should have 3 causes (all within the last hour)
        assert len(state.top_causes) == 3
        
        # Check they are ordered by size DESC (largest first)
        sizes = [c.size for c in state.top_causes]
        assert sizes == sorted(sizes, reverse=True), f"Sizes not in descending order: {sizes}"
        
        # Check every cause has non-zero size
        for cause in state.top_causes:
            assert cause.size > 0, f"Cause has zero size: {cause}"
        
        # The highest intensity event should be first (largest size)
        assert state.top_causes[0].size > state.top_causes[1].size
        assert state.top_causes[1].size > state.top_causes[2].size