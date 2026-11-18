"""
Cognitive State API Stubs — /v1/cognition/*

Stub endpoints for the Structural Learning Engine. These provide the
scaffolding for the human collaborator to implement the complex cognitive
logic later. The endpoints are wired into SurrealDB and return properly
shaped Pydantic models.

Endpoints:
  POST   /v1/cognition/experience   — log a cognitive experience
  POST   /v1/cognition/reflect      — trigger reflection on past experiences
  GET    /v1/cognition/patterns     — list extracted patterns
  GET    /v1/cognition/abstractions — list abstractions
  GET    /v1/cognition/skills       — get the skill tree
  GET    /v1/cognition/state        — aggregate cognitive state snapshot
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aura.models.cognition import (
    Abstraction,
    AbstractionLevel,
    CognitiveState,
    Pattern,
    PatternDomain,
    SkillTree,
    SkillTreeNode,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/cognition", tags=["cognition"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class ExperienceLogRequest(BaseModel):
    """Request to log a cognitive experience for pattern extraction."""

    user_id: str = Field(default="default")
    session_id: str = Field(default="main")
    domain: str = Field(default="general", description="e.g., coding, conversation, emotional")
    context: dict[str, Any] = Field(default_factory=dict)
    outcome: dict[str, Any] = Field(default_factory=dict)
    emotional_snapshot: dict[str, float] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)


class ExperienceLogResponse(BaseModel):
    """Response after logging an experience."""

    success: bool
    experience_id: str
    patterns_triggered: list[str] = Field(default_factory=list)
    new_patterns_extracted: int = 0


class ReflectRequest(BaseModel):
    """Request to trigger cognitive reflection."""

    user_id: str = Field(default="default")
    depth: int = Field(default=1, ge=1, le=5, description="Reflection depth (1=light, 5=deep)")
    domain: str | None = None
    experience_ids: list[str] = Field(default_factory=list)


class ReflectResponse(BaseModel):
    """Response after a reflection cycle."""

    success: bool
    reflection_id: str
    patterns_reinforced: list[str] = Field(default_factory=list)
    patterns_deprecated: list[str] = Field(default_factory=list)
    new_abstractions: list[str] = Field(default_factory=list)
    insights: list[str] = Field(default_factory=list)


class PatternsListResponse(BaseModel):
    """Response for listing patterns."""

    success: bool
    count: int
    patterns: list[dict[str, Any]]


class AbstractionsListResponse(BaseModel):
    """Response for listing abstractions."""

    success: bool
    count: int
    abstractions: list[dict[str, Any]]


class SkillTreeResponse(BaseModel):
    """Response for the skill tree."""

    success: bool
    tree: dict[str, Any]
    node_count: int


# ---------------------------------------------------------------------------
# POST /v1/cognition/experience
# ---------------------------------------------------------------------------

@router.post("/experience", response_model=ExperienceLogResponse)
async def log_cognitive_experience(request: ExperienceLogRequest) -> ExperienceLogResponse:
    """
    Log a cognitive experience for future pattern extraction.

    **Status**: STUB — stores the experience in SurrealDB. Pattern extraction
    logic will be implemented by the human collaborator.

    The experience is stored in the ``experience`` table with graph edges
    to any matching patterns, abstractions, and skills.
    """
    from aura.db.client import get_db_client

    db = get_db_client()
    experience_id = f"experience:{int(datetime.utcnow().timestamp() * 1000)}"

    try:
        record = {
            "user_id": request.user_id,
            "session_id": request.session_id,
            "domain": request.domain,
            "context": request.context,
            "outcome": request.outcome,
            "emotional_snapshot": request.emotional_snapshot,
            "tags": request.tags,
            "timestamp": datetime.utcnow(),
            "processed": False,  # Awaiting L2 analysis
        }
        await db.create(experience_id, record)
        logger.info(f"Experience logged: {experience_id} (domain={request.domain})")

        # TODO: Trigger async L2 pattern extraction
        # await trigger_l2_extraction(experience_id)

        return ExperienceLogResponse(
            success=True,
            experience_id=experience_id,
            patterns_triggered=[],
            new_patterns_extracted=0,
        )

    except Exception as e:
        logger.error(f"Failed to log experience: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to log experience: {e}",
        )


# ---------------------------------------------------------------------------
# POST /v1/cognition/reflect
# ---------------------------------------------------------------------------

@router.post("/reflect", response_model=ReflectResponse)
async def trigger_cognitive_reflection(request: ReflectRequest) -> ReflectResponse:
    """
    Trigger a cognitive reflection cycle.

    **Status**: STUB — placeholder. Will invoke the Reflection Engine and
    L2 analysis to consolidate experiences into patterns, reinforce or
    deprecate existing patterns, and generate new abstractions.

    Depth levels:
      1 — Quick review of recent experiences
      2 — Pattern matching against existing patterns
      3 — Cross-domain abstraction generation
      4 — Skill tree update and pruning
      5 — Deep meta-cognitive restructuring
    """
    from aura.db.client import get_db_client

    db = get_db_client()
    reflection_id = f"reflection:{int(datetime.utcnow().timestamp() * 1000)}"

    try:
        # Log the reflection request
        await db.create(reflection_id, {
            "user_id": request.user_id,
            "depth": request.depth,
            "domain": request.domain,
            "experience_ids": request.experience_ids,
            "timestamp": datetime.utcnow().isoformat(),
            "status": "pending",
        })

        logger.info(
            f"Reflection triggered: {reflection_id} "
            f"(depth={request.depth}, domain={request.domain or 'all'})"
        )

        # TODO: Dispatch to Reflection Engine
        # The human collaborator will implement the actual reflection logic
        # here, invoking L2 analysis and the structural learning engine.

        return ReflectResponse(
            success=True,
            reflection_id=reflection_id,
            patterns_reinforced=[],
            patterns_deprecated=[],
            new_abstractions=[],
            insights=["Reflection stub executed — awaiting cognitive logic implementation."],
        )

    except Exception as e:
        logger.error(f"Failed to trigger reflection: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger reflection: {e}",
        )


# ---------------------------------------------------------------------------
# GET /v1/cognition/patterns
# ---------------------------------------------------------------------------

@router.get("/patterns", response_model=PatternsListResponse)
async def list_patterns(
    domain: str | None = None,
    min_confidence: float = 0.0,
    limit: int = 50,
) -> PatternsListResponse:
    """
    List extracted cognitive patterns.

    Optionally filter by domain and minimum confidence.
    """
    from aura.db.client import get_db_client

    db = get_db_client()

    try:
        query = "SELECT * FROM pattern"
        params: dict[str, Any] = {}

        conditions: list[str] = []
        if domain:
            conditions.append("domain = $domain")
            params["domain"] = domain
        if min_confidence > 0:
            conditions.append("confidence >= $min_confidence")
            params["min_confidence"] = min_confidence

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY confidence DESC LIMIT $limit"
        params["limit"] = limit

        result = await db.query(query, params)

        patterns_list: list[dict[str, Any]] = []
        if isinstance(result, list):
            for row in result:
                if isinstance(row, dict):
                    clean = {
                        "pattern_id": str(row.get("id", row.get("pattern_id", ""))),
                        "name": row.get("name", ""),
                        "domain": row.get("domain", "general"),
                        "confidence": row.get("confidence", 0.0),
                        "activation_count": row.get("activation_count", 0),
                        "success_count": row.get("success_count", 0),
                    }
                    patterns_list.append(clean)

        return PatternsListResponse(
            success=True,
            count=len(patterns_list),
            patterns=patterns_list,
        )

    except Exception as e:
        logger.error(f"Failed to list patterns: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list patterns: {e}",
        )


# ---------------------------------------------------------------------------
# GET /v1/cognition/abstractions
# ---------------------------------------------------------------------------

@router.get("/abstractions", response_model=AbstractionsListResponse)
async def list_abstractions(
    level: str | None = None,
    limit: int = 50,
) -> AbstractionsListResponse:
    """
    List cognitive abstractions.

    Optionally filter by abstraction level (raw, pattern, concept, principle, meta).
    """
    from aura.db.client import get_db_client

    db = get_db_client()

    try:
        query = "SELECT * FROM abstraction"
        params: dict[str, Any] = {"limit": limit}

        if level and level in {"raw", "pattern", "concept", "principle", "meta"}:
            query += " WHERE level = $level"
            params["level"] = level

        query += " ORDER BY coherence_score DESC LIMIT $limit"

        result = await db.query(query, params)

        abstractions_list: list[dict[str, Any]] = []
        if isinstance(result, list):
            for row in result:
                if isinstance(row, dict):
                    clean = {
                        "abstraction_id": str(row.get("id", row.get("abstraction_id", ""))),
                        "name": row.get("name", ""),
                        "level": row.get("level", "pattern"),
                        "coherence_score": row.get("coherence_score", 0.0),
                        "evidence_count": row.get("evidence_count", 0),
                        "source_patterns": row.get("source_patterns", []),
                    }
                    abstractions_list.append(clean)

        return AbstractionsListResponse(
            success=True,
            count=len(abstractions_list),
            abstractions=abstractions_list,
        )

    except Exception as e:
        logger.error(f"Failed to list abstractions: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list abstractions: {e}",
        )


# ---------------------------------------------------------------------------
# GET /v1/cognition/skills
# ---------------------------------------------------------------------------

@router.get("/skills", response_model=SkillTreeResponse)
async def get_skill_tree(
    domain: str | None = None,
) -> SkillTreeResponse:
    """
    Get the complete skill tree with hierarchical structure.

    Returns all skill nodes organized by parent-child relationships.
    """
    from aura.db.client import get_db_client

    db = get_db_client()

    try:
        query = "SELECT * FROM skill"
        params: dict[str, Any] = {}

        if domain:
            query += " WHERE domain = $domain"
            params["domain"] = domain

        query += " ORDER BY mastery_level DESC"

        result = await db.query(query, params)

        skills_list: list[dict[str, Any]] = []
        if isinstance(result, list):
            for row in result:
                if isinstance(row, dict):
                    clean = {
                        "skill_id": str(row.get("id", row.get("skill_id", ""))),
                        "name": row.get("name", "Unknown"),
                        "node_type": row.get("node_type", "skill"),
                        "domain": row.get("domain", "general"),
                        "mastery_level": row.get("mastery_level", 0.0),
                        "parent_skill_id": str(row.get("parent_skill_id", "")) or None,
                        "child_skill_ids": [str(c) for c in (row.get("child_skill_ids") or [])],
                        "practice_count": row.get("practice_count", 0),
                        "last_practiced": str(row.get("last_practiced", "")) or None,
                    }
                    skills_list.append(clean)

        # Build tree structure
        tree: dict[str, Any] = {
            "name": "Aura Skill Tree",
            "root_nodes": [],
        }
        nodes_by_id: dict[str, dict[str, Any]] = {s["skill_id"]: {**s, "children": []} for s in skills_list}

        for node in skills_list:
            parent_id = node.get("parent_skill_id")
            if parent_id and parent_id in nodes_by_id:
                nodes_by_id[parent_id]["children"].append(nodes_by_id[node["skill_id"]])
            else:
                tree["root_nodes"].append(nodes_by_id[node["skill_id"]])

        return SkillTreeResponse(
            success=True,
            tree=tree,
            node_count=len(skills_list),
        )

    except Exception as e:
        logger.error(f"Failed to get skill tree: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get skill tree: {e}",
        )


# ---------------------------------------------------------------------------
# GET /v1/cognition/state
# ---------------------------------------------------------------------------

@router.get("/state")
async def get_cognitive_state() -> dict[str, Any]:
    """
    Get an aggregate snapshot of the cognitive architecture.

    Returns counts, averages, and top-level metrics for patterns,
    abstractions, and skills.
    """
    from aura.db.client import get_db_client

    db = get_db_client()

    try:
        # Query counts
        patterns_result = await db.query("SELECT count() as count FROM pattern GROUP ALL")
        abstractions_result = await db.query("SELECT count() as count FROM abstraction GROUP ALL")
        skills_result = await db.query("SELECT count() as count FROM skill GROUP ALL")

        def extract_count(result: Any) -> int:
            if isinstance(result, list) and len(result) > 0:
                item = result[0]
                if isinstance(item, dict):
                    return int(item.get("count", 0))
            return 0

        pattern_count = extract_count(patterns_result)
        abstraction_count = extract_count(abstractions_result)
        skill_count = extract_count(skills_result)

        state = CognitiveState(
            timestamp=datetime.utcnow(),
            pattern_count=pattern_count,
            abstraction_count=abstraction_count,
            skill_count=skill_count,
        )

        return {
            "success": True,
            "state": state.model_dump(),
        }

    except Exception as e:
        logger.error(f"Failed to get cognitive state: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cognitive state: {e}",
        )


# ---------------------------------------------------------------------------
# GET /v1/cognition/latent-state — TITANS Latent Memory Diagnostics
# ---------------------------------------------------------------------------

@router.get("/latent-state")
async def get_latent_state(user_id: str = "default") -> dict[str, Any]:
    """
    Get the TITANS latent memory state diagnostics for a user.

    Returns the latent state summary, surprise statistics, emotional centroid,
    domain distribution, and drift information.
    """
    try:
        from aura.engines.latent.engine import get_latent_engine
        engine = get_latent_engine()
        diagnostics = engine.get_state_diagnostics(user_id)
        return {"success": True, "latent_state": diagnostics}
    except Exception as e:
        logger.error(f"Failed to get latent state: {e}")
        return {
            "success": False,
            "latent_state": {"status": "unavailable", "error": str(e)},
        }
