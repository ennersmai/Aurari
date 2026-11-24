"""B4-04: Findings to agenda - share proposals and ask-the-owner questions."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aura.autonomy import agenda as agenda_mod, controls, findings, trace
from aura.autonomy.agenda import AgendaService
from aura.autonomy.delivery import get_deliverer
from aura.autonomy.investigation import InvestigationResult
from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.db.query_utils import extract_rows
from aura.orchestrator.workspace import Workspace, get_workspace, set_workspace
from tests.scenarios.runner import EmbeddedSurrealDB


_START = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
async def db(monkeypatch):
    d = EmbeddedSurrealDB()
    await d.connect()
    clock = FakeClock(_START)
    set_clock(clock)
    controls.reset_cache()
    for mod in (agenda_mod, controls, trace):
        monkeypatch.setattr(mod, "get_db_client", lambda: d)
    monkeypatch.setattr(settings, "curiosity_enabled", True)
    monkeypatch.setattr(settings, "workspace_enabled", True)
    monkeypatch.setattr(settings, "autonomy_enabled", True)
    monkeypatch.setattr(settings, "drives_enabled", True)
    monkeypatch.setattr(settings, "finding_share_relevance", 0.5)
    monkeypatch.setattr(settings, "finding_expiry_hours", 72)
    # Set up workspace with db
    from aura.orchestrator.workspace import get_workspace, set_workspace
    ws = Workspace()
    ws.db = d
    set_workspace(ws)
    d.clock = clock
    yield d
    controls.reset_cache()
    set_workspace(None)
    set_clock(Clock())
    await d.close()


@pytest.fixture
async def question_owner(db):
    """Create an owner-visible question."""
    rows = await db.query(
        "CREATE question CONTENT $d",
        {"d": {"content": "What does Pixel eat?", "visibility": "owner", "status": "open", "recorded_at": _START}},
    )
    return rows[0]


@pytest.fixture
async def question_ask_user(db):
    """Create an owner-visible question with ask_user route."""
    rows = await db.query(
        "CREATE question CONTENT $d",
        {"d": {"content": "Do you like cats?", "visibility": "owner", "status": "open", "recorded_at": _START}},
    )
    return rows[0]


@pytest.fixture
async def question_parked(db):
    """Create an owner-visible question that will be parked."""
    rows = await db.query(
        "CREATE question CONTENT $d",
        {"d": {"content": "What is the meaning of life?", "visibility": "owner", "status": "open", "recorded_at": _START}},
    )
    return rows[0]


@pytest.fixture
async def question_guest(db):
    """Create a guest-visible question."""
    rows = await db.query(
        "CREATE question CONTENT $d",
        {"d": {"content": "Guest question?", "visibility": "guest", "status": "open", "recorded_at": _START}},
    )
    return rows[0]


async def test_relevant_finding_creates_finding_item_and_share_proposal(db, question_owner, monkeypatch):
    """A relevant finding (relevance >= threshold) creates a finding item and share proposal."""
    # Mock relevance to return high value
    from aura.autonomy import curiosity
    monkeypatch.setattr(curiosity, "relevance", lambda q, ctx: 0.8)

    # Mock L2 draft call
    from aura.autonomy import findings as findings_mod

    class MockLLM:
        async def complete(self, messages, model=None, **kw):
            return "Found that Pixel eats kibble twice a day."

    monkeypatch.setattr(findings_mod, "_get_llm_client", lambda: MockLLM())

    result = InvestigationResult(
        question_id=str(question_owner["id"]),
        state="resolved",
        report="- Pixel the cat eats kibble twice a day, per https://vet.example/pixel\n- The vet recommends a weight check every six months",
        fact_ids=["fact:abc123", "fact:def456"],
        route="search",
    )

    await findings.publish(question_owner, result, db)

    # Check finding item created
    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'finding'"))
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "finding"
    assert "fact:abc123" in item["refs"]
    assert "fact:def456" in item["refs"]
    assert str(question_owner["id"]) in item["refs"]
    assert item["expires_at"] is not None

    # Check share proposal posted
    from aura.orchestrator.workspace import get_workspace
    ws = get_workspace()
    share_props = [p for p in ws.all() if p.kind.value == "share"]
    assert len(share_props) == 1
    # Compare IDs without the RecordID formatting
    share_ref = str(share_props[0].refs[0])
    item_id = str(item["id"])
    # Both should be "agenda_item:<id>" - extract just the ID part
    share_id = share_ref.split(":")[-1].replace("⟨", "").replace("⟩", "")
    item_id_clean = item_id.split(":")[-1].replace("⟨", "").replace("⟩", "")
    assert share_id == item_id_clean


async def test_irrelevant_finding_creates_no_item(db, question_owner, monkeypatch):
    """An irrelevant finding (relevance < threshold) creates no item."""
    from aura.autonomy import curiosity
    monkeypatch.setattr(curiosity, "relevance", lambda q, ctx: 0.2)

    result = InvestigationResult(
        question_id=str(question_owner["id"]),
        state="resolved",
        report="- Some irrelevant fact",
        fact_ids=["fact:abc123"],
        route="search",
    )

    await findings.publish(question_owner, result, db)

    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'finding'"))
    assert len(items) == 0

    # Check trace recorded
    traces = extract_rows(await db.query("SELECT * FROM autonomy_trace WHERE action = 'finding:irrelevant'"))
    assert len(traces) == 1


async def test_owner_only_question_creates_question_for_you(db, question_ask_user):
    """An ask_user route question creates a question_for_you item and no fact is written."""
    result = InvestigationResult(
        question_id=str(question_ask_user["id"]),
        state="resolved",
        report="Owner preference needed",
        fact_ids=[],  # No facts for owner-only
        route="ask_user",
    )

    await findings.publish(question_ask_user, result, db)

    # Check question_for_you item created
    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'question_for_you'"))
    assert len(items) == 1
    item = items[0]
    assert item["kind"] == "question_for_you"
    assert item["content"] == question_ask_user["content"]
    assert str(question_ask_user["id"]) in item["refs"]
    assert item["expires_at"] is not None

    # Check ask_user proposal posted
    from aura.orchestrator.workspace import get_workspace
    ws = get_workspace()
    ask_props = [p for p in ws.all() if p.kind.value == "ask_user"]
    assert len(ask_props) == 1
    # Compare IDs without the RecordID formatting
    ask_ref = str(ask_props[0].refs[0])
    item_id = str(item["id"])
    # Both should be "agenda_item:<id>" - extract just the ID part
    ask_id = ask_ref.split(":")[-1].replace("⟨", "").replace("⟩", "")
    item_id_clean = item_id.split(":")[-1].replace("⟨", "").replace("⟩", "")
    assert ask_id == item_id_clean


async def test_parked_question_creates_no_item(db, question_parked):
    """A parked question with a reason creates no item."""
    result = InvestigationResult(
        question_id=str(question_parked["id"]),
        state="parked",
        reason="no_findings",
        report="",
        fact_ids=[],
        route="search",
    )

    await findings.publish(question_parked, result, db)

    items = extract_rows(await db.query("SELECT * FROM agenda_item"))
    assert len(items) == 0


async def test_guest_question_creates_no_item(db, question_guest):
    """Guest questions create no agenda items."""
    result = InvestigationResult(
        question_id=str(question_guest["id"]),
        state="resolved",
        report="- Some finding",
        fact_ids=["fact:abc123"],
        route="search",
    )

    await findings.publish(question_guest, result, db)

    items = extract_rows(await db.query("SELECT * FROM agenda_item"))
    assert len(items) == 0


async def test_draft_call_runs_once_per_finding(db, question_owner, monkeypatch):
    """The L2 draft call runs exactly once per finding."""
    from aura.autonomy import curiosity
    monkeypatch.setattr(curiosity, "relevance", lambda q, ctx: 0.8)

    call_count = 0

    class MockLLM:
        async def complete(self, messages, model=None, **kw):
            nonlocal call_count
            call_count += 1
            return "Summary"

    from aura.autonomy import findings as findings_mod
    # Reset the global client
    findings_mod._llm_client = None
    mock_client = MockLLM()
    monkeypatch.setattr(findings_mod, "_get_llm_client", lambda: mock_client)

    result = InvestigationResult(
        question_id=str(question_owner["id"]),
        state="resolved",
        report="- Fact one is here\n- Fact two is also here",
        fact_ids=["fact:abc123", "fact:def456"],
        route="search",
    )

    await findings.publish(question_owner, result, db)

    assert call_count == 1


async def test_delivery_respects_silent_and_quiet_hours(db, question_owner, monkeypatch):
    """Delivery respects silent mode and quiet hours."""
    from aura.autonomy import curiosity
    monkeypatch.setattr(curiosity, "relevance", lambda q, ctx: 0.8)

    class MockLLM:
        async def complete(self, messages, model=None, **kw):
            return "Summary"

    from aura.autonomy import findings as findings_mod
    monkeypatch.setattr(findings_mod, "_get_llm_client", lambda: MockLLM())

    result = InvestigationResult(
        question_id=str(question_owner["id"]),
        state="resolved",
        report="- Fact 1",
        fact_ids=["fact:abc123"],
        route="search",
    )

    await findings.publish(question_owner, result, db)

    # Test silent mode
    await controls.set_level("silent", db)

    from aura.orchestrator.workspace import get_workspace
    ws = get_workspace()
    deliverer = get_deliverer()
    from aura.autonomy.agenda import AgendaService
    svc = AgendaService(db)
    deliverer.service = svc

    delivered = await deliverer.deliver_due()
    assert len(delivered) == 0

    # Test quiet hours
    await controls.set_level("open", db)
    set_clock(FakeClock(datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)))
    monkeypatch.setattr(settings, "app_timezone", "UTC")
    monkeypatch.setattr(settings, "quiet_hours_start", "22:00")
    monkeypatch.setattr(settings, "quiet_hours_end", "08:00")

    delivered = await deliverer.deliver_due()
    assert len(delivered) == 0

    set_clock(Clock())


async def test_curiosity_drive_drops_on_resolution(db, question_owner, monkeypatch):
    """The curiosity drive drops on question_resolved event."""
    from aura.autonomy import curiosity, drives
    monkeypatch.setattr(curiosity, "relevance", lambda q, ctx: 0.8)

    class MockLLM:
        async def complete(self, messages, model=None, **kw):
            return "Summary"

    from aura.autonomy import findings as findings_mod
    monkeypatch.setattr(findings_mod, "_get_llm_client", lambda: MockLLM())

    # Reset drives
    drives.reset_cache()
    await db.query("DELETE drive_state")
    monkeypatch.setattr(settings, "drive_delta_question_opened_curiosity", 0.2)
    monkeypatch.setattr(settings, "drive_delta_question_resolved_curiosity", -0.15)
    monkeypatch.setattr(settings, "drive_baseline", 0.3)

    # Open a question first (raises curiosity)
    await drives.on_event("question_opened", db=db)
    vals_before = drives.current().levels["curiosity"]
    assert vals_before > 0.3

    # Now publish findings (should trigger question_resolved event)
    result = InvestigationResult(
        question_id=str(question_owner["id"]),
        state="resolved",
        report="- Fact 1",
        fact_ids=["fact:abc123"],
        route="search",
    )

    await findings.publish(question_owner, result, db)

    # Check curiosity drive dropped
    vals_after = drives.current().levels["curiosity"]
    assert vals_after < vals_before


async def test_finding_item_expires_after_configured_hours(db, question_owner, monkeypatch):
    """Finding items expire after finding_expiry_hours."""
    from aura.autonomy import curiosity
    monkeypatch.setattr(curiosity, "relevance", lambda q, ctx: 0.8)

    class MockLLM:
        async def complete(self, messages, model=None, **kw):
            return "Summary"

    from aura.autonomy import findings as findings_mod
    monkeypatch.setattr(findings_mod, "_get_llm_client", lambda: MockLLM())

    monkeypatch.setattr(settings, "finding_expiry_hours", 1)

    result = InvestigationResult(
        question_id=str(question_owner["id"]),
        state="resolved",
        report="- Fact 1",
        fact_ids=["fact:abc123"],
        route="search",
    )

    await findings.publish(question_owner, result, db)

    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'finding'"))
    assert len(items) == 1
    item = items[0]
    assert item["expires_at"] is not None

    # Advance clock past expiry
    from aura.clock import get_clock
    get_clock().advance(2 * 3600)  # 2 hours

    # Expire due items
    from aura.autonomy.agenda import AgendaService
    svc = AgendaService(db)
    expired = await svc.expire_due(get_clock().now())
    assert expired == 1

    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'finding'"))
    assert len(items) == 1
    assert items[0]["state"] == "expired"

async def test_runner_ask_user_route_creates_question_for_you_without_facts(db, question_ask_user, monkeypatch):
    """The runner itself routes ask_user questions to the owner and stores no fact."""
    from aura.autonomy import investigation as inv_mod

    monkeypatch.setattr(inv_mod, "get_db_client", lambda: db)
    runner = inv_mod.InvestigationRunner(llm_client=object(), executor=object(), db=db)
    result = await runner.run(question_ask_user, "ask_user", None)
    assert result.owner_only and not result.fact_ids
    items = extract_rows(await db.query("SELECT * FROM agenda_item WHERE kind = 'question_for_you'"))
    assert len(items) == 1
    assert extract_rows(await db.query("SELECT * FROM memory WHERE provenance = 'external'")) == []
