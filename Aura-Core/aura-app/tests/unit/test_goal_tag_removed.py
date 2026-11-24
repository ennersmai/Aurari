"""B3-06: Remove the pursuit text tag; goal creation under the gate.

Tests:
- Prompt contains the tag text with the flag off and not with it on.
- _consider_new_goal creates nothing from boredom or idle_exploration triggers when on.
- An accepted proposal still creates a goal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.engines.goal.engine import GoalEngine
from aura.llm.layers import LLMLayers, SynthesisContext
from aura.models.emotion import EmotionState, EmotionVector
from aura.models.goal import Goal, GoalContext
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
GID = "goal:g1"


def _goal_ctx(active_goals=None, current_focus=None, pending_proposals=None, pursuit_suggestions=None):
    """Build a GoalContext with optional fields."""
    return GoalContext(
        active_goals=active_goals or [],
        current_focus=current_focus,
        pending_proposals=pending_proposals or [],
        pursuit_suggestions=pursuit_suggestions or [],
    )


class TestPromptGoalInstructions:
    """Test that the L3 system prompt includes/excludes the GOAL_PURSUIT_REQUEST tag."""

    def setup_method(self):
        self.layers = LLMLayers.__new__(LLMLayers)
        # Mock the LLM client to avoid network calls
        self.layers.client = AsyncMock()

    def _base_context(self, goal_context=None):
        return SynthesisContext(
            user_input="hello",
            user_id="test_user",
            emotional_state=EmotionState(
                timestamp=_START,
                vector=EmotionVector(),
                dominant=("neutral", 0.0),
                description="Neutral",
            ),
            goal_context=goal_context,
        )

    def test_prompt_has_tag_when_goals_v2_off(self, monkeypatch):
        """With goals_v2_enabled=False, the prompt must contain the tag text byte for byte."""
        monkeypatch.setattr(settings, "goals_v2_enabled", False)

        goal = Goal(
            goal_id=GID,
            name="Test Goal",
            description="A test goal",
            goal_type="learning_gap",
            priority=0.8,
            status="active",
            origin="owner",
        )
        ctx = self._base_context(goal_context=_goal_ctx(active_goals=[goal]))

        prompt = self.layers.build_l3_system_prompt(ctx)

        # The tag instruction block must be present exactly
        assert "[GOAL_PURSUIT_REQUEST:goal_id]" in prompt
        assert "I'd like to work on [GOAL_PURSUIT_REQUEST:goal:abc123] independently. May I?" in prompt
        assert "Can I pursue [GOAL_PURSUIT_REQUEST:goal:abc123] autonomously for a bit?" in prompt
        assert "The marker MUST use the EXACT goal_id from the active_goals list above." in prompt
        # request_pursuit tool must NOT be mentioned
        assert "request_pursuit" not in prompt

    def test_prompt_has_no_tag_when_goals_v2_on(self, monkeypatch):
        """With goals_v2_enabled=True, the tag text must be absent; request_pursuit tool is taught instead."""
        monkeypatch.setattr(settings, "goals_v2_enabled", True)

        goal = Goal(
            goal_id=GID,
            name="Test Goal",
            description="A test goal",
            goal_type="learning_gap",
            priority=0.8,
            status="active",
            origin="owner",
        )
        ctx = self._base_context(goal_context=_goal_ctx(active_goals=[goal]))

        prompt = self.layers.build_l3_system_prompt(ctx)

        # The tag must NOT appear
        assert "[GOAL_PURSUIT_REQUEST:" not in prompt
        # The request_pursuit tool instruction must be present
        assert "request_pursuit" in prompt
        assert "read, write, execute, or send" in prompt
        assert "Read scope starts immediately" in prompt
        assert "other scopes require owner approval" in prompt

    def test_pursuit_suggestions_tag_off_when_v2_on(self, monkeypatch):
        """Pursuit suggestions block also switches to request_pursuit when v2 is on."""
        monkeypatch.setattr(settings, "goals_v2_enabled", True)

        # Need at least one active goal for the goals section to be included
        goal = Goal(
            goal_id=GID,
            name="Test Goal",
            description="A test goal",
            goal_type="learning_gap",
            priority=0.8,
            status="active",
            origin="owner",
        )
        ctx = self._base_context(goal_context=_goal_ctx(
            active_goals=[goal],
            pursuit_suggestions=[{"goal_id": GID, "goal_name": "Test", "reason": "test reason"}]
        ))

        prompt = self.layers.build_l3_system_prompt(ctx)

        # Tag must not appear in pursuit_suggestions either
        assert "[GOAL_PURSUIT_REQUEST:" not in prompt
        # request_pursuit instruction must be there
        assert "request_pursuit" in prompt
        assert "read, write, execute, or send" in prompt
        assert "Read scope starts immediately" in prompt
        assert "other scopes require owner approval" in prompt

    def test_pursuit_suggestions_tag_on_when_v2_off(self, monkeypatch):
        """Pursuit suggestions block keeps the tag when v2 is off."""
        monkeypatch.setattr(settings, "goals_v2_enabled", False)

        # Need at least one active goal for the goals section to be included
        goal = Goal(
            goal_id=GID,
            name="Test Goal",
            description="A test goal",
            goal_type="learning_gap",
            priority=0.8,
            status="active",
            origin="owner",
        )
        ctx = self._base_context(goal_context=_goal_ctx(
            active_goals=[goal],
            pursuit_suggestions=[{"goal_id": GID, "goal_name": "Test", "reason": "test reason"}]
        ))

        prompt = self.layers.build_l3_system_prompt(ctx)

        # Tag must appear in pursuit_suggestions
        assert "[GOAL_PURSUIT_REQUEST:goal_id]" in prompt
        assert "⚠️ ACTION REQUIRED" in prompt
        # request_pursuit must NOT be mentioned
        assert "request_pursuit" not in prompt


class TestGoalEngineConsiderNewGoal:
    """Test that _consider_new_goal is gated by goals_v2_enabled."""

    @pytest.fixture
    async def engine(self, monkeypatch):
        """Create a GoalEngine with embedded DB and fake clock."""
        d = EmbeddedSurrealDB()
        await d.connect()
        set_clock(FakeClock(_START))

        # Patch the DB client getter
        import aura.engines.goal.engine as engine_mod
        monkeypatch.setattr(engine_mod, "get_db_client", lambda: d)

        # Disable the tick loop sleep
        async def _no_sleep(_):
            return None
        monkeypatch.setattr(engine_mod.asyncio, "sleep", _no_sleep)

        # Create engine without loading goals
        engine = GoalEngine.__new__(GoalEngine)
        engine.db = d
        engine._llm_layers = None
        engine._emotion_engine = None
        engine._learning_engine = None
        engine._identity_engine = None
        engine._message_bus = None
        engine.active_goals = []
        engine.current_boredom_level = 0.0
        engine.last_user_interaction = _START
        # Set last_goal_generation to 2 hours ago to bypass rate limit
        engine.last_goal_generation = _START - timedelta(hours=2)
        engine._last_internal_interaction_update = _START
        engine.boredom_threshold = 0.6
        engine.idle_time_threshold = 300.0
        engine.logger = MagicMock()

        yield engine

        set_clock(Clock())
        await d.close()

    async def test_consider_new_goal_boredom_blocked_when_v2_on(self, engine, monkeypatch):
        """_consider_new_goal('boredom') returns immediately when goals_v2_enabled is True."""
        monkeypatch.setattr(settings, "goals_v2_enabled", True)

        # Spy on generate_goal_on_demand
        engine.generate_goal_on_demand = AsyncMock()

        await engine._consider_new_goal("boredom")

        # Should NOT call generate_goal_on_demand
        engine.generate_goal_on_demand.assert_not_awaited()

    async def test_consider_new_goal_idle_exploration_blocked_when_v2_on(self, engine, monkeypatch):
        """_consider_new_goal('idle_exploration') returns immediately when goals_v2_enabled is True."""
        monkeypatch.setattr(settings, "goals_v2_enabled", True)

        engine.generate_goal_on_demand = AsyncMock()

        await engine._consider_new_goal("idle_exploration")

        engine.generate_goal_on_demand.assert_not_awaited()

    async def test_consider_new_goal_curiosity_blocked_when_v2_on(self, engine, monkeypatch):
        """_consider_new_goal('curiosity') returns immediately when goals_v2_enabled is True."""
        monkeypatch.setattr(settings, "goals_v2_enabled", True)

        engine.generate_goal_on_demand = AsyncMock()

        await engine._consider_new_goal("curiosity")

        engine.generate_goal_on_demand.assert_not_awaited()

    async def test_consider_new_goal_accepted_proposal_creates_goal_when_v2_on(self, engine, monkeypatch):
        """_consider_new_goal with accepted_proposal=True still creates a goal when v2 is on."""
        monkeypatch.setattr(settings, "goals_v2_enabled", True)

        # Mock formulate_goal (called when engines are not set) to simulate goal creation
        created_goal = Goal(
            goal_id="goal:new123",
            name="New Goal",
            description="Created from proposal",
            goal_type="user_requested",
            priority=0.7,
            status="active",
            origin="accepted_proposal",
        )
        engine.formulate_goal = AsyncMock(return_value=created_goal)

        await engine._consider_new_goal("proposal", accepted_proposal=True)

        # Should call formulate_goal with the trigger
        engine.formulate_goal.assert_awaited_once()
        call_args = engine.formulate_goal.await_args
        assert call_args.args[0] == "proposal"

    async def test_consider_new_goal_works_when_v2_off(self, engine, monkeypatch):
        """_consider_new_goal works normally when goals_v2_enabled is False."""
        monkeypatch.setattr(settings, "goals_v2_enabled", False)

        engine.formulate_goal = AsyncMock()

        await engine._consider_new_goal("boredom")

        # Should call formulate_goal (since engines are not set in test fixture)
        engine.formulate_goal.assert_awaited_once()

    async def test_check_boredom_is_read_only_getter(self, engine):
        """check_boredom returns the current boredom level without side effects."""
        engine.current_boredom_level = 0.75

        boredom = await engine.check_boredom()

        assert boredom == 0.75
        # The value should be the stored level, not computed
        assert engine.current_boredom_level == 0.75


class TestCheckBoredomReadOnly:
    """Verify check_boredom is a read-only getter (input to drive gains)."""

    @pytest.fixture
    async def engine(self, monkeypatch):
        d = EmbeddedSurrealDB()
        await d.connect()
        set_clock(FakeClock(_START))
        import aura.engines.goal.engine as engine_mod
        monkeypatch.setattr(engine_mod, "get_db_client", lambda: d)
        async def _no_sleep(_):
            return None
        monkeypatch.setattr(engine_mod.asyncio, "sleep", _no_sleep)

        engine = GoalEngine.__new__(GoalEngine)
        engine.db = d
        engine._llm_layers = None
        engine._emotion_engine = None
        engine._learning_engine = None
        engine._identity_engine = None
        engine._message_bus = None
        engine.active_goals = []
        engine.current_boredom_level = 0.0
        engine.last_user_interaction = _START
        engine.last_goal_generation = _START
        engine._last_internal_interaction_update = _START
        engine.boredom_threshold = 0.6
        engine.idle_time_threshold = 300.0
        engine.logger = MagicMock()

        yield engine

        set_clock(Clock())
        await d.close()

    async def test_check_boredom_does_not_modify_state(self, engine):
        """check_boredom should not modify any engine state."""
        initial_boredom = engine.current_boredom_level
        initial_last_gen = engine.last_goal_generation
        initial_interaction = engine.last_user_interaction

        await engine.check_boredom()
        await engine.check_boredom()
        await engine.check_boredom()

        # State unchanged
        assert engine.current_boredom_level == initial_boredom
        assert engine.last_goal_generation == initial_last_gen
        assert engine.last_user_interaction == initial_interaction