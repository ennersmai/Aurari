"""
Discord Bot API Routes.

Provides REST endpoints + WebSocket for controlling and observing
the Discord bot integration from the Aura frontend.

Endpoints:
  GET  /discord/status              â€“ Bot status, connected guilds
  POST /discord/connect             â€“ Start the Discord bot
  POST /discord/disconnect          â€“ Stop the Discord bot
  GET  /discord/events              â€“ Fetch recent I/O events
  GET  /discord/events/stats        â€“ Fetch event statistics
  GET  /discord/channels            â€“ Fetch channel-level stats
  POST /discord/channel/mute        â€“ Mute/unmute a channel
  POST /discord/channel/unmute      â€“ Unmute a channel
  GET  /discord/channel/rules       â€“ Fetch response rules per channel
  POST /discord/channel/rules       â€“ Update response rules
  GET  /discord/context             â€“ Fetch conversation context (recent messages)
  WS   /discord/stream              â€“ Real-time event stream
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field

from aura.config import settings
from aura.discord.bot import DiscordBotStatus, DiscordMessageEvent

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/discord", tags=["discord"])

# Global bot reference (set by main.py)
_bot: Any = None


def set_bot(bot: Any) -> None:
    """Inject the AuraDiscordBot singleton."""
    global _bot
    _bot = bot


def get_bot() -> Any:
    """Get bot or raise."""
    if _bot is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Discord bot not initialized",
        )
    return _bot


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------

class DiscordStatusResponse(BaseModel):
    """Status response for GET /discord/status."""
    status: str
    bot_user: str | None = None
    bot_user_id: int | None = None
    connected_guilds: list[dict[str, Any]] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)


class DiscordConnectRequest(BaseModel):
    """Request body for POST /discord/connect."""
    pass


class DiscordCommandRequest(BaseModel):
    """Request body for POST /discord/command (optional future use)."""
    command: str = Field(..., description="Bot command to execute")


class DiscordEventResponse(BaseModel):
    """Paginated response for GET /discord/events."""
    events: list[dict[str, Any]]
    count: int


class ChannelStats(BaseModel):
    """Per-channel statistics."""
    channel_id: str
    channel_name: str
    guild_id: str
    guild_name: str
    total_incoming: int = 0
    total_outgoing: int = 0
    avg_response_time_ms: float = 0.0
    last_activity: str | None = None
    is_muted: bool = False
    response_rules: dict[str, Any] = Field(default_factory=dict)


class EventStatsResponse(BaseModel):
    """Response for GET /discord/events/stats."""
    total_events: int
    incoming_count: int
    outgoing_count: int
    avg_response_time_ms: float
    top_channels: list[dict[str, Any]]
    top_users: list[dict[str, Any]]
    events_per_hour: list[dict[str, Any]]


class ChannelRulesUpdate(BaseModel):
    """Request body for updating channel response rules."""
    channel_id: str
    enabled: bool = True
    min_response_confidence: float = 0.5
    allowed_emotions: list[str] = Field(default_factory=list)
    response_template: str | None = None
    cooldown_seconds: int = 30


class ContextMessage(BaseModel):
    """A message in the conversation context."""
    event_id: str
    timestamp: str
    direction: str
    author_name: str
    author_id: str
    content: str
    channel_name: str
    guild_name: str


class ContextResponse(BaseModel):
    """Response for GET /discord/context."""
    channel_id: str
    channel_name: str
    guild_name: str
    messages: list[ContextMessage]
    total_count: int


# ---------------------------------------------------------------------------
# In-memory state (for per-channel rules and mute status)
# ---------------------------------------------------------------------------

# { channel_id: { "muted": bool, "rules": {...} } }
_channel_state: dict[str, dict[str, Any]] = defaultdict(lambda: {
    "muted": False,
    "rules": {
        "enabled": True,
        "min_response_confidence": 0.5,
        "allowed_emotions": [],
        "response_template": None,
        "cooldown_seconds": 30,
    },
})

# Track last response time per channel for cooldown
_last_response: dict[str, float] = {}


# ---------------------------------------------------------------------------
# REST Endpoints
# ---------------------------------------------------------------------------

@router.get("/status", response_model=DiscordStatusResponse)
async def get_discord_status() -> DiscordStatusResponse:
    """Get the current Discord bot status, guilds, and config."""
    bot = get_bot()

    allowed = settings.discord_allowed_channels.strip()
    allowed_list = [cid.strip() for cid in allowed.split(",") if cid.strip()]

    return DiscordStatusResponse(
        status=bot.status.value,
        bot_user=bot.bot_user,
        bot_user_id=bot.bot_user_id,
        connected_guilds=bot.connected_guilds,
        config={
            "enabled": settings.discord_enabled,
            "command_prefix": settings.discord_command_prefix,
            "allowed_channels": allowed_list,
            "max_message_length": settings.discord_max_message_length,
            "stream_responses": settings.discord_stream_responses,
            "active_mode": settings.discord_active_mode,
            "active_cooldown_seconds": settings.discord_active_cooldown_seconds,
        },
    )


@router.post("/connect")
async def connect_discord() -> dict[str, Any]:
    """Start the Discord bot connection."""
    bot = get_bot()

    if bot.status == DiscordBotStatus.CONNECTED:
        return {"status": "ok", "message": "Bot is already connected"}

    success = await bot.start()
    if success:
        return {"status": "ok", "message": f"Bot connecting as {bot.bot_user}"}
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start Discord bot. Check AURA_DISCORD_BOT_TOKEN and logs.",
        )


@router.post("/disconnect")
async def disconnect_discord() -> dict[str, Any]:
    """Stop the Discord bot connection."""
    bot = get_bot()

    if bot.status == DiscordBotStatus.DISCONNECTED:
        return {"status": "ok", "message": "Bot is already disconnected"}

    await bot.stop()
    return {"status": "ok", "message": "Bot disconnected"}


@router.get("/events", response_model=DiscordEventResponse)
async def get_discord_events(count: int = 50) -> DiscordEventResponse:
    """
    Get recent Discord I/O events.

    Args:
        count: Maximum number of events to return (default 50, max 200)
    """
    bot = get_bot()
    count = min(count, 200)
    events = await bot.get_recent_events(count)

    event_dicts = [
        {
            "event_id": e.event_id,
            "timestamp": e.timestamp,
            "direction": e.direction,
            "channel_id": e.channel_id,
            "channel_name": e.channel_name,
            "guild_id": e.guild_id,
            "guild_name": e.guild_name,
            "author_id": e.author_id,
            "author_name": e.author_name,
            "content": e.content[:500] + ("..." if len(e.content) > 500 else ""),
            "processing_time_ms": e.processing_time_ms,
            "emotional_state": e.emotional_state,
        }
        for e in events
    ]

    return DiscordEventResponse(events=event_dicts, count=len(event_dicts))


@router.get("/events/stats")
async def get_event_stats() -> dict[str, Any]:
    """
    Get aggregated statistics about Discord events.
    
    Returns:
        - total_events: Total number of events
        - incoming_count / outgoing_count: Direction breakdown
        - avg_response_time_ms: Average processing time
        - top_channels: Most active channels
        - top_users: Most active users
        - events_per_hour: Hourly distribution
    """
    bot = get_bot()
    events = await bot.get_recent_events(500)

    total = len(events)
    incoming = sum(1 for e in events if e.direction == "in")
    outgoing = sum(1 for e in events if e.direction == "out")
    
    response_times = [e.processing_time_ms for e in events if e.processing_time_ms > 0]
    avg_response = sum(response_times) / len(response_times) if response_times else 0.0

    # Top channels
    channel_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "name": "", "guild": ""})
    for e in events:
        key = e.channel_id
        channel_stats[key]["count"] += 1
        channel_stats[key]["name"] = e.channel_name
        channel_stats[key]["guild"] = e.guild_name
    
    top_channels = sorted(
        [{"channel_id": k, **v} for k, v in channel_stats.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    # Top users
    user_stats: dict[str, dict] = defaultdict(lambda: {"count": 0, "name": ""})
    for e in events:
        key = e.author_id
        user_stats[key]["count"] += 1
        user_stats[key]["name"] = e.author_name
    
    top_users = sorted(
        [{"user_id": k, **v} for k, v in user_stats.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:10]

    # Events per hour
    hourly: dict[str, int] = defaultdict(int)
    for e in events:
        try:
            dt = datetime.fromisoformat(e.timestamp)
            hour_key = dt.strftime("%Y-%m-%d %H:00")
            hourly[hour_key] += 1
        except Exception:
            pass
    
    events_per_hour = [
        {"hour": k, "count": v}
        for k, v in sorted(hourly.items(), key=lambda x: x[0], reverse=True)[:24]
    ]

    return {
        "total_events": total,
        "incoming_count": incoming,
        "outgoing_count": outgoing,
        "avg_response_time_ms": round(avg_response, 2),
        "top_channels": top_channels,
        "top_users": top_users,
        "events_per_hour": events_per_hour,
    }


@router.get("/channels")
async def get_channel_info() -> list[dict[str, Any]]:
    """
    Get detailed information about all channels the bot can see.
    
    Returns per-channel stats including mute status and response rules.
    """
    bot = get_bot()
    events = await bot.get_recent_events(1000)

    # Aggregate per-channel stats
    channel_data: dict[str, dict] = {}
    
    for e in events:
        cid = e.channel_id
        if cid not in channel_data:
            channel_data[cid] = {
                "channel_id": cid,
                "channel_name": e.channel_name,
                "guild_id": e.guild_id,
                "guild_name": e.guild_name,
                "incoming": 0,
                "outgoing": 0,
                "response_times": [],
                "last_activity": e.timestamp,
                "unique_users": set(),
            }
        
        entry = channel_data[cid]
        if e.direction == "in":
            entry["incoming"] += 1
            entry["unique_users"].add(e.author_id)
        else:
            entry["outgoing"] += 1
        
        if e.processing_time_ms > 0:
            entry["response_times"].append(e.processing_time_ms)
        
        # Update last activity
        if e.timestamp > entry["last_activity"]:
            entry["last_activity"] = e.timestamp

    # Build response
    result = []
    for cid, data in channel_data.items():
        rts = data["response_times"]
        avg_rt = sum(rts) / len(rts) if rts else 0.0
        
        state = _channel_state.get(cid, {"muted": False, "rules": {}})
        
        result.append({
            "channel_id": cid,
            "channel_name": data["channel_name"],
            "guild_id": data["guild_id"],
            "guild_name": data["guild_name"],
            "total_messages": data["incoming"] + data["outgoing"],
            "incoming_count": data["incoming"],
            "outgoing_count": data["outgoing"],
            "avg_response_time_ms": round(avg_rt, 2),
            "last_activity": data["last_activity"],
            "unique_users": len(data["unique_users"]),
            "is_muted": state["muted"],
            "response_rules": state["rules"],
        })

    # Sort by total messages descending
    result.sort(key=lambda x: x["total_messages"], reverse=True)
    
    return result


@router.post("/channel/mute")
async def mute_channel(request: dict[str, Any]) -> dict[str, Any]:
    """Mute a channel (Aura will not respond to messages)."""
    channel_id = request.get("channel_id")
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required")
    
    _channel_state[channel_id]["muted"] = True
    logger.info(f"Channel {channel_id} muted")
    
    return {"status": "ok", "message": f"Channel {channel_id} muted"}


@router.post("/channel/unmute")
async def unmute_channel(request: dict[str, Any]) -> dict[str, Any]:
    """Unmute a channel (Aura will respond to messages again)."""
    channel_id = request.get("channel_id")
    if not channel_id:
        raise HTTPException(status_code=400, detail="channel_id is required")
    
    _channel_state[channel_id]["muted"] = False
    logger.info(f"Channel {channel_id} unmuted")
    
    return {"status": "ok", "message": f"Channel {channel_id} unmuted"}


@router.get("/channel/rules")
async def get_channel_rules(channel_id: str | None = None) -> Any:
    """
    Get response rules for channels.
    
    Args:
        channel_id: Optional. If provided, return rules for that channel only.
    """
    if channel_id:
        state = _channel_state.get(channel_id, {"muted": False, "rules": {}})
        return {
            "channel_id": channel_id,
            "is_muted": state["muted"],
            "rules": state["rules"],
        }
    
    # Return all channel rules
    all_rules = {}
    for cid, state in _channel_state.items():
        all_rules[cid] = {
            "is_muted": state["muted"],
            "rules": state["rules"],
        }
    
    return all_rules


@router.post("/channel/rules")
async def update_channel_rules(request: ChannelRulesUpdate) -> dict[str, Any]:
    """
    Update response rules for a specific channel.
    """
    channel_id = request.channel_id
    
    _channel_state[channel_id]["rules"] = {
        "enabled": request.enabled,
        "min_response_confidence": request.min_response_confidence,
        "allowed_emotions": request.allowed_emotions,
        "response_template": request.response_template,
        "cooldown_seconds": request.cooldown_seconds,
    }
    
    # Also unmute if enabling rules
    if request.enabled:
        _channel_state[channel_id]["muted"] = False
    
    logger.info(f"Updated rules for channel {channel_id}")
    
    return {"status": "ok", "message": f"Rules updated for channel {channel_id}"}


@router.get("/context")
async def get_discord_context(
    channel_id: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """
    Get conversation context from Discord.
    
    This returns the recent messages that Aura has seen, grouped by channel.
    Useful for understanding what context Aura has about ongoing conversations.
    
    Args:
        channel_id: Optional. Filter to a specific channel.
        limit: Maximum number of messages to return (default 50, max 200).
    """
    bot = get_bot()
    count = min(limit, 200)
    events = await bot.get_recent_events(count)
    
    # Filter by channel if specified
    if channel_id:
        events = [e for e in events if e.channel_id == channel_id]
    
    # Build context messages
    messages = []
    for e in events:
        messages.append(ContextMessage(
            event_id=e.event_id,
            timestamp=e.timestamp,
            direction=e.direction,
            author_name=e.author_name,
            author_id=e.author_id,
            content=e.content,
            channel_name=e.channel_name,
            guild_name=e.guild_name,
        ))
    
    # Group by channel
    channel_groups: dict[str, dict] = {}
    for msg in messages:
        key = msg.channel_id
        if key not in channel_groups:
            channel_groups[key] = {
                "channel_id": key,
                "channel_name": msg.channel_name,
                "guild_name": msg.guild_name,
                "messages": [],
            }
        channel_groups[key]["messages"].append(msg)
    
    return {
        "total_messages": len(messages),
        "channels": list(channel_groups.values()),
    }

# ---------------------------------------------------------------------------
# Database-backed Conversation Endpoints
# ---------------------------------------------------------------------------

@router.get("/conversations/{conversation_id}/messages")
async def get_discord_conversation_messages(conversation_id: str) -> list[dict[str, Any]]:
    """Get persisted messages for a Discord conversation from the database."""
    from aura.db.client import get_db_client
    db = get_db_client()
    result = await db.query("SELECT * FROM message WHERE conversation_id = $conv_id ORDER BY timestamp ASC", {"conv_id": conversation_id})
    messages = []
    for msg in (m for m in result if isinstance(m, dict)):
        msg_id = msg.get("id", "")
        if hasattr(msg_id, "__str__") and not isinstance(msg_id, str): msg_id = str(msg_id)
        messages.append({"id": msg_id, "conversation_id": msg.get("conversation_id", conversation_id), "content": msg.get("content", ""), "role": msg.get("role", "user"), "timestamp": msg.get("timestamp", ""), "source": msg.get("source", "discord"), "channel_id": msg.get("channel_id", ""), "guild_id": msg.get("guild_id", "")})
    return messages

@router.get("/conversations")
async def get_discord_conversations() -> list[dict[str, Any]]:
    """Get all Discord conversations from the database."""
    from aura.db.client import get_db_client
    db = get_db_client()
    result = await db.query("SELECT DISTINCT conversation_id FROM message WHERE source = 'discord' ORDER BY timestamp DESC")
    conversations = []
    seen = set()
    for row in (r for r in result if isinstance(r, dict)):
        conv_id = row.get("conversation_id")
        if conv_id and conv_id not in seen:
            seen.add(conv_id)
            parts = conv_id.split(":")
            if len(parts) >= 3: guild_id, channel_id = parts[1], parts[2]
            else: guild_id, channel_id = "unknown", conv_id
            count_result = await db.query("SELECT count(*) as cnt FROM message WHERE conversation_id = $cid", {"cid": conv_id})
            msg_count = 0
            for cr in (c for c in count_result if isinstance(c, dict)): msg_count = cr.get("cnt", 0)
            conversations.append({"conversation_id": conv_id, "guild_id": guild_id, "channel_id": channel_id, "message_count": msg_count, "created_at": None, "updated_at": None})
    return conversations


# ---------------------------------------------------------------------------
# WebSocket â€“ Real-time Event Stream
# ---------------------------------------------------------------------------

@router.websocket("/stream")
async def discord_event_stream(websocket: WebSocket) -> None:
    """
    WebSocket endpoint streaming Discord I/O events in real time.

    Connect: ws://127.0.0.1:8080/discord/stream

    Event schema:
      { "type": "discord_event" | "status_change",
        "data": { ... } }
    """
    bot = get_bot()
    await websocket.accept()

    event_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    # Listener callbacks
    def on_event(event: DiscordMessageEvent) -> None:
        payload = {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "direction": event.direction,
            "channel_name": event.channel_name,
            "guild_name": event.guild_name,
            "author_name": event.author_name,
            "content": event.content[:500] + ("..." if len(event.content) > 500 else ""),
            "processing_time_ms": event.processing_time_ms,
            "emotional_state": event.emotional_state,
        }
        try:
            event_queue.put_nowait(
                {"type": "discord_event", "data": payload}
            )
        except asyncio.QueueFull:
            pass

    def on_status(new_status: DiscordBotStatus) -> None:
        try:
            event_queue.put_nowait(
                {"type": "status_change", "data": {"status": new_status.value}}
            )
        except asyncio.QueueFull:
            pass

    bot.add_event_listener(on_event)
    bot.add_status_listener(on_status)

    # Send initial status
    await websocket.send_json({
        "type": "status_change",
        "data": {"status": bot.status.value},
    })

    try:
        while True:
            try:
                msg = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                await websocket.send_json(msg)
            except asyncio.TimeoutError:
                # Heartbeat
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning(f"Discord WebSocket error: {exc}")
    finally:
        bot.remove_event_listener(on_event)
        bot.remove_status_listener(on_status)
        logger.info("Discord WebSocket client disconnected")
