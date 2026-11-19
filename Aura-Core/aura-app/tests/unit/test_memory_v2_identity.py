"""W3-10: venue and speaker reach the turn.

Memory PRD 4.4, M4. These tests pin the memory v2 identity helpers and the
turn seam that carries their results: ``process_query`` must put the turn's
venue and speaker on the ``TurnContext``, and the default venue is the app.

The turn tests drive the real ``Orchestrator.process_query`` through the
``turn_orchestrator`` fixture (see ``tests/conftest.py``), which wires every
engine and the LLM layers onto mocks so no database, LLM or network is
touched. They capture the context by wrapping the fixture's real
``_gather_turn_context``; the same object is then returned, and the pipeline
fills in ``speaker`` and ``venue`` on it.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.engines.memory.v2.identity import (
    speaker_key,
    venue_for_discord,
    visibility_for_venue,
    visible_in_venue,
)


async def _drain() -> None:
    """Drain the background post-response task so it does not leak."""
    for _ in range(5):
        await asyncio.sleep(0)


async def _process_query_capturing_context(orch, **kwargs):
    """Run ``process_query`` and return the ``TurnContext`` it gathered."""
    captured = {}
    original = orch._gather_turn_context

    async def _capture(*args, **inner_kwargs):
        ctx = await original(*args, **inner_kwargs)
        captured["ctx"] = ctx
        return ctx

    orch._gather_turn_context = _capture
    orch.llm_layers.l1_classify_intent = AsyncMock(return_value={"intent": "CHAT"})
    orch.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    orch.tool_executor.extract_tool_calls = MagicMock(return_value=[])

    await orch.process_query("hello", **kwargs)
    await _drain()
    return captured["ctx"]


# ---------------------------------------------------------------------------
# speaker_key
# ---------------------------------------------------------------------------
def test_speaker_key_owner_is_owner():
    assert speaker_key("discord_42", "owner") == "owner"


def test_speaker_key_guest_is_the_discord_user_id():
    assert speaker_key("discord_42", "guest") == "discord_42"


def test_speaker_key_trusted_is_the_discord_user_id():
    assert speaker_key("discord_42", "trusted") == "discord_42"


# ---------------------------------------------------------------------------
# venue_for_discord
# ---------------------------------------------------------------------------
def test_venue_for_discord_dm():
    assert venue_for_discord("dm", "chan_1", "discord_42") == "dm:discord_42"


def test_venue_for_discord_guild_channel():
    assert (
        venue_for_discord("1", "2", "discord_42")
        == "guild:1/channel:2"
    )


# ---------------------------------------------------------------------------
# visibility_for_venue
# ---------------------------------------------------------------------------
def test_visibility_for_app_is_owner():
    assert visibility_for_venue("app", "owner") == "owner"


def test_visibility_for_dm_is_private_to_its_speaker():
    assert (
        visibility_for_venue("dm:discord_42", "discord_42")
        == "private:discord_42"
    )


def test_visibility_for_owner_dm_is_private_to_owner():
    assert visibility_for_venue("dm:owner", "owner") == "private:owner"


def test_visibility_for_guild_channel_is_the_guild():
    assert (
        visibility_for_venue("guild:1/channel:2", "discord_42")
        == "guild:1"
    )


# ---------------------------------------------------------------------------
# visible_in_venue
# ---------------------------------------------------------------------------
def test_visible_in_app_is_owner():
    assert visible_in_venue("app") == ["owner"]


def test_visible_in_dm_is_private_only():
    assert visible_in_venue("dm:discord_42") == ["private:discord_42"]


def test_visible_in_owner_dm_includes_owner():
    assert visible_in_venue("dm:owner") == ["private:owner", "owner"]


def test_visible_in_guild_channel_is_the_guild():
    assert visible_in_venue("guild:1/channel:2") == ["guild:1"]


# ---------------------------------------------------------------------------
# process_query puts venue and speaker on the turn context
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_process_query_stores_guild_venue_and_guest_speaker(turn_orchestrator):
    ctx = await _process_query_capturing_context(
        turn_orchestrator,
        user_id="discord_42",
        requester_role="guest",
        venue="guild:1/channel:2",
    )

    assert ctx.venue == "guild:1/channel:2"
    assert ctx.speaker == "discord_42"


@pytest.mark.asyncio
async def test_process_query_stores_owner_speaker(turn_orchestrator):
    ctx = await _process_query_capturing_context(
        turn_orchestrator,
        user_id="discord_42",
        requester_role="owner",
        venue="dm:owner",
    )

    assert ctx.venue == "dm:owner"
    assert ctx.speaker == "owner"


@pytest.mark.asyncio
async def test_process_query_default_venue_is_app(turn_orchestrator):
    ctx = await _process_query_capturing_context(turn_orchestrator, user_id="discord_42")

    assert ctx.venue == "app"