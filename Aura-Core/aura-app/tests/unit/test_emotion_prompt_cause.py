"""Tests for emotion prompt cause phrase and block (W3-25)."""

from datetime import datetime, timezone, timedelta

import pytest

from aura.engines.emotion.describe import cause_phrase
from aura.models.emotion import EmotionCause, EmotionState, EmotionVector
from aura.llm.layers import LLMLayers, SynthesisContext


class TestCausePhrase:
    """Tests for the cause_phrase function."""

    def test_message_from_person(self):
        """Message from a specific person."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id="discord_42",
            dominant_change="joy",
            size=0.3,
        )
        now = datetime(2026, 1, 1, 12, 3, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a message from discord_42 3 minutes ago"

    def test_message_without_person(self):
        """Message without a person_id."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id=None,
            dominant_change="joy",
            size=0.3,
        )
        now = datetime(2026, 1, 1, 12, 5, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a message from conversation 5 minutes ago"

    def test_tool_failed(self):
        """Tool failure."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="tool_failed",
            source="tool",
            person_id=None,
            dominant_change="anger",
            size=0.5,
        )
        now = datetime(2026, 1, 1, 12, 12, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a tool failure from a tool 12 minutes ago"

    def test_tool_succeeded(self):
        """Tool success."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="tool_succeeded",
            source="tool",
            person_id=None,
            dominant_change="joy",
            size=0.4,
        )
        now = datetime(2026, 1, 1, 12, 7, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a tool success from a tool 7 minutes ago"

    def test_memory_recall(self):
        """Memory recall."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="memory_recall",
            source="memory",
            person_id=None,
            dominant_change="nostalgia",
            size=0.2,
        )
        now = datetime(2026, 1, 1, 12, 30, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a memory recall from memory 30 minutes ago"

    def test_memory_write_failed(self):
        """Memory write failure."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="memory_write_failed",
            source="memory",
            person_id=None,
            dominant_change="sadness",
            size=0.6,
        )
        now = datetime(2026, 1, 1, 12, 45, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a memory write failure from memory 45 minutes ago"

    def test_self_critique(self):
        """Self critique."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="self_critique",
            source="orchestrator",
            person_id=None,
            dominant_change="doubt",
            size=0.3,
        )
        now = datetime(2026, 1, 1, 12, 15, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since self critique from internal critique 15 minutes ago"

    def test_hours_ago(self):
        """Age in hours (over an hour)."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id="discord_42",
            dominant_change="joy",
            size=0.3,
        )
        now = datetime(2026, 1, 1, 13, 30, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a message from discord_42 3 hours ago"

    def test_one_hour_ago(self):
        """Exactly one hour ago (boundary case)."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id="discord_42",
            dominant_change="joy",
            size=0.3,
        )
        now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a message from discord_42 1 hour ago"

    def test_seconds_ago(self):
        """Age in seconds (under a minute)."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id="discord_42",
            dominant_change="joy",
            size=0.3,
        )
        now = datetime(2026, 1, 1, 12, 0, 30, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a message from discord_42 30 seconds ago"

    def test_unknown_kind(self):
        """Unknown kind falls back to generic description."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="unknown_event",
            source="conversation",
            person_id=None,
            dominant_change="curiosity",
            size=0.1,
        )
        now = datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a unknown event from conversation 10 minutes ago"

    def test_unknown_source(self):
        """Unknown source falls back to generic description."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="unknown_source",
            person_id=None,
            dominant_change="curiosity",
            size=0.1,
        )
        now = datetime(2026, 1, 1, 12, 10, 0, tzinfo=timezone.utc)
        phrase = cause_phrase(cause, now)
        assert phrase == "since a message from unknown_source 10 minutes ago"


