"""Tests for EmotionState interface: deviation, baseline, top_causes, explain (W3-24)."""

import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.config import settings
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector


class FakeDB:
    """Fake database that records writes and supports queries."""

    def __init__(self):
        self.writes: list[dict[str, Any]] = []
        self.emotion_events: list[dict[str, Any]] = []

    async def create(self, table: str, data: dict[str, Any]) -> Any:
        self.writes.append({"table": table, "data": data})
        if table == "emotion_event":
            self.emotion_events.append(data)
        return {"id": f"{table}:test"}

    async def query(self, sql: str, params: dict | None = None) -> list:
        # Handle the specific queries used by the engine
        if "emotion_event" in sql and "WHERE at >= $since" in sql:
            since = params.get("since") if params else None
            if since:
                filtered = [e for e in self.emotion_events if e.get("at", datetime.min) >= since]
                # Sort by size DESC, at DESC for _get_top_causes
                if "ORDER BY size DESC" in sql:
                    filtered.sort(key=lambda x: (x.get("size", 0), x.get("at", datetime.min)), reverse=True)
                # Sort by at DESC for explain
                elif "ORDER BY at DESC" in sql:
                    filtered.sort(key=lambda x: x.get("at", datetime.min), reverse=True)
                return filtered[:3] if "LIMIT 3" in sql else filtered
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


