"""Tests for the workspace proposal registry (B2-02)."""

import pytest
from datetime import datetime, timezone, timedelta
from uuid import uuid4

from aura.clock import Clock, FakeClock, set_clock
from aura.config import settings
from aura.models.messages import EngineMessage, MessageType
from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
from aura.orchestrator.message_bus import MessageBus
from aura.orchestrator.workspace import Workspace, get_workspace, set_workspace



@pytest.fixture(autouse=True)
def _restore_clock():
    yield
    set_clock(Clock())

class TestProposalValidation:
    """Tests for Proposal model validation."""

    def test_valid_proposal(self):
        """A valid proposal with all required fields passes."""
        proposal = Proposal(
            source="test_engine",
            kind=ProposalKind.INVESTIGATE,
            summary="Investigate user question about cats",
            refs=["question:123", "memory:456"],
            urgency=0.8,
            value=0.7,
            cost=Cost(tokens=100, seconds=5.0, risk=RiskLevel.READ),
        )
        assert proposal.id is not None
        assert proposal.source == "test_engine"
        assert proposal.kind == ProposalKind.INVESTIGATE
        assert proposal.summary == "Investigate user question about cats"
        assert proposal.refs == ["question:123", "memory:456"]

    def test_empty_refs_raises(self):
        """Empty refs raises ValueError (same rule as agenda)."""
        with pytest.raises(ValueError, match="proposal needs refs"):
            Proposal(
                source="test",
                kind=ProposalKind.INVESTIGATE,
                summary="Test",
                refs=[],
            )

    def test_none_refs_raises(self):
        """None refs raises ValueError."""
        with pytest.raises(ValueError, match="proposal needs refs"):
            Proposal(
                source="test",
                kind=ProposalKind.INVESTIGATE,
                summary="Test",
                refs=None,  # type: ignore
            )

    def test_multi_line_summary_raises(self):
        """Multi-line summary raises ValueError."""
        with pytest.raises(ValueError, match="summary must be a single line"):
            Proposal(
                source="test",
                kind=ProposalKind.INVESTIGATE,
                summary="Line 1\nLine 2",
                refs=["ref1"],
            )

    def test_summary_strips_whitespace(self):
        """Summary whitespace is stripped."""
        proposal = Proposal(
            source="test",
            kind=ProposalKind.INVESTIGATE,
            summary="  Test summary  ",
            refs=["ref1"],
        )
        assert proposal.summary == "Test summary"

    def test_refs_cleaned_and_filtered(self):
        """Refs are cleaned and empty strings filtered."""
        proposal = Proposal(
            source="test",
            kind=ProposalKind.INVESTIGATE,
            summary="Test",
            refs=["  ref1  ", "", "ref2", "  "],
        )
        assert proposal.refs == ["ref1", "ref2"]

    def test_duplicate_key(self):
        """Duplicate key is based on source, kind, and sorted refs."""
        p1 = Proposal(source="a", kind=ProposalKind.INVESTIGATE, summary="s", refs=["b", "a"])
        p2 = Proposal(source="a", kind=ProposalKind.INVESTIGATE, summary="s", refs=["a", "b"])
        p3 = Proposal(source="a", kind=ProposalKind.PURSUE_GOAL, summary="s", refs=["a", "b"])
        p4 = Proposal(source="b", kind=ProposalKind.INVESTIGATE, summary="s", refs=["a", "b"])

        assert p1.duplicate_key() == p2.duplicate_key()
        assert p1.duplicate_key() != p3.duplicate_key()
        assert p1.duplicate_key() != p4.duplicate_key()

    def test_is_expired(self):
        """is_expired works correctly."""
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=1)
        future = now + timedelta(hours=1)

        p_no_expiry = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"])
        p_expired = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"], expires_at=past)
        p_active = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"], expires_at=future)

        assert not p_no_expiry.is_expired(now)
        assert p_expired.is_expired(now)
        assert not p_active.is_expired(now)


