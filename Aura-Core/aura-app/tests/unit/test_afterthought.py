"""P2-30: Afterthought.

Parsing and wording are tested directly. ``afterthought.run`` runs against the
embedded SurrealDB (real schema) with a fake LLM. The coordinator gate runs the
real ``_turn_pipeline`` (``turn_orchestrator`` fixture) with ``afterthought.run``
replaced. No real model calls.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from aura.api.routes import chat as chat_routes
from aura.autonomy import channel
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.orchestrator import afterthought
from aura.orchestrator.afterthought import (
    SAGE_SYSTEM,
    WRITER_SYSTEM,
    Verdict,
    compose,
    parse_verdict,
    question_key,
    topic_of,
)
from aura.tiers import LEAN, CORE, TITAN, afterthought_allowed, reset_tier_cache
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
CONV = "conversation:c1"
QUESTION = "Should I run the schema migration on the live database tonight?"
REPLY = "Yes, run it tonight; it is a small change."


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    reset_tier_cache()
    monkeypatch.setattr(settings, "tier_overrides_path", str(tmp_path / "o.json"))
    monkeypatch.setattr(settings, "afterthought_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", True)
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", False)
    monkeypatch.setattr(settings, "model_stack_index", 2)
    afterthought._in_flight.clear()
    set_clock(FakeClock(_START))
    yield
    set_clock(Clock())
    reset_tier_cache()


def _verdict(material=True, kind="correction", addendum="The migration locks the users table."):
    return json.dumps({"material": material, "kind": kind, "addendum": addendum})


class FakeLayers:
    """plain_call returns the Sage answer or the writer body, by system prompt."""

    def __init__(self, sage: str, body: str = "It locks the users table, so do it off hours.",
                 gate: asyncio.Event | None = None) -> None:
        self.sage, self.body, self.gate = sage, body, gate
        self.calls: list[dict] = []

    async def plain_call(self, model, system, user, max_tokens, temperature):
        self.calls.append({"model": model, "system": system, "user": user})
        if system == SAGE_SYSTEM:
            if self.gate is not None:
                await self.gate.wait()
            return self.sage
        return self.body

    def sage_calls(self):
        return [c for c in self.calls if c["system"] == SAGE_SYSTEM]


@pytest.fixture
async def db():
    d = EmbeddedSurrealDB()
    await d.connect()
    yield d
    await d.close()


async def _run(db, layers, *, question=QUESTION, question_turn=1, turns_now=1):
    return await afterthought.run(
        layers=layers, conversation_id=CONV, question=question,
        history=[{"role": "user", "content": "We are moving to v2."},
                 {"role": "assistant", "content": "Good plan."}],
        reply=REPLY, question_turn=question_turn, turns_now=lambda: turns_now, db=db,
    )


async def _followups(db):
    return await db.query(
        "SELECT * FROM message WHERE conversation_id = $c AND meta.afterthought != NONE",
        {"c": CONV},
    )


async def _traces(db):
    return await db.query(
        "SELECT * FROM autonomy_trace WHERE source = $s ORDER BY at", {"s": "afterthought"}
    )


# ------------------------------------------------------------------- parsing


def test_parse_material_and_not_material():
    assert parse_verdict(_verdict()) == Verdict(True, "correction", "The migration locks the users table.")
    assert parse_verdict(_verdict(False, "none", "")) == Verdict(False, "none", "")
    fenced = "```json\n" + _verdict(kind="risk") + "\n```"
    assert parse_verdict(fenced).kind == "risk"


@pytest.mark.parametrize("text", [
    None, "", "not json", "Sure! " + _verdict(), _verdict() + " hope that helps", "[1, 2]",
    json.dumps({"material": "true", "kind": "correction", "addendum": "x"}),
    json.dumps({"material": 1, "kind": "correction", "addendum": "x"}),
    json.dumps({"material": True, "kind": "typo", "addendum": "x"}),
    json.dumps({"material": True, "kind": "correction", "addendum": 3}),
    json.dumps({"material": True, "kind": "correction"}),
    json.dumps({"material": True, "kind": "correction", "addendum": "x", "why": "y"}),
    json.dumps({"material": True, "kind": "none", "addendum": "x"}),
    json.dumps({"material": True, "kind": "risk", "addendum": "   "}),
])
def test_parse_malformed_is_none(text):
    assert parse_verdict(text) is None


def test_prompts_forbid_rephrasing_and_have_no_em_dash():
    assert "Never rephrase, restate, summarise or polish the first answer" in SAGE_SYSTEM
    assert "do not repeat or rephrase your earlier answer" in WRITER_SYSTEM
    for text in (SAGE_SYSTEM, WRITER_SYSTEM, afterthought.EARLY_OPENING, afterthought.LATE_OPENING):
        assert "—" not in text and "–" not in text


def test_wording_early_and_late():
    assert compose("Body.", late=False, question=QUESTION) == "Thinking about it more: Body."
    late = compose("Body.", late=True, question=QUESTION)
    assert late.startswith("About your earlier question on Should I run the schema migration")
    assert late.endswith(": Body.")


def test_topic_is_clipped_on_a_word(monkeypatch):
    monkeypatch.setattr(settings, "afterthought_topic_max_chars", 20)
    assert topic_of("one two three four five six seven?") == "one two three four..."
    assert topic_of("short one?") == "short one"


def test_question_key_folds_case_and_space():
    assert question_key(CONV, "A  b") == question_key(CONV, " a b ")
    assert question_key(CONV, "a b") != question_key("conversation:c2", "a b")


# ---------------------------------------------------------------------- gate


def test_gate_titan_think_high_stakes_only(monkeypatch):
    assert afterthought_allowed(TITAN, "think", 0.8) is True
    assert afterthought_allowed(TITAN, "think", 0.79) is False
    assert afterthought_allowed(TITAN, "chat", 0.95) is False
    assert afterthought_allowed(TITAN, "think", None) is False
    assert afterthought_allowed(CORE, "think", 0.95) is False
    assert afterthought_allowed(LEAN, "think", 0.95) is False
    assert afterthought_allowed(None, "think", 0.95) is False
    monkeypatch.setattr(settings, "afterthought_enabled", False)
    assert afterthought_allowed(TITAN, "think", 0.95) is False
    monkeypatch.setattr(settings, "afterthought_enabled", True)
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    assert afterthought_allowed(TITAN, "think", 0.95) is False


# ----------------------------------------------------------------------- run


async def test_material_posts_one_followup(db, monkeypatch):
    monkeypatch.setattr(settings, "sage_model2", "sage/model")
    layers = FakeLayers(_verdict())
    assert await _run(db, layers) == "posted"
    rows = await _followups(db)
    assert len(rows) == 1
    msg = rows[0]
    assert msg["role"] == "assistant"
    assert msg["content"] == "Thinking about it more: It locks the users table, so do it off hours."
    assert msg["meta"]["kind"] == "correction" and msg["meta"]["late"] is False
    assert msg["timestamp"] == _START.replace(tzinfo=None).isoformat()
    sage = layers.sage_calls()
    assert len(sage) == 1 and sage[0]["model"] == "sage/model"
    assert QUESTION in sage[0]["user"] and REPLY in sage[0]["user"]
    assert "We are moving to v2." in sage[0]["user"]
    writer = [c for c in layers.calls if c["system"] == WRITER_SYSTEM]
    assert writer and "The migration locks the users table." in writer[0]["user"]
    traces = await _traces(db)
    assert [t["action"] for t in traces] == ["afterthought:posted:correction"]


async def test_not_material_posts_nothing_and_traces(db):
    layers = FakeLayers(_verdict(False, "none", "Same advice in other words."))
    assert await _run(db, layers) == "not_material"
    assert await _followups(db) == []
    assert len(layers.calls) == 1  # no writer call
    traces = await _traces(db)
    assert [t["action"] for t in traces] == ["afterthought:not_material"]
    assert "Same advice in other words." in traces[0]["why"]


async def test_malformed_is_not_material(db):
    assert await _run(db, FakeLayers("Yes, material: the table locks.")) == "malformed"
    assert await _followups(db) == []
    assert [t["action"] for t in await _traces(db)] == ["afterthought:malformed"]


async def test_never_two_sequential(db):
    layers = FakeLayers(_verdict())
    assert await _run(db, layers) == "posted"
    assert await _run(db, layers) == "duplicate"
    # The same question with other spacing and case is the same question.
    assert await _run(db, layers, question="  " + QUESTION.upper()) == "duplicate"
    assert len(await _followups(db)) == 1
    assert len(layers.sage_calls()) == 1


async def test_never_two_concurrent(db):
    gate = asyncio.Event()
    layers = FakeLayers(_verdict(), gate=gate)
    first = asyncio.create_task(_run(db, layers))
    await asyncio.sleep(0)
    second = asyncio.create_task(_run(db, layers))
    await asyncio.sleep(0)
    gate.set()
    assert sorted(await asyncio.gather(first, second)) == ["duplicate", "posted"]
    assert len(await _followups(db)) == 1


async def test_database_claim_blocks_a_second_post(db):
    # Two processes: the in-process set cannot help, the record id does.
    gate = asyncio.Event()
    layers = FakeLayers(_verdict(), gate=gate)
    first = asyncio.create_task(_run(db, layers))
    await asyncio.sleep(0)
    afterthought._in_flight.clear()
    second = asyncio.create_task(_run(db, layers))
    await asyncio.sleep(0)
    gate.set()
    assert sorted(await asyncio.gather(first, second)) == ["duplicate", "posted"]
    assert len(await _followups(db)) == 1


async def test_late_followup_wording(db):
    layers = FakeLayers(_verdict())
    assert await _run(db, layers, question_turn=2, turns_now=6) == "posted"
    msg = (await _followups(db))[0]
    assert msg["content"].startswith("About your earlier question on Should I run the schema")
    assert msg["meta"]["late"] is True


async def test_three_turns_later_is_not_late(db):
    assert await _run(db, FakeLayers(_verdict()), question_turn=2, turns_now=5) == "posted"
    assert (await _followups(db))[0]["content"].startswith("Thinking about it more: ")


async def test_writer_failure_posts_the_addendum(db):
    layers = FakeLayers(_verdict(), body="   ")
    assert await _run(db, layers) == "posted"
    msg = (await _followups(db))[0]
    assert msg["content"] == "Thinking about it more: The migration locks the users table."


async def test_sage_error_is_swallowed(db, caplog):
    layers = MagicMock()
    layers.plain_call = AsyncMock(side_effect=RuntimeError("provider down"))
    assert await _run(db, layers) == "failed"
    assert await _followups(db) == []
    assert "provider down" in caplog.text


async def test_followup_reaches_the_route_and_the_channel(db, monkeypatch):
    monkeypatch.setattr(settings, "aura_ws_aura_enabled", True)
    channel.reset()
    from aura.api import websocket

    monkeypatch.setattr(websocket.aura_manager, "broadcast", AsyncMock())
    await _run(db, FakeLayers(_verdict()))
    monkeypatch.setattr(chat_routes, "get_db_client", lambda: db)
    out = await chat_routes.get_task_reports(conversation_id=CONV)
    assert len(out["messages"]) == 1
    routed = out["messages"][0]
    assert routed["content"].startswith("Thinking about it more: ")
    pushed = channel.events_since(0)
    assert [e["type"] for e in pushed] == ["chat_message"]
    assert pushed[0]["payload"]["id"] == routed["id"]
    assert pushed[0]["payload"]["content"] == routed["content"]
    channel.reset()


# --------------------------------------------------------------- coordinator


INTENTS = {"chat": "CHAT", "think": "CHAT"}


@pytest.fixture
def orch(turn_orchestrator, monkeypatch):
    o = turn_orchestrator
    o._mp = monkeypatch
    monkeypatch.setattr(settings, "l1_routes_enabled", True)
    monkeypatch.setattr(settings, "memory_v2_write_enabled", False)
    monkeypatch.setattr(settings, "recall_feedback_enabled", False)
    monkeypatch.setattr(settings, "consult_enabled", False)
    o.llm_layers.l3_synthesis = AsyncMock(return_value="resp")
    o.tool_executor.extract_tool_calls = MagicMock(return_value=[])
    o._log_interaction_experience = AsyncMock()
    o._fake_tool_registry.select_tools = AsyncMock(return_value=[])
    o._at_run = AsyncMock(return_value="posted")
    monkeypatch.setattr(afterthought, "run", o._at_run)
    return o


async def _turn(o, route="think", stakes=0.9, *, index=2, role="owner", venue="app",
                conversation_id="c1", stream=False, message="hard question"):
    o._mp.setattr(settings, "model_stack_index", index)
    o.llm_layers.l1_classify_intent = AsyncMock(return_value={
        "intent": INTENTS[route], "route": route, "stakes": stakes, "confidence": 0.9,
    })
    if stream:
        o.llm_layers._stream_chunks_queue.append(["resp"])
    response = None
    async for ev in o._turn_pipeline(
        message, "u1", [{"role": "user", "content": "before"}], stream=stream,
        context_limit=None, conversation_id=conversation_id, session_id=None,
        context_mode="deep_work", requester_role=role, venue=venue,
    ):
        if ev.kind == "done":
            response = ev.text
    await asyncio.sleep(0)
    return response


async def test_flag_off_no_task_and_same_turn(orch, monkeypatch):
    on = await _turn(orch)
    assert orch._at_run.await_count == 1
    l3_on = orch.llm_layers.l3_synthesis.call_args
    orch._at_run.reset_mock()
    monkeypatch.setattr(settings, "afterthought_enabled", False)
    orch.__dict__.pop("_afterthought_tasks", None)
    orch.__dict__.pop("_afterthought_turns", None)
    off = await _turn(orch)
    orch._at_run.assert_not_called()
    assert "_afterthought_tasks" not in orch.__dict__
    assert "_afterthought_turns" not in orch.__dict__
    assert off == on == "resp"
    l3_off = orch.llm_layers.l3_synthesis.call_args
    assert l3_off.kwargs == l3_on.kwargs
    assert len(l3_off.args) == len(l3_on.args)


async def test_qualifying_turn_schedules_once_with_inputs(orch):
    await _turn(orch, stakes=0.8)
    orch._at_run.assert_awaited_once()
    kw = orch._at_run.await_args.kwargs
    assert kw["conversation_id"] == "c1" and kw["question"] == "hard question"
    assert kw["reply"] == "resp" and kw["history"] == [{"role": "user", "content": "before"}]
    assert kw["layers"] is orch.llm_layers
    assert kw["question_turn"] == 1 and kw["turns_now"]() == 1
    await _turn(orch, route="chat")
    await _turn(orch, route="chat")
    assert kw["turns_now"]() == 3  # later turns of the conversation are counted


async def test_streaming_turn_schedules_too(orch):
    assert await _turn(orch, stream=True) == "resp"
    orch._at_run.assert_awaited_once()


@pytest.mark.parametrize("kwargs", [
    {"route": "chat"},
    {"stakes": 0.79},
    {"index": 1},
    {"index": 0},
    {"role": "guest"},
    {"venue": "discord:general"},
    {"conversation_id": None},
])
async def test_non_qualifying_turns_schedule_nothing(orch, kwargs):
    await _turn(orch, **kwargs)
    orch._at_run.assert_not_called()


async def test_tier_profiles_off_schedules_nothing(orch, monkeypatch):
    monkeypatch.setattr(settings, "tier_profiles_enabled", False)
    await _turn(orch)
    orch._at_run.assert_not_called()


async def test_reply_is_not_delayed_by_a_slow_afterthought(orch, monkeypatch):
    never = asyncio.Event()

    async def slow(**kwargs):
        await never.wait()

    monkeypatch.setattr(afterthought, "run", slow)
    assert await asyncio.wait_for(_turn(orch), timeout=5) == "resp"
    tasks = orch.__dict__["_afterthought_tasks"]
    assert len(tasks) == 1
    for t in list(tasks):
        t.cancel()
    await asyncio.sleep(0)


async def test_afterthought_error_never_reaches_the_turn(orch, monkeypatch, caplog):
    monkeypatch.setattr(afterthought, "run", AsyncMock(side_effect=RuntimeError("boom")))
    assert await _turn(orch) == "resp"
    await asyncio.sleep(0)
    assert "Afterthought task failed: boom" in caplog.text
    assert orch.__dict__["_afterthought_tasks"] == set()
