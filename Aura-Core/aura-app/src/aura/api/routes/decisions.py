"""Decision API routes for owner approval management."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from aura.executor.decisions import get_decision_service

router = APIRouter(prefix="/decisions", tags=["decisions"])


class DecisionResponse(BaseModel):
    """Response model for a single decision."""
    success: bool = True
    decision: dict | None = None
    message: str = ""


class DecisionListResponse(BaseModel):
    """Response model for decision list."""
    success: bool = True
    decisions: list[dict] = []
    count: int = 0


class AnswerRequest(BaseModel):
    """Request model for answering a decision."""
    allow: bool


@router.get("", response_model=DecisionListResponse)
async def list_pending_decisions() -> DecisionListResponse:
    """List all pending decisions, newest first.

    Returns:
        List of pending decisions
    """
    service = get_decision_service()
    decisions = await service.pending()
    return DecisionListResponse(
        decisions=decisions,
        count=len(decisions),
    )


@router.post("/{decision_id}", response_model=DecisionResponse)
async def answer_decision(decision_id: str, request: AnswerRequest) -> DecisionResponse:
    """Answer a pending decision (allow or deny).

    Args:
        decision_id: The decision ID (e.g., "decision:abc123")
        request: {"allow": true|false}

    Returns:
        The updated decision record

    Raises:
        404: Decision not found
        400: Decision is not pending
        503: OpenCode client not configured
    """
    service = get_decision_service()
    
    try:
        decision = await service.answer(decision_id, request.allow, "owner")
        return DecisionResponse(
            decision=decision,
            message=f"Decision {request.allow and 'allowed' or 'denied'}",
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))