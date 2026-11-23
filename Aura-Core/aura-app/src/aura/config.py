"""Application configuration using Pydantic Settings."""

import logging

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# (stack, layer) pairs already warned about an unset per-stack fallback.
_FALLBACK_WARNED: set[tuple[int, str]] = set()


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # SurrealDB Configuration
    surreal_url: str = Field(
        default="ws://localhost:8000/rpc",
        validation_alias="SURREAL_URL"
    )
    surreal_user: str = Field(
        default="root",
        validation_alias="SURREAL_USER"
    )
    surreal_pass: str = Field(
        default="root",
        validation_alias="SURREAL_PASS"
    )
    surreal_ns: str = Field(
        default="aura",
        validation_alias="SURREAL_NS"
    )
    surreal_db: str = Field(
        default="main",
        validation_alias="SURREAL_DB"
    )

    # OpenRouter API Configuration
    openrouter_api_key: str = Field(default="")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")

    # =========================================================================
    # LOCAL LLM (Ollama) Configuration
    # =========================================================================
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="AURA_OLLAMA_URL",
        description="Ollama server URL for local LLM inference",
    )

    # -------------------------------------------------------------------------
    # CONTEXT-MODE INFERENCE ROUTING (Sovereign Orchestrator)
    # -------------------------------------------------------------------------
    local_inference_url: str = Field(
        default="http://127.0.0.1:8000/v1/chat/completions",
        validation_alias="AURA_LOCAL_INFERENCE_URL",
        description="OpenAI-compatible endpoint for private_rp context mode "
                    "(llama.cpp server, text-generation-webui, vLLM, Ollama API, etc.)",
    )
    local_inference_api_key: str = Field(
        default="",
        validation_alias="AURA_LOCAL_INFERENCE_API_KEY",
        description="Optional API key for local inference endpoint (e.g., vLLM auth)",
    )
    local_inference_timeout: float = Field(
        default=300.0,
        validation_alias="AURA_LOCAL_INFERENCE_TIMEOUT",
        description="Timeout in seconds for local inference requests (models can be slow on cold start)",
    )

    local_llm_enabled: bool = Field(
        default=False,
        validation_alias="AURA_LOCAL_LLM_ENABLED",
        description="Master switch: enable local LLM inference via Ollama",
    )
    local_llm_fallback_to_cloud: bool = Field(
        default=True,
        validation_alias="AURA_LOCAL_LLM_FALLBACK_TO_CLOUD",
        description="If local model fails, automatically fall back to cloud",
    )

    # =========================================================================
    # LOCAL TTS (Qwen3-TTS) Configuration
    # =========================================================================
    qwen3_tts_base_url: str = Field(
        default="http://localhost:50000",
        validation_alias="AURA_QWEN3_TTS_URL",
        description="Qwen3-TTS server URL for local TTS with voice cloning and emotional control",
    )
    qwen3_tts_enabled: bool = Field(
        default=True,
        validation_alias="AURA_QWEN3_TTS_ENABLED",
        description="Enable local Qwen3-TTS (voice cloning + emotional control). Auto-detects availability; fallback to Edge-TTS is automatic.",
    )
    qwen3_tts_default_speaker: str = Field(
        default="serena",
        validation_alias="AURA_QWEN3_TTS_SPEAKER",
        description="Default speaker/voice for Qwen3-TTS (serena, vivian, ryan, aiden, ono_anna, sohee, eric, dylan, uncle_fu)",
    )
    qwen3_tts_model_dir: str = Field(
        default="./Qwen3-TTS",
        validation_alias="AURA_QWEN3_TTS_MODEL_DIR",
        description="Path to Qwen3-TTS model directory",
    )
    tts_provider: str = Field(
        default="edge",
        validation_alias="AURA_TTS_PROVIDER",
        description="TTS provider: 'edge' (cloud Edge-TTS), 'qwen3' (local Qwen3-TTS), or 'fishaudio' (local FishAudio)",
    )

    # =========================================================================
    # LOCAL TTS (FishAudio / Fish-Speech) Configuration
    # =========================================================================
    fish_audio_base_url: str = Field(
        default="http://localhost:50001",
        validation_alias="AURA_FISH_AUDIO_URL",
        description="FishAudio server URL for local TTS with voice cloning",
    )
    fish_audio_enabled: bool = Field(
        default=True,
        validation_alias="AURA_FISH_AUDIO_ENABLED",
        description="Enable local FishAudio (voice cloning + multi-speaker). Auto-detects availability; fallback to Edge-TTS is automatic.",
    )
    fish_audio_default_speaker: str = Field(
        default="default",
        validation_alias="AURA_FISH_AUDIO_SPEAKER",
        description="Default speaker/voice for FishAudio",
    )
    fish_audio_model_dir: str = Field(
        default="./FishAudio",
        validation_alias="AURA_FISH_AUDIO_MODEL_DIR",
        description="Path to FishAudio (fish-speech-1.5) model directory",
    )

    # =========================================================================
    # MODEL STACK INDEX — Live-switch between 3 model configurations
    # 0 = Default stack (AURA_L1_MODEL, etc.)
    # 1 = Stack 1 (AURA_L1_MODEL1, etc.)
    # 2 = Stack 2 (AURA_L1_MODEL2, etc.)
    # =========================================================================
    model_stack_index: int = Field(
        default=0,
        validation_alias="AURA_MODEL_STACK_INDEX",
        description="Active model stack: 0 (default), 1 (stack1), 2 (stack2). Hot-swappable at runtime.",
        ge=0,
        le=2,
    )

    # LLM Model Configuration (Hot-Swappable via Environment Variables)
    # --- DEFAULT STACK (index 0) ---
    l1_model: str = Field(
        default="google/gemini-2.0-flash-001",
        validation_alias="AURA_L1_MODEL",
        description="L1 Instinct Layer - Fast responses (<500ms)",
    )
    l1_model_fallback: str | None = Field(
        default=None,
        validation_alias="AURA_L1_MODEL_FALLBACK",
        description="L1 Fallback Model - Used when primary model fails (rate limit/5xx)",
    )
    l2_model: str = Field(
        default="anthropic/claude-3.5-sonnet",
        validation_alias="AURA_L2_MODEL",
        description="L2 Reasoning Layer - Deep analysis (async)",
    )
    l2_model_fallback: str | None = Field(
        default=None,
        validation_alias="AURA_L2_MODEL_FALLBACK",
        description="L2 Fallback Model - Used when primary model fails (rate limit/5xx)",
    )
    l3_model: str = Field(
        default="deepseek/deepseek-chat",
        validation_alias="AURA_L3_MODEL",
        description="L3 Synthesis Layer - Primary response generation",
    )
    l3_model_fallback: str | None = Field(
        default=None,
        validation_alias="AURA_L3_MODEL_FALLBACK",
        description="L3 Fallback Model - Used when primary model fails (rate limit/5xx)",
    )
    l4_model: str = Field(
        default="qwen/qwen-2.5-72b-instruct",
        validation_alias="AURA_L4_MODEL",
        description="L4 Emotion Analysis Layer - Emotion detection from conversation (async).",
    )
    l4_model_fallback: str | None = Field(
        default=None,
        validation_alias="AURA_L4_MODEL_FALLBACK",
        description="L4 Fallback Model - Used when primary model fails (rate limit/5xx)",
    )
    l5_model: str = Field(
        default="google/gemini-2.0-flash-001",
        validation_alias="AURA_L5_MODEL",
        description="L5 Structure Layer - Specialized for JSON extraction, summarization, and structural tasks.",
    )
    l5_model_fallback: str | None = Field(
        default=None,
        validation_alias="AURA_L5_MODEL_FALLBACK",
        description="L5 Fallback Model - Used when primary model fails (rate limit/5xx)",
    )

    # --- PER-STACK FALLBACKS (stack 1 = FALLBACK1, stack 2 = FALLBACK2) ---
    l1_model_fallback1: str | None = Field(
        default=None,
        validation_alias="AURA_L1_MODEL_FALLBACK1",
        description="Stack 1: L1 Fallback Model. Unset: the shared AURA_L1_MODEL_FALLBACK is used (warns once).",
    )
    l1_model_fallback2: str | None = Field(
        default=None,
        validation_alias="AURA_L1_MODEL_FALLBACK2",
        description="Stack 2: L1 Fallback Model. Unset: the shared AURA_L1_MODEL_FALLBACK is used (warns once).",
    )
    l2_model_fallback1: str | None = Field(
        default=None,
        validation_alias="AURA_L2_MODEL_FALLBACK1",
        description="Stack 1: L2 Fallback Model. Unset: the shared AURA_L2_MODEL_FALLBACK is used (warns once).",
    )
    l2_model_fallback2: str | None = Field(
        default=None,
        validation_alias="AURA_L2_MODEL_FALLBACK2",
        description="Stack 2: L2 Fallback Model. Unset: the shared AURA_L2_MODEL_FALLBACK is used (warns once).",
    )
    l3_model_fallback1: str | None = Field(
        default=None,
        validation_alias="AURA_L3_MODEL_FALLBACK1",
        description="Stack 1: L3 Fallback Model. Unset: the shared AURA_L3_MODEL_FALLBACK is used (warns once).",
    )
    l3_model_fallback2: str | None = Field(
        default=None,
        validation_alias="AURA_L3_MODEL_FALLBACK2",
        description="Stack 2: L3 Fallback Model. Unset: the shared AURA_L3_MODEL_FALLBACK is used (warns once).",
    )
    l4_model_fallback1: str | None = Field(
        default=None,
        validation_alias="AURA_L4_MODEL_FALLBACK1",
        description="Stack 1: L4 Fallback Model. Unset: the shared AURA_L4_MODEL_FALLBACK is used (warns once).",
    )
    l4_model_fallback2: str | None = Field(
        default=None,
        validation_alias="AURA_L4_MODEL_FALLBACK2",
        description="Stack 2: L4 Fallback Model. Unset: the shared AURA_L4_MODEL_FALLBACK is used (warns once).",
    )
    l5_model_fallback1: str | None = Field(
        default=None,
        validation_alias="AURA_L5_MODEL_FALLBACK1",
        description="Stack 1: L5 Fallback Model. Unset: the shared AURA_L5_MODEL_FALLBACK is used (warns once).",
    )
    l5_model_fallback2: str | None = Field(
        default=None,
        validation_alias="AURA_L5_MODEL_FALLBACK2",
        description="Stack 2: L5 Fallback Model. Unset: the shared AURA_L5_MODEL_FALLBACK is used (warns once).",
    )

    # --- STACK 1 (MODEL1 suffix) ---
    l1_model1: str = Field(
        default="google/gemini-2.0-flash-001",
        validation_alias="AURA_L1_MODEL1",
        description="Stack 1: L1 Instinct Layer",
    )
    l2_model1: str = Field(
        default="google/gemini-2.0-flash-001",
        validation_alias="AURA_L2_MODEL1",
        description="Stack 1: L2 Reasoning Layer",
    )
    l3_model1: str = Field(
        default="x-ai/grok-4.3",
        validation_alias="AURA_L3_MODEL1",
        description="Stack 1: L3 Synthesis Layer",
    )
    l4_model1: str = Field(
        default="qwen/qwen-2.5-72b-instruct",
        validation_alias="AURA_L4_MODEL1",
        description="Stack 1: L4 Emotion Analysis Layer",
    )
    l5_model1: str = Field(
        default="google/gemini-3.1-flash-lite",
        validation_alias="AURA_L5_MODEL1",
        description="Stack 1: L5 Structure Layer",
    )

    # --- STACK 2 (MODEL2 suffix) ---
    l1_model2: str = Field(
        default="google/gemma-4-26b-a4b-it",
        validation_alias="AURA_L1_MODEL2",
        description="Stack 2: L1 Instinct Layer",
    )
    l2_model2: str = Field(
        default="deepseek/deepseek-v4-pro",
        validation_alias="AURA_L2_MODEL2",
        description="Stack 2: L2 Reasoning Layer",
    )
    l3_model2: str = Field(
        default="google/gemini-3.1-pro-preview",
        validation_alias="AURA_L3_MODEL2",
        description="Stack 2: L3 Synthesis Layer",
    )
    l4_model2: str = Field(
        default="anthropic/claude-haiku-4.5",
        validation_alias="AURA_L4_MODEL2",
        description="Stack 2: L4 Emotion Analysis Layer",
    )
    l5_model2: str = Field(
        default="qwen/qwen3.6-plus",
        validation_alias="AURA_L5_MODEL2",
        description="Stack 2: L5 Structure Layer",
    )

    # =========================================================================
    # Embeddings Configuration
    # SOVEREIGN-NATIVE: All stacks use local nomic-embed-text-v1.5 (768D).
    # Cloud LLMs must NEVER write to the vector space — SurrealDB schema is
    # locked at 768 dimensions.  Changing these defaults will corrupt the DB.
    # =========================================================================
    embeddings_model: str = Field(
        default="nomic-ai/nomic-embed-text-v1.5",
        validation_alias="AURA_EMBEDDING_MODEL",
        description="Embedding model — sovereign-native local (768D). Do NOT change to a cloud model.",
    )
    embeddings_model1: str = Field(
        default="nomic-ai/nomic-embed-text-v1.5",
        validation_alias="AURA_EMBEDDING_MODEL1",
        description="Stack 1: Embedding model — sovereign-native local (768D).",
    )
    embeddings_model2: str = Field(
        default="nomic-ai/nomic-embed-text-v1.5",
        validation_alias="AURA_EMBEDDING_MODEL2",
        description="Stack 2: Embedding model — sovereign-native local (768D).",
    )
    embeddings_dimension: int = Field(
        default=768,
        validation_alias="AURA_EMBEDDING_DIMENSION",
        description="Embedding vector dimension (768 = nomic-embed-text-v1.5). Locked by SurrealDB schema.",
    )
    embeddings_dimension1: int = Field(
        default=768,
        validation_alias="AURA_EMBEDDING_DIMENSION1",
        description="Stack 1: Embedding vector dimension (768, locked).",
    )
    embeddings_dimension2: int = Field(
        default=768,
        validation_alias="AURA_EMBEDDING_DIMENSION2",
        description="Stack 2: Embedding vector dimension (768, locked).",
    )

    # =========================================================================
    # SGLang Constrained Sampler Configuration
    # Provides radix-attention + constrained output for XML thought clusters.
    # Active only when local_llm_enabled=True AND sglang_enabled=True.
    # =========================================================================
    sglang_enabled: bool = Field(
        default=False,
        validation_alias="AURA_SGLANG_ENABLED",
        description="Enable SGLang constrained sampling for local L1/L3 layers.",
    )
    sglang_url: str = Field(
        default="http://127.0.0.1:30000",
        validation_alias="AURA_SGLANG_URL",
        description="SGLang server URL (default port 30000).",
    )
    sglang_l1_enabled: bool = Field(
        default=True,
        validation_alias="AURA_SGLANG_L1_ENABLED",
        description="Inject SGLang sampling params into L1 (Instinct) calls.",
    )
    sglang_l3_enabled: bool = Field(
        default=True,
        validation_alias="AURA_SGLANG_L3_ENABLED",
        description="Inject SGLang sampling params into L3 (Synthesis) calls.",
    )
    sglang_max_new_tokens: int = Field(
        default=4096,
        validation_alias="AURA_SGLANG_MAX_NEW_TOKENS",
        description="SGLang max_new_tokens sampling parameter.",
    )
    sglang_temperature: float = Field(
        default=0.7,
        validation_alias="AURA_SGLANG_TEMPERATURE",
        description="SGLang temperature sampling parameter.",
    )
    sglang_top_p: float = Field(
        default=0.9,
        validation_alias="AURA_SGLANG_TOP_P",
        description="SGLang top_p sampling parameter.",
    )
    sglang_top_k: int = Field(
        default=50,
        validation_alias="AURA_SGLANG_TOP_K",
        description="SGLang top_k sampling parameter.",
    )
    sglang_repetition_penalty: float = Field(
        default=1.05,
        validation_alias="AURA_SGLANG_REPETITION_PENALTY",
        description="SGLang repetition_penalty to reduce token repetition in long XML outputs.",
    )

    # =========================================================================
    # INFERENCE COCKPIT — Runtime-mutable via POST /system/inference-config
    # All values are hot-swappable without restart.
    # =========================================================================
    inference_temperature: float = Field(
        default=0.7,
        validation_alias="AURA_INFERENCE_TEMPERATURE",
        ge=0.0,
        le=2.0,
        description="Generation temperature (0=deterministic, 1.5=creative). Applied to L1 and L3.",
    )
    inference_top_p: float = Field(
        default=0.9,
        validation_alias="AURA_INFERENCE_TOP_P",
        ge=0.0,
        le=1.0,
        description="Nuclear sampling — tokens outside top-p are discarded.",
    )
    inference_min_p: float = Field(
        default=0.05,
        validation_alias="AURA_INFERENCE_MIN_P",
        ge=0.0,
        le=1.0,
        description="Min-P: minimum probability relative to top token. extra_body for cloud; sampling_params for SGLang.",
    )
    inference_frequency_penalty: float = Field(
        default=0.0,
        validation_alias="AURA_INFERENCE_FREQUENCY_PENALTY",
        ge=-2.0,
        le=2.0,
        description="Penalize tokens proportional to their past frequency.",
    )
    inference_presence_penalty: float = Field(
        default=0.0,
        validation_alias="AURA_INFERENCE_PRESENCE_PENALTY",
        ge=-2.0,
        le=2.0,
        description="Flat penalty for any token that has appeared in the context.",
    )
    inference_context_length: int = Field(
        default=8192,
        validation_alias="AURA_INFERENCE_CONTEXT_LENGTH",
        ge=2048,
        le=131072,
        description="Max context window in tokens. Enforced during prompt assembly (3090 VRAM safeguard).",
    )
    inference_max_tokens: int = Field(
        default=2048,
        validation_alias="AURA_INFERENCE_MAX_TOKENS",
        ge=256,
        le=32768,
        description="Max new tokens to generate per L3 response.",
    )
    l3_native_tools: bool = Field(
        default=False,
        validation_alias="AURA_L3_NATIVE_TOOLS",
        description="Offer L3 tools through the model API's native tools parameter (W2-36). Off unless the model supports tools.",
    )

    # =========================================================================
    # LAYER ENABLE / DISABLE — Per-layer cognitive bypass
    # Enables running a single 24B on L3 only, or any custom layer mix.
    # =========================================================================
    layer_l1_enabled: bool = Field(
        default=True,
        validation_alias="AURA_LAYER_L1_ENABLED",
        description="L1 Instinct: intent classification & vector routing. Disable → all input routed as CHAT to L3.",
    )
    layer_l2_enabled: bool = Field(
        default=True,
        validation_alias="AURA_LAYER_L2_ENABLED",
        description="L2 Reasoning: async deep analysis & insight extraction. Disable → skips silently.",
    )
    layer_l3_enabled: bool = Field(
        default=True,
        validation_alias="AURA_LAYER_L3_ENABLED",
        description="L3 Synthesis: primary response generation. Disable → L1 cold-start reply used as fallback.",
    )
    layer_l4_enabled: bool = Field(
        default=True,
        validation_alias="AURA_LAYER_L4_ENABLED",
        description="L4 Emotion: post-response emotion delta analysis. Disable → skips silently.",
    )
    layer_l5_enabled: bool = Field(
        default=True,
        validation_alias="AURA_LAYER_L5_ENABLED",
        description="L5 Structure: JSON extraction & retry logic. Disable → 1-shot call, no repair.",
    )

    def model_for(self, layer: str) -> str:
        """Return the model of ``layer`` ("l1".."l5") for the active stack."""
        if layer not in ("l1", "l2", "l3", "l4", "l5"):
            raise ValueError(f"Unknown layer {layer!r}; expected 'l1'..'l5'")
        suffix = {1: "1", 2: "2"}.get(self.model_stack_index, "")
        return getattr(self, f"{layer}_model{suffix}")

    def models_for_stack(self, index: int) -> dict[str, str]:
        """Return {"l1".."l5": model} for stack ``index`` (0, 1 or 2)."""
        if index not in (0, 1, 2):
            raise ValueError(f"Unknown stack {index!r}; expected 0..2")
        suffix = {1: "1", 2: "2"}.get(index, "")
        return {
            layer: getattr(self, f"{layer}_model{suffix}")
            for layer in ("l1", "l2", "l3", "l4", "l5")
        }

    def fallback_for(self, layer: str) -> str | None:
        """Return the fallback model of ``layer`` for the active stack.

        Stack 1/2 read ``lX_model_fallback1`` / ``lX_model_fallback2``. If that
        is unset the shared ``lX_model_fallback`` is used and a warning is
        logged once per process per (stack, layer). Stack 0 reads the shared one.
        """
        if layer not in ("l1", "l2", "l3", "l4", "l5"):
            raise ValueError(f"Unknown layer {layer!r}; expected 'l1'..'l5'")
        stack = self.model_stack_index
        shared = getattr(self, f"{layer}_model_fallback")
        if stack not in (1, 2):
            return shared
        value = getattr(self, f"{layer}_model_fallback{stack}")
        if value is not None:
            return value
        if (stack, layer) not in _FALLBACK_WARNED:
            _FALLBACK_WARNED.add((stack, layer))
            logging.getLogger(__name__).warning(
                "AURA_%s_MODEL_FALLBACK%d is unset; stack %d uses the shared "
                "AURA_%s_MODEL_FALLBACK.", layer.upper(), stack, stack, layer.upper(),
            )
        return shared

    @property
    def active_l1_model(self) -> str:
        """Return the L1 model for the active stack."""
        return self.model_for("l1")

    @property
    def active_l2_model(self) -> str:
        """Return the L2 model for the active stack."""
        return self.model_for("l2")

    @property
    def active_l3_model(self) -> str:
        """Return the L3 model for the active stack."""
        return self.model_for("l3")

    @property
    def active_l4_model(self) -> str:
        """Return the L4 model for the active stack."""
        return self.model_for("l4")

    @property
    def active_l5_model(self) -> str:
        """Return the L5 model for the active stack."""
        return self.model_for("l5")

    @property
    def active_embeddings_model(self) -> str:
        """Return the embeddings model for the active stack."""
        if self.model_stack_index == 1:
            return self.embeddings_model1
        elif self.model_stack_index == 2:
            return self.embeddings_model2
        return self.embeddings_model

    @property
    def active_embeddings_dimension(self) -> int:
        """Return the embeddings dimension for the active stack."""
        if self.model_stack_index == 1:
            return self.embeddings_dimension1
        elif self.model_stack_index == 2:
            return self.embeddings_dimension2
        return self.embeddings_dimension

    # Application Configuration
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8080)
    app_timezone: str = Field(
        default="UTC",
        validation_alias="APP_TIMEZONE",
        description="Timezone for the application (e.g., UTC, Europe/Paris, US/Pacific)",
    )

    # Emotion Engine Configuration
    emotion_tick_rate: float = Field(default=1.0, description="Seconds between emotion ticks")
    emotion_persistence_interval: float = Field(
        default=60.0, description="Seconds between emotion state saves"
    )

    # Memory injection configuration
    memory_inject_max_chars: int = Field(
        default=600,
        validation_alias="AURA_MEMORY_INJECT_MAX_CHARS",
        description="Maximum characters of a memory's content to inject into L3 prompts. "
                    "Longer content is truncated and a '...' marker is appended. "
                    "Does not affect what is stored.",
    )

    # Memory salience (W3-11)
    memory_salience_active_min: float = Field(
        default=0.1,
        validation_alias="AURA_MEMORY_SALIENCE_ACTIVE_MIN",
        description="Minimum absolute deviation from the emotional baseline for a "
                    "dimension to count as active in memory salience.",
    )
    memory_salience_weights: tuple[float, float, float] = Field(
        default=(0.4, 0.4, 0.2),
        validation_alias="AURA_MEMORY_SALIENCE_WEIGHTS",
        description="Salience weights for (emotional intensity, prediction error, "
                    "interaction depth).",
    )

    # Memory v2 episode writes (W3-12)
    memory_v2_write_enabled: bool = Field(
        default=False,
        validation_alias="AURA_MEMORY_V2_WRITE_ENABLED",
        description="Store every turn as a memory v2 episode. Off by default so "
                    "the write path can be compared with today's memory writes.",
    )

    # Memory v2 recall (W3-17)
    memory_v2_recall_enabled: bool = Field(
        default=False,
        validation_alias="AURA_MEMORY_V2_RECALL_ENABLED",
        description="When true, the memories block retrieves facts through the "
                    "memory v2 channels (filtered by venue visibility) instead of "
                    "the memory table. Off by default.",
    )

    # Memory v2 extraction (W3-13)
    memory_extraction_model: str = Field(
        default="",
        validation_alias="AURA_MEMORY_EXTRACTION_MODEL",
        description="Model used for memory v2 extraction. Empty uses the active stack L2 model (settings.active_l2_model).",
    )
    memory_extraction_max_attempts: int = Field(
        default=3,
        validation_alias="AURA_MEMORY_EXTRACTION_MAX_ATTEMPTS",
        description="Extraction attempts before an episode is marked failed; below "
                    "this it stays pending for the dream cycle to retry.",
    )

    # Dreaming v2 retry extraction (W4-08)
    dreaming_v2_enabled: bool = Field(
        default=False,
        validation_alias="AURA_DREAMING_V2_ENABLED",
        description="Enable the dreaming v2 retry extraction phase. When on, the dream "
                    "cycle retries pending extractions that are older than the minimum age.",
    )
    dreaming_retry_batch: int = Field(
        default=20,
        validation_alias="AURA_DREAMING_RETRY_BATCH",
        description="Maximum number of pending episodes to retry per dream cycle.",
        ge=1,
        le=100,
    )
    dreaming_retry_min_age_minutes: int = Field(
        default=10,
        validation_alias="AURA_DREAMING_RETRY_MIN_AGE_MINUTES",
        description="Minimum age in minutes for a pending episode to be retried by the "
                    "dream cycle. Fresh episodes are left alone.",
        ge=1,
        le=1440,
    )
    dreaming_archive_superseded_days: int = Field(
        default=90,
        validation_alias="AURA_DREAMING_ARCHIVE_SUPERSEDED_DAYS",
        description="Days after a fact was superseded before the dream cycle archives it "
                    "(pinned facts are never archived). Archived rows are kept, not read.",
        ge=1,
    )
    dreaming_archive_ephemeral_days: int = Field(
        default=7,
        validation_alias="AURA_DREAMING_ARCHIVE_EPHEMERAL_DAYS",
        description="Days after which the dream cycle archives an ephemeral episode.",
        ge=1,
    )

    dreaming_replay_batch: int = Field(
        default=200,
        validation_alias="AURA_DREAMING_REPLAY_BATCH",
        description="Top current facts by salience and recency the dream cycle replays (plus every fact recorded since the last cycle).",
        ge=1,
    )
    dreaming_replay_recency_days: int = Field(
        default=14,
        validation_alias="AURA_DREAMING_REPLAY_RECENCY_DAYS",
        description="Recency scale in days for replay priority: salience * exp(-age_days / this).",
        ge=1,
    )
    dreaming_theme_min_facts: int = Field(
        default=4,
        validation_alias="AURA_DREAMING_THEME_MIN_FACTS",
        description="Smallest community of facts that becomes a theme.",
        ge=1,
    )
    dreaming_theme_summary_words: int = Field(
        default=80,
        validation_alias="AURA_DREAMING_THEME_SUMMARY_WORDS",
        description="Word cap for theme and entity summaries.",
        ge=1,
    )
    dreaming_theme_max_per_cycle: int = Field(
        default=10,
        validation_alias="AURA_DREAMING_THEME_MAX_PER_CYCLE",
        description="Model calls for theme summaries per dream cycle.",
        ge=1,
    )
    dreaming_entity_summary_max_per_cycle: int = Field(
        default=10,
        validation_alias="AURA_DREAMING_ENTITY_SUMMARY_MAX_PER_CYCLE",
        description="Model calls for entity summaries per dream cycle.",
        ge=1,
    )

    # Memory v2 entity resolution (W3-14)
    memory_entity_match_threshold: float = Field(
        default=0.92,
        validation_alias="AURA_MEMORY_ENTITY_MATCH_THRESHOLD",
        description="Minimum embedding cosine similarity for a new surface form "
                    "to resolve to an existing entity.",
    )
    memory_entity_close_margin: float = Field(
        default=0.02,
        validation_alias="AURA_MEMORY_ENTITY_CLOSE_MARGIN",
        description="When the top two entity matches are both above the threshold "
                    "and within this margin, the closer one is taken and the pair "
                    "is logged.",
    )

    # Memory v2 fact provenance (W3-15)
    memory_hearsay_confidence: float = Field(
        default=0.3,
        validation_alias="AURA_MEMORY_HEARSAY_CONFIDENCE",
        description="Confidence for a fact learned from someone speaking about "
                    "another person.",
    )
    memory_observed_confidence: float = Field(
        default=0.8,
        validation_alias="AURA_MEMORY_OBSERVED_CONFIDENCE",
        description="Confidence for a fact the speaker stated about themselves or "
                    "their own world.",
    )
    memory_inferred_confidence: float = Field(
        default=0.5,
        validation_alias="AURA_MEMORY_INFERRED_CONFIDENCE",
        description="Confidence for a fact Aura inferred rather than heard stated.",
    )

    # Memory v2 conflict check (W3-16)
    memory_duplicate_similarity: float = Field(
        default=0.95,
        validation_alias="AURA_MEMORY_DUPLICATE_SIMILARITY",
        description="Embedding cosine similarity at or above which a new fact "
                    "is a duplicate of an existing fact.",
    )
    memory_contradiction_similarity: float = Field(
        default=0.8,
        validation_alias="AURA_MEMORY_CONTRADICTION_SIMILARITY",
        description="Embedding cosine similarity at or above which a negated "
                    "fact contradicts an existing fact.",
    )
    memory_duplicate_confidence_step: float = Field(
        default=0.1,
        validation_alias="AURA_MEMORY_DUPLICATE_CONFIDENCE_STEP",
        description="Confidence added to an existing fact when the same "
                    "statement is stored again.",
    )

    # Memory v2 owner identity (W3-15a)
    owner_display_name: str = Field(
        default="",
        validation_alias="AURA_OWNER_NAME",
        description="The owner's display name (e.g., 'Mai'). Empty uses 'owner' as the name.",
    )
    owner_aliases: list[str] = Field(
        default_factory=list,
        validation_alias="AURA_OWNER_ALIASES",
        description="Additional aliases for the owner entity (comma-separated in env).",
    )

    # =========================================================================
    # RECALL ENGINE Configuration (M2)
    # The Recall Engine assembles the prompt context from today's channels
    # behind one entry point, with deduplication and a token budget. These
    # fields are the budget, the per-block shares, the token estimate, the
    # ablation switches (PRD rule 7) and the trace cap.
    # =========================================================================
    recall_token_budget: int = Field(
        default=3000,
        validation_alias="AURA_RECALL_TOKEN_BUDGET",
        description="Total token budget the Recall Engine assembles into the context "
                    "packet. Per-block shares are taken from this.",
    )
    recall_chars_per_token: int = Field(
        default=4,
        validation_alias="AURA_RECALL_CHARS_PER_TOKEN",
        description="Characters per token used by the Recall Engine's token estimate "
                    "(estimate_tokens = ceil(len(text) / this)).",
    )
    recall_share_insights: float = Field(
        default=0.15,
        validation_alias="AURA_RECALL_SHARE_INSIGHTS",
        description="Share of the Recall Engine token budget allocated to the insights "
                    "block.",
    )
    recall_share_latent: float = Field(
        default=0.10,
        validation_alias="AURA_RECALL_SHARE_LATENT",
        description="Share of the Recall Engine token budget allocated to the latent "
                    "intuition block.",
    )
    recall_share_cold_start: float = Field(
        default=0.30,
        validation_alias="AURA_RECALL_SHARE_COLD_START",
        description="Share of the Recall Engine token budget allocated to the cold-start "
                    "block (core memories, recent context, key insights).",
    )
    recall_share_memories: float = Field(
        default=0.45,
        validation_alias="AURA_RECALL_SHARE_MEMORIES",
        description="Share of the Recall Engine token budget allocated to the retrieved "
                    "memories block.",
    )
    recall_dedup_enabled: bool = Field(
        default=True,
        validation_alias="AURA_RECALL_DEDUP_ENABLED",
        description="Ablation switch: when false, the Recall Engine skips deduplication "
                    "and keeps every candidate (PRD rule 7).",
    )
    recall_budget_enabled: bool = Field(
        default=True,
        validation_alias="AURA_RECALL_BUDGET_ENABLED",
        description="Ablation switch: when false, the Recall Engine skips the token "
                    "budget and keeps every surviving candidate (PRD rule 7).",
    )
    recall_trace_keep: int = Field(
        default=200,
        validation_alias="AURA_RECALL_TRACE_KEEP",
        description="Number of Recall Engine traces to keep in memory for the "
                    "GET /recall/trace/{turn_id} endpoint (PRD 6.6).",
    )
    recall_dense_k: int = Field(
        default=20,
        validation_alias="AURA_RECALL_DENSE_K",
        description="Number of candidates the dense vector channel retrieves.",
    )
    recall_dense_ef: int = Field(
        default=40,
        validation_alias="AURA_RECALL_DENSE_EF",
        description="HNSW search breadth used by the dense vector channel.",
    )
    recall_lexical_k: int = Field(
        default=20,
        validation_alias="AURA_RECALL_LEXICAL_K",
        description="Number of candidates the lexical BM25 channel retrieves.",
    )
    recall_query_join_max_words: int = Field(
        default=6,
        validation_alias="AURA_RECALL_QUERY_JOIN_MAX_WORDS",
        description="Inputs of at most this many words are joined with the previous "
                    "user turn when building the Recall Engine queries (PRD 6.3 step 2).",
    )
    recall_rrf_k: int = Field(
        default=60,
        validation_alias="AURA_RECALL_RRF_K",
        description="Constant k in Reciprocal Rank Fusion's 1 / (k + rank + 1) score.",
    )
    recall_channels_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_CHANNELS_ENABLED",
        description="When true, the memories block retrieves through the dense and "
                    "lexical channels fused with RRF (PRD 6.3 steps 2-4) instead of "
                    "retrieve_for_l3_parts. Off by default.",
    )
    recall_gate_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_GATE_ENABLED",
        description="When true, a turn that is only a greeting or acknowledgement "
                    "reuses the previous packet's memories block instead of running "
                    "retrieval (PRD 6.3 step 1). Off by default.",
    )
    recall_gate_phrases: list[str] = Field(
        default_factory=lambda: [
            "hi",
            "hello",
            "hey",
            "thanks",
            "thank you",
            "ok",
            "okay",
            "cool",
            "nice",
            "great",
            "got it",
            "good morning",
            "good night",
            "bye",
            "lol",
            "yes",
            "no",
        ],
        validation_alias="AURA_RECALL_GATE_PHRASES",
        description="Greetings and acknowledgements that never need memory retrieval "
                    "when the recall gate is enabled.",
    )
    recall_abstain_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_ABSTAIN_ENABLED",
        description="When true, the memories block abstains (and the packet sets "
                    "abstain) when neither the lexical channel nor the dense "
                    "channel found anything relevant. Off by default.",
    )
    recall_abstain_min_similarity: float = Field(
        default=0.55,
        validation_alias="AURA_RECALL_ABSTAIN_MIN_SIMILARITY",
        description="Best dense cosine similarity below which the memories block "
                    "abstains when the lexical channel returned no hits. Tune this "
                    "for the embedding model in use.",
    )
    recall_entity_channel_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_ENTITY_CHANNEL_ENABLED",
        description="When true, the entity channel runs in the recall engine, "
                    "finding facts about entities mentioned in the last two turns.",
    )
    recall_entity_k: int = Field(
        default=20,
        validation_alias="AURA_RECALL_ENTITY_K",
        description="Number of candidate facts the entity channel retrieves.",
    )
    recall_temporal_channel_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_TEMPORAL_CHANNEL_ENABLED",
        description="When true, the temporal channel runs in the recall engine, "
                    "finding facts from a time range parsed from the input.",
    )
    recall_temporal_k: int = Field(
        default=20,
        validation_alias="AURA_RECALL_TEMPORAL_K",
        description="Number of candidate facts the temporal channel retrieves.",
    )

    recall_graph_channel_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_GRAPH_CHANNEL_ENABLED",
        description="When true, the graph channel runs in the recall engine: "
                    "Personalised PageRank from the dense, lexical and entity hits.",
    )
    recall_themes_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_THEMES_ENABLED",
        description="When true, the fact path adds the best qualifying dream theme "
                    "as a <theme> line at the top of the memories block.",
    )
    recall_theme_min_similarity: float = Field(
        default=0.55,
        validation_alias="AURA_RECALL_THEME_MIN_SIMILARITY",
        description="Cosine similarity between query and theme embedding at which "
                    "a theme qualifies.",
    )
    recall_theme_min_members: int = Field(
        default=2,
        validation_alias="AURA_RECALL_THEME_MIN_MEMBERS",
        description="Fused facts that are members of a theme at which it qualifies.",
    )
    recall_theme_k: int = Field(
        default=1,
        validation_alias="AURA_RECALL_THEME_K",
        description="Most themes rendered in the memories block.",
    )
    recall_graph_k: int = Field(
        default=20,
        validation_alias="AURA_RECALL_GRAPH_K",
        description="Number of candidate facts the graph channel retrieves.",
    )
    recall_graph_weights: dict[str, float] = Field(
        default={"about": 1.0, "co_used": 1.0, "derived_from": 0.5, "mentions": 0.2},
        validation_alias="AURA_RECALL_GRAPH_WEIGHTS",
        description="Edge weight per relation for the graph channel.",
    )
    recall_graph_alpha: float = Field(
        default=0.15,
        validation_alias="AURA_RECALL_GRAPH_ALPHA",
        description="PageRank teleport probability back to the seed facts.",
    )
    recall_graph_iterations: int = Field(
        default=20,
        validation_alias="AURA_RECALL_GRAPH_ITERATIONS",
        description="Power iterations of the graph channel's PageRank.",
    )
    recall_graph_degree_damping: float = Field(
        default=0.5,
        validation_alias="AURA_RECALL_GRAPH_DEGREE_DAMPING",
        description="Exponent on a node's degree that damps hubs in the graph channel.",
    )
    recall_graph_max_nodes: int = Field(
        default=500,
        validation_alias="AURA_RECALL_GRAPH_MAX_NODES",
        description="Cap on the subgraph the graph channel expands.",
    )

    recall_rerank_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_RERANK_ENABLED",
        description="When true, fused facts are reranked on features (provenance, "
                    "confidence, salience, age, emotional resonance) and then "
                    "diversified with maximal marginal relevance.",
    )
    recall_rerank_provenance_weights: dict[str, float] = Field(
        default={"observed": 1.0, "external": 0.9, "inferred": 0.8, "hearsay": 0.6},
        validation_alias="AURA_RECALL_RERANK_PROVENANCE_WEIGHTS",
        description="Score multiplier per fact provenance in the rerank step.",
    )
    recall_rerank_salience_boost: float = Field(
        default=0.2,
        validation_alias="AURA_RECALL_RERANK_SALIENCE_BOOST",
        description="Score is multiplied by 1 + this * salience.",
    )
    recall_rerank_decay_days: float = Field(
        default=365.0,
        validation_alias="AURA_RECALL_RERANK_DECAY_DAYS",
        description="Score is multiplied by exp(-age_days / this).",
    )
    recall_rerank_resonance_weight: float = Field(
        default=0.10,
        validation_alias="AURA_RECALL_RERANK_RESONANCE_WEIGHT",
        description="Weight of the emotional resonance term added to the score.",
    )
    recall_rerank_mmr_lambda: float = Field(
        default=0.7,
        validation_alias="AURA_RECALL_RERANK_MMR_LAMBDA",
        description="Relevance weight in maximal marginal relevance (1 = no diversity).",
    )

    # --- SKILLS V2 (G5-01) ---
    skills_v2_enabled: bool = Field(
        default=False,
        validation_alias="AURA_SKILLS_V2_ENABLED",
        description="Parent flag for skill documents, versions and selection (G5, G6).",
    )
    skill_dup_similarity: float = Field(
        default=0.85,
        validation_alias="AURA_SKILL_DUP_SIMILARITY",
        description="Cosine of when_to_use embeddings at or above which a proposal "
        "becomes a new version of the existing skill (G5-02).",
    )

    recall_feedback_enabled: bool = Field(
        default=False,
        validation_alias="AURA_RECALL_FEEDBACK_ENABLED",
        description="After a turn, record which recalled facts the reply used.",
    )
    recall_feedback_min_overlap: float = Field(
        default=0.3,
        validation_alias="AURA_RECALL_FEEDBACK_MIN_OVERLAP",
        description="Share of a fact's content words in the reply that counts as used.",
    )
    recall_feedback_min_similarity: float = Field(
        default=0.6,
        validation_alias="AURA_RECALL_FEEDBACK_MIN_SIMILARITY",
        description="Reply-to-fact embedding similarity that counts as used.",
    )
    recall_unused_penalty: float = Field(
        default=0.9,
        validation_alias="AURA_RECALL_UNUSED_PENALTY",
        description="Rerank multiplier for a fact injected but unused for many turns.",
    )
    recall_unused_penalty_after: int = Field(
        default=5,
        validation_alias="AURA_RECALL_UNUSED_PENALTY_AFTER",
        description="Unused streak at which the rerank penalty starts.",
    )

    # CORS Configuration
    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:3001",
        description="Comma-separated list of allowed origins",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse CORS origins string into list."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    # =========================================================================
    # PARALLEL APPRAISAL (P2-05)
    # =========================================================================
    appraisal_parallel_enabled: bool = Field(
        default=False,
        validation_alias="AURA_APPRAISAL_PARALLEL_ENABLED",
        description="When true (and emotion_appraisal_enabled and layer_l4_enabled), L4 appraisal "
                    "starts at turn start, in parallel with L1, and the post-response chain no "
                    "longer appraises. Off means appraisal runs in the post-response chain.",
    )
    appraisal_turn_deadline_ms: int = Field(
        default=1200,
        ge=0,
        validation_alias="AURA_APPRAISAL_TURN_DEADLINE_MS",
        description="How long the turn waits for the parallel appraisal before building the "
                    "synthesis context. If it is not done it finishes in the background and "
                    "applies to the next turn.",
    )

    # =========================================================================
    # EMOTION APPRAISAL (W3-20)
    # =========================================================================
    emotion_appraisal_enabled: bool = Field(
        default=False,
        validation_alias="AURA_EMOTION_APPRAISAL_ENABLED",
        description="Enable the appraisal pathway (Emotion PRD 5.3). When on, every turn is appraised and an emotion_event record is written. Off by default.",
    )

    # =========================================================================
    # EMOTION MOOD (W4-13, Emotion PRD 6.2)
    # =========================================================================
    emotion_mood_enabled: bool = Field(
        default=False,
        validation_alias="AURA_EMOTION_MOOD_ENABLED",
        description="Track mood (valence, arousal, control) as a slow average of the emotional state; it shifts the resting point of the positive dimensions. Off by default.",
    )
    emotion_mood_half_life_hours: float = Field(
        default=8.0, gt=0.0,
        validation_alias="AURA_EMOTION_MOOD_HALF_LIFE_HOURS",
        description="Half-life of the mood average, in real hours.",
    )
    emotion_mood_baseline_gain: float = Field(
        default=0.1,
        validation_alias="AURA_EMOTION_MOOD_BASELINE_GAIN",
        description="Baseline shift of the positive dimensions per unit of mood valence.",
    )
    emotion_mood_baseline_shift_max: float = Field(
        default=0.1, ge=0.0,
        validation_alias="AURA_EMOTION_MOOD_BASELINE_SHIFT_MAX",
        description="Cap on the mood baseline shift (either direction).",
    )
    emotion_mood_appraisal_bias_enabled: bool = Field(
        default=False,
        validation_alias="AURA_EMOTION_MOOD_APPRAISAL_BIAS_ENABLED",
        description="Let mood nudge the congruence of ambiguous events (separate flag, for ablation).",
    )
    emotion_mood_appraisal_bias: float = Field(
        default=0.1,
        validation_alias="AURA_EMOTION_MOOD_APPRAISAL_BIAS",
        description="Congruence shift per unit of mood valence for an ambiguous event (|congruence| < 0.3), capped at 0.1.",
    )
    # Projection weights over deviations from baseline. Valence: +1 for the
    # positive set and -1 for the negative set of EmotionEngine._compute_valence
    # (surprise and nostalgia neutral). Arousal: high-energy dimensions positive
    # (anger, fear, surprise, fascination, awe, joy at a smaller weight), calm or
    # flat ones negative (serenity, boredom). Control: confident or capable
    # dimensions positive (pride, certainty, joy, trust), helpless or unsure ones
    # negative (fear, shame, confusion, doubt).
    emotion_mood_valence_weights: dict[str, float] = Field(
        default_factory=lambda: {
            **{d: 1.0 for d in (
                "joy", "love", "interest", "trust", "curiosity", "fascination",
                "wonder", "awe", "beauty", "serenity", "empathy", "compassion",
                "gratitude", "pride", "certainty",
            )},
            **{d: -1.0 for d in (
                "fear", "sadness", "anger", "disgust", "shame", "envy",
                "doubt", "confusion", "boredom", "melancholy",
            )},
        }
    )
    emotion_mood_arousal_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "anger": 1.0, "fear": 1.0, "surprise": 0.8, "fascination": 0.5,
            "awe": 0.5, "joy": 0.5, "interest": 0.3, "curiosity": 0.3,
            "wonder": 0.3, "disgust": 0.3, "envy": 0.3, "sadness": -0.3,
            "melancholy": -0.3, "boredom": -0.8, "serenity": -1.0,
        }
    )
    emotion_mood_control_weights: dict[str, float] = Field(
        default_factory=lambda: {
            "pride": 1.0, "certainty": 1.0, "joy": 0.5, "trust": 0.3,
            "anger": 0.3, "fear": -1.0, "shame": -1.0, "confusion": -0.8,
            "doubt": -0.8, "sadness": -0.3,
        }
    )

    # =========================================================================
    # EMOTION RELATIONSHIPS (W4-14, Emotion PRD 6.3)
    # =========================================================================
    emotion_relationships_enabled: bool = Field(
        default=False,
        validation_alias="AURA_EMOTION_RELATIONSHIPS_ENABLED",
        description="Keep a relationship (affection, trust, familiarity, tension) on each person's entity. The speaker's relationship sets the resting point of love and trust, scales the message's impulses and caps a stranger's hostility. Off by default.",
    )
    # Starting values: a person never seen gets the stranger values, the owner
    # (entity key "owner") gets the owner values for affection, trust and
    # familiarity (tension starts at the stranger value).
    emotion_relationship_stranger_affection: float = Field(default=0.0, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_STRANGER_AFFECTION")
    emotion_relationship_stranger_trust: float = Field(default=0.3, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_STRANGER_TRUST")
    emotion_relationship_stranger_familiarity: float = Field(default=0.0, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_STRANGER_FAMILIARITY")
    emotion_relationship_stranger_tension: float = Field(default=0.0, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_STRANGER_TENSION")
    emotion_relationship_owner_affection: float = Field(default=0.5, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_OWNER_AFFECTION")
    emotion_relationship_owner_trust: float = Field(default=0.7, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_OWNER_TRUST")
    emotion_relationship_owner_familiarity: float = Field(default=0.6, ge=0.0, le=1.0, validation_alias="AURA_EMOTION_RELATIONSHIP_OWNER_FAMILIARITY")
    # Mapping into the dimension's range: love baseline = affection * love_scale,
    # trust baseline = trust * trust_scale. The scales are chosen so the owner's
    # starting values give the configured global baselines (love 0.05 = 0.5 * 0.1,
    # trust 0.2 = 0.7 * 0.2857), so turning the flag on barely moves the owner.
    emotion_relationship_love_scale: float = Field(default=0.1, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_LOVE_SCALE")
    emotion_relationship_trust_scale: float = Field(default=0.2 / 0.7, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_TRUST_SCALE")
    emotion_relationship_warmth_gain: float = Field(
        default=0.5, ge=0.0,
        description="Positive-warmth impulses are multiplied by 1 + gain * (affection + familiarity) / 2.",
        validation_alias="AURA_EMOTION_RELATIONSHIP_WARMTH_GAIN",
    )
    emotion_stranger_familiarity: float = Field(
        default=0.2, ge=0.0, le=1.0,
        description="A person with familiarity below this is a stranger for the hostility cap.",
        validation_alias="AURA_EMOTION_STRANGER_FAMILIARITY",
    )
    emotion_stranger_hostility_cap: float = Field(
        default=0.3, ge=0.0,
        description="Cap on each negative-dimension impulse per event from a stranger.",
        validation_alias="AURA_EMOTION_STRANGER_HOSTILITY_CAP",
    )
    # Step sizes per event (each field is clamped to [0, 1]; no time decay).
    emotion_relationship_familiarity_step: float = Field(default=0.03, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_FAMILIARITY_STEP")
    emotion_relationship_affection_gain: float = Field(default=0.02, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_AFFECTION_GAIN")
    emotion_relationship_affection_loss: float = Field(default=0.005, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_AFFECTION_LOSS")
    emotion_relationship_tension_rise: float = Field(default=0.03, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_TENSION_RISE")
    emotion_relationship_tension_ease: float = Field(default=0.02, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_TENSION_EASE")
    emotion_relationship_trust_gain: float = Field(default=0.02, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_TRUST_GAIN")
    emotion_relationship_trust_loss: float = Field(default=0.03, ge=0.0, validation_alias="AURA_EMOTION_RELATIONSHIP_TRUST_LOSS")
    # Venue caps (W4-15, Emotion PRD 7)
    emotion_guest_cap_enabled: bool = Field(
        default=False,
        description="Limit how far guests together can move her state: the sum of the size of guest emotion_events in the last hour is capped. Off by default.",
        validation_alias="AURA_EMOTION_GUEST_CAP_ENABLED",
    )
    emotion_guest_cap_per_hour: float = Field(
        default=0.5, ge=0.0,
        description="Budget (sum of emotion_event size) for all guest events in a sliding hour.",
        validation_alias="AURA_EMOTION_GUEST_CAP_PER_HOUR",
    )

    # =========================================================================
    # SYSTEM STATE MACHINE (Sleep/Wake Cycle)
    # =========================================================================
    system_idle_after_minutes: int = Field(
        default=15,
        validation_alias="AURA_SYSTEM_IDLE_AFTER_MINUTES",
        description="Minutes of no user interaction before transitioning to IDLE.",
        ge=1,
        le=24 * 60,
    )
    system_dream_after_minutes: int = Field(
        default=30,
        validation_alias="AURA_SYSTEM_DREAM_AFTER_MINUTES",
        description="Minutes of no user interaction before transitioning to DREAMING -> SLEEPING.",
        ge=1,
        le=24 * 60,
    )
    system_wake_word: str = Field(
        default="Aura",
        validation_alias="AURA_SYSTEM_WAKE_WORD",
        description="Wake word that can bring the system out of SLEEPING state.",
    )
    system_auto_wake_on_query: bool = Field(
        default=False,
        validation_alias="AURA_SYSTEM_AUTO_WAKE_ON_QUERY",
        description="If true, any incoming user query auto-wakes the system from SLEEPING; if false, queries are rejected unless wake word is present or UI triggers wake.",
    )

    # =========================================================================
    # TOOL SYNTHESIS Configuration
    # =========================================================================
    school_synthesis_enabled: bool = Field(
        default=False,
        validation_alias="AURA_SCHOOL_SYNTHESIS_ENABLED",
        description="Enable dynamic tool synthesis via the School API",
    )

    # =========================================================================
    # TOOL SELECTION Configuration (W2-30)
    # =========================================================================
    tool_selection_threshold: int = Field(
        default=15,
        validation_alias="AURA_TOOL_SELECTION_THRESHOLD",
        description="Number of available tools above which selection by similarity runs",
        ge=1,
    )
    tool_selection_top_k: int = Field(
        default=8,
        validation_alias="AURA_TOOL_SELECTION_TOP_K",
        description="Number of top tools to return when selection runs",
        ge=1,
    )
    # =========================================================================
    # TIER PROFILES (P2-03)
    # =========================================================================
    tier_profiles_enabled: bool = Field(
        default=False,
        validation_alias="AURA_TIER_PROFILES_ENABLED",
        description="When true, the active tier's profile (aura.tiers) governs L3 reasoning, "
                    "L2 post-analysis, tools offered, tool gating and the context budget. "
                    "Off means the pre-tier behaviour exactly.",
    )
    task_graphs_enabled: bool = Field(
        default=False,
        validation_alias="AURA_TASK_GRAPHS_ENABLED",
        description="When true (and tier profiles are on and the active profile allows task "
                    "graphs, i.e. Titan), the plan_task tool is offered and callable. "
                    "Off means the tool list is exactly as before.",
    )
    task_graph_parallel: int = Field(
        default=3,
        validation_alias="AURA_TASK_GRAPH_PARALLEL",
        description="Task graph scheduler: research and think nodes that may run at once "
                    "(code nodes have their own limit of 1, D4).",
        ge=1,
        le=16,
    )
    task_code_nodes_enabled: bool = Field(
        default=False,
        validation_alias="AURA_TASK_CODE_NODES_ENABLED",
        description="P2-10: run code nodes (aura-lead in a git worktree, review, owner-approved "
                    "merge). Needs task_graphs_enabled. Off means code nodes fail with the "
                    "P2-09 placeholder reason.",
    )
    task_worktree_root: str = Field(
        default="",
        validation_alias="AURA_TASK_WORKTREE_ROOT",
        description="Directory for code-node git worktrees. Empty means <workspace>/../.aura-worktrees. "
                    "Must not be inside the workspace.",
    )
    task_git_timeout_seconds: float = Field(
        default=60.0,
        validation_alias="AURA_TASK_GIT_TIMEOUT_SECONDS",
        description="Timeout for each git command a code node runs.",
        gt=0.0,
    )
    task_code_node_default_minutes: int = Field(
        default=30,
        validation_alias="AURA_TASK_CODE_NODE_DEFAULT_MINUTES",
        description="Time limit for a code node's sessions (lead, subagents, review) when the "
                    "graph has no time budget. The wait for the merge approval is not limited.",
        ge=1,
    )
    task_merge_poll_seconds: float = Field(
        default=5.0,
        validation_alias="AURA_TASK_MERGE_POLL_SECONDS",
        description="How often a ready_to_merge code node checks its merge decision.",
        gt=0.0,
    )
    task_git_author_name: str = Field(
        default="Aura",
        validation_alias="AURA_TASK_GIT_AUTHOR_NAME",
        description="Author and committer name of the commit Aura makes in a code node's worktree.",
    )
    task_git_author_email: str = Field(
        default="aura@localhost",
        validation_alias="AURA_TASK_GIT_AUTHOR_EMAIL",
        description="Author and committer email of the commit Aura makes in a code node's worktree.",
    )
    task_research_model: str = Field(
        default="",
        validation_alias="AURA_TASK_RESEARCH_MODEL",
        description="Model for research nodes of a task graph; empty means the active L5 model.",
    )
    task_node_report_max_tokens: int = Field(
        default=800,
        validation_alias="AURA_TASK_NODE_REPORT_MAX_TOKENS",
        description="A task node's report is cut to this many tokens (estimate) with a marker; "
                    "the full transcript stays on the node record.",
        ge=1,
    )
    tier_overrides_path: str = Field(
        default=".aura/tier_overrides.json",
        validation_alias="AURA_TIER_OVERRIDES_PATH",
        description="Per-tier knob overrides, relative to the app directory unless absolute.",
    )
    tier_recall_share: float = Field(
        default=0.3,
        validation_alias="AURA_TIER_RECALL_SHARE",
        description="Share of context_budget_tokens given to recall; history gets the rest.",
        ge=0.0,
        le=1.0,
    )

    l1_routes_enabled: bool = Field(
        default=False,
        validation_alias="AURA_L1_ROUTES_ENABLED",
        description="When true, L1 also returns a route (chat, tool, think, task, teach) and a "
                    "stakes score (P2-06); intent is derived from the route. Off means the "
                    "original L1 prompt and parsing exactly.",
    )

    tool_selection_success_weight: float = Field(
        default=0.2,
        validation_alias="AURA_TOOL_SELECTION_SUCCESS_WEIGHT",
        description="Weight of recent success rate in the tool selection score",
        ge=0.0,
        le=1.0,
    )

    # =========================================================================
    # TOOL LOOP Configuration (W2-31)
    # =========================================================================
    tool_loop_max_rounds: int = Field(
        default=5,
        validation_alias="AURA_TOOL_LOOP_MAX_ROUNDS",
        description="Maximum tool loop rounds before stopping and asking the user to continue. "
                    "With tool_loop_budgets_enabled this is only a deprecated alias of "
                    "tool_loop_safety_rounds.",
        ge=1,
        le=20,
    )
    tool_loop_budgets_enabled: bool = Field(
        default=False,
        validation_alias="AURA_TOOL_LOOP_BUDGETS_ENABLED",
        description="When true, the tool loop ends on time and cost budgets, the no-progress "
                    "guard or the safety breaker instead of a round cap (P2-41). Off means "
                    "tool_loop_max_rounds and the max-rounds suffix exactly.",
    )
    tool_loop_safety_rounds: int = Field(
        default=40,
        validation_alias="AURA_TOOL_LOOP_SAFETY_ROUNDS",
        description="Safety breaker: rounds after which a budgeted tool loop stops and logs an incident",
        ge=1,
        le=1000,
    )
    tool_loop_default_budget_seconds: int = Field(
        default=120,
        validation_alias="AURA_TOOL_LOOP_DEFAULT_BUDGET_SECONDS",
        description="Tool loop time budget per turn when no tier profile supplies one (Core value)",
        ge=1,
    )
    tool_loop_default_budget_usd: float = Field(
        default=0.20,
        validation_alias="AURA_TOOL_LOOP_DEFAULT_BUDGET_USD",
        description="Tool loop cost budget per turn when no tier profile supplies one (Core value); 0 disables",
        ge=0.0,
    )

    @model_validator(mode="after")
    def _max_rounds_feeds_safety_breaker(self) -> "Settings":
        # AURA_TOOL_LOOP_MAX_ROUNDS is a deprecated alias of the safety setting (P2-41):
        # explicitly set (env or .env) and the safety setting is not -> it feeds the breaker.
        fields = self.model_fields_set
        if "tool_loop_max_rounds" in fields and "tool_loop_safety_rounds" not in fields:
            logging.getLogger(__name__).warning(
                "AURA_TOOL_LOOP_MAX_ROUNDS is deprecated; use AURA_TOOL_LOOP_SAFETY_ROUNDS. "
                "Using %d as the safety breaker.", self.tool_loop_max_rounds,
            )
            self.tool_loop_safety_rounds = self.tool_loop_max_rounds
        return self

    # =========================================================================
    # OPENCODE SERVER Configuration (W3-27)
    # =========================================================================
    opencode_command: list[str] = Field(
        default_factory=list,
        validation_alias="AURA_OPENCODE_COMMAND",
        description="Command to run opencode as a JSON list. Empty means ['opencode'] from PATH.",
    )
    opencode_version_pin: str = Field(
        default="2.3.2",
        validation_alias="AURA_OPENCODE_VERSION_PIN",
        description="Pinned major.minor.patch version. Refuses other major versions.",
    )
    opencode_host: str = Field(
        default="127.0.0.1",
        validation_alias="AURA_OPENCODE_HOST",
        description="Host to bind the opencode server to.",
    )
    opencode_port: int = Field(
        default=0,
        validation_alias="AURA_OPENCODE_PORT",
        description="Port to bind the opencode server to. 0 picks a free port.",
        ge=0,
        le=65535,
    )
    opencode_start_timeout_secs: int = Field(
        default=30,
        validation_alias="AURA_OPENCODE_START_TIMEOUT_SECS",
        description="Timeout in seconds for the opencode server to start and respond to /api/info.",
        ge=1,
        le=300,
    )
    opencode_agent_model: str = Field(
        default="sluice/coder",
        validation_alias="AURA_OPENCODE_AGENT_MODEL",
        description="Model to use for OpenCode agents (the router's coder pool through the sluice provider).",
    )
    opencode_lead_model: str = Field(
        default="",
        validation_alias="AURA_OPENCODE_LEAD_MODEL",
        description="Model for the aura-lead agent of code nodes (P2-10). Empty means opencode_agent_model.",
    )
    opencode_worker_model: str = Field(
        default="",
        validation_alias="AURA_OPENCODE_WORKER_MODEL",
        description="Model for aura-explore, aura-build and aura-review (P2-10). Empty means opencode_agent_model.",
    )
    opencode_config_dir: str = Field(
        default="",
        validation_alias="AURA_OPENCODE_CONFIG_DIR",
        description="Directory for OpenCode config (opencode/opencode.jsonc). Empty means <Aura data dir>/opencode-config.",
    )
    opencode_router_base_url: str = Field(
        default="http://127.0.0.1:8787/v1",
        validation_alias="AURA_OPENCODE_ROUTER_BASE_URL",
        description="Base URL for the sluice provider (OpenCode router).",
    )

    # =========================================================================
    # WORKSPACES AND DELEGATION Configuration (G3 / W3-29)
    # =========================================================================
    workspaces: dict[str, str] = Field(
        default_factory=dict,
        validation_alias="AURA_WORKSPACES",
        description="JSON object mapping workspace names to absolute paths. "
                    "Workspaces must be explicitly registered; Aura's own source tree "
                    "is NOT a workspace unless registered.",
    )
    delegation_enabled: bool = Field(
        default=False,
        validation_alias="AURA_DELEGATION_ENABLED",
        description="Enable delegation to OpenCode agents. Off by default.",
    )
    delegation_default_tokens: int = Field(
        default=200000,
        validation_alias="AURA_DELEGATION_DEFAULT_TOKENS",
        description="Default token budget for delegated tasks.",
        ge=1000,
    )
    delegation_default_minutes: int = Field(
        default=30,
        validation_alias="AURA_DELEGATION_DEFAULT_MINUTES",
        description="Default time budget in minutes for delegated tasks.",
        ge=1,
        le=1440,
    )
    # =========================================================================
    # DELEGATION CONTROLS (G4-01)
    # =========================================================================
    delegation_guidance_max_chars: int = Field(
        default=4000,
        description="Longest guidance text the /delegations guidance route accepts.",
        ge=1,
    )
    delegation_closed_list_limit: int = Field(
        default=50,
        description="How many closed delegations GET /delegations returns.",
        ge=1,
    )
    delegation_list_steps_limit: int = Field(
        default=20,
        description="How many recent steps GET /delegations shows per task.",
        ge=1,
    )
    # G4-02: blocker monitor, heartbeat, re-attach
    delegation_error_streak: int = Field(
        default=3,
        validation_alias="AURA_DELEGATION_ERROR_STREAK",
        description="Failed tool events in a row that raise a blocker.",
        ge=1,
    )
    delegation_repeat_limit: int = Field(
        default=4,
        validation_alias="AURA_DELEGATION_REPEAT_LIMIT",
        description="Times the same tool with the same arguments may run in one task before a blocker.",
        ge=2,
    )
    delegation_budget_warn_fraction: float = Field(
        default=0.8,
        validation_alias="AURA_DELEGATION_BUDGET_WARN_FRACTION",
        description="Fraction of the time or token budget at which a blocker is raised (the 100% stop is separate).",
        gt=0.0,
        le=1.0,
    )
    delegation_heartbeat_seconds: float = Field(
        default=60.0,
        validation_alias="AURA_DELEGATION_HEARTBEAT_SECONDS",
        description="Seconds between 'still working' status steps while a delegation runs.",
        gt=0.0,
    )
    delegation_blocker_recent_steps: int = Field(
        default=5,
        validation_alias="AURA_DELEGATION_BLOCKER_RECENT_STEPS",
        description="Recent step summaries included in a blocker decision and in the suggestion prompt.",
        ge=1,
    )
    policy_table: dict[str, dict[str, str]] = Field(
        default_factory=lambda: {
            "owner": {"read": "allow", "write": "allow", "execute": "ask", "send": "ask"},
            "trusted": {"read": "allow", "write": "deny", "execute": "deny", "send": "deny"},
            "guest": {"read": "deny", "write": "deny", "execute": "deny", "send": "deny"},
        },
        validation_alias="AURA_POLICY_TABLE",
        description="Policy table keyed by role, mapping risk class to decision "
                    "('allow', 'ask', 'deny'). Default follows PRD 11.3 recommendation.",
    )

    # =========================================================================
    # IDE / CODE EXECUTION Configuration
    # =========================================================================
    aura_workspace_path: str = Field(
        default="",
        validation_alias="AURA_WORKSPACE_PATH",
        description="Path to Aura's workspace directory for code projects",
    )
    code_execution_enabled: bool = Field(
        default=False,
        validation_alias="AURA_CODE_EXECUTION_ENABLED",
        description="Enable sandboxed code execution for Aura",
    )
    code_execution_timeout: int = Field(
        default=30,
        validation_alias="AURA_CODE_EXECUTION_TIMEOUT",
        description="Timeout in seconds for code execution",
        ge=5,
        le=300,
    )

    # =========================================================================
    # DISCORD BOT Configuration
    # =========================================================================
    discord_enabled: bool = Field(
        default=False,
        validation_alias="AURA_DISCORD_ENABLED",
        description="Enable Discord bot integration. Requires a valid bot token.",
    )
    discord_bot_token: str = Field(
        default="",
        validation_alias="AURA_DISCORD_BOT_TOKEN",
        description="Discord Bot Token from https://discord.com/developers/applications",
    )
    discord_command_prefix: str = Field(
        default="!aura",
        validation_alias="AURA_DISCORD_COMMAND_PREFIX",
        description="Prefix for Discord bot commands (e.g., !aura chat, !aura status)",
    )
    discord_allowed_channels: str = Field(
        default="",
        validation_alias="AURA_DISCORD_ALLOWED_CHANNELS",
        description="Comma-separated list of Discord channel IDs the bot is allowed to respond in. Empty = all channels.",
    )
    discord_max_message_length: int = Field(
        default=2000,
        validation_alias="AURA_DISCORD_MAX_MESSAGE_LENGTH",
        description="Maximum length of Discord messages (Discord limit: 2000). Longer responses are split.",
        ge=100,
        le=2000,
    )
    discord_stream_responses: bool = Field(
        default=True,
        validation_alias="AURA_DISCORD_STREAM_RESPONSES",
        description="Send streaming 'Aura is typing...' indicators while processing",
    )
    discord_active_mode: bool = Field(
        default=False,
        validation_alias="AURA_DISCORD_ACTIVE_MODE",
        description="When enabled, Aura actively participates in allowed channels "
                    "(responds to ALL messages, not just @mentions/commands). "
                    "Uses a cooldown to avoid spam.",
    )
    discord_active_cooldown_seconds: float = Field(
        default=30.0,
        validation_alias="AURA_DISCORD_ACTIVE_COOLDOWN_SECONDS",
        description="Minimum seconds between unprompted responses in active mode (per channel).",
        ge=5.0,
        le=300.0,
    )
    discord_owner_ids: str = Field(
        default="",
        validation_alias="AURA_DISCORD_OWNER_IDS",
        description="Comma-separated Discord user ids that act as the owner role for tool "
                    "execution. Other Discord users are treated as guests and cannot "
                    "trigger tool calls.",
    )

    # =========================================================================
    # OUTCOME SIGNALS (G5-03)
    # =========================================================================

    outcome_signals_enabled: bool = Field(
        default=False,
        validation_alias="AURA_OUTCOME_SIGNALS_ENABLED",
        description="Replace the hard-coded per-turn success with a real outcome signal.",
    )
    outcome_rephrase_turns: int = Field(
        default=2,
        validation_alias="AURA_OUTCOME_REPHRASE_TURNS",
        description="How many earlier owner turns a rephrase or correction can mark negative.",
        ge=1,
        le=10,
    )
    outcome_rephrase_similarity: float = Field(
        default=0.8,
        validation_alias="AURA_OUTCOME_REPHRASE_SIMILARITY",
        description="Cosine of two owner message embeddings that counts as a rephrase.",
    )
    outcome_rephrase_overlap: float = Field(
        default=0.6,
        validation_alias="AURA_OUTCOME_REPHRASE_OVERLAP",
        description="Content-word overlap of two owner messages that counts as a rephrase.",
    )

    # =========================================================================
    # BEHAVIOUR (B1..B5)
    # =========================================================================

    autonomy_default_level: str = Field(
        default="important",
        validation_alias="AURA_AUTONOMY_DEFAULT_LEVEL",
        description="Initial autonomy level: silent, important or open.",
        pattern="^(silent|important|open)$",
    )
    quiet_hours_start: str = Field(
        default="22:00",
        validation_alias="AURA_QUIET_HOURS_START",
        description="Local HH:MM when quiet hours begin (app_timezone).",
    )
    quiet_hours_end: str = Field(
        default="08:00",
        validation_alias="AURA_QUIET_HOURS_END",
        description="Local HH:MM when quiet hours end (app_timezone).",
    )

    autonomy_enabled: bool = Field(
        default=False,
        validation_alias="AURA_AUTONOMY_ENABLED",
        description="Master flag for any unprompted delivery.",
    )

    workspace_enabled: bool = Field(
        default=False,
        validation_alias="AURA_WORKSPACE_ENABLED",
        description="Behaviour workspace (B2).",
    )

    drives_enabled: bool = Field(
        default=False,
        validation_alias="AURA_DRIVES_ENABLED",
        description="Drives (B2).",
    )

    goals_v2_enabled: bool = Field(
        default=False,
        validation_alias="AURA_GOALS_V2_ENABLED",
        description="Goals v2 (B3).",
    )

    curiosity_enabled: bool = Field(
        default=False,
        validation_alias="AURA_CURIOSITY_ENABLED",
        description="Curiosity (B4).",
    )

    interruptibility_model_enabled: bool = Field(
        default=False,
        validation_alias="AURA_INTERRUPTIBILITY_MODEL_ENABLED",
        description="Interruptibility model (B5).",
    )

    dismissal_learning_enabled: bool = Field(
        default=False,
        validation_alias="AURA_DISMISSAL_LEARNING_ENABLED",
        description="Learn from dismissed items (B5).",
    )

    # Agenda priority decay per hour, per kind (B1-02)
    agenda_decay_per_hour_finding: float = Field(
        default=0.02,
        ge=0.0,
        validation_alias="AURA_AGENDA_DECAY_PER_HOUR_FINDING",
        description="Hourly exponential decay rate of agenda priority for kind finding.",
    )
    agenda_decay_per_hour_task_done: float = Field(
        default=0.01,
        ge=0.0,
        validation_alias="AURA_AGENDA_DECAY_PER_HOUR_TASK_DONE",
        description="Hourly exponential decay rate of agenda priority for kind task_done.",
    )
    agenda_decay_per_hour_needs_decision: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="AURA_AGENDA_DECAY_PER_HOUR_NEEDS_DECISION",
        description="Hourly exponential decay rate of agenda priority for kind needs_decision.",
    )
    agenda_decay_per_hour_question_for_you: float = Field(
        default=0.01,
        ge=0.0,
        validation_alias="AURA_AGENDA_DECAY_PER_HOUR_QUESTION_FOR_YOU",
        description="Hourly exponential decay rate of agenda priority for kind question_for_you.",
    )
    agenda_decay_per_hour_reminder: float = Field(
        default=0.0,
        ge=0.0,
        validation_alias="AURA_AGENDA_DECAY_PER_HOUR_REMINDER",
        description="Hourly exponential decay rate of agenda priority for kind reminder.",
    )
    agenda_decay_per_hour_observation: float = Field(
        default=0.05,
        ge=0.0,
        validation_alias="AURA_AGENDA_DECAY_PER_HOUR_OBSERVATION",
        description="Hourly exponential decay rate of agenda priority for kind observation.",
    )

    agenda_fallback_seconds: float = Field(
        default=300.0,
        gt=0.0,
        validation_alias="AURA_AGENDA_FALLBACK_SECONDS",
        description="Fallback check interval for stuck agenda items (delivery is event-driven).",
    )
    agenda_message_priority: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        validation_alias="AURA_AGENDA_MESSAGE_PRIORITY",
        description="Effective priority at or above which a delivered agenda item publishes aura_message.",
    )

    aura_ws_aura_enabled: bool = Field(
        default=False,
        validation_alias="AURA_WS_AURA_ENABLED",
        description="Enable the /ws/aura owner channel. Off: the socket closes with 1008 and publish sends nothing.",
    )
    aura_channel_buffer: int = Field(
        default=200,
        ge=1,
        validation_alias="AURA_CHANNEL_BUFFER",
        description="Recent channel events kept for catch-up (ring buffer size).",
    )
    aura_channel_ping_seconds: float = Field(
        default=30.0,
        gt=0.0,
        validation_alias="AURA_CHANNEL_PING_SECONDS",
        description="Idle seconds before /ws/aura sends a ping.",
    )

    # =========================================================================
    # Utility Helper
    # =========================================================================

    def get_fallback(self, model_id: str) -> str | None:
        """
        Get fallback model for a given model ID.
        
        Args:
            model_id: The primary model identifier
            
        Returns:
            Fallback model ID if available, None otherwise
        """
        for layer in ("l1", "l2", "l3", "l4", "l5"):
            if model_id == self.model_for(layer):
                return self.fallback_for(layer)
        return None


# Global settings instance
settings = Settings()

# Debug: Log database config at startup
logger = logging.getLogger(__name__)
logger.info(f"Database config loaded: url={settings.surreal_url}, user={settings.surreal_user}, ns={settings.surreal_ns}, db={settings.surreal_db}")