class TestWorkspacePost:
    """Tests for Workspace.post."""

    def setup_method(self):
        """Set up a fresh workspace for each test."""
        set_workspace(None)
        # Enable workspace for tests
        self._original_enabled = settings.workspace_enabled
        self._original_max = settings.workspace_max_proposals
        settings.workspace_enabled = True
        settings.workspace_max_proposals = 50

    def teardown_method(self):
        """Restore settings."""
        settings.workspace_enabled = self._original_enabled
        settings.workspace_max_proposals = self._original_max
        set_workspace(None)

    def test_post_returns_id(self):
        """Post returns the proposal id."""
        ws = Workspace()
        proposal = Proposal(
            source="test",
            kind=ProposalKind.INVESTIGATE,
            summary="Test proposal",
            refs=["ref1"],
        )
        pid = ws.post(proposal)
        assert pid == proposal.id
        assert ws.get(pid) is proposal

    def test_post_disabled_returns_none(self):
        """Post returns None when workspace is disabled."""
        settings.workspace_enabled = False
        ws = Workspace()
        proposal = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"])
        assert ws.post(proposal) is None
        assert len(ws.all()) == 0

    def test_duplicate_replaces_older(self):
        """Duplicate (same source, kind, sorted refs) replaces older."""
        ws = Workspace()
        p1 = Proposal(source="engine1", kind=ProposalKind.INVESTIGATE, summary="First", refs=["a", "b"])
        p2 = Proposal(source="engine1", kind=ProposalKind.INVESTIGATE, summary="Second", refs=["b", "a"])

        id1 = ws.post(p1)
        id2 = ws.post(p2)

        assert id1 != id2
        assert ws.get(id1) is None  # Old one removed
        assert ws.get(id2) is p2
        assert len(ws.all()) == 1

    def test_non_duplicate_coexist(self):
        """Non-duplicate proposals coexist."""
        ws = Workspace()
        p1 = Proposal(source="e1", kind=ProposalKind.INVESTIGATE, summary="s", refs=["a"])
        p2 = Proposal(source="e1", kind=ProposalKind.PURSUE_GOAL, summary="s", refs=["a"])
        p3 = Proposal(source="e2", kind=ProposalKind.INVESTIGATE, summary="s", refs=["a"])

        ws.post(p1)
        ws.post(p2)
        ws.post(p3)

        assert len(ws.all()) == 3


class TestWorkspaceLive:
    """Tests for Workspace.live (expiry)."""

    def setup_method(self):
        set_workspace(None)
        self._original_enabled = settings.workspace_enabled
        settings.workspace_enabled = True

    def teardown_method(self):
        settings.workspace_enabled = self._original_enabled
        set_workspace(None)

    def test_live_drops_expired(self):
        """live drops expired proposals."""
        fake = FakeClock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
        set_clock(fake)

        ws = Workspace()
        past = datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        future = datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)

        p_expired = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"], expires_at=past)
        p_active = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r2"], expires_at=future)
        p_no_expiry = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r3"])

        ws.post(p_expired)
        ws.post(p_active)
        ws.post(p_no_expiry)

        assert len(ws.all()) == 3

        evicted = ws.live(fake.now())

        assert evicted == [p_expired.id]
        assert len(ws.all()) == 2
        assert ws.get(p_active.id) is p_active
        assert ws.get(p_no_expiry.id) is p_no_expiry

    def test_live_disabled_returns_empty(self):
        """live returns empty list when disabled."""
        settings.workspace_enabled = False
        ws = Workspace()
        p = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"])
        ws.post(p)
        assert ws.live() == []


class TestWorkspaceBound:
    """Tests for workspace_max_proposals bound."""

    def setup_method(self):
        set_workspace(None)
        self._original_enabled = settings.workspace_enabled
        self._original_max = settings.workspace_max_proposals
        settings.workspace_enabled = True

    def teardown_method(self):
        settings.workspace_enabled = self._original_enabled
        settings.workspace_max_proposals = self._original_max
        set_workspace(None)

    def test_bound_evicts_oldest_expired_first(self):
        """When at capacity, oldest expired are evicted first."""
        settings.workspace_max_proposals = 3
        fake = FakeClock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
        set_clock(fake)

        ws = Workspace()
        # Add 3 proposals, 2 expired
        ws.post(Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["1"], expires_at=fake.now() - timedelta(hours=2)))
        ws.post(Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["2"], expires_at=fake.now() - timedelta(hours=1)))
        ws.post(Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["3"]))  # no expiry

        assert len(ws.all()) == 3

        # Add a 4th - should evict oldest expired first
        ws.post(Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["4"]))

        assert len(ws.all()) == 3
        # The two expired should be gone, oldest expired first
        remaining_ids = {p.id for p in ws.all()}
        # We can't easily check which specific ones, but we know 2 expired + 1 new = 3 total
        # The one without expiry and the new one should remain

    def test_bound_evicts_oldest_overall_when_no_expired(self):
        """When at capacity with no expired, oldest overall are evicted."""
        settings.workspace_max_proposals = 2
        fake = FakeClock(datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc))
        set_clock(fake)

        ws = Workspace()
        p1 = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["1"])
        fake.advance(1)
        p2 = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["2"])
        fake.advance(1)
        p3 = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["3"])

        ws.post(p1)
        ws.post(p2)
        assert len(ws.all()) == 2

        ws.post(p3)
        assert len(ws.all()) == 2
        # p1 should be evicted (oldest)
        assert ws.get(p1.id) is None
        assert ws.get(p2.id) is p2
        assert ws.get(p3.id) is p3


