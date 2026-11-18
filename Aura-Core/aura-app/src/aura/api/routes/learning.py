"""Learning Engine API routes."""

from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from aura.models.learning import LearningContext, Insight

router = APIRouter()

# Global learning engine reference (will be set by main.py)
_learning_engine: Any = None


def set_learning_engine(engine: Any) -> None:
    """Set the global learning engine instance."""
    global _learning_engine
    _learning_engine = engine


def get_learning_engine() -> Any:
    """Get the learning engine or raise error."""
    if _learning_engine is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Learning engine not initialized",
        )
    return _learning_engine


class ExperienceRequest(BaseModel):
    """Request model for logging experience."""

    user_id: str = Field(default="default")
    task_type: str = Field(..., description="e.g., 'code_debugging', 'conversation'")
    domain: str = Field(..., description="e.g., 'javascript', 'philosophy'")
    context: dict[str, Any] = Field(..., description="Task context")
    aura_response: dict[str, Any] = Field(..., description="Aura's response")
    outcome: dict[str, Any] = Field(..., description="Result of interaction")
    emotional_state: dict[str, Any] = Field(default_factory=dict)


class InsightRequest(BaseModel):
    """Request model for creating an insight."""

    content: str
    type: str = Field(default="PATTERN", description="FACT, PREFERENCE, or PATTERN")
    domain: str = "general"
    user_id: str = "default"
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    emotional_signature: dict[str, float] = Field(default_factory=dict)


class InsightFeedbackRequest(BaseModel):
    """Request model for insight application feedback."""

    insight_id: str
    success: bool


@router.post("/experience")
async def log_experience(request: ExperienceRequest) -> dict[str, Any]:
    """
    Log an interaction experience for learning.

    This captures:
    - User query and context
    - Aura's response and reasoning
    - Outcome (success/failure)
    - Emotional state during interaction

    Experiences are clustered for pattern extraction.
    """
    engine = get_learning_engine()

    try:
        experience_id = await engine.log_experience(request.model_dump())

        return {
            "success": True,
            "experience_id": experience_id,
            "message": "Experience logged successfully",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to log experience: {str(e)}",
        )


