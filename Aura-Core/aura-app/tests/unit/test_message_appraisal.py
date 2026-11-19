"""Tests for W3-22: message appraisal pathway and keyword fallback removal."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.config import settings
from aura.models.appraisal import Appraisal, AppraisalEvent
from aura.models.emotion import EmotionPhysicsConfig, EmotionVector
from aura.orchestrator.coordinator import Orchestrator


class FakeDB:
    """Fake database that records writes."""

    def __init__(self):
        self.writes = []

    async def create(self, table: str, data: dict):
        self.writes.append({"table": table, "data": data})
        return {"id": f"{table}:test"}

    async def query(self, sql: str, params: dict | None = None):
        return []

    async def select(self, rid: str):
        return []

    async def merge(self, rid: str, data: dict):
        return {"id": rid}


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

    set_clock(fake_clock)

    config = EmotionPhysicsConfig()
    engine = EmotionEngine(config=config)
    engine.db = fake_db
    engine._message_bus = None
    engine.current_vector = config.baseline.model_copy()
    engine.previous_vector = config.baseline.model_copy()

    with patch("aura.api.websocket.broadcast_emotion_update", new_callable=AsyncMock):
        yield engine


@pytest.fixture
def turn_orchestrator(emotion_engine, fake_db, fake_clock, monkeypatch):
    """Create a minimal Orchestrator for testing the post-response chain."""
    from aura.engines.learning.engine import LearningEngine
    from aura.engines.identity.engine import IdentityEngine
    from aura.engines.goal.engine import GoalEngine
    from aura.engines.reflection.engine import ReflectionEngine
    from aura.orchestrator.message_bus import MessageBus
    from aura.llm.layers import LLMLayers
    from aura.executor.tool_executor import ToolExecutor
    from aura.clock import set_clock

    set_clock(fake_clock)

    # Mock all engines
    learning_engine = AsyncMock(spec=LearningEngine)
    learning_engine.db = fake_db
    learning_engine.get_learning_context = AsyncMock(return_value=MagicMock())
    learning_engine.log_experience = AsyncMock()
    learning_engine.get_skill = AsyncMock(return_value=None)
    learning_engine.ingest_mcp_server = AsyncMock()
    learning_engine.ingest_local_tool_module = AsyncMock()

    identity_engine = AsyncMock(spec=IdentityEngine)
    identity_engine.get_identity_context = AsyncMock(
        return_value=MagicMock(core_identity="Aura", tone_and_style="Helpful")
    )

    goal_engine = AsyncMock(spec=GoalEngine)
    goal_engine.get_goal_context = AsyncMock(return_value=MagicMock(active_goals=[]))
    goal_engine.check_goals_needing_autonomous_pursuit = AsyncMock(return_value=[])
    goal_engine.record_user_interaction = AsyncMock()

    reflection_engine = AsyncMock(spec=ReflectionEngine)

    message_bus = MagicMock(spec=MessageBus)
    message_bus.publish = AsyncMock()

    llm_layers = MagicMock(spec=LLMLayers)
    llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    llm_layers.l3_synthesis = AsyncMock(return_value="test response")
    llm_layers.l4_emotion_analysis = AsyncMock(return_value={})
    llm_layers.l4_appraise_message = AsyncMock(
        return_value=(
            Appraisal(
                congruence=0.0,
                novelty=0.0,
                certainty=0.5,
                control=0.5,
                agency="circumstance",
                warmth=0.0,
                beauty=0.0,
                intensity=0.5,
            ),
            {"joy": 0.3, "curiosity": 0.2},
        )
    )
    llm_layers.build_l3_system_prompt = MagicMock(return_value="PROMPT")
    llm_layers.context_mode = "deep_work"

    tool_executor = MagicMock(spec=ToolExecutor)
    tool_executor.extract_tool_calls = MagicMock(return_value=[])
    tool_executor.execute_and_feedback = AsyncMock(return_value="")

    # Create orchestrator via __new__ to avoid __init__ side effects
    orch = Orchestrator.__new__(Orchestrator)
    orch.emotion_engine = emotion_engine
    orch.learning_engine = learning_engine
    orch.identity_engine = identity_engine
    orch.goal_engine = goal_engine
    orch.reflection_engine = reflection_engine
    orch.message_bus = message_bus
    orch.llm_layers = llm_layers
    orch.tool_executor = tool_executor
    orch.db = fake_db
    orch.critique_buffer = {}
    orch._last_system_prompt = {}
    orch._state_lock = asyncio.Lock()
    orch.logger = MagicMock()
    orch.logger.info = MagicMock()
    orch.logger.warning = MagicMock()
    orch.logger.error = MagicMock()
    orch._current_session_namespace = None
    orch._current_identity_overlay = None

    # Mock _publish_trace
    orch._publish_trace = MagicMock()

    # Mock _sleep_gate to always allow
    orch._sleep_gate = AsyncMock(return_value=(True, None))

    # Mock _record_user_interaction
    orch._record_user_interaction = AsyncMock()

    # Mock _resolve_session
    orch._resolve_session = AsyncMock()

    # Mock _pre_intent_reply to return None (continue to intent classification)
    orch._pre_intent_reply = AsyncMock(return_value=None)

    # Mock _classify_intent
    orch._classify_intent = AsyncMock(return_value=({"intent": "CHAT"}, "CHAT", None))

    # Mock _resolve_forced_tool
    orch._resolve_forced_tool = AsyncMock(return_value=(False, None))

    # Mock _gather_turn_context
    from aura.orchestrator.coordinator import TurnContext
    from aura.llm.layers import SynthesisContext
    ctx = TurnContext(
        emotional_state=MagicMock(vector=EmotionVector()),
        learning_context=MagicMock(),
        identity_context=MagicMock(),
        goal_context=MagicMock(active_goals=[]),
        resonance_score=0.5,
        recent_critique=None,
        cold_start_xml=None,
        latent_intuition_xml=None,
        synthesis_context=MagicMock(spec=SynthesisContext),
        speaker="owner",
        venue="app",
    )
    orch._gather_turn_context = AsyncMock(return_value=ctx)

    # Mock _cache_system_prompt
    orch._cache_system_prompt = AsyncMock()

    # Mock _generate_blocking
    orch._generate_blocking = AsyncMock(return_value="test response")

    # Mock _schedule_post_response
    orch._schedule_post_response = MagicMock()

    yield orch


class TestMessageAppraisal:
    """Tests for the new message appraisal pathway (W3-22)."""

    @pytest.mark.asyncio
    async def test_t14_failing_l4_appraisal_no_state_change_warning_logged(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """T14 on new path: a failing L4 call produces no state change and a warning."""
        orch = turn_orchestrator

        # Make l4_appraise_message raise an exception
        orch.llm_layers.l4_appraise_message = AsyncMock(
            side_effect=Exception("L4 API error")
        )

        initial_vector = emotion_engine.current_vector.model_copy()

        # Enable appraisal pathway
        with patch.object(settings, "emotion_appraisal_enabled", True):
            await orch._post_response_chain(
                user_input="hello",
                response="hi there",
                emotional_before=MagicMock(vector=initial_vector),
                user_id="u1",
                conversation_id="c1",
                goal_context=MagicMock(),
                learning_context=MagicMock(),
                enable_l2=False,
                l2_reasoning_enabled=False,
                resonance_score=0.5,
                conversation_history=[{"role": "user", "content": "hello"}],
                venue="app",
                speaker="owner",
            )

        # State should be unchanged
        assert emotion_engine.current_vector.model_dump() == initial_vector.model_dump()

        # Warning should have been logged
        orch.logger.warning.assert_called()
        warning_calls = [str(call) for call in orch.logger.warning.call_args_list]
        assert any("L4 message appraisal failed" in c for c in warning_calls)

        # No emotion_event should be written
        emotion_writes = [w for w in fake_db.writes if w["table"] == "emotion_event"]
        assert len(emotion_writes) == 0

    @pytest.mark.asyncio
    async def test_t14_failing_l4_legacy_no_state_change_warning_logged(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """T14 on legacy path: a failing L4 call produces no state change and a warning."""
        orch = turn_orchestrator

        # Make l4_emotion_analysis raise an exception
        orch.llm_layers.l4_emotion_analysis = AsyncMock(
            side_effect=Exception("L4 API error")
        )

        initial_vector = emotion_engine.current_vector.model_copy()

        # Disable appraisal pathway (use legacy)
        with patch.object(settings, "emotion_appraisal_enabled", False):
            with patch.object(settings, "layer_l4_enabled", True):
                await orch._post_response_chain(
                    user_input="hello",
                    response="hi there",
                    emotional_before=MagicMock(vector=initial_vector),
                    user_id="u1",
                    conversation_id="c1",
                    goal_context=MagicMock(),
                    learning_context=MagicMock(),
                    enable_l2=False,
                    l2_reasoning_enabled=False,
                    resonance_score=0.5,
                    conversation_history=[{"role": "user", "content": "hello"}],
                    venue="app",
                    speaker="owner",
                )

        # State should be unchanged
        assert emotion_engine.current_vector.model_dump() == initial_vector.model_dump()

        # Warning should have been logged
        orch.logger.warning.assert_called()
        warning_calls = [str(call) for call in orch.logger.warning.call_args_list]
        assert any("L4 emotion analysis failed" in c for c in warning_calls)

    @pytest.mark.asyncio
    async def test_no_keyword_fallback_for_architecture_blueprint_reply(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """No keyword-based change happens for a reply full of 'architecture' and 'blueprint'."""
        orch = turn_orchestrator

        # Legacy path with L4 returning nothing (empty dict)
        orch.llm_layers.l4_emotion_analysis = AsyncMock(return_value={})

        initial_vector = emotion_engine.current_vector.model_copy()

        # Disable appraisal pathway (use legacy)
        with patch.object(settings, "emotion_appraisal_enabled", False):
            with patch.object(settings, "layer_l4_enabled", True):
                await orch._post_response_chain(
                    user_input="hello",
                    response="The architecture and blueprint of the system are vast and crystallizing.",
                    emotional_before=MagicMock(vector=initial_vector),
                    user_id="u1",
                    conversation_id="c1",
                    goal_context=MagicMock(),
                    learning_context=MagicMock(),
                    enable_l2=False,
                    l2_reasoning_enabled=False,
                    resonance_score=0.5,
                    conversation_history=[{"role": "user", "content": "hello"}],
                    venue="app",
                    speaker="owner",
                )

        # State should be unchanged (no fallback applied)
        assert emotion_engine.current_vector.model_dump() == initial_vector.model_dump()

        # Warning should have been logged (L4 returned nothing)
        orch.logger.warning.assert_called()
        warning_calls = [str(call) for call in orch.logger.warning.call_args_list]
        assert any("L4 emotion analysis returned no emotion deltas" in c for c in warning_calls)

    @pytest.mark.asyncio
    async def test_appraisal_receives_person_id_and_venue(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """With the flag on, a message is appraised and appraise receives person_id and venue."""
        orch = turn_orchestrator

        # Track the appraisal event passed to emotion_engine.appraise
        captured_event = {}

        async def capture_appraise(event):
            captured_event["event"] = event
            return MagicMock(vector=emotion_engine.current_vector)

        emotion_engine.appraise = capture_appraise

        with patch.object(settings, "emotion_appraisal_enabled", True):
            await orch._post_response_chain(
                user_input="hello",
                response="hi there",
                emotional_before=MagicMock(vector=emotion_engine.current_vector),
                user_id="u1",
                conversation_id="c1",
                goal_context=MagicMock(),
                learning_context=MagicMock(),
                enable_l2=False,
                l2_reasoning_enabled=False,
                resonance_score=0.5,
                conversation_history=[{"role": "user", "content": "hello"}],
                venue="discord",
                speaker="user123",
            )

        # Verify the appraisal event has correct person_id and venue
        assert "event" in captured_event
        event = captured_event["event"]
        assert isinstance(event, AppraisalEvent)
        assert event.person_id == "user123"
        assert event.venue == "discord"
        assert event.kind == "message"
        assert event.source == "conversation"

    @pytest.mark.asyncio
    async def test_reply_text_never_reaches_l4_appraise_message(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """The reply text never reaches l4_appraise_message (assert on call arguments)."""
        orch = turn_orchestrator

        # Track calls to l4_appraise_message
        captured_calls = []

        async def capture_call(user_input, recent_history, speaker):
            captured_calls.append({
                "user_input": user_input,
                "recent_history": recent_history,
                "speaker": speaker,
            })
            return (
                Appraisal(
                    congruence=0.0,
                    novelty=0.0,
                    certainty=0.5,
                    control=0.5,
                    agency="circumstance",
                    warmth=0.0,
                    beauty=0.0,
                    intensity=0.5,
                ),
                {"joy": 0.3},
            )

        orch.llm_layers.l4_appraise_message = capture_call

        user_input = "hello"
        aura_response = "This is Aura's reply which should NOT be in the history"

        with patch.object(settings, "emotion_appraisal_enabled", True):
            await orch._post_response_chain(
                user_input=user_input,
                response=aura_response,
                emotional_before=MagicMock(vector=emotion_engine.current_vector),
                user_id="u1",
                conversation_id="c1",
                goal_context=MagicMock(),
                learning_context=MagicMock(),
                enable_l2=False,
                l2_reasoning_enabled=False,
                resonance_score=0.5,
                conversation_history=[{"role": "user", "content": "hello"}],
                venue="app",
                speaker="owner",
            )

        # Verify l4_appraise_message was called
        assert len(captured_calls) == 1
        call = captured_calls[0]

        # The call should have user_input but NOT aura_response
        assert call["user_input"] == user_input
        assert call["speaker"] == "owner"

        # The recent_history should NOT contain Aura's reply
        history = call["recent_history"]
        for turn in history:
            assert aura_response not in turn.get("content", ""), \
                "Aura's reply text should not be in the history passed to l4_appraise_message"

    @pytest.mark.asyncio
    async def test_legacy_path_uses_both_user_input_and_aura_response(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """Legacy _apply_l4_emotion_analysis receives both user_input and aura_response."""
        orch = turn_orchestrator

        captured_calls = []

        async def capture_call(user_input, aura_response, current_emotions):
            captured_calls.append({
                "user_input": user_input,
                "aura_response": aura_response,
                "current_emotions": current_emotions,
            })
            return {"joy": 0.3}

        orch.llm_layers.l4_emotion_analysis = capture_call

        user_input = "hello"
        aura_response = "This is Aura's reply"

        with patch.object(settings, "emotion_appraisal_enabled", False):
            with patch.object(settings, "layer_l4_enabled", True):
                await orch._post_response_chain(
                    user_input=user_input,
                    response=aura_response,
                    emotional_before=MagicMock(vector=emotion_engine.current_vector),
                    user_id="u1",
                    conversation_id="c1",
                    goal_context=MagicMock(),
                    learning_context=MagicMock(),
                    enable_l2=False,
                    l2_reasoning_enabled=False,
                    resonance_score=0.5,
                    conversation_history=[{"role": "user", "content": "hello"}],
                    venue="app",
                    speaker="owner",
                )

        # Verify _apply_l4_emotion_analysis was called with both inputs
        assert len(captured_calls) == 1
        call = captured_calls[0]
        assert call["user_input"] == user_input
        assert call["aura_response"] == aura_response


class TestFallbackRemovalCharacterisation:
    """Characterisation tests updated for W3-22 (keyword fallback removed)."""

    @pytest.mark.asyncio
    async def test_no_keyword_fallback_in_legacy_path(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """changed on purpose by W3-22 (keyword fallback removed)"""
        orch = turn_orchestrator

        # Legacy path with L4 returning emotions that would trigger keyword fallback
        # (intensity_words like "architecture", "blueprint")
        orch.llm_layers.l4_emotion_analysis = AsyncMock(return_value={})

        initial_vector = emotion_engine.current_vector.model_copy()

        with patch.object(settings, "emotion_appraisal_enabled", False):
            with patch.object(settings, "layer_l4_enabled", True):
                await orch._post_response_chain(
                    user_input="hello",
                    response="The architecture and blueprint are vast and crystallizing electric.",
                    emotional_before=MagicMock(vector=initial_vector),
                    user_id="u1",
                    conversation_id="c1",
                    goal_context=MagicMock(),
                    learning_context=MagicMock(),
                    enable_l2=False,
                    l2_reasoning_enabled=False,
                    resonance_score=0.5,
                    conversation_history=[{"role": "user", "content": "hello"}],
                    venue="app",
                    speaker="owner",
                )

        # State should be unchanged - no keyword fallback applied
        assert emotion_engine.current_vector.model_dump() == initial_vector.model_dump()

    @pytest.mark.asyncio
    async def test_no_keyword_fallback_in_appraisal_path(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """changed on purpose by W3-22 (keyword fallback removed)"""
        orch = turn_orchestrator

        # Make l4_appraise_message fail
        orch.llm_layers.l4_appraise_message = AsyncMock(
            side_effect=Exception("L4 API error")
        )

        initial_vector = emotion_engine.current_vector.model_copy()

        with patch.object(settings, "emotion_appraisal_enabled", True):
            await orch._post_response_chain(
                user_input="hello",
                response="The architecture and blueprint are vast and crystallizing electric.",
                emotional_before=MagicMock(vector=initial_vector),
                user_id="u1",
                conversation_id="c1",
                goal_context=MagicMock(),
                learning_context=MagicMock(),
                enable_l2=False,
                l2_reasoning_enabled=False,
                resonance_score=0.5,
                conversation_history=[{"role": "user", "content": "hello"}],
                venue="app",
                speaker="owner",
            )

        # State should be unchanged - no fallback applied
        assert emotion_engine.current_vector.model_dump() == initial_vector.model_dump()

        # Warning logged but no fallback
        orch.logger.warning.assert_called()
        warning_calls = [str(call) for call in orch.logger.warning.call_args_list]
        assert any("L4 message appraisal failed" in c for c in warning_calls)


class TestAppraisalL4Switch:
    """Tests for the L4 switch respect in appraisal pathway (W3-22 supervisor fix)."""

    @pytest.mark.asyncio
    async def test_appraisal_enabled_l4_disabled_does_nothing(
        self, turn_orchestrator, emotion_engine, fake_db, fake_clock
    ):
        """When emotion_appraisal_enabled=True but layer_l4_enabled=False, _appraise_message is not called."""
        orch = turn_orchestrator

        # Track calls to _appraise_message and _apply_l4_emotion_analysis
        appraise_called = False
        l4_analysis_called = False

        original_appraise = orch._appraise_message
        original_l4_analysis = orch._apply_l4_emotion_analysis

        async def track_appraise(*args, **kwargs):
            nonlocal appraise_called
            appraise_called = True
            return await original_appraise(*args, **kwargs)

        async def track_l4_analysis(*args, **kwargs):
            nonlocal l4_analysis_called
            l4_analysis_called = True
            return await original_l4_analysis(*args, **kwargs)

        orch._appraise_message = track_appraise
        orch._apply_l4_emotion_analysis = track_l4_analysis

        initial_vector = emotion_engine.current_vector.model_copy()

        # Enable appraisal but disable L4
        with patch.object(settings, "emotion_appraisal_enabled", True):
            with patch.object(settings, "layer_l4_enabled", False):
                await orch._post_response_chain(
                    user_input="hello",
                    response="hi there",
                    emotional_before=MagicMock(vector=initial_vector),
                    user_id="u1",
                    conversation_id="c1",
                    goal_context=MagicMock(),
                    learning_context=MagicMock(),
                    enable_l2=False,
                    l2_reasoning_enabled=False,
                    resonance_score=0.5,
                    conversation_history=[{"role": "user", "content": "hello"}],
                    venue="app",
                    speaker="owner",
                )

        # Neither _appraise_message nor _apply_l4_emotion_analysis should be called
        assert not appraise_called, "_appraise_message should not be called when L4 is disabled"
        assert not l4_analysis_called, "_apply_l4_emotion_analysis should not be called when L4 is disabled"

        # State should be unchanged
        assert emotion_engine.current_vector.model_dump() == initial_vector.model_dump()