"""Discord bot integration for Aura AGI.

Provides a Discord bot that forwards messages to the Aura orchestrator
and sends responses back, with full UI observability via event broadcasting.
"""

from aura.discord.bot import AuraDiscordBot, DiscordBotStatus, bot_instance

__all__ = ["AuraDiscordBot", "DiscordBotStatus", "bot_instance"]
