"""System state machine API routes (Sleep/Wake cycle)."""

from typing import Any
import asyncio
import logging
import os

from fastapi import APIRouter, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, Field

router = APIRouter()

# Global orchestrator reference (will be set by main.py)
_orchestrator: Any = None
logger = logging.getLogger(__name__)


def set_orchestrator(orchestrator: Any) -> None:
    """Set the global orchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator


def get_orchestrator() -> Any:
    """Get the orchestrator or raise error."""
    if _orchestrator is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Orchestrator not initialized",
        )
    return _orchestrator


class ForceStateRequest(BaseModel):
    """Request body for forcing sleep/wake."""

    user_id: str = Field(default="default")


class WakeResponse(BaseModel):
    """Wake endpoint response."""

    greeting: str
    state: dict[str, Any]


@router.get("/state")
async def get_system_state() -> dict[str, Any]:
    """Get current system state."""
    orchestrator = get_orchestrator()
    return await orchestrator.get_system_state()


@router.post("/state/sleep")
async def force_sleep(request: ForceStateRequest) -> dict[str, Any]:
    """Force the system into DREAMING -> SLEEPING sequence."""
    orchestrator = get_orchestrator()
    return await orchestrator.enter_sleep_mode(user_id=request.user_id, forced=True)


@router.post("/state/wake", response_model=WakeResponse)
async def force_wake(request: ForceStateRequest) -> WakeResponse:
    """Force the system to wake to ACTIVE and return a greeting."""
    orchestrator = get_orchestrator()
    greeting = await orchestrator.wake_up(user_id=request.user_id, forced=True)
    state = await orchestrator.get_system_state()
    return WakeResponse(greeting=greeting, state=state)


@router.post("/restart")
async def trigger_restart(background_tasks: BackgroundTasks) -> dict[str, Any]:
    """
    Trigger a soft restart of the backend process.

    Docker restart policy for the backend container should be set to 'always' or 'unless-stopped'
    so the process is respawned automatically after exit.
    """
    orchestrator = get_orchestrator()
    logger.warning("🔄 SYSTEM RESTART TRIGGERED VIA /system/restart")

    # 1. Best-effort: consolidate memory before shutdown
    try:
        # 'default' matches the default user_id used elsewhere for maintenance
        coro = orchestrator.learning_engine.consolidate_memory("default")
        # Run with timeout guard so restart isn't blocked indefinitely
        await asyncio.wait_for(coro, timeout=10.0)
    except Exception as e:  # pragma: no cover - defensive
        logger.error(f"Failed to save state before restart: {e}")

    # 2. Kill the process after a short delay so the HTTP 200 response is sent first
    async def _kill() -> None:
        await asyncio.sleep(1.0)
        logger.info("👋 Goodbye. Initiating process exit for Docker restart.")
        os._exit(0)

    background_tasks.add_task(_kill)
    return {"status": "restarting", "message": "System is rebooting..."}


class ModelStackRequest(BaseModel):
    """Request body for switching model stacks."""

    stack_index: int = Field(
        default=0,
        ge=0,
        le=2,
        description="Model stack index: 0 (default), 1 (stack1), 2 (stack2)"
    )


@router.get("/model-stack")
async def get_model_stack() -> dict[str, Any]:
    """Get current model stack configuration."""
    from aura.config import settings

    return {
        "stack_index": settings.model_stack_index,
        "models": {
            "l1": settings.active_l1_model,
            "l2": settings.active_l2_model,
            "l3": settings.active_l3_model,
            "l4": settings.active_l4_model,
            "l5": settings.active_l5_model,
            "embeddings": settings.active_embeddings_model,
            "embeddings_dimension": settings.active_embeddings_dimension,
        },
        "available_stacks": [
            {
                "index": index,
                **{f"l{n}": getattr(settings, f"l{n}_model{suffix}") for n in range(1, 6)},
            }
            for index, suffix in ((0, ""), (1, "1"), (2, "2"))
        ],
    }


@router.post("/model-stack")
async def set_model_stack(request: ModelStackRequest) -> dict[str, Any]:
    """
    Switch the active model stack at runtime.

    This updates the in-memory settings.model_stack_index, which
    immediately affects all subsequent LLM calls via active_l*_model properties.
    """
    from aura.config import settings

    old_index = settings.model_stack_index
    object.__setattr__(settings, "model_stack_index", request.stack_index)

    logger.info(
        f"🔄 Model stack switched: {old_index} → {request.stack_index} "
        f"(L3: {settings.active_l3_model})"
    )

    return {
        "success": True,
        "previous_stack": old_index,
        "current_stack": request.stack_index,
        "active_models": {
            "l1": settings.active_l1_model,
            "l2": settings.active_l2_model,
            "l3": settings.active_l3_model,
            "l4": settings.active_l4_model,
            "l5": settings.active_l5_model,
            "embeddings": settings.active_embeddings_model,
        },
    }
