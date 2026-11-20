"""Avatar state machine — cognitive states from pipeline events (PRD avatar 8, 11, V4).

This module implements the cognitive state machine that tracks the avatar's
internal cognitive state based on pipeline events. No model calls are made;
state transitions are driven entirely by trace events from the recall engine,
L3 reasoning, delegation, and dreaming.

The state machine builds the PRD 11 `avatar_state` payload for websocket
broadcasting.
"""

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from aura.clock import get_clock
from aura.engines.emotion.engine import EmotionEngine


class CognitiveState(str, Enum):
    """Avatar cognitive states (PRD avatar 8)."""
    ATTENDING = "attending"
    RECALLING = "recalling"
    THINKING = "thinking"
    UNSURE = "unsure"
    FOUND_IT = "found_it"
    SURPRISED = "surprised"
    WORKING = "working"
    CURIOUS = "curious"
    RESTING = "resting"
    IDLE = "idle"


class AvatarEventType(str, Enum):
    """Event types that drive state transitions."""
    MESSAGE_RECEIVED = "message_received"
    RECALL_STARTED = "recall_started"
    RECALL_FINISHED = "recall_finished"
    REASONING_STARTED = "reasoning_started"
    REASONING_FINISHED = "reasoning_finished"
    DELEGATION_RUNNING = "delegation_running"
    DREAMING = "dreaming"
    PREDICTION_ERROR = "prediction_error"


@dataclass
class AvatarEvent:
    """Event that drives the avatar state machine."""
    type: AvatarEventType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class AvatarStatePayload:
    """The PRD 11 avatar_state payload."""
    deviation: dict[str, float]
    mood: Optional[dict[str, float]]
    cognitive_state: str
    events: list[dict[str, Any]]
    speaking: bool
    gaze_target: str


