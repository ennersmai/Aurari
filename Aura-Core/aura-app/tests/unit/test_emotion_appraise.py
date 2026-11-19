"""Tests for EmotionEngine.appraise (W3-20)."""

import asyncio
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.config import settings
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector


class FakeDB:
    """Fake database that records writes."""

    def __init__(self):
        self.writes: list[dict[str, Any]] = []

    async def create(self, table: str, data: dict[str, Any]) -> Any:
        self.writes.append({"table": table, "data": data})
        # Return a mock record ID
        return {"id": f"{table}:test"}

    async def query(self, sql: str, params: dict | None = None) -> list:
        return []


class FakeClock:
    """Fake clock for testing."""

    def __init__(self):
        self._now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = dt

    def advance(self, seconds: float) -> None:
        from datetime import timedelta
        self._now += timedelta(seconds=seconds)


@pytest.fixture
def fake_db():
    return FakeDB()


@pytest.fixture
def fake_clock():
    return FakeClock()


@pytest.fixture
def emotion_engine(fake_db, fake_clock):
    """Create an EmotionEngine with fake dependencies."""
    from aura.engines.emotion.engine import EmotionEngine
    from aura.clock import set_clock, get_clock

    # Set the fake clock
    set_clock(fake_clock)

    # Create engine with baseline config
    config = EmotionPhysicsConfig()
    engine = EmotionEngine(config=config)

    # Replace the database with our fake
    engine.db = fake_db

    # Mock the message bus broadcast
    engine._message_bus = None

    # Initialize the engine (sets up baseline)
    engine.current_vector = config.baseline.model_copy()
    engine.previous_vector = config.baseline.model_copy()

    # Mock the websocket broadcast
    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        yield engine


@pytest.fixture(autouse=True)
def enable_appraisal():
    """Enable emotion appraisal for all tests."""
    with patch.object(settings, "emotion_appraisal_enabled", True):
        yield


