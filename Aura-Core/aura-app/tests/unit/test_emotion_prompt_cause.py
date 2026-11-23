"""Tests for emotion prompt cause phrase and block (W3-25)."""

from datetime import datetime, timezone, timedelta

import pytest

from aura.engines.emotion.describe import cause_phrase
from aura.models.emotion import EmotionCause, EmotionState, EmotionVector
from aura.llm.layers import LLMLayers, SynthesisContext


_T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _phrase(kind, seconds, person_id=None):
    cause = EmotionCause(
        at=_T0, kind=kind, source="conversation", person_id=person_id,
        dominant_change="joy", size=0.3,
    )
    return cause_phrase(cause, _T0 + timedelta(seconds=seconds))


class TestCausePhrase:
    """Tests for the cause_phrase function."""

    def test_message_from_person(self):
        assert _phrase("message", 180, person_id="discord_42") == (
            "since a message from discord_42 3 minutes ago"
        )

    def test_message_without_person(self):
        assert _phrase("message", 300) == "since something said in conversation 5 minutes ago"

    @pytest.mark.parametrize(
        "kind,expected",
        [
            ("tool_failed", "since a tool let you down 12 minutes ago"),
            ("tool_succeeded", "since a tool came through for you 12 minutes ago"),
            ("task_result", "since a task came back 12 minutes ago"),
            ("prediction", "since a prediction played out 12 minutes ago"),
            ("memory_recall", "since a memory resurfaced 12 minutes ago"),
            (
                "memory_write_failed",
                "since a memory slipped away before it could be kept 12 minutes ago",
            ),
            (
                "self_critique",
                "since you looked back critically at your own words 12 minutes ago",
            ),
            ("unknown_event", "since unknown event 12 minutes ago"),
        ],
    )
    def test_kind_templates(self, kind, expected):
        assert _phrase(kind, 720) == expected

    def test_a_moment_ago(self):
        assert _phrase("message", 30, person_id="discord_42") == (
            "since a message from discord_42 a moment ago"
        )

    def test_hours_ago(self):
        assert _phrase("message", 3 * 3600 + 1800, person_id="discord_42") == (
            "since a message from discord_42 3 hours ago"
        )

    def test_one_hour_ago(self):
        assert _phrase("message", 3600, person_id="discord_42") == (
            "since a message from discord_42 1 hour ago"
        )

    def test_days_ago(self):
        assert _phrase("tool_failed", 86400) == "since a tool let you down 1 day ago"
        assert _phrase("tool_failed", 2 * 86400 + 5000) == "since a tool let you down 2 days ago"

    def test_no_em_dash_anywhere(self):
        kinds = [
            "message", "tool_failed", "tool_succeeded", "task_result", "prediction",
            "memory_recall", "memory_write_failed", "self_critique", "other_kind",
        ]
        for kind in kinds:
            for secs in (10, 720, 7200, 200000):
                assert "—" not in _phrase(kind, secs, person_id="p")
                assert "—" not in _phrase(kind, secs)


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
        assert "since a tool let you down" not in prompt  # Second cause should not appear


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


def test_l3_system_prompt_has_no_em_dash():
    layers = LLMLayers.__new__(LLMLayers)
    context = SynthesisContext(
        user_input="hi",
        emotional_state=EmotionState(
            timestamp=_T0,
            vector=EmotionVector(),
            dominant=("neutral", 0.0),
            description="Neutral",
            top_causes=[],
        ),
    )
    prompt = layers._build_l3_system_prompt(context, "T", None)
    assert "—" not in prompt
