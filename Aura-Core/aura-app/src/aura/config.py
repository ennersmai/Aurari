"""Application configuration using Pydantic Settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @property
    def active_l1_model(self) -> str:
        """Return the L1 model for the active stack."""
        if self.model_stack_index == 1:
            return self.l1_model1
        elif self.model_stack_index == 2:
            return self.l1_model2
        return self.l1_model

    @property
    def active_l2_model(self) -> str:
        """Return the L2 model for the active stack."""
        if self.model_stack_index == 1:
            return self.l2_model1
        elif self.model_stack_index == 2:
            return self.l2_model2
        return self.l2_model

    @property
    def active_l3_model(self) -> str:
        """Return the L3 model for the active stack."""
        if self.model_stack_index == 1:
            return self.l3_model1
        elif self.model_stack_index == 2:
            return self.l3_model2
        return self.l3_model

    @property
    def active_l4_model(self) -> str:
        """Return the L4 model for the active stack."""
        if self.model_stack_index == 1:
            return self.l4_model1
        elif self.model_stack_index == 2:
            return self.l4_model2
        return self.l4_model

    @property
    def active_l5_model(self) -> str:
        """Return the L5 model for the active stack."""
        if self.model_stack_index == 1:
            return self.l5_model1
        elif self.model_stack_index == 2:
            return self.l5_model2
        return self.l5_model

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
    # AGENT LOOP Configuration
    # =========================================================================
    agent_loop_max_iterations: int = Field(
        default=10,
        validation_alias="AURA_AGENT_LOOP_MAX_ITERATIONS",
        description="Maximum iterations for free-running agent loops before requiring human confirmation",
        ge=1,
        le=50,
    )
    agent_loop_require_approval: bool = Field(
        default=True,
        validation_alias="AURA_AGENT_LOOP_REQUIRE_APPROVAL",
        description="Require human approval for destructive actions (file writes, code execution)",
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
        description="Maximum tool loop rounds before stopping and asking the user to continue",
        ge=1,
        le=20,
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
        if model_id == self.l1_model:
            return self.l1_model_fallback
        if model_id == self.l2_model:
            return self.l2_model_fallback
        if model_id == self.l3_model:
            return self.l3_model_fallback
        if model_id == self.l4_model:
            return self.l4_model_fallback
        if model_id == self.l5_model:
            return self.l5_model_fallback
        return None


# Global settings instance
settings = Settings()

# Debug: Log database config at startup
import logging
logger = logging.getLogger(__name__)
logger.info(f"Database config loaded: url={settings.surreal_url}, user={settings.surreal_user}, ns={settings.surreal_ns}, db={settings.surreal_db}")