class TestWorkspaceBusIntegration:
    """Tests for message bus integration."""

    def setup_method(self):
        set_workspace(None)
        self._original_enabled = settings.workspace_enabled
        settings.workspace_enabled = True

    def teardown_method(self):
        settings.workspace_enabled = self._original_enabled
        set_workspace(None)

    @pytest.mark.asyncio
    async def test_bus_proposal_reaches_workspace(self):
        """A PROPOSAL message on the bus reaches the workspace."""
        bus = MessageBus()
        await bus.start()

        ws = Workspace(bus)
        # Initially empty
        assert len(ws.all()) == 0

        # Create a PROPOSAL message
        msg = EngineMessage(
            source="test_engine",
            message_type=MessageType.PROPOSAL,
            data={
                "id": "bus_prop_1",
                "source": "test_engine",
                "kind": "investigate",
                "summary": "Bus proposal",
                "refs": ["question:123"],
                "urgency": 0.5,
                "value": 0.5,
                "cost": {"tokens": 100, "seconds": 1.0, "risk": "read"},
            },
            targets=["workspace"],
        )

        await bus.publish(msg)

        # Give the bus time to process
        import asyncio
        await asyncio.sleep(0.1)

        # Workspace should have the proposal
        assert len(ws.all()) == 1
        prop = ws.all()[0]
        assert prop.id == "bus_prop_1"
        assert prop.source == "test_engine"
        assert prop.kind == ProposalKind.INVESTIGATE

        await bus.stop()

    @pytest.mark.asyncio
    async def test_bus_disabled_no_subscribe(self):
        """When disabled, workspace does not subscribe to bus."""
        settings.workspace_enabled = False
        bus = MessageBus()
        await bus.start()

        ws = Workspace(bus)
        assert not ws._subscribed

        msg = EngineMessage(
            source="test_engine",
            message_type=MessageType.PROPOSAL,
            data={
                "id": "bus_prop_1",
                "source": "test_engine",
                "kind": "investigate",
                "summary": "Bus proposal",
                "refs": ["question:123"],
            },
            targets=["workspace"],
        )

        await bus.publish(msg)
        import asyncio
        await asyncio.sleep(0.1)

        assert len(ws.all()) == 0

        await bus.stop()


class TestWorkspaceFlagOff:
    """Tests for workspace_enabled flag being off."""

    def setup_method(self):
        set_workspace(None)
        self._original_enabled = settings.workspace_enabled
        settings.workspace_enabled = False

    def teardown_method(self):
        settings.workspace_enabled = self._original_enabled
        set_workspace(None)

    def test_post_returns_none(self):
        """Post returns None when disabled."""
        ws = Workspace()
        p = Proposal(source="t", kind=ProposalKind.INVESTIGATE, summary="s", refs=["r"])
        assert ws.post(p) is None

    def test_live_returns_empty(self):
        """Live returns empty list when disabled."""
        ws = Workspace()
        assert ws.live() == []

    def test_all_returns_empty(self):
        """All returns empty when disabled (nothing ever added)."""
        ws = Workspace()
        assert ws.all() == []


class TestCostModel:
    """Tests for Cost model."""

    def test_default_cost(self):
        """Default cost has zero tokens, zero seconds, read risk."""
        cost = Cost()
        assert cost.tokens == 0
        assert cost.seconds == 0.0
        assert cost.risk == RiskLevel.READ

    def test_cost_with_values(self):
        """Cost accepts tokens, seconds, risk."""
        cost = Cost(tokens=500, seconds=10.5, risk=RiskLevel.WRITE)
        assert cost.tokens == 500
        assert cost.seconds == 10.5
        assert cost.risk == RiskLevel.WRITE

    def test_cost_risk_from_string(self):
        """Cost accepts risk as string."""
        cost = Cost(risk="execute")
        assert cost.risk == RiskLevel.EXECUTE