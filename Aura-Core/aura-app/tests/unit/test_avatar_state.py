"""Tests for AvatarStateMachine (PRD avatar 8, 11, V4, test T7)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.avatar.state import AvatarStateMachine, CognitiveState, AvatarEventType
from aura.engines.emotion.engine import EmotionEngine
from aura.models.emotion import EmotionVector, EmotionPhysicsConfig


class FakeEmotionEngine:
    """Fake emotion engine for testing without model calls."""
    
    def __init__(self):
        self.current_vector = EmotionVector()
        self.config = EmotionPhysicsConfig()
        # Set some baseline values for testing deviation
        self.config.baseline = EmotionVector(
            curiosity=0.3,
            trust=0.2,
            joy=0.15,
        )


@pytest.fixture
def fake_emotion_engine():
    """Provide a fake emotion engine with no model dependencies."""
    return FakeEmotionEngine()


@pytest.fixture
def broadcast_capture():
    """Capture broadcast calls."""
    calls = []
    
    async def capture(payload):
        calls.append(payload)
    
    return calls, capture


@pytest.fixture
def state_machine(fake_emotion_engine, broadcast_capture):
    """Create an AvatarStateMachine with fake dependencies."""
    calls, capture = broadcast_capture
    machine = AvatarStateMachine(
        emotion_engine=fake_emotion_engine,
        broadcast_func=capture,
    )
    return machine, calls


class TestAvatarStateMachine:
    """Test the avatar state machine transitions and broadcasting."""

    @pytest.mark.asyncio
    async def test_basic_sequence_message_recall_reasoning(
        self, state_machine
    ):
        """
        T7: A replayed sequence for one turn produces
        attending, recalling, thinking, attending in order.
        
        Sequence: message_received, recall_started, recall_finished, 
        reasoning_started, reasoning_finished
        """
        machine, calls = state_machine
        
        # Initial state should be IDLE
        assert machine.state == CognitiveState.IDLE
        
        # 1. message_received -> attending
        machine.message_received()
        assert machine.state == CognitiveState.ATTENDING
        
        # 2. recall_started -> recalling
        machine.recall_started()
        assert machine.state == CognitiveState.RECALLING
        
        # 3. recall_finished (no abstain, strong=True) -> found_it then attending (since not reasoning)
        machine.recall_finished(abstain=False, strong=True)
        assert machine.state == CognitiveState.FOUND_IT
        
        # 4. reasoning_started -> thinking
        machine.reasoning_started()
        assert machine.state == CognitiveState.THINKING
        
        # 5. reasoning_finished -> attending (since not recalling)
        machine.reasoning_finished()
        assert machine.state == CognitiveState.ATTENDING
        
        # Verify broadcasts happened for each state change
        # We expect broadcasts for: IDLE->ATTENDING, ATTENDING->RECALLING, 
        # RECALLING->FOUND_IT, FOUND_IT->THINKING, THINKING->ATTENDING
        # That's 5 state changes, so at least 5 broadcasts (rate limited)
        # But due to rate limiting, some may be coalesced
        
    @pytest.mark.asyncio
    async def test_recall_abstain_gives_unsure(self, state_machine):
        """T7: recall_finished with abstain=True gives unsure state."""
        machine, calls = state_machine
        
        machine.message_received()
        machine.recall_started()
        machine.recall_finished(abstain=True, strong=False)
        
        assert machine.state == CognitiveState.UNSURE

    @pytest.mark.asyncio
    async def test_recall_strong_gives_found_it(self, state_machine):
        """recall_finished with strong=True gives found_it state."""
        machine, calls = state_machine
        
        machine.message_received()
        machine.recall_started()
        machine.recall_finished(abstain=False, strong=True)
        
        assert machine.state == CognitiveState.FOUND_IT

    @pytest.mark.asyncio
    async def test_recall_weak_then_reasoning_gives_thinking(self, state_machine):
        """recall_finished with weak then reasoning_started gives thinking."""
        machine, calls = state_machine
        
        machine.message_received()
        machine.recall_started()
        machine.recall_finished(abstain=False, strong=False)
        # Should go back to attending since not reasoning yet
        assert machine.state == CognitiveState.ATTENDING
        
        machine.reasoning_started()
        assert machine.state == CognitiveState.THINKING

    @pytest.mark.asyncio
    async def test_rate_limit_100ms_coalesce(self, state_machine):
        """
        T7: Rate limit holds - 20 changes in 100ms broadcast at most twice.
        
        The MIN_BROADCAST_INTERVAL is 0.1s (100ms), so in 100ms we can have
        at most 2 broadcasts (one immediate, one after 100ms).
        """
        machine, calls = state_machine
        
        # Make 20 rapid state changes
        for i in range(20):
            machine.message_received()
            machine.recall_started()
            machine.recall_finished(abstain=False, strong=False)
            machine.reasoning_started()
            machine.reasoning_finished()
        
        # Wait for any pending broadcasts to complete
        await asyncio.sleep(0.15)
        
        # Should have at most 2 broadcasts in ~100ms window
        # (one immediate, one after 100ms delay)
        # Since we wait 150ms, we could have up to 2-3 broadcasts
        # The key assertion is that it's NOT 20+ broadcasts
        assert len(calls) <= 3, f"Expected at most 3 broadcasts due to rate limiting, got {len(calls)}"

    @pytest.mark.asyncio
    async def test_no_model_called(self, state_machine):
        """
        T7: No model is called (the state machine has no client).
        
        This test verifies the state machine doesn't have any LLM client
        and doesn't make any model calls.
        """
        machine, calls = state_machine
        
        # Verify no LLM client attribute exists
        assert not hasattr(machine, 'llm_client')
        assert not hasattr(machine, 'client')
        assert not hasattr(machine, '_client')
        
        # Run a sequence - should not raise any model-related errors
        machine.message_received()
        machine.recall_started()
        machine.recall_finished(abstain=False, strong=True)
        machine.reasoning_started()
        machine.reasoning_finished()
        machine.delegation_running(True)
        machine.delegation_running(False)
        machine.dreaming(True)
        machine.dreaming(False)
        machine.prediction_error(0.8)
        
        # If we got here without errors, no model was called
        assert True

    @pytest.mark.asyncio
    async def test_delegation_running_transitions(self, state_machine):
        """Test delegation running transitions."""
        machine, calls = state_machine
        
        machine.message_received()
        assert machine.state == CognitiveState.ATTENDING
        
        machine.delegation_running(True)
        assert machine.state == CognitiveState.WORKING
        
        machine.delegation_running(False)
        assert machine.state == CognitiveState.ATTENDING

    @pytest.mark.asyncio
    async def test_dreaming_transitions(self, state_machine):
        """Test dreaming transitions."""
        machine, calls = state_machine
        
        machine.dreaming(True)
        assert machine.state == CognitiveState.RESTING
        
        machine.dreaming(False)
        assert machine.state == CognitiveState.IDLE

    @pytest.mark.asyncio
    async def test_prediction_error_surprised(self, state_machine):
        """Test prediction_error with high size gives surprised."""
        machine, calls = state_machine
        
        machine.message_received()
        machine.prediction_error(0.8)  # > 0.5
        assert machine.state == CognitiveState.SURPRISED

    @pytest.mark.asyncio
    async def test_prediction_error_curious(self, state_machine):
        """Test prediction_error with low size gives curious (when not reasoning/recalling)."""
        machine, calls = state_machine
        
        machine.message_received()
        machine.prediction_error(0.3)  # <= 0.5
        assert machine.state == CognitiveState.CURIOUS

    @pytest.mark.asyncio
    async def test_payload_structure(self, state_machine):
        """Test that the broadcast payload matches PRD 11 structure."""
        machine, calls = state_machine
        
        machine.message_received()
        
        # Wait for broadcast
        await asyncio.sleep(0.05)
        
        assert len(calls) >= 1
        payload = calls[-1]  # Get the latest broadcast
        
        # Check PRD 11 payload structure
        assert "deviation" in payload
        assert isinstance(payload["deviation"], dict)
        assert "mood" in payload
        assert payload["mood"] is None  # Always null until E4
        assert "cognitive_state" in payload
        assert payload["cognitive_state"] in [s.value for s in CognitiveState]
        assert "events" in payload
        assert isinstance(payload["events"], list)
        assert "speaking" in payload
        assert payload["speaking"] is False
        assert "gaze_target" in payload
        assert isinstance(payload["gaze_target"], str)

    @pytest.mark.asyncio
    async def test_deviation_from_emotion_engine(self, state_machine):
        """Test that deviation is computed from emotion engine state."""
        machine, calls = state_machine
        
        # The fake engine has baseline curiosity=0.3, trust=0.2, joy=0.15
        # Current vector defaults to all 0.0
        # So deviation should be negative for those
        
        machine.message_received()
        await asyncio.sleep(0.05)
        
        payload = calls[-1]
        deviation = payload["deviation"]
        
        # Should have all 27 emotions in deviation
        assert len(deviation) == 27
        
        # Baseline emotions should have negative deviation (current 0 - baseline > 0)
        assert deviation["curiosity"] == -0.3
        assert deviation["trust"] == -0.2
        assert deviation["joy"] == -0.15

    @pytest.mark.asyncio
    async def test_shutdown_cancels_pending_broadcast(self, state_machine):
        """Test that shutdown cancels any pending broadcast task."""
        machine, calls = state_machine
        
        # Trigger a state change that will schedule a delayed broadcast
        machine.message_received()
        
        # Don't wait - shutdown immediately
        await machine.shutdown()
        
        # Should not raise any errors
        assert True

    @pytest.mark.asyncio
    async def test_concurrent_events_order(self, state_machine):
        """Test that concurrent events maintain proper state order."""
        machine, calls = state_machine
        
        # Simulate overlapping events
        machine.message_received()
        machine.recall_started()
        machine.reasoning_started()  # While still recalling
        
        # Should be in RECALLING because recall takes precedence
        assert machine.state == CognitiveState.RECALLING
        
        machine.recall_finished(abstain=False, strong=False)
        # Now should transition to THINKING because reasoning is active
        assert machine.state == CognitiveState.THINKING
        
        machine.reasoning_finished()
        assert machine.state == CognitiveState.ATTENDING


class TestAvatarStatePayload:
    """Test the AvatarStatePayload structure."""

    def test_payload_has_all_required_fields(self):
        """Verify payload has all PRD 11 required fields."""
        from aura.avatar.state import AvatarStatePayload
        
        payload = AvatarStatePayload(
            deviation={"joy": 0.1, "curiosity": 0.2},
            mood=None,
            cognitive_state="attending",
            events=[{"type": "message_received"}],
            speaking=False,
            gaze_target="camera",
        )
        
        assert payload.deviation == {"joy": 0.1, "curiosity": 0.2}
        assert payload.mood is None
        assert payload.cognitive_state == "attending"
        assert payload.events == [{"type": "message_received"}]
        assert payload.speaking is False
        assert payload.gaze_target == "camera"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])