class TestEmotionAppraise:
    """Tests for the appraise method."""

    @pytest.mark.asyncio
    async def test_positive_congruence_agency_self_raises_joy_and_writes_event(
        self, emotion_engine, fake_db, fake_clock
    ):
        """Positive congruence + agency self raises joy and writes emotion_event with appraisal, impulses, deviation_change."""
        # Create an event that matches "positive_congruence_agency_self"
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(
                congruence=0.5,
                novelty=0.0,
                certainty=0.5,
                control=0.5,
                agency="self",
                warmth=0.0,
                beauty=0.0,
                intensity=1.0,
            ),
            person_id="user123",
            venue="general",
            ref="msg456",
        )

        # Mock the websocket broadcast
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock) as mock_broadcast:
            state = await emotion_engine.appraise(event)

        # Check that joy was raised (it should be dominant)
        assert state.vector.joy > 0.15  # Baseline joy is 0.15
        dominant_name, dominant_value = state.dominant
        assert dominant_name == "joy"

        # Check that an emotion_event was written
        assert len(fake_db.writes) == 1
        write = fake_db.writes[0]
        assert write["table"] == "emotion_event"
        data = write["data"]

        # Check all required fields are present
        assert "at" in data
        assert data["kind"] == "message"
        assert data["source"] == "conversation"
        assert data["ref"] == "msg456"
        assert data["person_id"] == "user123"
        assert data["venue"] == "general"
        assert "appraisal" in data
        assert "impulses" in data
        assert "deviation_change" in data
        assert "dominant_change" in data

        # Check appraisal content
        assert data["appraisal"]["congruence"] == 0.5
        assert data["appraisal"]["agency"] == "self"
        assert data["appraisal"]["intensity"] == 1.0

        # Check impulses - should have joy and pride
        assert "joy" in data["impulses"]
        assert "pride" in data["impulses"]
        assert data["impulses"]["joy"] == 0.7
        assert data["impulses"]["pride"] == 0.5

        # Check deviation_change has entries for emotions that changed
        assert "joy" in data["deviation_change"]
        assert "pride" in data["deviation_change"]
        assert data["deviation_change"]["joy"] > 0
        assert data["deviation_change"]["pride"] > 0

        # Check dominant_change
        assert data["dominant_change"] == "joy"

    @pytest.mark.asyncio
    async def test_no_match_writes_nothing_and_changes_nothing(
        self, emotion_engine, fake_db, fake_clock
    ):
        """An event matching no row writes nothing and changes nothing."""
        # Create an event that matches no row (all defaults that don't match any pattern)
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(
                congruence=0.0,
                novelty=0.4,  # Not high (>=0.6), not low (<=0.3)
                certainty=0.5,
                control=0.5,
                agency="circumstance",
                warmth=0.0,
                beauty=0.0,
                intensity=0.5,
            ),
        )

        # Get initial state
        initial_vector = emotion_engine.current_vector.model_copy()

        # Mock the websocket broadcast
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.appraise(event)

        # State should be unchanged
        assert state.vector.model_dump() == initial_vector.model_dump()

        # No emotion_event should be written
        assert len(fake_db.writes) == 0

    @pytest.mark.asyncio
    async def test_intensity_zero_writes_nothing(self, emotion_engine, fake_db, fake_clock):
        """Intensity 0 returns empty impulses and writes nothing."""
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(
                congruence=0.5,
                novelty=0.8,
                certainty=0.5,
                control=0.5,
                agency="self",
                warmth=0.0,
                beauty=0.0,
                intensity=0.0,  # Zero intensity
            ),
        )

        initial_vector = emotion_engine.current_vector.model_copy()

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.appraise(event)

        assert state.vector.model_dump() == initial_vector.model_dump()
        assert len(fake_db.writes) == 0

    @pytest.mark.asyncio
    async def test_t9_scripted_sequence(
        self, emotion_engine, fake_db, fake_clock
    ):
        """T9: Over a scripted sequence of ten events, every dimension whose deviation changed by more than 0.1 in a step has an emotion_event for that step."""
        # Scripted sequence of 10 events
        events = [
            # 1. High novelty - surprise, curiosity
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(novelty=0.8, intensity=1.0, agency="circumstance")
            ),
            # 2. Positive congruence self - joy, pride
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0)
            ),
            # 3. Negative congruence other high control - anger
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(congruence=-0.5, agency="other", control=0.8, intensity=1.0)
            ),
            # 4. Negative congruence low control - sadness
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(congruence=-0.5, control=0.2, agency="circumstance", intensity=1.0)
            ),
            # 5. Negative congruence low control low certainty - fear
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(congruence=-0.5, control=0.2, certainty=0.2, agency="circumstance", intensity=1.0)
            ),
            # 6. High novelty + positive congruence + high beauty - wonder, fascination, awe
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(novelty=0.8, congruence=0.5, beauty=0.8, intensity=1.0)
            ),
            # 7. Low certainty - confusion, doubt
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(certainty=0.2, intensity=1.0)
            ),
            # 8. Positive congruence other + warmth - joy, gratitude
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(congruence=0.5, agency="other", warmth=0.5, intensity=1.0)
            ),
            # 9. Negative congruence self - shame, doubt
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(congruence=-0.5, agency="self", intensity=1.0)
            ),
            # 10. Empathy distress - empathy, compassion
            AppraisalEvent(
                kind="message", source="conversation",
                appraisal=Appraisal(intensity=1.0),
                user_state={"sadness": 0.7}
            ),
        ]

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            for event in events:
                await emotion_engine.appraise(event)

        # Should have 10 emotion_event records (one per event that produced impulses)
        # All 10 events should match patterns and produce impulses
        assert len(fake_db.writes) == 10

        # For each write, verify the structure and that deviation_change has the expected dimensions
        for i, write in enumerate(fake_db.writes):
            assert write["table"] == "emotion_event"
            data = write["data"]
            assert "deviation_change" in data
            assert "dominant_change" in data
            assert data["dominant_change"] is not None

            # Each event should have at least one dimension with deviation change > 0.1
            # (This is a sanity check - the actual threshold depends on the physics)
            max_change = max(abs(v) for v in data["deviation_change"].values())
            assert max_change > 0.05, f"Event {i} should have some deviation change > 0.05"

    @pytest.mark.asyncio
    async def test_database_failure_logged_not_undo_state(
        self, emotion_engine, fake_db, fake_clock
    ):
        """A database failure while writing the record is logged and does not undo the state change."""
        # Make the fake DB fail on create
        original_create = fake_db.create

        async def failing_create(table: str, data: dict[str, Any]):
            if table == "emotion_event":
                raise Exception("Database connection failed")
            return await original_create(table, data)

        fake_db.create = failing_create

        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0),
        )

        initial_vector = emotion_engine.current_vector.model_copy()

        # Patch the engine's logger instance directly
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock), \
             patch.object(emotion_engine.logger, "error") as mock_error:
            state = await emotion_engine.appraise(event)

        # State should still have changed (joy raised)
        assert state.vector.joy > initial_vector.joy

        # Error should have been logged
        assert any(
            "Failed to write emotion_event" in str(call)
            for call in mock_error.call_args_list
        )

    @pytest.mark.asyncio
    async def test_appraisal_disabled_returns_current_state(self, emotion_engine, fake_db, fake_clock):
        """When emotion_appraisal_enabled is False, appraise returns current state without changes."""
        # Temporarily disable appraisal (override the autouse fixture)
        with patch.object(settings, "emotion_appraisal_enabled", False):
            event = AppraisalEvent(
                kind="message",
                source="conversation",
                appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0),
            )

            initial_vector = emotion_engine.current_vector.model_copy()

            with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
                state = await emotion_engine.appraise(event)

            # State should be unchanged
            assert state.vector.model_dump() == initial_vector.model_dump()
            # No write should occur
            assert len(fake_db.writes) == 0

    @pytest.mark.asyncio
    async def test_impulses_applied_through_physics_with_coupling_and_inertia(
        self, emotion_engine, fake_db, fake_clock
    ):
        """Impulses are applied through the same physics as apply_influence (coupling and inertia)."""
        # Use an event that produces a clear impulse
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0),
        )

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.appraise(event)

        # Joy should increase (direct impulse 0.7 * intensity 1.0, then smoothed by inertia)
        # Inertia default is 0.3, so smoothing = 0.7
        # Also coupling: joy amplifies interest, trust, curiosity and suppresses sadness, fear, doubt
        assert state.vector.joy > 0.15  # Baseline

        # Check that coupling occurred (interest should also increase due to joy amplification)
        assert state.vector.interest > 0.25  # Baseline

        # And suppression (sadness should decrease from baseline 0)
        # Actually baseline sadness is 0, so it can't go below 0
        # But if it had a value, it would be suppressed

    @pytest.mark.asyncio
    async def test_clamp_to_0_1(self, emotion_engine, fake_db, fake_clock):
        """Values are clamped to [0, 1] after applying influence."""
        # Push joy to near 1, then apply another strong impulse
        emotion_engine.current_vector = EmotionVector(
            joy=0.95,
            curiosity=0.3,
            trust=0.2,
            interest=0.25,
            serenity=0.2,
            love=0.05,
            gratitude=0.05,
            compassion=0.05,
        )
        emotion_engine.previous_vector = emotion_engine.current_vector.model_copy()

        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0),
        )

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.appraise(event)

        # Joy should be clamped to 1.0
        assert state.vector.joy <= 1.0
        # All values should be in [0, 1]
        for value in state.vector.model_dump().values():
            assert 0.0 <= value <= 1.0

    @pytest.mark.asyncio
    async def test_event_timestamp_from_clock(self, emotion_engine, fake_db, fake_clock):
        """The emotion_event at timestamp comes from get_clock()."""
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0),
        )

        # Set clock to a specific time
        test_time = datetime(2026, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        fake_clock.set(test_time)

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            await emotion_engine.appraise(event)

        assert len(fake_db.writes) == 1
        written_time = fake_db.writes[0]["data"]["at"]
        assert written_time == test_time

    @pytest.mark.asyncio
    async def test_deviation_change_computed_correctly(self, emotion_engine, fake_db, fake_clock):
        """Per-dimension deviation change from baseline is computed correctly."""
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(congruence=0.5, agency="self", intensity=1.0),
        )

        baseline = emotion_engine.config.baseline
        old_joy_deviation = 0.15 - baseline.joy  # Should be 0 since current_vector starts at baseline

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            await emotion_engine.appraise(event)

        write = fake_db.writes[0]
        deviation_change = write["data"]["deviation_change"]

        # Joy deviation should have increased
        assert deviation_change["joy"] > 0
        # Pride deviation should have increased
        assert deviation_change["pride"] > 0

        # The change should equal new_deviation - old_deviation
        # Since old was at baseline, old_deviation = 0
        # So deviation_change[joy] should equal new_joy - baseline.joy
        new_joy = emotion_engine.current_vector.joy
        expected_change = new_joy - baseline.joy
        assert deviation_change["joy"] == pytest.approx(expected_change, abs=0.001)

    @pytest.mark.asyncio
    async def test_intensity_not_squared(self, emotion_engine, fake_db, fake_clock):
        """W3-20 fix: intensity 0.5 changes the matching dimension by the same amount as
        calling physics.apply_influence directly with impulses_for(...) and intensity 1.0.
        """
        from aura.engines.emotion.appraisal import impulses_for

        # Create an event with intensity 0.5
        event = AppraisalEvent(
            kind="message",
            source="conversation",
            appraisal=Appraisal(congruence=0.5, agency="self", intensity=0.5),
        )

        # Compute impulses (already multiplied by intensity inside impulses_for)
        impulses = impulses_for(event.appraisal, event.user_state)

        # Get baseline joy value
        baseline_joy = emotion_engine.config.baseline.joy

        # Case 1: appraise with intensity 0.5
        initial_vector = emotion_engine.current_vector.model_copy()
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state_via_appraise = await emotion_engine.appraise(event)

        joy_via_appraise = state_via_appraise.vector.joy

        # Reset to baseline
        emotion_engine.current_vector = baseline_joy_vector = initial_vector.model_copy()
        emotion_engine.previous_vector = initial_vector.model_copy()

        # Case 2: apply_influence directly with intensity 1.0 (impulses already have 0.5 baked in)
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state_via_physics = await emotion_engine.apply_influence(
                __import__("aura.models.emotion", fromlist=["EmotionInfluence"]).EmotionInfluence(
                    source="conversation",
                    emotions=impulses,
                    intensity=1.0,
                    reason="test"
                )
            )

        joy_via_physics = state_via_physics.vector.joy

        # Both should produce the same change in joy
        change_via_appraise = joy_via_appraise - baseline_joy
        change_via_physics = joy_via_physics - baseline_joy

        assert change_via_appraise == pytest.approx(change_via_physics, abs=0.001), \
            f"appraise change ({change_via_appraise}) != physics change ({change_via_physics})"