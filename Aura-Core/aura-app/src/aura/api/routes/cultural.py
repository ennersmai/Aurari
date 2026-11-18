"""
Cultural routing API endpoints.

Provides federation-ready endpoints for cultural node management and routing.
Designed so other Aura instances can query and sync cultural context.

Endpoints:
  GET  /cultural/nodes   — List all cultural nodes
  POST /cultural/route   — Route to a node based on context signals
  GET  /cultural/active  — Get the currently active node + last decision
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel as PydanticBaseModel, Field

from aura.engines.cultural.router import get_cultural_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cultural", tags=["cultural"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class RouteRequest(PydanticBaseModel):
    """Request body for POST /cultural/route."""
    user_id: str | None = None
    language: str | None = Field(None, description="ISO language code or name, e.g. 'ja', 'russian'")
    location: str | None = Field(None, description="Country code, e.g. 'JP', 'RU'")
    explicit_preference: str | None = Field(None, description="Direct node code override, e.g. 'JP'")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/nodes")
async def list_cultural_nodes() -> dict[str, Any]:
    """
    List all cultural nodes.

    Returns the full set of loaded cultural nodes with their value profiles.
    Federation-ready: includes the node code as a key field on each entry.
    """
    cultural_router = get_cultural_router()
    nodes = await cultural_router.get_all_nodes()
    return {
        "success": True,
        "count": len(nodes),
        "nodes": [n.model_dump() for n in nodes],
    }


@router.post("/route")
async def route_cultural_context(request: RouteRequest) -> dict[str, Any]:
    """
    Route to the best-fit cultural node based on provided signals.

    Priority: explicit_preference > language > location > default.
    Logs the routing decision for audit and federation.
    """
    cultural_router = get_cultural_router()
    try:
        decision = await cultural_router.route(
            user_id=request.user_id,
            language=request.language,
            location=request.location,
            explicit_preference=request.explicit_preference,
        )
        node = await cultural_router.get_node(decision.selected_node)
        return {
            "success": True,
            "decision": decision.model_dump(),
            "node": node.model_dump() if node else None,
        }
    except Exception as e:
        logger.error(f"Cultural routing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/active")
async def get_active_cultural_node() -> dict[str, Any]:
    """
    Get the currently active cultural node and the last routing decision.

    Federation-ready: includes the node code as a top-level field so other
    Aura instances can query which cultural context is active.
    """
    cultural_router = get_cultural_router()
    active = cultural_router.get_active()
    return {
        "success": True,
        **active,
    }