@router.get("/insights")
async def get_insights(
    domain: str | None = None,
    confidence_min: float = 0.5,
    user_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Retrieve learned insights with filters.
    
    Automatically excludes deprecated insights.

    Args:
        domain: Filter by domain
        confidence_min: Minimum confidence threshold
        user_id: Filter for user-specific insights
        limit: Maximum insights to return

    Returns:
        List of insights matching criteria (excluding deprecated)
    """
    engine = get_learning_engine()

    try:
        # For generic retrieval, use empty context
        # retrieve_relevant already filters out deprecated insights
        insights = await engine.retrieve_relevant(
            context="",
            domain=domain,
            confidence_min=confidence_min,
            user_id=user_id,
            limit=limit,
        )

        return {
            "success": True,
            "count": len(insights),
            "insights": [insight.model_dump() for insight in insights],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve insights: {str(e)}",
        )


@router.post("/insights")
async def create_insight(request: InsightRequest) -> dict[str, Any]:
    """
    Manually create a learned insight.

    Typically insights are extracted automatically from patterns,
    but this allows manual insight creation for bootstrapping.
    """
    engine = get_learning_engine()

    try:
        insight_id = await engine.create_insight(request.model_dump())

        return {
            "success": True,
            "insight_id": insight_id,
            "message": "Insight created successfully",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create insight: {str(e)}",
        )


@router.post("/insights/feedback")
async def submit_insight_feedback(request: InsightFeedbackRequest) -> dict[str, Any]:
    """
    Submit feedback on insight application.

    Updates insight confidence via Bayesian updating based on success/failure.
    """
    engine = get_learning_engine()

    try:
        await engine.update_insight_confidence(
            insight_id=request.insight_id,
            success=request.success,
        )

        return {
            "success": True,
            "message": "Insight confidence updated",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update insight: {str(e)}",
        )


@router.delete("/insights/{insight_id}")
async def delete_insight(insight_id: str) -> dict[str, Any]:
    """
    Physically delete an insight from the database.
    
    Permanently removes the insight record. This action cannot be undone.
    """
    from aura.db.client import get_db_client
    import logging
    
    logger = logging.getLogger(__name__)
    db = get_db_client()
    
    try:
        # Check if insight exists
        result = await db.select(insight_id)
        if not result or len(result) == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Insight {insight_id} not found",
            )
        
        # Physically delete the insight
        await db.delete(insight_id)
        
        logger.info(f"Insight {insight_id} physically deleted from database")
        
        return {
            "success": True,
            "message": "Insight deleted successfully",
            "insight_id": insight_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete insight {insight_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete insight: {str(e)}",
        )


@router.get("/context")
async def get_learning_context(
    context: str,
    domain: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """
    Get complete learning context for LLM injection.

    Returns:
        - Relevant insights
        - Overall confidence level
        - Mastery level in domain
        - Emotional associations
    """
    engine = get_learning_engine()

    try:
        learning_context = await engine.get_learning_context(
            context=context, domain=domain, user_id=user_id
        )

        return {
            "success": True,
            "context": learning_context.model_dump(),
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get learning context: {str(e)}",
        )


@router.get("/skills")
async def get_skills(domain: str | None = None) -> dict[str, Any]:
    """
    Get all skills, optionally filtered by domain.

    Returns hierarchical skill tree structure.
    """
    engine = get_learning_engine()

    try:
        skills = await engine.get_skills_by_domain(domain) if domain else []

        return {
            "success": True,
            "count": len(skills),
            "skills": [skill.model_dump() for skill in skills],
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve skills: {str(e)}",
        )


@router.get("/skills/{skill_id}/mastery")
async def get_skill_mastery(skill_id: str) -> dict[str, Any]:
    """
    Calculate and return mastery level for a skill.

    Mastery is calculated from:
    - Sub-skill masteries
    - Insight confidence levels
    - Recent application success rates
    """
    engine = get_learning_engine()

    try:
        skill = await engine.get_skill(skill_id)

        if not skill:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill not found: {skill_id}",
            )

        # Mastery calculation handled by skill tree manager
        from aura.engines.learning.skills import SkillTreeManager

        skill_tree = SkillTreeManager()
        mastery = await skill_tree.calculate_mastery(skill_id)

        return {
            "success": True,
            "skill_id": skill_id,
            "name": skill.name,
            "mastery_level": mastery,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate mastery: {str(e)}",
        )


@router.post("/tools/ingest")
async def ingest_local_tool(module_name: str) -> dict[str, Any]:
    """
    Ingest a local tool module from src/aura/tools/.
    
    This registers a local Python tool as a skill that Aura can use.
    The tool file must expose:
    - TOOL_DEFINITION: JSON Schema describing the tool
    - run(arguments: Dict[str, Any]) -> str: Async function that executes the tool
    
    Args:
        module_name: Name of the module file (without .py extension)
                    e.g., "web_search" for src/aura/tools/web_search.py
    
    Returns:
        Success message with tool name
    """
    engine = get_learning_engine()
    
    try:
        result = await engine.ingest_local_tool_module(module_name)
        
        return {
            "success": True,
            "message": result,
            "module_name": module_name,
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to ingest tool module: {str(e)}",
        )


@router.get("/status")
async def get_engine_status() -> dict[str, Any]:
    """Get learning engine status."""
    engine = get_learning_engine()

    status_info = engine.get_status()
    status_info["experiences_logged"] = engine.experiences_logged
    status_info["insights_created"] = engine.insights_created

    return {"success": True, "status": status_info}


@router.get("/skills/registry")
async def get_skill_registry() -> dict[str, Any]:
    """
    Retrieves all active skills (both abstract and executable tools) for visualization.
    
    Returns a complete registry of all skills in the system, including:
    - Skill metadata (name, domain, mastery level)
    - Tool execution configuration (if applicable)
    - Skill hierarchy information
    """
    engine = get_learning_engine()
    
    try:
        # Use the skill tree manager to get all skills
        from aura.engines.learning.skills import SkillTreeManager
        skill_tree = SkillTreeManager()
        
        # Fetch all skills from database
        skills = await skill_tree.get_all_skills(domain=None)
        
        # Clean up the results - convert SurrealDB RecordIDs to strings
        clean_skills = []
        for skill in skills:
            # Extract skill_id from the record
            skill_id = skill.get('id', skill.get('skill_id', ''))
            if isinstance(skill_id, dict) and 'id' in skill_id:
                skill_id = skill_id['id']
            skill_id = str(skill_id)
            
            # Convert RecordID objects to strings for serialization
            parent_id = skill.get('parent_skill_id')
            if parent_id:
                # Handle RecordID objects from SurrealDB
                from surrealdb.data.types.record_id import RecordID
                if isinstance(parent_id, RecordID):
                    parent_id = str(parent_id)
                elif not isinstance(parent_id, str):
                    parent_id = str(parent_id)
            
            sub_skill_ids = skill.get('sub_skill_ids', [])
            # Convert any RecordID objects in sub_skill_ids array to strings
            if sub_skill_ids:
                from surrealdb.data.types.record_id import RecordID
                sub_skill_ids = [
                    str(sid) if isinstance(sid, RecordID) else str(sid) if sid else None
                    for sid in sub_skill_ids
                ]
                # Filter out None values
                sub_skill_ids = [sid for sid in sub_skill_ids if sid]
            
            # Build cleaned skill object
            clean_skill = {
                'skill_id': skill_id,
                'name': skill.get('name', 'Unknown'),
                'domain': skill.get('domain', 'general'),
                'mastery_level': skill.get('mastery_level', 0.0),
                'skill_type': skill.get('skill_type', 'abstract'),  # abstract, local_function, etc.
                'created': str(skill.get('created', '')),
                'last_practiced': str(skill.get('last_practiced', '')) if skill.get('last_practiced') else None,
                'emotional_signature': skill.get('emotional_signature', {}),
                'parent_skill_id': parent_id,
                'sub_skill_ids': sub_skill_ids,
            }
            
            # Add execution config if it's a tool
            if skill.get('execution_config'):
                clean_skill['execution_config'] = skill.get('execution_config')
            
            # Truncate definition if present (for display purposes)
            if skill.get('definition'):
                definition = skill.get('definition', '')
                if len(definition) > 200:
                    clean_skill['definition'] = definition[:200] + "..."
                else:
                    clean_skill['definition'] = definition
            
            clean_skills.append(clean_skill)
        
        return {
            "success": True,
            "count": len(clean_skills),
            "skills": clean_skills
        }
        
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to fetch skill registry: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve skill registry: {str(e)}"
        )


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str) -> dict[str, Any]:
    """
    Delete a skill from the database.
    
    This will permanently remove the skill and allow you to re-ingest it.
    
    Args:
        skill_id: The ID of the skill to delete (e.g., "skill:abc123")
    
    Returns:
        Success message with deleted skill ID
    """
    try:
        from aura.engines.learning.skills import SkillTreeManager
        skill_tree = SkillTreeManager()
        
        # Attempt to delete the skill
        success = await skill_tree.delete_skill(skill_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill not found: {skill_id}"
            )
        
        return {
            "success": True,
            "message": f"Skill {skill_id} deleted successfully",
            "skill_id": skill_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete skill {skill_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete skill: {str(e)}"
        )


@router.get("/skills/{skill_id}/triggers")
async def get_skill_triggers(skill_id: str) -> dict[str, Any]:
    """
    Fetch semantic trigger phrases for a given skill.

    This is used by the frontend System tab to show background trigger generation progress/results.
    """
    engine = get_learning_engine()

    try:
        # Ensure we query with a proper RecordID when possible (SurrealDB compares record<skill> values)
        skill_ref: Any = skill_id
        try:
            from surrealdb import RecordID
            if ":" in skill_id:
                table, rid = skill_id.split(":", 1)
                skill_ref = RecordID(table, rid)
        except Exception:
            skill_ref = skill_id

        rows = await engine.db.query(
            """
            SELECT phrase, confidence
            FROM semantic_trigger
            WHERE target_action = $skill
            ORDER BY phrase
            """,
            {"skill": skill_ref},
        )

        triggers = [r.get("phrase") for r in rows if isinstance(r, dict) and isinstance(r.get("phrase"), str)]

        return {
            "success": True,
            "skill_id": skill_id,
            "count": len(triggers),
            "triggers": triggers,
        }

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to fetch triggers for skill {skill_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve triggers for skill {skill_id}: {str(e)}"
        )