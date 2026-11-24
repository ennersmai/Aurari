"""Findings to agenda: share proposals and ask-the-owner questions (B4-04).

After an investigation, `findings.publish(question, result)`:
- If the finding matters to the owner (relevance >= `finding_share_relevance`),
  create an agenda `finding` item whose `content` is drafted by one short L2 call,
  `refs` the fact ids and question id, and post a `share` proposal.
- If the question's route is `ask_user` or the result says only the owner can answer,
  create a `question_for_you` item with the question as `content` and `refs=[question_id]`.
- Items expire after `finding_expiry_hours` (default 72).
- A parked question with a reason creates no item.
- The `question_resolved` event is sent to the workspace, lowering the curiosity drive.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from aura.autonomy import agenda as agenda_mod, trace
from aura.clock import get_clock
from aura.config import settings
from aura.db.client import get_db_client
from aura.db.query_utils import extract_rows
from aura.llm.unified_provider import UnifiedLLMClient
from aura.orchestrator.workspace import fire_event

_OWNER_VISIBILITY = ("owner", "private:owner")

logger = logging.getLogger(__name__)

_llm_client: UnifiedLLMClient | None = None


def _get_llm_client() -> UnifiedLLMClient:
    """Get or create the unified LLM client (patched in tests)."""
    global _llm_client
    if _llm_client is None:
        _llm_client = UnifiedLLMClient()
    return _llm_client


async def _draft_finding_summary(question_content: str, fact_lines: list[str]) -> str:
    """Draft a short summary of the findings using an L2 model call."""
    if not fact_lines:
        return ""
    model = settings.active_l2_model
    client = _get_llm_client()
    prompt = (
        f"Question: {question_content}\n"
        f"Findings (one per line):\n" + "\n".join(f"- {ln}" for ln in fact_lines) +
        "\n\nWrite a concise 1-2 sentence summary of what was found, "
        "suitable for the owner. Do not include sources or URLs."
    )
    try:
        resp = await client.complete(
            messages=[{"role": "user", "content": prompt}],
            model=model,
            temperature=0.2,
            max_tokens=150,
        )
        return resp.strip()
    except Exception as e:
        logger.warning("L2 draft for finding summary failed: %s", e)
        # Fallback: join the fact lines
        return "; ".join(fact_lines[:3])


async def publish(question: dict[str, Any], result: Any, db: Any = None) -> None:
    """Publish findings from a completed investigation to the agenda.

    Args:
        question: The question dict (must have id, content, visibility, route).
        result: InvestigationResult with state, report, fact_ids, route.
        db: Optional database client.
    """
    db = db if db is not None else get_db_client()
    qid = str(question.get("id"))
    q_content = question.get("content") or ""
    route = getattr(result, "route", None) or question.get("route", "search")
    state = getattr(result, "state", None)
    fact_ids = getattr(result, "fact_ids", None) or []
    report = getattr(result, "report", "") or ""

    # Always send question_resolved event to workspace (lowers curiosity drive)
    fire_event("question_resolved", {"question_id": qid, "state": state})

    # Parked question with a reason creates no item
    if state == "parked" and getattr(result, "reason", ""):
        return

    # Only owner-visible questions create items
    if question.get("visibility") not in _OWNER_VISIBILITY:
        return

    # If route is ask_user or result says only owner can answer -> question_for_you
    if route == "ask_user" or getattr(result, "owner_only", False):
        from aura.autonomy.agenda import AgendaService
        svc = AgendaService(db)
        expires_at = get_clock().now() + timedelta(hours=settings.finding_expiry_hours)
        item = await svc.create(
            kind="question_for_you",
            content=q_content,
            refs=[qid],
            priority=0.7,
            expires_at=expires_at,
            source="investigation",
        )
        await trace.record(
            "investigation",
            "finding:question_for_you",
            "owner-only question routed to agenda",
            allowed=True,
            refs=[item.id],
            db=db,
        )
        # Post ask_user proposal
        from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
        from aura.orchestrator.workspace import get_workspace
        ws = get_workspace()
        proposal = Proposal(
            source="investigation",
            kind=ProposalKind.ASK_USER,
            summary=f"Question for you: {q_content[:80]}",
            refs=[item.id],
            urgency=0.8,
            value=0.8,
            cost=Cost(tokens=0, seconds=0.0, risk=RiskLevel.READ),
        )
        ws.post(proposal)
        return

    # If finding is resolved and has facts, check relevance
    if state == "resolved" and fact_ids:
        # Calculate relevance using the same logic as B4-01
        # We need to load the context and compute relevance
        from aura.autonomy.curiosity import Context, load_context, relevance
        ctx = await load_context(db)

        # Build a temporary question dict for relevance calculation
        temp_question = {"content": q_content, "id": qid}
        rel = relevance(temp_question, ctx)

        if rel >= settings.finding_share_relevance:
            # Draft summary via L2
            fact_lines = []
            if report:
                from aura.autonomy.investigation import _findings
                fact_lines = _findings(report)

            summary = await _draft_finding_summary(q_content, fact_lines)

            # Create agenda finding item
            from aura.autonomy.agenda import AgendaService
            svc = AgendaService(db)
            refs = [str(fid) for fid in fact_ids] + [qid]
            expires_at = get_clock().now() + timedelta(hours=settings.finding_expiry_hours)
            item = await svc.create(
                kind="finding",
                content=summary or "Found something relevant.",
                refs=refs,
                priority=min(1.0, 0.5 + rel * 0.3),
                expires_at=expires_at,
                source="investigation",
            )
            # Post share proposal
            from aura.models.proposal import Cost, Proposal, ProposalKind, RiskLevel
            from aura.orchestrator.workspace import get_workspace
            ws = get_workspace()
            proposal = Proposal(
                source="investigation",
                kind=ProposalKind.SHARE,
                summary=f"Share finding: {item.content[:80]}",
                refs=[item.id],
                urgency=0.6,
                value=0.6,
                cost=Cost(tokens=0, seconds=0.0, risk=RiskLevel.READ),
            )
            ws.post(proposal)
            await trace.record(
                "investigation",
                "finding:share",
                f"finding item created with relevance {rel:.2f}",
                allowed=True,
                refs=[item.id, qid],
                db=db,
            )
        else:
            await trace.record(
                "investigation",
                "finding:irrelevant",
                f"relevance {rel:.2f} below threshold {settings.finding_share_relevance}",
                allowed=False,
                refs=[qid],
                db=db,
            )