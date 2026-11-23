"""Owner event channel for the app (B1-04, PRD 8.4).

``publish`` builds an envelope ``{"v": 1, "seq": n, "type", "at", "payload"}``,
keeps it in a bounded ring buffer and pushes it to every ``/ws/aura``
connection. ``seq`` is a monotone integer per process. Events go to the owner's
app connection only; nothing here talks to Discord.

``chat_message`` payloads are exactly the message dicts of
``GET /chat/task-reports`` (``id``, ``conversationId``, ``content``, ``role``,
``timestamp``, ``meta``), so task reports can later publish instead of being
polled.

The flag ``aura_ws_aura_enabled`` off makes ``publish`` a no-op that still
returns the envelope (not buffered, not sent, no seq consumed).
"""

import collections
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from aura.clock import get_clock
from aura.config import settings

logger = logging.getLogger(__name__)

EVENT_TYPES = frozenset(
    {"aura_message", "agenda_update", "drive_state", "chat_message", "autonomy_state", "ping"}
)


@dataclass
class PresenceState:
    """What the app last told us about the owner (for B5; nothing else is read)."""

    typing: bool = False
    active_view: str | None = None
    last_interaction_at: datetime | None = None


presence = PresenceState()

_seq = 0
_buffer: collections.deque[dict[str, Any]] = collections.deque(maxlen=settings.aura_channel_buffer)


def reset() -> None:
    """Clear seq, buffer and presence (tests). Re-reads the buffer size setting."""
    global _seq, _buffer, presence
    _seq = 0
    _buffer = collections.deque(maxlen=settings.aura_channel_buffer)
    presence = PresenceState()


def last_seq() -> int:
    return _seq


def _envelope(seq: int, event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "v": 1,
        "seq": seq,
        "type": event_type,
        "at": get_clock().now().isoformat(),
        "payload": payload,
    }


def ping_envelope() -> dict[str, Any]:
    """A ping for one client. Does not consume a seq and is never buffered."""
    return _envelope(_seq, "ping", {})


def events_since(since_seq: int = 0) -> list[dict[str, Any]]:
    """Buffered events with seq greater than ``since_seq``, oldest first."""
    return [e for e in _buffer if e["seq"] > since_seq]


async def publish(
    event_type: str, payload: dict[str, Any] | None = None, *, persist: bool = True
) -> dict[str, Any]:
    """Build, buffer (when ``persist``) and broadcast an event; return the envelope."""
    global _seq
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown channel event type: {event_type}")
    body = dict(payload or {})
    if not settings.aura_ws_aura_enabled:
        return _envelope(_seq, event_type, body)
    _seq += 1  # single-threaded event loop: no await between read and write
    envelope = _envelope(_seq, event_type, body)
    if persist:
        _buffer.append(envelope)
    from aura.api.websocket import aura_manager

    await aura_manager.broadcast(envelope)
    return envelope


def update_presence(data: dict[str, Any]) -> None:
    """Store the known presence fields from a client message."""
    if isinstance(data.get("typing"), bool):
        presence.typing = data["typing"]
    view = data.get("active_view")
    if view is None or isinstance(view, str):
        if "active_view" in data:
            presence.active_view = view[:100] if view else None
    presence.last_interaction_at = get_clock().now()
