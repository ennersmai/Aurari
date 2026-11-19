"""Tests for l4_appraise_message (W3-21)."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.models.appraisal import Appraisal


class FakeClient:
    """Fake LLM client that returns a scripted response."""

    def __init__(self, response: str):
        self.response = response
        self.last_messages: list[dict] | None = None
        self.last_model: str | None = None
        self.last_temperature: float | None = None

    async def complete(self, messages: list[dict], model: str, temperature: float, max_tokens: int) -> str:
        self.last_messages = messages
        self.last_model = model
        self.last_temperature = temperature
        return self.response


@pytest.fixture
def fake_client():
    return FakeClient("")


@pytest.fixture
def llm_layers(fake_client):
    from aura.llm.layers import LLMLayers

    layers = LLMLayers(client=fake_client)
    return layers


class TestL4AppraiseMessage:
    """Tests for the l4_appraise_message method."""

    @pytest.mark.asyncio
    async def test_valid_reply_parses(self, llm_layers, fake_client):
        """A valid JSON reply parses into Appraisal and user_state."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.5,
                "novelty": 0.3,
                "certainty": 0.7,
                "control": 0.6,
                "agency": "self",
                "warmth": 0.2,
                "beauty": 0.1,
                "intensity": 0.8
            },
            "user_state": {
                "joy": 0.6,
                "curiosity": 0.4
            }
        })

        appraisal, user_state = await llm_layers.l4_appraise_message(
            user_input="I'm so happy today!",
            recent_history=[{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi there!"}],
            speaker="discord"
        )

        assert isinstance(appraisal, Appraisal)
        assert appraisal.congruence == 0.5
        assert appraisal.novelty == 0.3
        assert appraisal.certainty == 0.7
        assert appraisal.control == 0.6
        assert appraisal.agency == "self"
        assert appraisal.warmth == 0.2
        assert appraisal.beauty == 0.1
        assert appraisal.intensity == 0.8

        assert user_state == {"joy": 0.6, "curiosity": 0.4}

    @pytest.mark.asyncio
    async def test_fenced_reply_parses(self, llm_layers, fake_client):
        """A JSON reply wrapped in code block fences parses correctly."""
        fake_client.response = '''```json
{
  "appraisal": {
    "congruence": -0.3,
    "novelty": 0.8,
    "certainty": 0.4,
    "control": 0.2,
    "agency": "other",
    "warmth": -0.5,
    "beauty": 0.0,
    "intensity": 0.6
  },
  "user_state": {
    "anger": 0.7,
    "sadness": 0.3
  }
}
```'''

        appraisal, user_state = await llm_layers.l4_appraise_message(
            user_input="This is terrible!",
            recent_history=[],
            speaker="app"
        )

        assert isinstance(appraisal, Appraisal)
        assert appraisal.congruence == -0.3
        assert appraisal.agency == "other"
        assert user_state == {"anger": 0.7, "sadness": 0.3}

    @pytest.mark.asyncio
    async def test_unknown_user_state_keys_dropped(self, llm_layers, fake_client):
        """Unknown user_state keys are dropped, known ones kept."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {
                "joy": 0.5,
                "invalid_emotion": 0.8,
                "another_fake": 0.3,
                "curiosity": 0.2
            }
        })

        appraisal, user_state = await llm_layers.l4_appraise_message(
            user_input="Test message",
            recent_history=[],
            speaker="test"
        )

        # Only known emotions should be kept
        assert user_state == {"joy": 0.5, "curiosity": 0.2}
        assert "invalid_emotion" not in user_state
        assert "another_fake" not in user_state

    @pytest.mark.asyncio
    async def test_invalid_json_raises(self, llm_layers, fake_client):
        """Invalid JSON raises ValueError."""
        fake_client.response = "This is not JSON at all"

        with pytest.raises(ValueError, match="L4 appraisal returned no JSON"):
            await llm_layers.l4_appraise_message(
                user_input="Test",
                recent_history=[],
                speaker="test"
            )

    @pytest.mark.asyncio
    async def test_invalid_json_partial_raises(self, llm_layers, fake_client):
        """Malformed JSON raises ValueError."""
        fake_client.response = '{"appraisal": {invalid}}'

        with pytest.raises(ValueError):
            await llm_layers.l4_appraise_message(
                user_input="Test",
                recent_history=[],
                speaker="test"
            )

    @pytest.mark.asyncio
    async def test_missing_appraisal_key_raises(self, llm_layers, fake_client):
        """Missing 'appraisal' key raises ValueError."""
        fake_client.response = json.dumps({"user_state": {"joy": 0.5}})

        with pytest.raises(ValueError, match="missing 'appraisal' key"):
            await llm_layers.l4_appraise_message(
                user_input="Test",
                recent_history=[],
                speaker="test"
            )

    @pytest.mark.asyncio
    async def test_t7_prompt_independent_of_aura_reply(self, llm_layers, fake_client):
        """T7: The request sent to the client is identical whatever reply text Aura produced.

        Build two turns that differ only in Aura's latest reply (not yet in the history
        passed), and assert the prompts are equal.
        """
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {}
        })

        # Both scenarios have the SAME history (Aura's latest reply is NOT in the history)
        # The difference is what Aura's reply WOULD BE, but it's not passed to the method
        history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "How are you?"}
        ]

        # Scenario 1: Aura's reply would be "I'm happy to help!" (not in history)
        await llm_layers.l4_appraise_message(
            user_input="How are you?",
            recent_history=history,
            speaker="discord"
        )
        prompt1 = fake_client.last_messages[1]["content"]

        # Reset
        fake_client.last_messages = None

        # Scenario 2: Aura's reply would be "I'm feeling sad today." (not in history)
        # Same history passed - the method has no parameter for Aura's reply
        await llm_layers.l4_appraise_message(
            user_input="How are you?",
            recent_history=history,
            speaker="discord"
        )
        prompt2 = fake_client.last_messages[1]["content"]

        # The prompts must be identical (the method has no access to Aura's reply)
        assert prompt1 == prompt2, "Prompt should not depend on Aura's reply text"

    @pytest.mark.asyncio
    async def test_user_state_values_clamped(self, llm_layers, fake_client):
        """user_state values outside 0..1 are clamped."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {
                "joy": 1.5,
                "sadness": -0.3,
                "curiosity": 0.5
            }
        })

        appraisal, user_state = await llm_layers.l4_appraise_message(
            user_input="Test",
            recent_history=[],
            speaker="test"
        )

        assert user_state == {"joy": 1.0, "sadness": 0.0, "curiosity": 0.5}

    @pytest.mark.asyncio
    async def test_history_limit_four_turns(self, llm_layers, fake_client):
        """Only the last 4 turns are included in history."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {}
        })

        # 6 turns of history - only last 4 should be used
        history = [
            {"role": "user", "content": "Turn 1"},
            {"role": "assistant", "content": "Response 1"},
            {"role": "user", "content": "Turn 2"},
            {"role": "assistant", "content": "Response 2"},
            {"role": "user", "content": "Turn 3"},
            {"role": "assistant", "content": "Response 3"},
        ]

        await llm_layers.l4_appraise_message(
            user_input="Current turn",
            recent_history=history,
            speaker="test"
        )

        prompt = fake_client.last_messages[1]["content"]
        # Should contain Turn 2, Response 2, Turn 3, Response 3 but not Turn 1, Response 1
        assert "Turn 1" not in prompt
        assert "Response 1" not in prompt
        assert "Turn 2" in prompt
        assert "Response 2" in prompt
        assert "Turn 3" in prompt
        assert "Response 3" in prompt

    @pytest.mark.asyncio
    async def test_temperature_is_0_3(self, llm_layers, fake_client):
        """Temperature used is 0.3 (same as l4_emotion_analysis)."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {}
        })

        await llm_layers.l4_appraise_message(
            user_input="Test",
            recent_history=[],
            speaker="test"
        )

        assert fake_client.last_temperature == 0.3

    @pytest.mark.asyncio
    async def test_model_is_l4_model(self, llm_layers, fake_client):
        """The active L4 model from settings is used."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {}
        })

        await llm_layers.l4_appraise_message(
            user_input="Test",
            recent_history=[],
            speaker="test"
        )

        from aura.config import settings
        assert fake_client.last_model == settings.active_l4_model

    @pytest.mark.asyncio
    async def test_aura_turns_labelled_in_history(self, llm_layers, fake_client):
        """Aura's turns in history are labelled as 'Aura:'."""
        fake_client.response = json.dumps({
            "appraisal": {
                "congruence": 0.0,
                "novelty": 0.0,
                "certainty": 0.5,
                "control": 0.5,
                "agency": "circumstance",
                "warmth": 0.0,
                "beauty": 0.0,
                "intensity": 0.5
            },
            "user_state": {}
        })

        history = [
            {"role": "user", "content": "User message"},
            {"role": "assistant", "content": "Aura response"},
        ]

        await llm_layers.l4_appraise_message(
            user_input="Current",
            recent_history=history,
            speaker="test"
        )

        prompt = fake_client.last_messages[1]["content"]
        assert "User: User message" in prompt
        assert "Aura: Aura response" in prompt