class TestEmotionStateInterface:
    """Tests for the new EmotionState interface fields."""

    @pytest.mark.asyncio
    async def test_deviation_equals_vector_minus_baseline(self, emotion_engine, fake_db, fake_clock):
        """deviation equals vector minus baseline."""
        # Get initial state at baseline
        state = await emotion_engine.get_current_state()

        # At baseline, deviation should be all zeros
        assert state.baseline is not None
        assert state.deviation is not None
        for emotion, dev in state.deviation.items():
            assert dev == pytest.approx(0.0, abs=0.001), f"Deviation for {emotion} should be 0 at baseline"

        # Apply an influence to change the state
        from aura.models.emotion import EmotionInfluence
        influence = EmotionInfluence(
            source="conversation",
            emotions={"joy": 0.5},
            intensity=1.0,
            reason="test"
        )

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.apply_influence(influence)

        # Verify deviation = vector - baseline
        assert state.baseline is not None
        assert state.deviation is not None
        for emotion in state.vector.model_dump():
            vector_val = state.vector.model_dump()[emotion]
            baseline_val = state.baseline.get(emotion, 0.0)
            expected_dev = vector_val - baseline_val
            assert state.deviation[emotion] == pytest.approx(expected_dev, abs=0.001), \
                f"Deviation for {emotion} should equal vector - baseline"

    @pytest.mark.asyncio
    async def test_top_causes_orders_and_caps_at_three(self, emotion_engine, fake_db, fake_clock):
        """top_causes orders by size DESC and caps at three, newest first among equals."""
        # Create some emotion events with different sizes
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fake_clock.set(base_time)

        # Add events directly to fake DB (simulating what appraise would write)
        events = [
            {"at": base_time - timedelta(minutes=30), "kind": "message", "source": "conversation",
             "size": 0.1, "dominant_change": "joy", "ref": "1", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=20), "kind": "message", "source": "conversation",
             "size": 0.3, "dominant_change": "anger", "ref": "2", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=10), "kind": "message", "source": "conversation",
             "size": 0.2, "dominant_change": "sadness", "ref": "3", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=5), "kind": "message", "source": "conversation",
             "size": 0.4, "dominant_change": "fear", "ref": "4", "person_id": "p1", "venue": "general"},
        ]
        fake_db.emotion_events.extend(events)

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_current_state()

        # Should have exactly 3 top causes (capped at 3)
        assert len(state.top_causes) == 3

        # Should be ordered by size DESC: 0.4, 0.3, 0.2
        assert state.top_causes[0].size == 0.4
        assert state.top_causes[0].dominant_change == "fear"
        assert state.top_causes[1].size == 0.3
        assert state.top_causes[1].dominant_change == "anger"
        assert state.top_causes[2].size == 0.2
        assert state.top_causes[2].dominant_change == "sadness"

        # The event with size 0.1 should be excluded

    @pytest.mark.asyncio
    async def test_top_causes_newest_first_among_equals(self, emotion_engine, fake_db, fake_clock):
        """Among events with equal size, newest comes first."""
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fake_clock.set(base_time)

        # Add events with same size but different times
        events = [
            {"at": base_time - timedelta(minutes=30), "kind": "message", "source": "conversation",
             "size": 0.2, "dominant_change": "joy", "ref": "1", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=20), "kind": "message", "source": "conversation",
             "size": 0.2, "dominant_change": "anger", "ref": "2", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=10), "kind": "message", "source": "conversation",
             "size": 0.2, "dominant_change": "sadness", "ref": "3", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=5), "kind": "message", "source": "conversation",
             "size": 0.2, "dominant_change": "fear", "ref": "4", "person_id": "p1", "venue": "general"},
        ]
        fake_db.emotion_events.extend(events)

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_current_state()

        # Should have exactly 3 (capped)
        assert len(state.top_causes) == 3
        # Newest first among equals: fear (5 min ago), sadness (10 min ago), anger (20 min ago)
        assert state.top_causes[0].dominant_change == "fear"
        assert state.top_causes[1].dominant_change == "sadness"
        assert state.top_causes[2].dominant_change == "anger"

    @pytest.mark.asyncio
    async def test_top_causes_empty_when_no_events(self, emotion_engine, fake_db, fake_clock):
        """top_causes is empty when there are no events."""
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_current_state()

        assert state.top_causes == []

    @pytest.mark.asyncio
    async def test_top_causes_empty_when_query_fails(self, emotion_engine, fake_db, fake_clock):
        """top_causes is empty when the query fails."""
        # Make the query fail by breaking the fake DB
        async def failing_query(sql: str, params: dict | None = None) -> list:
            raise Exception("Database error")

        fake_db.query = failing_query

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_current_state()

        # Should return empty list on failure
        assert state.top_causes == []

    @pytest.mark.asyncio
    async def test_explain_filters_by_time_with_fake_clock(self, emotion_engine, fake_db, fake_clock):
        """explain filters by time with the fake clock."""
        base_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        fake_clock.set(base_time)

        # Add events at different times
        events = [
            {"at": base_time - timedelta(hours=2), "kind": "message", "source": "conversation",
             "size": 0.1, "dominant_change": "joy", "ref": "1", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=30), "kind": "message", "source": "conversation",
             "size": 0.2, "dominant_change": "anger", "ref": "2", "person_id": "p1", "venue": "general"},
            {"at": base_time - timedelta(minutes=10), "kind": "message", "source": "conversation",
             "size": 0.3, "dominant_change": "sadness", "ref": "3", "person_id": "p1", "venue": "general"},
        ]
        fake_db.emotion_events.extend(events)

        # Default since (last hour) - should get 2 events
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            causes = await emotion_engine.explain()

        assert len(causes) == 2
        # Newest first
        assert causes[0].dominant_change == "sadness"
        assert causes[1].dominant_change == "anger"

        # Explicit since - 2 hours ago
        since_2h = base_time - timedelta(hours=2)
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            causes = await emotion_engine.explain(since=since_2h)

        assert len(causes) == 3
        assert causes[0].dominant_change == "sadness"
        assert causes[1].dominant_change == "anger"
        assert causes[2].dominant_change == "joy"

        # Since 1 hour ago - should get 2 events
        since_1h = base_time - timedelta(hours=1)
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            causes = await emotion_engine.explain(since=since_1h)

        assert len(causes) == 2
        assert causes[0].dominant_change == "sadness"
        assert causes[1].dominant_change == "anger"

    @pytest.mark.asyncio
    async def test_explain_empty_when_no_events(self, emotion_engine, fake_db, fake_clock):
        """explain returns empty list when there are no events."""
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            causes = await emotion_engine.explain()

        assert causes == []

    @pytest.mark.asyncio
    async def test_explain_empty_when_query_fails(self, emotion_engine, fake_db, fake_clock):
        """explain returns empty list when the query fails."""
        async def failing_query(sql: str, params: dict | None = None) -> list:
            raise Exception("Database error")

        fake_db.query = failing_query

        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            causes = await emotion_engine.explain()

        assert causes == []

    @pytest.mark.asyncio
    async def test_get_state_returns_current_state(self, emotion_engine, fake_db, fake_clock):
        """get_state returns get_current_state (per-person state is E5)."""
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_state(person_id="user123")

        # Should return the same as get_current_state
        current = await emotion_engine.get_current_state()
        assert state.vector.model_dump() == current.vector.model_dump()
        assert state.dominant == current.dominant

    @pytest.mark.asyncio
    async def test_broadcast_payload_keeps_old_keys_and_has_new_ones(self, emotion_engine, fake_db, fake_clock):
        """The broadcast payload keeps its old keys and has the new ones."""
        # Capture the broadcast payload
        captured_payload = {}

        async def mock_broadcast(data):
            captured_payload.update(data.get("data", {}))

        # Trigger a broadcast by applying an influence
        from aura.models.emotion import EmotionInfluence
        influence = EmotionInfluence(
            source="conversation",
            emotions={"joy": 0.3},
            intensity=1.0,
            reason="test broadcast"
        )

        with patch("aura.api.websocket.broadcast_emotion_update", side_effect=mock_broadcast):
            await emotion_engine.apply_influence(influence)

        # Old keys that must be present
        old_keys = [
            "joy", "love", "trust", "interest", "fear", "sadness", "anger", "surprise", "disgust",
            "awe", "beauty", "wonder", "serenity", "melancholy", "nostalgia",
            "empathy", "gratitude", "pride", "shame", "envy", "compassion",
            "curiosity", "confusion", "certainty", "doubt", "fascination", "boredom",
            "current_state", "dominant", "timestamp", "volatility", "valence", "arousal", "entropy"
        ]

        for key in old_keys:
            assert key in captured_payload, f"Old key '{key}' missing from broadcast payload"

        # New keys from W3-24
        new_keys = ["deviation", "baseline", "mood", "top_causes"]
        for key in new_keys:
            assert key in captured_payload, f"New key '{key}' missing from broadcast payload"

        # Verify new keys have correct types
        assert isinstance(captured_payload["deviation"], dict)
        assert isinstance(captured_payload["baseline"], dict)
        assert captured_payload["mood"] is None  # Always None until E4
        assert isinstance(captured_payload["top_causes"], list)

    @pytest.mark.asyncio
    async def test_mood_is_none_until_e4(self, emotion_engine, fake_db, fake_clock):
        """mood is always None until E4."""
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_current_state()

        assert state.mood is None

    @pytest.mark.asyncio
    async def test_baseline_contains_expected_emotions(self, emotion_engine, fake_db, fake_clock):
        """baseline contains all 27 emotions with expected values."""
        with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
            state = await emotion_engine.get_current_state()

        assert state.baseline is not None
        baseline = state.baseline

        # Check all 27 emotions are present
        expected_emotions = [
            "love", "joy", "interest", "trust", "fear", "sadness", "anger", "surprise", "disgust",
            "awe", "beauty", "wonder", "serenity", "melancholy", "nostalgia",
            "empathy", "gratitude", "pride", "shame", "envy", "compassion",
            "curiosity", "confusion", "certainty", "doubt", "fascination", "boredom"
        ]
        for emotion in expected_emotions:
            assert emotion in baseline, f"Baseline missing emotion: {emotion}"

        # Check specific baseline values from config
        assert baseline["curiosity"] == 0.3
        assert baseline["trust"] == 0.2
        assert baseline["joy"] == 0.15
        assert baseline["interest"] == 0.25
        assert baseline["serenity"] == 0.2
        assert baseline["love"] == 0.05
        assert baseline["gratitude"] == 0.05
        assert baseline["compassion"] == 0.05