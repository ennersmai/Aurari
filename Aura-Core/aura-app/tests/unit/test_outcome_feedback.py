"""B1-03: explicit outcome feedback and task evidence (extends G5-03). No model calls."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from aura.api.routes import chat
from aura.clock import get_clock
from aura.config import settings
from aura.engines.learning import outcomes
from aura.executor.delegation import DelegationConfig, DelegationRunner


class FakeEmbeddings:
    async def embed(self, text):
        return None


class FakeLearning:
    def __init__(self):
        self.patches = []

    async def set_experience_outcome(self, eid, outcome):
        self.patches.append((eid, outcome))

    def last(self, eid):
        return next((o for e, o in reversed(self.patches) if e == eid), None)


class FakeDb:
    def __init__(self, messages=None, experiences=None):
        self.messages = messages or {}
        self.experiences = experiences or []

    async def select(self, thing):
        return [self.messages[thing]] if thing in self.messages else []

    async def query(self, sql, vars=None):
        return [e for e in self.experiences if e["text"] == vars["text"]][:1]


@pytest.fixture(autouse=True)
def _flags(monkeypatch):
    monkeypatch.setattr(settings, "outcome_signals_enabled", True)
    monkeypatch.setattr(settings, "skills_v2_enabled", False)
    outcomes.reset_rings()
    yield
    outcomes.reset_rings()
    chat.set_orchestrator(None)


def _orch(engine):
    chat.set_orchestrator(SimpleNamespace(learning_engine=engine, db=None))


async def _turn(engine, eid, text, key="c1"):
    await outcomes.track_turn_outcome(
        engine, FakeEmbeddings(), key=key, speaker="owner", text=text, experience_id=eid
    )


async def test_explicit_down_overrides_implicit_unknown():
    engine = FakeLearning()
    await _turn(engine, "e1", "what is the capital of france")
    _orch(engine)
    out = await chat.post_outcome(chat.OutcomeRequest(experience_id="e1", signal="down"))
    assert out["signal"] == "negative"
    assert engine.last("e1") == {"signal": "negative", "success": False, "source": "explicit"}


async def test_explicit_up_overrides_implicit_negative():
    engine = FakeLearning()
    await _turn(engine, "e1", "what is the capital of france")
    await _turn(engine, "e2", "no, wrong city")  # correction marks e1 negative
    assert engine.last("e1")["signal"] == "negative"
    _orch(engine)
    await chat.post_outcome(chat.OutcomeRequest(experience_id="e1", signal="up"))
    assert engine.last("e1") == {"signal": "positive", "success": True, "source": "explicit"}


async def test_guest_gets_403_and_nothing_changes():
    engine = FakeLearning()
    _orch(engine)
    with pytest.raises(HTTPException) as exc:
        await chat.post_outcome(
            chat.OutcomeRequest(experience_id="e1", signal="up", requester_role="guest")
        )
    assert exc.value.status_code == 403
    assert engine.patches == []


async def test_message_id_resolves_to_experience(monkeypatch):
    engine = FakeLearning()
    db = FakeDb(
        messages={"message:1": {"role": "assistant", "content": "Paris", "meta": None}},
        experiences=[{"experience_id": "exp-9", "text": "Paris"}],
    )
    monkeypatch.setattr(chat, "get_db_client", lambda: db)
    _orch(engine)
    out = await chat.post_outcome(chat.OutcomeRequest(message_id="message:1", signal="up"))
    assert out["experience_id"] == "exp-9"
    db.messages["message:2"] = {"role": "assistant", "content": "x", "meta": {"experience_id": "exp-3"}}
    out = await chat.post_outcome(chat.OutcomeRequest(message_id="message:2", signal="down"))
    assert out["experience_id"] == "exp-3"
    with pytest.raises(HTTPException) as exc:
        await chat.post_outcome(chat.OutcomeRequest(message_id="message:404", signal="up"))
    assert exc.value.status_code == 404


async def test_flag_off_route_404_and_nothing_changes(monkeypatch):
    monkeypatch.setattr(settings, "outcome_signals_enabled", False)
    engine = FakeLearning()
    _orch(engine)
    with pytest.raises(HTTPException) as exc:
        await chat.post_outcome(chat.OutcomeRequest(experience_id="e1", signal="up"))
    assert exc.value.status_code == 404
    assert engine.patches == []


async def test_skill_hook_called_on_explicit(monkeypatch):
    engine = FakeLearning()
    calls = []

    async def hook(eid, signal):
        calls.append((eid, signal))

    await outcomes.apply_explicit_outcome(engine, "e1", "up", hook)
    assert calls == [("e1", "positive")]


# -- task evidence --------------------------------------------------------------


def _runner(role="owner", conv="c1", requested_at=None):
    cfg = DelegationConfig(
        goal="g", workspace="w", agent="a", success_criteria="s", tokens=1, minutes=1,
        requester_role=role, conversation_id=conv, requested_at=requested_at,
    )
    return DelegationRunner(cfg)


class FakeQueue:
    def __init__(self):
        self.db = SimpleNamespace(merge=self._merge)

    async def _merge(self, *a, **k):
        return None

    async def fail_task(self, *a, **k):
        return None


async def test_passing_delegated_task_marks_requesting_turn_positive():
    engine = FakeLearning()
    requested = get_clock().now() - timedelta(seconds=1)
    await _turn(engine, "e0", "an earlier question about bread")
    # make e0 older than the request
    outcomes._turn_log["c1"][0].at = requested - timedelta(seconds=60)
    await _turn(engine, "e1", "please refactor the parser")  # logged after the request
    await _runner(requested_at=requested)._finalize_task(
        FakeQueue(), "task:1", "succeeded", "Review passed", reviewed=True
    )
    assert engine.last("e1") == {"signal": "positive", "success": True, "source": "task"}
    assert engine.last("e0") is None


async def test_failing_or_unreviewed_task_leaves_turn_alone():
    engine = FakeLearning()
    requested = get_clock().now() - timedelta(seconds=1)
    await _turn(engine, "e1", "please refactor the parser")
    r = _runner(requested_at=requested)
    await r._finalize_task(FakeQueue(), "task:1", "failed", "Review failed: x")
    await r._finalize_task(FakeQueue(), "task:2", "succeeded", "No files changed")
    await r._finalize_task(FakeQueue(), "task:3", "needs_owner", "?")
    assert engine.patches == []


async def test_task_does_not_override_explicit_and_flag_off_is_noop(monkeypatch):
    engine = FakeLearning()
    requested = get_clock().now() - timedelta(seconds=1)
    await _turn(engine, "e1", "please refactor the parser")
    await outcomes.apply_explicit_outcome(engine, "e1", "down")
    assert await outcomes.record_task_evidence("c1", requested) is None
    assert engine.last("e1")["source"] == "explicit"
    await _turn(engine, "e2", "something else entirely")
    monkeypatch.setattr(settings, "outcome_signals_enabled", False)
    assert await outcomes.record_task_evidence("c1", requested) is None
    assert engine.last("e2") is None


async def test_guest_delegation_never_records_evidence():
    engine = FakeLearning()
    requested = get_clock().now() - timedelta(seconds=1)
    await _turn(engine, "e1", "please refactor the parser")
    await _runner(role="guest", requested_at=requested)._finalize_task(
        FakeQueue(), "task:1", "succeeded", "Review passed", reviewed=True
    )
    assert engine.patches == []
