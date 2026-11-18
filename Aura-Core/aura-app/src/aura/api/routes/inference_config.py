"""Inference Cockpit API Routes

GET  /system/inference-config  — read current live inference configuration
POST /system/inference-config  — hot-swap any parameter without restarting

All mutations propagate immediately: every subsequent LLM request reads from
`settings` at invocation time (not at object construction), so there is zero
latency between a UI change and the next model call.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(tags=["inference-config"])
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema — shared between GET response and POST body
# ---------------------------------------------------------------------------

class InferenceConfig(BaseModel):
    """Complete snapshot of the live inference cockpit state."""

    # ── Sampling ──────────────────────────────────────────────────────────
    temperature: float = Field(0.7, ge=0.0, le=2.0,
        description="Generation temperature (0=deterministic, 1.5=very creative)")
    top_p: float = Field(0.9, ge=0.0, le=1.0,
        description="Nuclear sampling nucleus (tokens outside top-p are discarded)")
    min_p: float = Field(0.05, ge=0.0, le=1.0,
        description="Min-P: minimum probability relative to top token")
    frequency_penalty: float = Field(0.0, ge=-2.0, le=2.0,
        description="Penalize tokens proportional to past frequency")
    presence_penalty: float = Field(0.0, ge=-2.0, le=2.0,
        description="Flat penalty for any token that appeared in context")
    context_length: int = Field(8192, ge=2048, le=131072,
        description="Max context window in tokens (3090 VRAM safeguard)")
    max_tokens: int = Field(2048, ge=256, le=32768,
        description="Max new tokens to generate per L3 response")

    # ── Layer toggles ─────────────────────────────────────────────────────
    layer_l1_enabled: bool = Field(True,
        description="L1 Instinct: intent classification & vector routing")
    layer_l2_enabled: bool = Field(True,
        description="L2 Reasoning: async deep analysis (post-response)")
    layer_l3_enabled: bool = Field(True,
        description="L3 Synthesis: primary response generation")
    layer_l4_enabled: bool = Field(True,
        description="L4 Emotion: post-response emotion delta analysis")
    layer_l5_enabled: bool = Field(True,
        description="L5 Structure: JSON extraction & retry logic")

    # ── Routing ───────────────────────────────────────────────────────────
    local_mode_enabled: bool = Field(False,
        description="Route LLM calls to local Ollama endpoint")
    sglang_enabled: bool = Field(False,
        description="Enable SGLang constrained sampler for L1/L3")
    model_stack_index: int = Field(0, ge=0, le=2,
        description="Active model stack: 0=Lean, 1=Core, 2=Titan")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/inference-config", response_model=InferenceConfig)
async def get_inference_config() -> InferenceConfig:
    """Return the current live inference configuration."""
    from aura.config import settings

    return InferenceConfig(
        temperature=settings.inference_temperature,
        top_p=settings.inference_top_p,
        min_p=settings.inference_min_p,
        frequency_penalty=settings.inference_frequency_penalty,
        presence_penalty=settings.inference_presence_penalty,
        context_length=settings.inference_context_length,
        max_tokens=settings.inference_max_tokens,
        layer_l1_enabled=settings.layer_l1_enabled,
        layer_l2_enabled=settings.layer_l2_enabled,
        layer_l3_enabled=settings.layer_l3_enabled,
        layer_l4_enabled=settings.layer_l4_enabled,
        layer_l5_enabled=settings.layer_l5_enabled,
        local_mode_enabled=settings.local_llm_enabled,
        sglang_enabled=settings.sglang_enabled,
        model_stack_index=settings.model_stack_index,
    )


@router.post("/inference-config")
async def set_inference_config(config: InferenceConfig) -> dict[str, Any]:
    """Hot-swap the live inference configuration.

    Uses ``object.__setattr__`` to bypass Pydantic's frozen model so that
    mutation is safe without reloading the module.  Every subsequent LLM
    call picks up the new values because the layer methods read from
    ``settings`` at invocation time.
    """
    from aura.config import settings

    _set = lambda attr, val: object.__setattr__(settings, attr, val)  # noqa: E731

    _set("inference_temperature",    config.temperature)
    _set("inference_top_p",          config.top_p)
    _set("inference_min_p",          config.min_p)
    _set("inference_frequency_penalty", config.frequency_penalty)
    _set("inference_presence_penalty",  config.presence_penalty)
    _set("inference_context_length",  config.context_length)
    _set("inference_max_tokens",      config.max_tokens)
    _set("layer_l1_enabled",          config.layer_l1_enabled)
    _set("layer_l2_enabled",          config.layer_l2_enabled)
    _set("layer_l3_enabled",          config.layer_l3_enabled)
    _set("layer_l4_enabled",          config.layer_l4_enabled)
    _set("layer_l5_enabled",          config.layer_l5_enabled)
    _set("local_llm_enabled",         config.local_mode_enabled)
    _set("sglang_enabled",            config.sglang_enabled)
    _set("model_stack_index",         config.model_stack_index)

    logger.info(
        "🎛️  Inference cockpit updated — temp=%.2f top_p=%.2f min_p=%.2f "
        "ctx=%d max_tokens=%d stack=%d local=%s sglang=%s | "
        "L1=%s L2=%s L3=%s L4=%s L5=%s",
        config.temperature, config.top_p, config.min_p,
        config.context_length, config.max_tokens,
        config.model_stack_index, config.local_mode_enabled, config.sglang_enabled,
        config.layer_l1_enabled, config.layer_l2_enabled, config.layer_l3_enabled,
        config.layer_l4_enabled, config.layer_l5_enabled,
    )

    return {
        "success": True,
        "config": config.model_dump(),
        "active_models": {
            "l1": settings.active_l1_model,
            "l2": settings.active_l2_model,
            "l3": settings.active_l3_model,
            "l4": settings.active_l4_model,
            "l5": settings.active_l5_model,
            "embeddings": settings.active_embeddings_model,
        },
    }