class TestEmotionalStateBlock:
    """Tests for the emotional_state block in the L3 system prompt."""

    def setup_method(self):
        """Set up the LLMLayers instance."""
        self.layers = LLMLayers()

    def test_block_without_causes_unchanged(self):
        """The block without causes is byte-for-byte as before."""
        context = SynthesisContext(
            user_input="hello",
            user_id="test_user",
            emotional_state=EmotionState(
                timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                vector=EmotionVector(),
                dominant=("neutral", 0.0),
                description="Neutral",
                top_causes=[],  # No causes
            ),
        )

        prompt = self.layers.build_l3_system_prompt(context)

        # Extract the emotional_state block
        import re
        match = re.search(r'<emotional_state>.*?</emotional_state>', prompt, re.DOTALL)
        assert match is not None, "emotional_state block not found"
        block = match.group(0)

        # The block should match the exact format without causes
        expected = """<emotional_state>
  <description>Neutral</description>
  <dominant>neutral</dominant>
</emotional_state>"""
        assert block == expected, f"Block mismatch:\nGot:\n{block}\n\nExpected:\n{expected}"

    def test_block_with_cause(self):
        """The block with a cause includes the cause line."""
        cause = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id="discord_42",
            dominant_change="joy",
            size=0.3,
        )

        context = SynthesisContext(
            user_input="hello",
            user_id="test_user",
            emotional_state=EmotionState(
                timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                vector=EmotionVector(),
                dominant=("joy", 0.7),
                description="Feeling happy",
                top_causes=[cause],
            ),
        )

        # Mock the clock to return a fixed time
        from aura.clock import FakeClock, set_clock, get_clock
        fake_clock = FakeClock()
        fake_clock.set(datetime(2026, 1, 1, 12, 3, 0, tzinfo=timezone.utc))
        set_clock(fake_clock)

        try:
            prompt = self.layers.build_l3_system_prompt(context)
        finally:
            # Restore real clock
            from aura.clock import Clock
            set_clock(Clock())

        # Extract the emotional_state block
        import re
        match = re.search(r'<emotional_state>.*?</emotional_state>', prompt, re.DOTALL)
        assert match is not None, "emotional_state block not found"
        block = match.group(0)

        # The block should have the cause line
        assert "<cause>since a message from discord_42 3 minutes ago</cause>" in block

        # Verify the structure
        expected_lines = [
            "<emotional_state>",
            "  <description>Feeling happy</description>",
            "  <dominant>joy</dominant>",
            "  <cause>since a message from discord_42 3 minutes ago</cause>",
            "</emotional_state>",
        ]
        for line in expected_lines:
            assert line in block, f"Missing line: {line}"

    def test_block_with_multiple_causes_uses_first(self):
        """When there are multiple causes, only the first (largest) is used."""
        cause1 = EmotionCause(
            at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            kind="message",
            source="conversation",
            person_id="discord_42",
            dominant_change="joy",
            size=0.5,  # Larger
        )
        cause2 = EmotionCause(
            at=datetime(2026, 1, 1, 11, 30, 0, tzinfo=timezone.utc),
            kind="tool_failed",
            source="tool",
            person_id=None,
            dominant_change="anger",
            size=0.3,  # Smaller
        )

        context = SynthesisContext(
            user_input="hello",
            user_id="test_user",
            emotional_state=EmotionState(
                timestamp=datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
                vector=EmotionVector(),
                dominant=("joy", 0.7),
                description="Feeling happy",
                top_causes=[cause1, cause2],  # Sorted by size desc
            ),
        )

        from aura.clock import FakeClock, set_clock
        fake_clock = FakeClock()
        fake_clock.set(datetime(2026, 1, 1, 12, 3, 0, tzinfo=timezone.utc))
        set_clock(fake_clock)

        try:
            prompt = self.layers.build_l3_system_prompt(context)
        finally:
            from aura.clock import Clock
            set_clock(Clock())

        # Should use the first (largest) cause
        assert "since a message from discord_42 3 minutes ago" in prompt
        assert "since a tool failure" not in prompt  # Second cause should not appear


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