class AvatarStateMachine:
    """
    Avatar state machine tracking cognitive states from pipeline events.

    States: attending, recalling, thinking, unsure, found_it, surprised,
            working, curious, resting, idle

    Events: message_received, recall_started, recall_finished(abstain, strong),
            reasoning_started, reasoning_finished, delegation_running(bool),
            dreaming(bool), prediction_error(size)

    Broadcasts `avatar_state` on change at most 10 times/second (100ms coalesce).
    """

    # Rate limiting: at most 10 broadcasts per second (100ms minimum interval)
    MIN_BROADCAST_INTERVAL = 0.1  # seconds

    def __init__(
        self,
        emotion_engine: EmotionEngine,
        broadcast_func: Callable[[dict[str, Any]], Any],
    ) -> None:
        """
        Initialize the avatar state machine.

        Args:
            emotion_engine: The emotion engine to get deviation from.
            broadcast_func: Async function to broadcast avatar_state messages.
        """
        self._emotion_engine = emotion_engine
        self._broadcast_func = broadcast_func

        # Current state
        self._state: CognitiveState = CognitiveState.IDLE
        self._events: list[dict[str, Any]] = []

        # Rate limiting
        self._last_broadcast_time: float = 0.0
        self._pending_broadcast: Optional[AvatarStatePayload] = None
        self._broadcast_task: Optional[asyncio.Task] = None

        # State tracking
        self._is_recalling: bool = False
        self._is_reasoning: bool = False
        self._is_delegating: bool = False
        self._is_dreaming: bool = False

    @property
    def state(self) -> CognitiveState:
        """Current cognitive state."""
        return self._state

    @property
    def events(self) -> list[dict[str, Any]]:
        """Current event list for the payload."""
        return self._events

    def _transition(self, new_state: CognitiveState) -> None:
        """Transition to a new state and schedule a broadcast."""
        if new_state != self._state:
            self._state = new_state
            self._schedule_broadcast()

    def _schedule_broadcast(self) -> None:
        """Schedule a broadcast respecting the 100ms rate limit."""
        now = time.monotonic()
        time_since_last = now - self._last_broadcast_time

        if time_since_last >= self.MIN_BROADCAST_INTERVAL:
            # Can broadcast immediately
            self._do_broadcast()
        else:
            # Schedule for later
            if self._broadcast_task is not None:
                self._broadcast_task.cancel()
            delay = self.MIN_BROADCAST_INTERVAL - time_since_last
            self._broadcast_task = asyncio.create_task(self._delayed_broadcast(delay))

    async def _delayed_broadcast(self, delay: float) -> None:
        """Broadcast after a delay."""
        await asyncio.sleep(delay)
        self._do_broadcast()

    def _do_broadcast(self) -> None:
        """Execute the broadcast."""
        self._last_broadcast_time = time.monotonic()
        payload = self._build_payload()
        if self._broadcast_func is not None:
            # Convert dataclass to dict for JSON serialization
            payload_dict = {
                "deviation": payload.deviation,
                "mood": payload.mood,
                "cognitive_state": payload.cognitive_state,
                "events": payload.events,
                "speaking": payload.speaking,
                "gaze_target": payload.gaze_target,
            }
            asyncio.create_task(self._broadcast_func(payload_dict))

    def _build_payload(self) -> AvatarStatePayload:
        """Build the PRD 11 avatar_state payload."""
        # Get deviation from emotion engine's current state
        # Note: we can't await here, so we use a synchronous approach
        # The emotion engine's current_vector has the current state
        current_vector = self._emotion_engine.current_vector
        baseline = self._emotion_engine.config.baseline

        current_dict = current_vector.model_dump()
        baseline_dict = baseline.model_dump()
        deviation = {
            emotion: current_dict.get(emotion, 0.0) - baseline_dict.get(emotion, 0.0)
            for emotion in current_dict
        }

        # Clear events after including them in payload
        events = self._events.copy()
        self._events.clear()

        return AvatarStatePayload(
            deviation=deviation,
            mood=None,  # Always null until E4
            cognitive_state=self._state.value,
            events=events,
            speaking=False,  # Not implemented yet
            gaze_target="camera",  # Default
        )

    # Event handlers
    def message_received(self) -> None:
        """Handle incoming user message."""
        self._events.append({"type": "message_received"})
        self._transition(CognitiveState.ATTENDING)

    def recall_started(self) -> None:
        """Handle recall engine start."""
        self._events.append({"type": "recall_started"})
        self._is_recalling = True
        self._transition(CognitiveState.RECALLING)

    def recall_finished(self, abstain: bool = False, strong: bool = False) -> None:
        """Handle recall engine finish."""
        self._events.append({
            "type": "recall_finished",
            "abstain": abstain,
            "strong": strong,
        })
        self._is_recalling = False

        if abstain:
            self._transition(CognitiveState.UNSURE)
        elif strong:
            self._transition(CognitiveState.FOUND_IT)
        elif self._is_reasoning:
            self._transition(CognitiveState.THINKING)
        else:
            self._transition(CognitiveState.ATTENDING)

    def reasoning_started(self) -> None:
        """Handle L3 reasoning start."""
        self._events.append({"type": "reasoning_started"})
        self._is_reasoning = True
        if self._is_recalling:
            # If we're still recalling, stay in recalling
            pass
        else:
            self._transition(CognitiveState.THINKING)

    def reasoning_finished(self) -> None:
        """Handle L3 reasoning finish."""
        self._events.append({"type": "reasoning_finished"})
        self._is_reasoning = False

        if self._is_recalling:
            self._transition(CognitiveState.RECALLING)
        else:
            self._transition(CognitiveState.ATTENDING)

    def delegation_running(self, running: bool) -> None:
        """Handle delegation start/stop."""
        self._events.append({
            "type": "delegation_running",
            "running": running,
        })
        self._is_delegating = running
        if running:
            self._transition(CognitiveState.WORKING)
        elif self._is_reasoning:
            self._transition(CognitiveState.THINKING)
        elif self._is_recalling:
            self._transition(CognitiveState.RECALLING)
        else:
            self._transition(CognitiveState.ATTENDING)

    def dreaming(self, active: bool) -> None:
        """Handle dreaming start/stop."""
        self._events.append({
            "type": "dreaming",
            "active": active,
        })
        self._is_dreaming = active
        if active:
            self._transition(CognitiveState.RESTING)
        else:
            self._transition(CognitiveState.IDLE)

    def prediction_error(self, size: float) -> None:
        """Handle prediction error (surprise)."""
        self._events.append({
            "type": "prediction_error",
            "size": size,
        })
        if size > 0.5:
            self._transition(CognitiveState.SURPRISED)
        elif self._is_reasoning:
            self._transition(CognitiveState.THINKING)
        elif self._is_recalling:
            self._transition(CognitiveState.RECALLING)
        else:
            self._transition(CognitiveState.CURIOUS)

    async def shutdown(self) -> None:
        """Clean up any pending broadcast task."""
        if self._broadcast_task is not None:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass