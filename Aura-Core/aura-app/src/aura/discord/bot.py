"""
Discord Bot integration for Aura AGI.

Connects Aura to Discord as a bot, forwarding messages through the
Orchestrator's cognitive stack and streaming responses back to channels.

Architecture:
  - Runs as an async task alongside FastAPI (not blocking the event loop)
  - Holds a reference to the Orchestrator for direct process_query() calls
  - Broadcasts all I/O events to an asyncio.Queue consumed by the API routes
    and WebSocket endpoints, giving the frontend real-time visibility
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from aura.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# discord.py is an optional dependency â€“ graceful degradation if missing
#
# We use importlib to avoid Pylance static-analysis errors when discord.py
# is not installed in the current venv.  All discord-typed function
# parameters are left unannotated (documented via comments) to prevent
# "Variable not allowed in type expression" diagnostics.
# ---------------------------------------------------------------------------
try:
    _discord = importlib.import_module("discord")
    _commands = importlib.import_module("discord.ext.commands")
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    _discord: Any = None  # type: ignore[no-redef]
    _commands: Any = None  # type: ignore[no-redef]
    logger.warning(
        "discord.py not installed. Install with: pip install discord.py>=2.3.0"
    )


# =========================================================================
# Data Models
# =========================================================================


class DiscordBotStatus(str, Enum):
    """Bot lifecycle states exposed to the API / frontend."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class DiscordMessageEvent:
    """A single I/O event broadcast to the frontend."""

    event_id: str
    timestamp: str
    direction: str  # "in" (Discord â†’ Aura) or "out" (Aura â†’ Discord)
    channel_id: str
    channel_name: str
    guild_id: str
    guild_name: str
    author_id: str
    author_name: str
    content: str
    # Processing metadata
    processing_time_ms: float = 0.0
    emotional_state: dict[str, Any] = field(default_factory=dict)


# =========================================================================
# Bot Implementation
# =========================================================================


class AuraDiscordBot:
    """
    Discord bot that routes messages through Aura's cognitive stack.

    Usage::

        bot = AuraDiscordBot()
        bot.set_orchestrator(orchestrator)
        await bot.start()
        ...
        await bot.stop()
    """

    def __init__(self) -> None:
        self._status: DiscordBotStatus = DiscordBotStatus.DISCONNECTED
        self._orchestrator: Any = None
        self._bot: Any = None  # commands.Bot at runtime
        self._lock = asyncio.Lock()
        self._bot_task: asyncio.Task[Any] | None = None

        # Event broadcast queue for frontend observability
        self._event_queue: asyncio.Queue[DiscordMessageEvent] = asyncio.Queue(
            maxsize=500
        )

        # Callbacks for external listeners (API routes, WebSocket)
        self._status_listeners: list[Callable[[DiscordBotStatus], None]] = []
        self._event_listeners: list[Callable[[DiscordMessageEvent], None]] = []

        # Track allowed channels (parsed from config)
        self._allowed_channel_ids: set[str] = set()

        # Active mode: per-channel cooldown tracker (channel_id â†’ last_response_timestamp)
        self._channel_cooldowns: dict[str, float] = {}

        # Conversation history per (user_id, channel_id) for speaker diarisation
        # Key: (user_id, channel_id) â†’ list of {"role": str, "content": str}
        self._conversation_histories: dict[tuple[str, str], list[dict[str, str]]] = {}
        self._max_history_per_channel = 40  # max messages to keep per channel context

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def status(self) -> DiscordBotStatus:
        return self._status

    @property
    def bot_user(self) -> str | None:
        """Return the bot's Discord username (e.g. 'Aura#1234')."""
        if self._bot and self._bot.user:
            return str(self._bot.user)
        return None

    @property
    def bot_user_id(self) -> int | None:
        """Return the bot's Discord user ID."""
        if self._bot and self._bot.user:
            return self._bot.user.id
        return None

    @property
    def connected_guilds(self) -> list[dict[str, Any]]:
        """Return a list of guilds the bot is connected to."""
        if not self._bot or not self._bot.guilds:
            return []
        return [
            {
                "id": str(g.id),
                "name": g.name,
                "member_count": g.member_count,
            }
            for g in self._bot.guilds
        ]

    def set_orchestrator(self, orchestrator: Any) -> None:
        """Inject the Orchestrator reference (called by main.py lifespan)."""
        self._orchestrator = orchestrator

    def add_status_listener(self, cb: Callable[[DiscordBotStatus], None]) -> None:
        """Register a callback invoked on every status change."""
        self._status_listeners.append(cb)

    def remove_status_listener(self, cb: Callable[[DiscordBotStatus], None]) -> None:
        """Unregister a status callback."""
        if cb in self._status_listeners:
            self._status_listeners.remove(cb)

    def add_event_listener(self, cb: Callable[[DiscordMessageEvent], None]) -> None:
        """Register a callback invoked on every I/O event."""
        self._event_listeners.append(cb)

    def remove_event_listener(
        self, cb: Callable[[DiscordMessageEvent], None]
    ) -> None:
        """Unregister an event callback."""
        if cb in self._event_listeners:
            self._event_listeners.remove(cb)

    async def get_recent_events(self, count: int = 50) -> list[DiscordMessageEvent]:
        """Drain the event queue and return up to *count* recent events."""
        events: list[DiscordMessageEvent] = []
        while not self._event_queue.empty() and len(events) < count:
            try:
                events.append(self._event_queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return events

    async def start(self) -> bool:
        """
        Start the Discord bot.

        Returns True on success, False on failure.
        """
        if not DISCORD_AVAILABLE:
            logger.error("Cannot start Discord bot: discord.py is not installed")
            await self._set_status(DiscordBotStatus.ERROR)
            return False

        token = settings.discord_bot_token
        if not token:
            logger.error(
                "Cannot start Discord bot: AURA_DISCORD_BOT_TOKEN is not set"
            )
            await self._set_status(DiscordBotStatus.ERROR)
            return False

        async with self._lock:
            if self._status == DiscordBotStatus.CONNECTED:
                logger.warning("Discord bot is already connected")
                return True

            await self._set_status(DiscordBotStatus.CONNECTING)

            # Parse allowed channels
            raw = settings.discord_allowed_channels.strip()
            self._allowed_channel_ids = {
                cid.strip() for cid in raw.split(",") if cid.strip()
            }

            # Build the bot with command prefix
            intents = _discord.Intents.default()
            intents.message_content = True  # Required to read message content
            intents.guilds = True

            prefix = settings.discord_command_prefix
            self._bot = _commands.Bot(command_prefix=prefix, intents=intents)

            # --- Register event handlers ---
            @self._bot.event
            async def on_ready() -> None:
                logger.info(
                    f"Discord bot connected as {self._bot.user} "
                    f"({len(self._bot.guilds)} guilds)"
                )
                # Load conversation history from database
                await self._load_history_from_db()
                await self._set_status(DiscordBotStatus.CONNECTED)

            @self._bot.event
            async def on_message(message: Any) -> None:
                # Always let discord.py process commands first â€“
                # without this, !aura ping / !aura chat etc. never fire.
                await self._bot.process_commands(message)
                await self._handle_message(message)

            @self._bot.event
            async def on_disconnect() -> None:
                logger.info("Discord bot disconnected")
                await self._set_status(DiscordBotStatus.DISCONNECTED)

            # --- Register slash-like text commands ---
            @self._bot.command(name="ping")
            async def ping_cmd(ctx: Any) -> None:
                """Health check: Aura responds with latency."""
                latency_ms = (
                    round(self._bot.latency * 1000, 1) if self._bot else 0
                )
                await ctx.reply(
                    f"ðŸ“ **Aura is online!**\n"
                    f"â€¢ Latency: `{latency_ms}ms`\n"
                    f"â€¢ Engines: Emotion, Learning, Identity, Goal, Reflection, Dreaming\n"
                    f"â€¢ Status: OPERATIONAL"
                )

            @self._bot.command(name="status")
            async def status_cmd(ctx: Any) -> None:
                """Show Aura's current emotional state."""
                if self._orchestrator and self._orchestrator.emotion_engine:
                    state = (
                        await self._orchestrator.emotion_engine.get_current_state()
                    )
                    await ctx.reply(
                        f"ðŸ’­ **Aura's Emotional State**\n"
                        f"â€¢ Dominant: `{state.dominant[0]}` ({state.dominant[1]:.2f})\n"
                        f"â€¢ Volatility: `{state.volatility:.3f}`\n"
                        f"â€¢ Description: {state.description}"
                    )
                else:
                    await ctx.reply("âš ï¸ Emotional engine not available.")

            # Remove built-in help command to avoid collision
            self._bot.remove_command("help")

            @self._bot.command(name="help")
            async def help_cmd(ctx: Any) -> None:
                """Show available commands."""
                await ctx.reply(
                    "ðŸ¤– **Aura Discord Commands**\n"
                    f"`{prefix} ping` â€“ Health check\n"
                    f"`{prefix} status` â€“ Current emotional state\n"
                    f"`{prefix} chat <message>` â€“ Talk to Aura\n"
                    f"`{prefix} help` â€“ Show this message\n\n"
                    "You can also just @mention me or reply to my messages!"
                )

            @self._bot.command(name="chat")
            async def chat_cmd(
                ctx: Any,
                *, message: str,
            ) -> None:
                """Send a chat message to Aura."""
                await self._process_and_reply(ctx, message)

            # Start the bot (blocking in background task)
            try:
                self._bot_task = asyncio.create_task(
                    self._bot.start(token, reconnect=True)
                )
            except _discord.LoginFailure:
                logger.error("Discord login failed: invalid bot token")
                await self._set_status(DiscordBotStatus.ERROR)
                return False
            except Exception as exc:
                logger.error(f"Discord bot failed to start: {exc}")
                await self._set_status(DiscordBotStatus.ERROR)
                return False

        return True

    async def stop(self) -> None:
        """Gracefully shut down the Discord bot."""
        async with self._lock:
            if self._bot and self._status == DiscordBotStatus.CONNECTED:
                logger.info("Shutting down Discord bot...")
                try:
                    await self._bot.close()
                except Exception as exc:
                    logger.warning(f"Error during bot shutdown: {exc}")
                self._bot = None
            await self._set_status(DiscordBotStatus.DISCONNECTED)

    # ------------------------------------------------------------------
    # Internal Helpers
    # ------------------------------------------------------------------

    async def _set_status(self, new_status: DiscordBotStatus) -> None:
        old = self._status
        self._status = new_status
        if old != new_status:
            logger.info(
                f"Discord bot status: {old.value} â†’ {new_status.value}"
            )
            for cb in self._status_listeners:
                try:
                    cb(new_status)
                except Exception:
                    pass

    async def _handle_message(
        self,
        message,  # _discord.Message
    ) -> None:
        """
        Core message handler.

        Rules:
        1. Ignore messages from the bot itself
        2. If allowed_channels is configured, only respond in those channels
        3. Respond to @mentions of the bot
        4. Respond to replies that quote the bot
        5. Respond to command-prefixed messages
        """
        logger.debug(
            f"[Discord] Message from {message.author} "
            f"in #{getattr(message.channel, 'name', 'DM')}: "
            f"{message.content[:80]}"
        )

        # Rule 1: Never reply to self
        if message.author.bot or not self._bot or not self._bot.user:
            logger.debug(
                f"[Discord] Ignoring â€” bot={message.author.bot}, "
                f"self._bot={'ok' if self._bot else 'None'}"
            )
            return
        if message.author.id == self._bot.user.id:
            return

        # Rule 2: Channel whitelist
        if (
            self._allowed_channel_ids
            and str(message.channel.id) not in self._allowed_channel_ids
        ):
            return

        # Determine if the bot is being addressed
        is_mentioned = self._bot.user in message.mentions
        is_reply_to_bot = (
            message.reference
            and message.reference.resolved
            and hasattr(message.reference.resolved, "author")
            and message.reference.resolved.author.id == self._bot.user.id
        )
        is_command = message.content.startswith(
            settings.discord_command_prefix
        )

        # Active participation mode: respond to ALL messages in allowed
        # channels, not just @mentions, subject to a per-channel cooldown.
        is_active_participation = False
        if settings.discord_active_mode:
            channel_id_now = str(message.channel.id)
            now_ts = asyncio.get_event_loop().time()
            last = self._channel_cooldowns.get(channel_id_now, 0.0)
            if (now_ts - last) >= settings.discord_active_cooldown_seconds:
                is_active_participation = True

        if not (is_mentioned or is_reply_to_bot or is_command or is_active_participation):
            return  # Not addressed to us

        # Record cooldown time for active-mode responses
        if is_active_participation and not (is_mentioned or is_reply_to_bot or is_command):
            self._channel_cooldowns[str(message.channel.id)] = asyncio.get_event_loop().time()

        logger.info(
            f"[Discord] Processing message from {message.author} â€” "
            f"mentioned={is_mentioned}, reply={is_reply_to_bot}, "
            f"command={is_command}"
        )

        # Handle commands (already processed by discord.ext.commands, but
        # strip the prefix for plain-text commands that don't match a registered
        # command)
        ctx = await self._bot.get_context(message)
        if ctx.valid:
            return  # Let the command handler deal with it

        # For @mentions and replies, extract the actual query
        content = message.content
        if is_mentioned:
            # Strip the @mention(s) from the content
            for m in message.mentions:
                content = content.replace(f"<@{m.id}>", "").replace(
                    f"<@!{m.id}>", ""
                )
            content = content.strip()

        if not content:
            # Mention-only message â€” send a greeting
            await message.reply(
                "ðŸ‘‹ Hello! I'm **Aura**, an AGI companion.\n"
                "Just mention me with a message, reply to my messages, "
                f"or use `{settings.discord_command_prefix} chat <message>` "
                "to talk!"
            )
            return

        # Forward through the cognitive stack
        await self._process_and_reply(message, content)

    async def _process_and_reply(
        self,
        source,  # _discord.Message | _commands.Context
        content: str | None = None,
    ) -> None:
        """
        Route a user message through Aura's Orchestrator and reply.

        Supports both raw discord.Message (for @mentions) and
        discord.ext.commands.Context (for !aura chat).
        """
        if content is None:
            if hasattr(source, "command"):
                # It's a commands.Context
                content = source.message.content
                prefix = settings.discord_command_prefix
                if content.startswith(prefix):
                    content = content[len(prefix) :].strip()
                if content.lower().startswith("chat"):
                    content = content[4:].strip()
            else:
                content = source.content

        if not content:
            await self._reply(source, "â“ What would you like to talk about?")
            return

        # Prepare channel/guild metadata for UI event
        channel = source.channel
        guild = (
            channel.guild
            if hasattr(channel, "guild") and channel.guild
            else None
        )
        channel_id = str(channel.id)
        channel_name = getattr(channel, "name", "DM")
        guild_id = str(guild.id) if guild else "dm"
        guild_name = guild.name if guild else "Direct Message"
        author = source.author
        author_id = str(author.id)
        author_name = str(author)

        # Broadcast INPUT event
        t_start = asyncio.get_event_loop().time()
        in_event = DiscordMessageEvent(
            event_id=f"discord_in_{int(t_start * 1000)}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            direction="in",
            channel_id=channel_id,
            channel_name=channel_name,
            guild_id=guild_id,
            guild_name=guild_name,
            author_id=author_id,
            author_name=author_name,
            content=content,
        )
        await self._broadcast_event(in_event)

        # Show typing indicator while processing
        # Use Discord user ID for proper speaker diarisation (not display name)
        discord_user_id = f"discord_{author_id}"
        if settings.discord_stream_responses:
            try:
                async with channel.typing():
                    response_text = await self._call_orchestrator(
                        content, author_name, discord_user_id, channel_id, guild_id
                    )
            except Exception as typing_err:
                # 403 Forbidden (Missing Access) â€” bot lacks typing permission.
                # Gracefully fall back to calling orchestrator without indicator.
                logger.debug(
                    "channel.typing() failed (%s), proceeding without indicator",
                    typing_err,
                )
                response_text = await self._call_orchestrator(
                    content, author_name, discord_user_id, channel_id, guild_id
                )
        else:
            response_text = await self._call_orchestrator(
                content, author_name, discord_user_id, channel_id, guild_id
            )

        t_end = asyncio.get_event_loop().time()
        elapsed_ms = (t_end - t_start) * 1000

        # Send response (chunked for Discord's 2000-char limit)
        await self._send_chunked(source, response_text)

        # Broadcast OUTPUT event
        emotional_state: dict[str, Any] = {}
        if self._orchestrator and self._orchestrator.emotion_engine:
            try:
                state = (
                    await self._orchestrator.emotion_engine.get_current_state()
                )
                emotional_state = {
                    "dominant": state.dominant[0],
                    "intensity": state.dominant[1],
                    "description": state.description,
                    "volatility": state.volatility,
                }
            except Exception:
                pass

        out_event = DiscordMessageEvent(
            event_id=f"discord_out_{int(t_end * 1000)}",
            timestamp=datetime.now(timezone.utc).isoformat(),
            direction="out",
            channel_id=channel_id,
            channel_name=channel_name,
            guild_id=guild_id,
            guild_name=guild_name,
            author_id=author_id,
            author_name=author_name,
            content=response_text,
            processing_time_ms=round(elapsed_ms, 1),
            emotional_state=emotional_state,
        )
        await self._broadcast_event(out_event)

    async def _call_orchestrator(
        self,
        user_input: str,
        user_name: str,
        user_id: str,
        channel_id: str,
        guild_id: str,
    ) -> str:
        """Forward user input to the Orchestrator and return Aura's response.
        
        Implements speaker diarisation by:
        1. Maintaining a shared conversation history per channel
        2. Prefixing each message with the speaker's display name so the LLM
           can distinguish who said what (e.g. "Mai: sleep well bro")
        3. Using the bot's own name ("Aura") for responses
        4. Persisting messages to the database for durability
        """
        if self._orchestrator is None:
            return (
                "âš ï¸ Aura's cognitive core is not initialized yet. "
                "Please wait for the backend to fully start, "
                "or check the dashboard."
            )

        try:
            # --- Speaker diarisation: retrieve shared channel history ---
            # Key is just channel_id so all users in the channel share context
            history_key = ("channel", channel_id)
            history = self._conversation_histories.get(history_key, [])

            # Trim to max size to avoid unbounded growth
            if len(history) > self._max_history_per_channel:
                history = history[-self._max_history_per_channel:]

            # Prefix user input with speaker name for LLM clarity
            labelled_input = f"{user_name}: {user_input}"

            response = await self._orchestrator.process_query(
                user_input=labelled_input,
                user_id=user_id,
                conversation_history=history,
                deep_analysis_enabled=True,
            )
            response_text = str(response)

            # --- Append this exchange to history with speaker labels ---
            if history_key not in self._conversation_histories:
                self._conversation_histories[history_key] = []
            self._conversation_histories[history_key].append(
                {"role": "user", "content": labelled_input}
            )
            # Label Aura's response so the LLM knows Aura said it
            labelled_response = f"Aura: {response_text}"
            self._conversation_histories[history_key].append(
                {"role": "assistant", "content": labelled_response}
            )

            # --- Persist messages to database ---
            try:
                await self._persist_messages(
                    channel_id=channel_id,
                    guild_id=guild_id,
                    user_input=labelled_input,
                    response_text=response_text,
                )
            except Exception as persist_err:
                logger.warning(
                    f"Failed to persist Discord messages for channel {channel_id}: {persist_err}"
                )

            return response_text
        except Exception as exc:
            logger.error(
                f"Orchestrator processing failed: {exc}", exc_info=True
            )
            return (
                f"ðŸ’” Aura encountered an internal error processing your message.\n"
                f"```{type(exc).__name__}: {exc}```"
            )

    async def _persist_messages(
        self,
        channel_id: str,
        guild_id: str,
        user_input: str,
        response_text: str,
    ) -> None:
        """Persist Discord conversation messages to the database.
        
        Creates a conversation (or reuses existing) for the channel and
        stores both user and assistant messages so they can be fetched
        by the frontend via the /api/conversations/{id}/messages endpoint.
        """
        from datetime import datetime
        
        from aura.db.client import get_db_client
        
        db = get_db_client()
        
        # Build a unique conversation ID for this guild+channel pair
        conversation_id = f"discord:{guild_id}:{channel_id}"
        
        now = datetime.utcnow().isoformat()
        timestamp_ms = int(datetime.utcnow().timestamp() * 1000)
        
        # Create user message
        user_msg_id = f"message:{timestamp_ms}"
        await db.create(
            user_msg_id,
            {
                "conversation_id": conversation_id,
                "content": user_input,
                "role": "user",
                "timestamp": now,
                "source": "discord",
                "channel_id": channel_id,
                "guild_id": guild_id,
            },
        )
        
        # Small delay to ensure unique message IDs
        await asyncio.sleep(0.01)
        
        # Create assistant message
        aura_msg_id = f"message:{int(datetime.utcnow().timestamp() * 1000) + 1}"
        await db.create(
            aura_msg_id,
            {
                "conversation_id": conversation_id,
                "content": response_text,
                "role": "assistant",
                "timestamp": now,
                "source": "discord",
                "channel_id": channel_id,
                "guild_id": guild_id,
            },
        )
        
        # Update or create conversation metadata
        try:
            await db.query(
                """
                UPDATE $conv_id SET
                    message_count = if(matching, length(matching), 0),
                    updated_at = $now,
                    last_message_at = $now
                WHERE NONE ALL SELECT * FROM message WHERE conversation_id = $conv_id
                """,
                {"conv_id": conversation_id, "now": now},
            )
        except Exception:
            # If UPDATE fails (e.g., no matching records), try CREATE
            try:
                await db.create(
                    conversation_id,
                    {
                        "conversation_id": conversation_id,
                        "title": f"Discord #{channel_id}",
                        "user_id": guild_id,
                        "session_id": channel_id,
                        "created_at": now,
                        "updated_at": now,
                        "message_count": 2,
                        "source": "discord",
                        "channel_id": channel_id,
                        "guild_id": guild_id,
                    },
                )
            except Exception:
                # Conversation already exists, ignore
                pass
        
        logger.info(
            f"Persisted Discord messages for conv={conversation_id}: "
            f"user_msg={user_msg_id}, aura_msg={aura_msg_id}"
        )

    async def _load_history_from_db(self) -> None:
        """Load conversation history from the database into memory."""
        try:
            from aura.db.client import get_db_client
            db = get_db_client()
            result = await db.query("SELECT DISTINCT conversation_id FROM message WHERE source = 'discord' ORDER BY timestamp DESC LIMIT 50")
            conversations = set()
            for row in (r for r in result if isinstance(r, dict)):
                conv_id = row.get("conversation_id")
                if conv_id:
                    conversations.add(conv_id)
            for conv_id in conversations:
                messages = await db.query("SELECT * FROM message WHERE conversation_id = $cid ORDER BY timestamp DESC LIMIT 40", {"cid": conv_id})
                history = []
                for msg in (m for m in messages if isinstance(m, dict)):
                    role = msg.get("role", "user")
                    content_msg = msg.get("content", "")
                    history.append({"role": role, "content": content_msg})
                history.reverse()
                parts = conv_id.split(":")
                if len(parts) >= 3:
                    channel_id = parts[2]
                    history_key = ("channel", channel_id)
                    self._conversation_histories[history_key] = history
            logger.info(f"Loaded history for {len(conversations)} Discord conversations")
        except Exception as e:
            logger.warning(f"Failed to load conversation history from database: {e}")

    async def _reply(
        self,
        source,  # _discord.Message | _commands.Context
        text: str,
    ) -> None:
        """Reply to a message or context, chunking if necessary."""
        await self._send_chunked(source, text)

    async def _send_chunked(
        self,
        source,  # _discord.Message | _commands.Context
        text: str,
    ) -> None:
        """Send potentially-long text in Discord-friendly chunks."""
        max_len = settings.discord_max_message_length

        if len(text) <= max_len:
            if hasattr(source, "command"):
                await source.reply(text)
            else:
                await source.reply(text)
            return

        # Split on double-newlines first, then on sentences, then hard-split
        chunks = self._chunk_text(text, max_len)
        channel = source.channel
        for i, chunk in enumerate(chunks):
            if i == 0:
                if hasattr(source, "command"):
                    await source.reply(chunk)
                else:
                    await source.reply(chunk)
            else:
                await channel.send(chunk)
            # Small delay between chunks to avoid rate-limiting
            if i < len(chunks) - 1:
                await asyncio.sleep(0.3)

    @staticmethod
    def _chunk_text(text: str, max_len: int) -> list[str]:
        """Split text into chunks respecting markdown code blocks."""
        chunks: list[str] = []

        # Try splitting on paragraphs first
        paragraphs = text.split("\n\n")
        current = ""
        for para in paragraphs:
            if len(current) + len(para) + 2 <= max_len:
                current = (current + "\n\n" + para).strip()
            else:
                if current:
                    chunks.append(current)
                # If single paragraph is still too long, split on sentences
                if len(para) > max_len:
                    sentences = re.split(r"(?<=[.!?])\s+", para)
                    sub = ""
                    for sent in sentences:
                        if len(sub) + len(sent) + 1 <= max_len:
                            sub = (sub + " " + sent).strip()
                        else:
                            if sub:
                                chunks.append(sub)
                            # If single sentence is too long, hard split
                            if len(sent) > max_len:
                                for j in range(
                                    0, len(sent), max_len - 3
                                ):
                                    chunks.append(
                                        sent[j : j + max_len - 3] + "..."
                                    )
                            else:
                                sub = sent
                    if sub:
                        current = sub
                    else:
                        current = ""
                else:
                    current = para
        if current:
            chunks.append(current)

        return chunks if chunks else [text[:max_len]]

    async def _broadcast_event(self, event: DiscordMessageEvent) -> None:
        """Push an event to the queue and notify all listeners."""
        # Push to internal queue
        try:
            self._event_queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest event to make room
            try:
                self._event_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self._event_queue.put_nowait(event)

        # Notify registered listeners
        for cb in self._event_listeners:
            try:
                cb(event)
            except Exception:
                pass


# =========================================================================
# Global singleton (set by main.py lifespan)
# =========================================================================

bot_instance = AuraDiscordBot()
