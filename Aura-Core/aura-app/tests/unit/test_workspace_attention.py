"""B2-03: the attention step (embedded SurrealDB, FakeClock)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.autonomy import controls, drives, registry
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.models.messages import MessageType
from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
from aura.orchestrator.message_bus import MessageBus
from aura.orchestrator.workspace import Budget, Workspace
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
BIG = Budget(tokens=100000, seconds=10000.0, allow_risk=True)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    drives.reset_cache()
    controls.reset_cache()
    registry.reset()
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "drives_enabled", False)
    await controls.set_level("open", db=d)
    d.clock = clock
    yield d
    drives.reset_cache()
    controls.reset_cache()
    registry.reset()
    set_clock(Clock())
    await d.close()


def _p(kind=ProposalKind.INVESTIGATE, ref="r1", urgency=0.5, value=0.5, cost=None, source="t"):
    return Proposal(source=source, kind=kind, summary="s", refs=[ref], urgency=urgency,
                    value=value, cost=cost or Cost(tokens=100, seconds=1.0))


async def _trace(db):
    return extract_rows(await db.query("SELECT * FROM autonomy_trace"))


async def test_user_message_preempts_best_proposal(db):
    ws = Workspace()
    ws.post(_p(urgency=1.0, value=1.0))
    called = []
    registry.add_interrupt_callback(lambda: called.append(1))
    ws.note_user_message()
    assert await ws.attend(db.clock.now(), BIG, db=db) is None
    assert called == [1]
    assert any(r["action"] == "attend:preempt" for r in await _trace(db))
    ws.clear_user_message()
    assert await ws.attend(db.clock.now(), BIG, db=db) is not None


async def test_highest_score_wins_and_is_traced(db):
    ws = Workspace()
    ws.post(_p(ref="low", urgency=0.2))
    ws.post(_p(ref="high", urgency=0.9))
    w = await ws.attend(db.clock.now(), BIG, db=db)
    assert w.proposal.refs == ["high"]
    rows = await _trace(db)
    win = [r for r in rows if r["action"].startswith("attend:winner")]
    assert len(win) == 1 and win[0]["refs"] == ["high"] and win[0]["cost"]["tokens"] == 100


async def test_tie_breaks_by_created_at(db):
    ws = Workspace()
    first = _p(ref="a")
    db.clock.advance(5)
    second = _p(ref="b")
    ws.post(second)
    ws.post(first)
    w = await ws.attend(db.clock.now(), BIG, db=db)
    assert w.proposal.refs == ["a"]


async def test_over_budget_rejected_and_logged(db):
    ws = Workspace()
    ws.post(_p(ref="pricey", urgency=1.0, value=1.0, cost=Cost(tokens=5000, seconds=1.0)))
    ws.post(_p(ref="cheap", urgency=0.1, value=0.1))
    w = await ws.attend(db.clock.now(), Budget(tokens=1000, seconds=60.0), db=db)
    assert w.proposal.refs == ["cheap"]
    rej = [r for r in await _trace(db) if r["action"].startswith("attend:reject")]
    assert len(rej) == 1 and rej[0]["why"] == "over_budget" and rej[0]["cost"]["tokens"] == 5000


async def test_risk_needs_allow_risk(db):
    ws = Workspace()
    ws.post(_p(cost=Cost(tokens=1, seconds=1.0, risk=RiskLevel.SEND)))
    assert await ws.attend(db.clock.now(), Budget(tokens=10, seconds=10.0), db=db) is None
    assert any(r["why"] == "risk_not_allowed" for r in await _trace(db))


async def test_respond_never_autonomous(db):
    ws = Workspace()
    ws.post(_p(kind=ProposalKind.RESPOND))
    assert await ws.attend(db.clock.now(), BIG, db=db) is None
    assert any(r["why"] == "respond_never_autonomous" for r in await _trace(db))


@pytest.mark.parametrize("mode", ["silent", "muted", "killed"])
async def test_gate_refusal_rejected_and_logged(db, mode):
    if mode == "silent":
        await controls.set_level("silent", db=db)
    elif mode == "muted":
        await controls.mute_kind("investigate", db=db)
    else:
        await controls.set_killed(True, db=db)
    ws = Workspace()
    ws.post(_p())
    assert await ws.attend(db.clock.now(), BIG, db=db) is None
    rows = await _trace(db)
    rej = [r for r in rows if r["action"].startswith("attend:reject")]
    assert len(rej) == 1 and rej[0]["why"].startswith("gate_refused:")


async def test_drive_gain_changes_winner_and_ablation(db, monkeypatch):
    ws = Workspace()
    ws.post(_p(kind=ProposalKind.INVESTIGATE, ref="inv"))
    ws.post(_p(kind=ProposalKind.CONSOLIDATE, ref="con"))
    m = drives.DriveModel.fresh()
    m.levels.update({d: 0.3 for d in drives.DRIVES})
    m.levels["curiosity"], m.levels["rest"] = 0.9, 0.1
    drives._model = m
    monkeypatch.setattr(settings, "drives_enabled", True)
    assert (await ws.attend(db.clock.now(), BIG, db=db)).proposal.refs == ["inv"]
    m.levels["curiosity"], m.levels["rest"] = 0.1, 0.9
    w = await ws.attend(db.clock.now(), BIG, db=db)
    assert w.proposal.refs == ["con"]
    # ablation: flag off, gain is exactly 1.0 and the earlier proposal wins the tie
    monkeypatch.setattr(settings, "drives_enabled", False)
    w = await ws.attend(db.clock.now(), BIG, db=db)
    assert w.drive_gain == 1.0 and w.proposal.refs == ["inv"]


async def test_ask_user_takes_max_of_connection_and_coherence(db, monkeypatch):
    from aura.orchestrator.workspace import drive_gain
    m = drives.DriveModel.fresh()
    m.levels.update({"connection": 0.2, "coherence": 0.8})
    drives._model = m
    monkeypatch.setattr(settings, "drives_enabled", True)
    assert drive_gain(ProposalKind.ASK_USER) == pytest.approx(0.8)


async def test_every_outcome_has_trace_row_stamped_by_fake_clock(db):
    ws = Workspace()
    ws.post(_p(ref="ok"))
    ws.post(_p(ref="big", cost=Cost(tokens=999999)))
    await ws.attend(db.clock.now(), Budget(tokens=1000, seconds=60.0), db=db)
    rows = [r for r in await _trace(db) if r["action"].startswith("attend:")]
    assert {r["action"].split(":")[1] for r in rows} == {"winner", "reject"}
    assert all(r["at"] == _START for r in rows)


async def test_flag_off_attend_returns_none(db, monkeypatch):
    ws = Workspace()
    ws.post(_p())
    monkeypatch.setattr(settings, "workspace_enabled", False)
    assert await ws.attend(db.clock.now(), BIG, db=db) is None
    assert not [r for r in await _trace(db) if r["action"].startswith("attend:")]


async def test_winner_broadcast_reaches_targets(db):
    bus = MessageBus()
    got = []

    async def handler(msg):
        got.append(msg)

    bus.subscribe("goal", handler)
    ws = Workspace(bus)
    ws.post(_p())
    await ws.attend(db.clock.now(), BIG, db=db)
    msg = await bus._message_queue.get()
    assert msg.targets == ["goal"] and msg.message_type == MessageType.STATE_UPDATE
    assert msg.data["kind"] == "workspace_winner"
