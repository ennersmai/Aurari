"""
Local AI Management API Routes

Provides endpoints for managing local LLM (Ollama) and TTS (Qwen3-TTS) services.
Used by the Mission Control AI Provider Panel.
"""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aura.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/local-ai", tags=["local-ai"])

# Global references (set during startup)
_unified_client = None
_qwen3_tts_engine = None


def set_unified_client(client: Any) -> None:
    """Set the unified LLM client reference."""
    global _unified_client
    _unified_client = client


def set_qwen3_tts_engine(engine: Any) -> None:
    """Set the Qwen3-TTS engine reference."""
    global _qwen3_tts_engine
    _qwen3_tts_engine = engine


# ============================================================================
# REQUEST / RESPONSE MODELS
# ============================================================================

class OllamaStatusResponse(BaseModel):
    available: bool
    base_url: str
    models: list[dict[str, Any]] = []
    error: str | None = None


class ModelPullRequest(BaseModel):
    model_name: str = Field(description="Model to pull, e.g. 'llama3.2', 'qwen2.5:14b'")


class LayerConfigRequest(BaseModel):
    layer: str = Field(description="Layer name: l1, l2, l3, l4, l5")
    provider: str = Field(description="Provider: 'cloud' or 'local'")
    model: str = Field(description="Model identifier")


class AIProviderStatus(BaseModel):
    """Full status of all AI providers for the Mission Control panel."""
    ollama_available: bool = False
    ollama_url: str = ""
    ollama_models: list[dict[str, Any]] = []
    qwen3_tts_available: bool = False
    qwen3_tts_url: str = ""
    fishaudio_available: bool = False
    fishaudio_url: str = ""
    tts_provider: str = "edge"
    local_llm_enabled: bool = False
    fallback_to_cloud: bool = True
    layers: dict[str, dict[str, str]] = {}


# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/status")
async def get_ai_provider_status() -> AIProviderStatus:
    """
    Get comprehensive status of all AI providers.
    Used by Mission Control to populate the AI Provider Panel.
    """
    ollama_available = False
    ollama_models = []
    qwen3_tts_available = False
    fishaudio_available = False

    # Check Ollama status
    if _unified_client:
        try:
            ollama_available = await _unified_client.is_local_available()
            if ollama_available:
                ollama_models = await _unified_client.list_local_models()
        except Exception as e:
            logger.warning(f"Failed to check Ollama status: {e}")

    # Check Qwen3-TTS status
    if _qwen3_tts_engine:
        try:
            qwen3_tts_available = await _qwen3_tts_engine.is_available()
        except Exception:
            pass

    # Check FishAudio status
    try:
        from aura.api.routes.voice import _get_fishaudio
        fishaudio = _get_fishaudio()
        if fishaudio:
            fishaudio_available = await fishaudio.is_available()
    except Exception:
        pass

    # Build layer config — always read from active stack (stack-aware)
    stack_idx = str(settings.model_stack_index)
    layers = {
        "l1": {
            "model": settings.active_l1_model,
            "provider": "local" if settings.active_l1_model.startswith("local/") else "cloud",
            "role": "Instinct (Fast Classification)",
            "stack_index": stack_idx,
        },
        "l2": {
            "model": settings.active_l2_model,
            "provider": "local" if settings.active_l2_model.startswith("local/") else "cloud",
            "role": "Reasoning (Deep Analysis)",
            "stack_index": stack_idx,
        },
        "l3": {
            "model": settings.active_l3_model,
            "provider": "local" if settings.active_l3_model.startswith("local/") else "cloud",
            "role": "Synthesis (Response Generation)",
            "stack_index": stack_idx,
        },
        "l4": {
            "model": settings.active_l4_model,
            "provider": "local" if settings.active_l4_model.startswith("local/") else "cloud",
            "role": "Emotion Analysis",
            "stack_index": stack_idx,
        },
        "l5": {
            "model": settings.active_l5_model,
            "provider": "local" if settings.active_l5_model.startswith("local/") else "cloud",
            "role": "Structure (JSON Extraction)",
            "stack_index": stack_idx,
        },
    }

    return AIProviderStatus(
        ollama_available=ollama_available,
        ollama_url=settings.ollama_base_url,
        ollama_models=ollama_models,
        qwen3_tts_available=qwen3_tts_available,
        qwen3_tts_url=settings.qwen3_tts_base_url,
        fishaudio_available=fishaudio_available,
        fishaudio_url=settings.fish_audio_base_url,
        tts_provider=settings.tts_provider,
        local_llm_enabled=settings.local_llm_enabled,
        fallback_to_cloud=settings.local_llm_fallback_to_cloud,
        layers=layers,
    )


@router.get("/ollama/models")
async def list_ollama_models() -> dict[str, Any]:
    """List all models available in Ollama."""
    if not _unified_client:
        raise HTTPException(status_code=503, detail="Unified client not initialized")

    try:
        models = await _unified_client.list_local_models()
        return {"success": True, "models": models, "count": len(models)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ollama/pull")
async def pull_ollama_model(request: ModelPullRequest) -> dict[str, Any]:
    """Pull (download) a model to Ollama."""
    if not _unified_client:
        raise HTTPException(status_code=503, detail="Unified client not initialized")

    logger.info(f"Pulling Ollama model: {request.model_name}")
    success = await _unified_client.pull_local_model(request.model_name)

    if success:
        return {"success": True, "message": f"Model {request.model_name} pulled successfully"}
    else:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to pull model {request.model_name}"
        )


@router.get("/ollama/health")
async def ollama_health() -> dict[str, Any]:
    """Check if Ollama server is running."""
    if not _unified_client:
        return {"available": False, "error": "Unified client not initialized"}

    available = await _unified_client.is_local_available()
    return {
        "available": available,
        "url": settings.ollama_base_url,
    }


@router.post("/layer/config")
async def update_layer_config(request: LayerConfigRequest) -> dict[str, Any]:
    """
    Update a cognitive layer's model configuration at runtime.
    
    This allows hot-swapping between local and cloud models per layer
    from the Mission Control AI Provider Panel.
    """
    valid_layers = {"l1", "l2", "l3", "l4", "l5"}
    if request.layer not in valid_layers:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid layer: {request.layer}. Must be one of {valid_layers}"
        )

    if request.provider not in ("cloud", "local"):
        raise HTTPException(
            status_code=400,
            detail="Provider must be 'cloud' or 'local'"
        )

    # Build the model identifier
    if request.provider == "local":
        model_id = f"local/{request.model}"
    else:
        model_id = request.model

    # Update settings in-memory (hot-swap)
    layer_attr = f"{request.layer}_model"
    old_model = getattr(settings, layer_attr, None)
    
    # Use object.__setattr__ since pydantic models may be frozen
    object.__setattr__(settings, layer_attr, model_id)

    logger.info(
        f"🔄 Layer {request.layer.upper()} model changed: {old_model} -> {model_id} "
        f"(provider: {request.provider})"
    )

    return {
        "success": True,
        "layer": request.layer,
        "old_model": old_model,
        "new_model": model_id,
        "provider": request.provider,
    }
