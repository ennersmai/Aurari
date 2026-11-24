"""B4-03: Curiosity daily budgets and rejection logging (T6).

Tests:
- After the ceiling, further investigate proposals are rejected and logged.
- Other proposal kinds are unaffected.
- Each ceiling alone triggers.
- Rollover at midnight with a FakeClock resets.
- Spend and tokens add up across runs.
- The endpoint reports remaining.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from aura.autonomy import budget as curiosity_budget, controls
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
from aura.orchestrator.workspace import Budget as WorkspaceBudget, Workspace
from tests.scenarios.runner import EmbeddedSurrealDB

_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    controls.reset_cache()
    monkeypatch.setattr(settings, "curiosity_enabled", True)
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    # Set low ceilings for testing
    monkeypatch.setattr(settings, "curiosity_daily_investigations", 2)
    monkeypatch.setattr(settings, "curiosity_daily_tokens", 1000)
    monkeypatch.setattr(settings, "curiosity_daily_spend_usd", 0.05)
    await controls.set_level("open", db=d)
    d.clock = clock
    ws = Workspace()
    ws.db = d
    # app_timezone pinned so 'local midnight' is deterministic
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    # Don't replace global workspace, just use local
    yield d, ws, clock
    controls.reset_cache()
    set_clock(Clock())
    await d.close()


def _investigate_proposal(ref="question:test", tokens=100, seconds=1.0):
    return Proposal(
        source="test",
        kind=ProposalKind.INVESTIGATE,
        summary="test investigation",
        refs=[ref],
        urgency=1.0,
        value=1.0,
        cost=Cost(tokens=tokens, seconds=seconds, risk=RiskLevel.READ),
    )


def _pursue_proposal(ref="goal:test", tokens=100, seconds=1.0):
    return Proposal(
        source="test",
        kind=ProposalKind.PURSUE_GOAL,
        summary="test pursuit",
        refs=[ref],
        urgency=1.0,
        value=1.0,
        cost=Cost(tokens=tokens, seconds=seconds, risk=RiskLevel.READ),
    )


async def _rejections(d):
    rows = extract_rows(await d.query(
        "SELECT * FROM autonomy_trace WHERE action = 'attend:reject:investigate'"))
    return [r["why"] for r in rows]


_B = WorkspaceBudget(tokens=10000, seconds=100.0)


@pytest.mark.parametrize("spend,which", [
    ({"investigations": 2}, "investigations"),
    ({"tokens": 1000}, "tokens"),
    ({"spend_usd": 0.05}, "spend_usd"),
])
async def test_each_ceiling_alone_rejects_and_logs(db, spend, which):
    d, ws, clock = db
    await curiosity_budget.record_spend(db=d, **spend)
    ws.post(_investigate_proposal("question:1"))
    assert await ws.run_cycle(budget=_B) is None
    assert f"daily budget reached: {which}" in await _rejections(d)


async def test_other_kinds_unaffected(db):
    d, ws, clock = db
    await curiosity_budget.record_spend(investigations=2, db=d)
    ws.post(_pursue_proposal("goal:1"))
    w = await ws.run_cycle(budget=_B)
    assert w is not None and w.proposal.kind == ProposalKind.PURSUE_GOAL


async def test_within_budget_investigate_can_win(db):
    d, ws, clock = db
    await curiosity_budget.record_spend(investigations=1, tokens=10, db=d)
    ws.post(_investigate_proposal("question:1"))
    w = await ws.run_cycle(budget=_B)
    assert w is not None and w.proposal.kind == ProposalKind.INVESTIGATE


async def test_midnight_rollover_resets(db):
    d, ws, clock = db
    await curiosity_budget.record_spend(investigations=2, db=d)
    ws.post(_investigate_proposal("question:1"))
    assert await ws.run_cycle(budget=_B) is None
    set_clock(FakeClock(datetime(2026, 1, 2, 0, 0, 1, tzinfo=timezone.utc)))
    ws.post(_investigate_proposal("question:2"))
    assert await ws.run_cycle(budget=_B) is not None


async def test_spend_and_tokens_add_up_across_runs(db):
    d, ws, clock = db
    await curiosity_budget.record_spend(investigations=1, tokens=300, spend_usd=0.01, db=d)
    await curiosity_budget.record_spend(investigations=1, tokens=200, spend_usd=0.02, db=d)
    rem = await curiosity_budget.get_remaining(db=d)
    assert rem["investigations_used"] == 2 and rem["tokens_used"] == 500
    assert rem["spend_usd_used"] == pytest.approx(0.03)
    assert rem["tokens_remaining"] == 500 and rem["spend_usd_remaining"] == pytest.approx(0.02)


async def test_endpoint_reports_remaining(db, monkeypatch):
    d, ws, clock = db
    from aura.api.routes import autonomy as autonomy_routes
    monkeypatch.setattr(curiosity_budget, "get_db_client", lambda: d)
    await curiosity_budget.record_spend(investigations=1, tokens=100, db=d)
    out = await autonomy_routes.get_autonomy_budget()
    assert out["investigations_remaining"] == 1 and out["tokens_remaining"] == 900


async def test_zero_spend_ceiling_allows_free_routes(db, monkeypatch):
    """Ceiling 0: tokens count, zero provider cost spends nothing, so free runs go on."""
    d, ws, clock = db
    monkeypatch.setattr(settings, "curiosity_daily_spend_usd", 0.0)
    await curiosity_budget.record_spend(investigations=1, tokens=300, spend_usd=0.0, db=d)
    ws.post(_investigate_proposal("question:1"))
    assert await ws.run_cycle(budget=_B) is not None


async def test_within_budget_investigate_still_passes_the_gate(db):
    """Supervisor fix: the budget check must not replace may_initiate."""
    d, ws, clock = db
    await controls.set_level("silent", db=d)
    ws.post(_investigate_proposal("question:gate"))
    w = await ws.run_cycle(budget=WorkspaceBudget(tokens=10000, seconds=100.0))
    assert w is None
    rows = extract_rows(await d.query("SELECT * FROM autonomy_trace WHERE action = 'attend:reject:investigate'"))
    assert rows and not any("daily budget" in r["why"] for r in rows)


async def test_zero_spend_ceiling_blocks_after_paid_spend(db, monkeypatch):
    """Ceiling 0 means free routes only: any recorded paid spend closes the day."""
    d, ws, clock = db
    monkeypatch.setattr(settings, "curiosity_daily_spend_usd", 0.0)
    await curiosity_budget.record_spend(investigations=1, tokens=10, spend_usd=0.01, db=d)
    ws.post(_investigate_proposal("question:paid"))
    assert await ws.run_cycle(budget=WorkspaceBudget(tokens=10000, seconds=100.0)) is None
    rows = extract_rows(await d.query("SELECT * FROM autonomy_trace WHERE action = 'attend:reject:investigate'"))
    assert any("daily budget reached: spend_usd" in r["why"] for r in rows)


async def test_record_spend_creates_the_day_row(db):
    d, ws, clock = db
    await curiosity_budget.record_spend(investigations=1, tokens=50, db=d)
    rem = await curiosity_budget.get_remaining(db=d)
    assert rem["investigations_used"] == 1 and rem["tokens_used"] == 50
