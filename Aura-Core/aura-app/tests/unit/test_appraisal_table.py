"""Tests for the appraisal table (Emotion PRD T8)."""

import json
import tempfile
from pathlib import Path

import pytest

from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.engines.emotion.appraisal import load_table, impulses_for, Pattern


class TestAppraisalTable:
    """Tests for the appraisal table loading and matching."""

    def test_load_default_table(self):
        """Default table loads without error."""
        table = load_table()
        assert len(table) > 0
        for pattern in table:
            assert isinstance(pattern, Pattern)
            assert pattern.name
            assert pattern.when
            assert pattern.impulse

    def test_load_table_validates_dimensions(self):
        """Unknown dimension in table raises at load."""
        bad_table = [
            {
                "name": "test_bad",
                "when": {"novelty": [0.6, 1.0]},
                "impulse": {"not_a_real_emotion": 0.5},
            }
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(bad_table, f)
            bad_path = f.name

        try:
            with pytest.raises(ValueError, match="Unknown emotion dimension"):
                load_table(bad_path)
        finally:
            Path(bad_path).unlink()

    def test_intensity_zero_gives_no_impulse(self):
        """Intensity 0 returns empty dict."""
        appraisal = Appraisal(
            congruence=0.5,
            novelty=0.8,
            certainty=0.5,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=0.0,
        )
        result = impulses_for(appraisal)
        assert result == {}

    def test_no_match_gives_empty(self):
        """Appraisal matching no row returns empty dict."""
        # All values at defaults that don't match any pattern
        appraisal = Appraisal(
            congruence=0.0,
            novelty=0.4,  # Not high (>=0.6), not low (<=0.3)
            certainty=0.5,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=0.5,
        )
        result = impulses_for(appraisal)
        assert result == {}

    def test_high_novelty(self):
        """High novelty produces surprise and curiosity."""
        appraisal = Appraisal(
            congruence=0.0,
            novelty=0.8,
            certainty=0.5,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        # surprise should be dominant (0.8 > 0.5)
        assert "surprise" in result
        assert "curiosity" in result
        assert result["surprise"] > result["curiosity"]
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "surprise"

    def test_high_novelty_positive_congruence_high_beauty(self):
        """High novelty + positive congruence + high beauty produces wonder, fascination, awe."""
        appraisal = Appraisal(
            congruence=0.5,
            novelty=0.8,
            certainty=0.5,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.8,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "wonder" in result
        assert "fascination" in result
        assert "awe" in result
        # wonder should be dominant (0.8 > 0.7 > 0.6)
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "wonder"

    def test_positive_congruence_agency_self(self):
        """Positive congruence + agency self produces joy and pride."""
        appraisal = Appraisal(
            congruence=0.5,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "joy" in result
        assert "pride" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "joy"

    def test_positive_congruence_agency_other_positive_warmth(self):
        """Positive congruence + agency other + positive warmth produces joy and gratitude."""
        appraisal = Appraisal(
            congruence=0.5,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="other",
            warmth=0.5,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "joy" in result
        assert "gratitude" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "gratitude"

    def test_negative_congruence_agency_other_high_control(self):
        """Negative congruence + agency other + high control produces anger."""
        appraisal = Appraisal(
            congruence=-0.5,
            novelty=0.0,
            certainty=0.5,
            control=0.8,
            agency="other",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "anger" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "anger"

    def test_negative_congruence_low_control(self):
        """Negative congruence + low control produces sadness."""
        appraisal = Appraisal(
            congruence=-0.5,
            novelty=0.0,
            certainty=0.5,  # Not low
            control=0.2,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "sadness" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "sadness"

    def test_negative_congruence_low_control_low_certainty_fear(self):
        """Negative congruence + low control + low certainty produces fear (from this row) and sadness (from row above, not double-counted)."""
        appraisal = Appraisal(
            congruence=-0.5,
            novelty=0.0,
            certainty=0.2,
            control=0.2,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "fear" in result
        assert "sadness" in result  # From negative_congruence_low_control row (not double-counted)
        # fear should be dominant (0.6) vs sadness (0.7) - but wait, sadness is 0.7 from first row
        # Actually the first row gives sadness=0.7, second row gives fear=0.6
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "sadness"  # Sadness (0.7) > fear (0.6)

    def test_negative_congruence_agency_self(self):
        """Negative congruence + agency self produces shame and doubt."""
        appraisal = Appraisal(
            congruence=-0.5,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "shame" in result
        assert "doubt" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "shame"

    def test_low_certainty(self):
        """Low certainty produces confusion and doubt."""
        appraisal = Appraisal(
            congruence=0.0,
            novelty=0.0,
            certainty=0.2,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal)
        assert "confusion" in result
        assert "doubt" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "confusion"

    def test_empathy_sadness_distress(self):
        """User state with sadness >= 0.5 produces empathy and compassion."""
        appraisal = Appraisal(
            congruence=0.0,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        user_state = {"sadness": 0.7, "joy": 0.1}
        result = impulses_for(appraisal, user_state=user_state)
        assert "empathy" in result
        assert "compassion" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "empathy"

    def test_empathy_fear_distress(self):
        """User state with fear >= 0.5 produces empathy and compassion."""
        appraisal = Appraisal(
            congruence=0.0,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="circumstance",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        user_state = {"fear": 0.6, "joy": 0.1}
        result = impulses_for(appraisal, user_state=user_state)
        assert "empathy" in result
        assert "compassion" in result
        dominant = max(result.items(), key=lambda x: x[1])[0]
        assert dominant == "empathy"

    def test_intensity_scales_impulses(self):
        """Intensity scales all impulses proportionally."""
        appraisal_high = Appraisal(
            congruence=0.5,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        appraisal_low = Appraisal(
            congruence=0.5,
            novelty=0.0,
            certainty=0.5,
            control=0.5,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=0.5,
        )
        result_high = impulses_for(appraisal_high)
        result_low = impulses_for(appraisal_low)
        # Each impulse should be half
        for dim in result_high:
            assert result_low[dim] == pytest.approx(result_high[dim] * 0.5)

    def test_impulses_capped_at_one(self):
        """Impulses are capped at 1.0."""
        # Create an appraisal that matches multiple patterns with overlapping emotions
        # Use a custom table with overlapping impulses
        custom_table = [
            Pattern({"name": "test1", "when": {"novelty": [0.6, 1.0]}, "impulse": {"surprise": 0.8}}),
            Pattern({"name": "test2", "when": {"congruence": [0.2, 1.0], "agency": "self"}, "impulse": {"surprise": 0.5}}),
        ]
        appraisal = Appraisal(
            congruence=0.5,
            novelty=0.8,
            certainty=0.5,
            control=0.5,
            agency="self",
            warmth=0.0,
            beauty=0.0,
            intensity=1.0,
        )
        result = impulses_for(appraisal, table=custom_table)
        assert result["surprise"] == 1.0  # Capped at 1.0

    def test_appraisal_event_model(self):
        """AppraisalEvent model works correctly."""
        event = AppraisalEvent(
            kind="message",
            source="discord",
            appraisal=Appraisal(novelty=0.8, agency="other"),
            person_id="user123",
            venue="general",
            ref="msg456",
            user_state={"sadness": 0.6},
        )
        assert event.kind == "message"
        assert event.source == "discord"
        assert event.appraisal.novelty == 0.8
        assert event.person_id == "user123"
        assert event.venue == "general"
        assert event.ref == "msg456"
        assert event.user_state["sadness"] == 0.6

    def test_appraisal_field_validators_clamp(self):
        """Field validators clamp values to valid ranges."""
        # Test upper bounds - validators should clamp
        appraisal = Appraisal(
            congruence=2.0,  # Should clamp to 1.0
            novelty=2.0,  # Should clamp to 1.0
            certainty=2.0,  # Should clamp to 1.0
            control=2.0,  # Should clamp to 1.0
            warmth=2.0,  # Should clamp to 1.0
            beauty=2.0,  # Should clamp to 1.0
            intensity=2.0,  # Should clamp to 1.0
        )
        assert appraisal.congruence == 1.0
        assert appraisal.novelty == 1.0
        assert appraisal.certainty == 1.0
        assert appraisal.control == 1.0
        assert appraisal.warmth == 1.0
        assert appraisal.beauty == 1.0
        assert appraisal.intensity == 1.0

        # Test lower bounds - validators should clamp
        appraisal = Appraisal(
            congruence=-2.0,  # Should clamp to -1.0
            novelty=-1.0,  # Should clamp to 0.0
            certainty=-1.0,  # Should clamp to 0.0
            control=-1.0,  # Should clamp to 0.0
            warmth=-2.0,  # Should clamp to -1.0
            beauty=-1.0,  # Should clamp to 0.0
            intensity=-1.0,  # Should clamp to 0.0
        )
        assert appraisal.congruence == -1.0
        assert appraisal.novelty == 0.0
        assert appraisal.certainty == 0.0
        assert appraisal.control == 0.0
        assert appraisal.warmth == -1.0
        assert appraisal.beauty == 0.0
        assert appraisal.intensity == 0.0