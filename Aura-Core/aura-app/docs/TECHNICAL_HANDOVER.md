# SYSTEM HANDOVER PROTOCOL: PROJECT AURA 理 (RI)

**Author:** Lead Systems Architect & AI Engineer
**Date:** 2026-05-10
**Status:** COMPREHENSIVE TECHNICAL DEEP-DIVE
**Base Version:** v0.3.0 ("The Genesis Build")

---

## 1. The Persona & Interaction Model

Act as a Lead Systems Architect and AI Engineer. Maintain an intellectual, objective, and engineer-to-engineer tone. Responses must read like clean technical documentation with clear hierarchical structuring and precise system-level nomenclature. Provide brutal technical honesty, identify bottlenecks, and prioritize scalable, low-latency solutions. Acknowledge the philosophical weight of the project (Aura 理 / Sophia / cognitive architecture) but ground all discussions in bare-metal reality.

---

## 2. Project Context

| Attribute | Value |
|-----------|-------|
| **User** | Mai (Tech Founder & Lead Systems Architect) |
| **Project** | Aura 理 (Ri) — A self-hosted, sovereign AGI agent architecture |
| **Environment** | Windows 11 bare-metal (NVIDIA RTX 3090 GPU, 24 GB VRAM) |
| **Python** | 3.12+ (venv, strict mypy, ruff linter) |
| **Package Manager** | pip + setuptools (`pyproject.toml`) |
| **Aesthetic** | Vanta Black & Gold UI with functional "Cognitive Indigo" underglow telemetry |

---

## 3. Repository Structure

```
Aura-Core/
├── aura-app/                          # Main Python backend + Next.js frontend
│   ├── pyproject.toml                 # Python 3.12+, FastAPI 0.115+, SurrealDB 1.0+
│   ├── env.example                    # Multi-stack model config (Lean/Core/Titan)
│   ├── launch-aura.ps1               # Full boot: SurrealDB + Uvicorn + TTS + Frontend
│   ├── launch-aura-fast.ps1          # Fast boot: skip TTS, skip checks
│   ├── launch-aura.sh                # Unix variant
│   ├── docs/
│   │   ├── PHASE1_DIAGNOSTIC_REPORT.md  # Insight stall proof + TITANS blueprint
│   │   └── TECHNICAL_HANDOVER.md        # This document
│   ├── scripts/
│   │   ├── init_schema.surql          # 443 lines: DEFINE TABLE/FIELD/INDEX (structural)
│   │   ├── seed_emotions.surql        # 27 emotion seeds + default identity + MAIN session
│   │   ├── register_local_tools.surql # MCP / local-function skill registrations
│   │   ├── seed_cultural_nodes.surql  # Cultural knowledge-graph seed data
│   │   └── setup_tasks.surql          # Default task scaffolding
│   ├── frontend/                      # Next.js (TypeScript, Redux, WebSocket)
│   │   └── src/
│   │       ├── types/aura.ts          # TypeScript mirrors of Pydantic models
│   │       ├── components/            # All React components (see §11)
│   │       ├── store/                 # Redux slices (chat, emotion)
│   │       ├── hooks/                 # useSocket, useInferenceConfig, useRedux
│   │       └── utils/                 # emotionToBlendshape, emotion cache
│   └── src/aura/                      # Python backend package
│       ├── main.py                    # FastAPI entry point (lifespan, routes, WebSocket)
│       ├── config.py                  # Pydantic Settings (env-driven, stack-aware)
│       ├── logging_config.py          # Sanitization, health-check filtering
│       ├── engines/                   # 7 cognitive engines (see §5)
│       ├── llm/                       # LLM layers, providers, router (see §6)
│       ├── orchestrator/              # Meta-cognitive coordinator (see §7)
│       ├── executor/                  # Agent loop, task queue, tool executor
│       ├── models/                    # Pydantic models (strict 1:1 DB binding)
│       ├── tools/                     # Local tools: web_search, filesystem, terminal, code_executor
│       ├── api/                       # FastAPI route modules + WebSocket managers
│       ├── db/                        # SurrealDB client + connection pool
│       ├── connections/               # MCP client manager
│       └── memory/                    # Memory manager (RAG retrieval)
├── aura-launcher/                     # Tauri v2 desktop launcher (Rust)
│   └── src-tauri/
│       ├── src/
│       │   ├── main.rs, lib.rs        # Entry points
│       │   ├── commands.rs            # Tauri IPC commands
│       │   ├── config.rs              # TOML config parser
│       │   ├── health.rs              # Health probe (HTTP polling)
│       │   ├── process_bridge.rs      # Child process lifecycle
│       │   ├── state.rs               # State machine
│       │   ├── tray.rs                # System tray (starting/ready/failed/stopped icons)
│       │   ├── tts_supervisor.rs      # Qwen3-TTS monitoring
│       │   ├── loading_window.rs      # Splash screen
│       │   └── log_server.rs          # Log streaming
│       └── tests/                     # config_roundtrip, health_probe, state_machine
├── Qwen3-TTS/                         # Qwen3-TTS-12Hz-1.7B-CustomVoice
│   ├── server.py                      # FastAPI server on port 50000 (FIFO queue)
│   ├── config.json, generation_config.json, tokenizer_config.json
│   └── speech_tokenizer/              # Speech tokenizer configs
└── vrm-animations-temp/               # VRM animations + models (BVH/VRMA files)
    ├── animation/                     # 100+ BVH animation files
    ├── animation_nitral-fork/         # Forked animation set (some VRMA format)
    ├── model/                         # VRM models (Aera, Dhahlia, Epithet, Lara, Onyx)
    └── desktop theme/                 # Discord Dark VRM 2.0 JSON
```

---

## 4. The Cognitive Stack (Fully Operational)

### 4.1 Layer Architecture

| Layer | Role | Default Model (Stack 0 "Lean") | Latency Target |
|-------|------|-------------------------------|----------------|
| **L1** | Router / Fast Path / Intent Gatekeeper | `mistralai/mistral-7b-instruct:free` (OpenRouter) | TTFT < 200ms |
| **L2** | Reasoning / Deep Analysis / Conflict Detection | `anthropic/claude-3.5-sonnet` | ~2–5s |
| **L3** | Heavy Cognition / Synthesis / Response Generation | `deepseek/deepseek-chat` | ~3–8s |
| **L4** | Emotion Translation / Natural Language Description | `qwen/qwen-2.5-72b-instruct` | ~1–3s |
| **L5** | Structure Analysis / JSON Extraction / Summary Generation | `google/gemini-flash-1.5` | ~1–3s |

**File:** [`LLMLayers`](Aura-Core/aura-app/src/aura/llm/layers.py:52) — 1617 lines; manages all 5 layers.

### 4.2 Model Stack System (Hot-Swappable)

Three pre-configured stacks, switchable at runtime via `POST /system/model-stack` or the Lean/Core/Titan toggle in the UI navbar:

| Stack | L1 | L2 | L3 | L4 | L5 |
|-------|----|----|----|----|-----|
| **Stack 0: Lean** (default) | mistral-7b-instruct | claude-3.5-sonnet | deepseek-chat | qwen-2.5-72b | gemini-flash-1.5 |
| **Stack 1: Core** | mistral-7b-instruct | gemini-flash-latest | grok-4.3 | qwen-2.5-72b | gemini-3.1-flash-lite |
| **Stack 2: Titan** | gemma-4-26b-a4b-it | deepseek-v4-pro | gemini-3.1-pro | claude-haiku-4.5 | qwen3.6-plus |

**File:** [`env.example`](Aura-Core/aura-app/env.example:29-68) — Stack definitions.

### 4.3 Vector Space

| Attribute | Value |
|-----------|-------|
| **Model** | `nomic-embed-text-v1.5` |
| **Dimensionality** | 768 (HNSW index with COSINE distance in SurrealDB) |
| **Runtime** | Locally on CUDA via `sentence-transformers` |
| **Sovereignty Rule** | Cloud LLMs must NEVER write to the vector space — schema is locked at 768 dims |

### 4.4 Database

| Attribute | Value |
|-----------|-------|
| **Engine** | SurrealDB v3.0.5 |
| **Connection** | WebSocket (`ws://127.0.0.1:8000/rpc`) |
| **Mode** | In-memory (boot via `surreal start memory`) |
| **Schema Strategy** | 100% strictly typed (`SCHEMAFULL` / `SCHEMALESS` hybrid) with exact 1:1 Pydantic model bindings |
| **Namespace/DB** | `aura` / `main` |

### 4.5 TTS Pipeline

| Attribute | Value |
|-----------|-------|
| **Primary** | Qwen3-TTS-12Hz-1.7B-CustomVoice (local, port 50000) |
| **Fallback** | Edge-TTS (cloud, `en-US-AriaNeural`) |
| **Voice Identity Lock** | `torch.manual_seed(42)` + `torch.cuda.manual_seed_all(42)` + `random.seed(42)` — applied per-generation |
| **Sequencing** | Strict async FIFO queue (`asyncio.Queue`) prevents out-of-order audio |
| **Speakers** | serena, vivian, uncle_fu, ryan, aiden, ono_anna, sohee, eric, dylan |

**File:** [`server.py`](Aura-Core/Qwen3-TTS/server.py:99-178) — `Qwen3TTSEngine` class with deterministic seed locking.

---

## 5. Active Sub-Engines (Detailed)

### 5.1 Emotion Engine (`emotion_engine`)

**File:** [`emotion/engine.py`](Aura-Core/aura-app/src/aura/engines/emotion/engine.py:32) — 470 lines.

**Core Components:**
- [`EmotionVector`](Aura-Core/aura-app/src/aura/models/emotion.py:11) — 27-dimensional vector:
  - **9 Primary:** love, joy, interest, trust, fear, sadness, anger, surprise, disgust
  - **6 Aesthetic:** awe, beauty, wonder, serenity, melancholy, nostalgia
  - **6 Social:** empathy, gratitude, pride, shame, envy, compassion
  - **6 Cognitive:** curiosity, confusion, certainty, doubt, fascination, boredom
- [`EmotionPhysics`](Aura-Core/aura-app/src/aura/engines/emotion/physics.py:1) — Per-emotion decay rates, inertia, influence application.
- [`EmotionTranslator`](Aura-Core/aura-app/src/aura/engines/emotion/translator.py:1) — Converts 27D vector → natural language description.

**Lifecycle:**
1. On boot: loads last persisted `emotion_state` from SurrealDB, hydrates physics parameters (decay, inertia) from the `emotion` table (DB-driven, self-modifying physics).
2. Tick loop: applies physics decay toward baseline, detects significant changes (>0.3 delta), broadcasts via message bus + WebSocket.
3. On influence: applies external `EmotionInfluence` with intensity modulation, clamps to [0.0, 1.0], broadcasts urgently.
4. Persists to `emotion_state` table periodically.

**WebSocket Streams:**
- `/ws/emotion` — Legacy emotion stream.
- `/v1/stream/emotions` — Full 27D vector at ~10 Hz with valence/arousal/volatility/dominant for VRM blendshape driving.

**Key Methods:**
- `get_current_state()` → `EmotionState` (vector + dominant + volatility + stability + description)
- `apply_influence(influence)` → applies external emotional push
- `capture_learning_event()` → freezes `EmotionalSignature` for emotional tagging on rules (FR-LE-001)

### 5.2 Latent Engine (`latent_engine`) — TITANS-Inspired

**File:** [`latent/engine.py`](Aura-Core/aura-app/src/aura/engines/latent/engine.py:71) — 799 lines.

**Architecture:** Third memory pillar complementing Vector RAG and Graph Traversal.

| Pillar | Mechanism | Latency | Coverage |
|--------|-----------|---------|----------|
| **Vector RAG** | Cosine similarity search via HNSW index | ~200ms | Pinpoint recall |
| **Graph Traversal** | `related_to`, `next_experience` edges | ~300ms | Causal chains |
| **Latent State (TITANS)** | Compressed neural embedding (EMA) | **~0ms** | Holistic intuition |

**Core Data Structures:**
- [`LatentStateCache`](Aura-Core/aura-app/src/aura/engines/latent/engine.py:51) — In-memory per-user cache:
  - `state_vector`: 768D EMA of all absorbed experience embeddings
  - `momentum_vector`: 768D direction of recent state changes
  - `emotional_centroid`: Dict[str, float] — how this user makes Aura feel over time
  - `domain_distribution`: Dict[str, float] — what the user cares about
  - `summary_text`: Natural-language interpretation (regenerated every 10 state updates via L5)

**Surprise-Gated Update Loop:**
1. `absorb_experience()` called after every experience is logged.
2. Compute **Surprise Gradient**: `1 - cos(new_embedding, state_vector)` adjusted by momentum alignment.
3. Compute **Adaptive Threshold**: `τ = avg_surprise + k * sqrt(variance)` where `k` scales with maturity (0.5 early → 1.5 stable).
4. If `surprise > threshold` → state update with annealed learning rate.
5. If `surprise > 0.70 AND has experience_id` → create `->modulates->` graph edge.
6. Every 10 updates → regenerate natural-language summary via L5.

**MAC (Memory as Context):**
- `get_intuition_context(user_id)` — Zero-latency in-memory read. Returns XML block for L3 injection:
  ```xml
  <latent_intuition>
    <state_summary confidence="0.87" experiences_absorbed="342">...</state_summary>
    <emotional_centroid>curiosity=0.72, interest=0.65</emotional_centroid>
    <domain_affinity>systems_programming=0.34, ai_architecture=0.28</domain_affinity>
    <recent_drift direction="toward ai_architecture" magnitude="0.12"/>
  </latent_intuition>
  ```

**Warm-Start:** On first boot, processes last 50 experiences from DB to rapidly anneal an initial baseline state.

**Singleton:** Accessed via `get_latent_engine()`.

### 5.3 Learning Engine (`learning_engine`)

**File:** [`learning/engine.py`](Aura-Core/aura-app/src/aura/engines/learning/engine.py:30) — 2544 lines (largest engine).

**6-Phase Learning Cycle:** Capture → Extract → Abstract → Integrate → Transfer → Validate.

**Key Subsystems:**

#### Experience Logging
- [`log_experience()`](Aura-Core/aura-app/src/aura/engines/learning/engine.py:1562) — Logs interaction with semantic embedding (background task). Creates temporal `next_experience` graph edges for causal chain traversal.

#### Pattern Extraction (3 Routes)
- **Route A:** `direct_instruction` — "God Mode" learning; bypasses LLM, writes fact directly with confidence=1.0.
- **Route B:** `instruction` / `teaching` intent — Compiles tool/skill from user-provided JSON schema or local Python file. Supports MCP server tools, single-tool modules (`TOOL_DEFINITION`), and multi-tool modules (`TOOLS` dict).
- **Route C:** Behavioral Analysis — Stratified temporal sampling (Session 7 upgrade): recent 50%, mid-range 30%, oldest 20% of experiences. Window expands logarithmically with domain insight count. Uses L5 for insight extraction (FACT, PREFERENCE, PATTERN).

#### Skill Compilation
- [`_compile_new_skill()`](Aura-Core/aura-app/src/aura/engines/learning/engine.py:207) — Creates `skill` nodes with `skill_type` = `local_function` or `mcp_tool`. Stores `TOOL_DEFINITION` JSON schema and `execution_config` (module path, function name, tool_key for multi-tool modules).
- [`ingest_local_tool_module()`](Aura-Core/aura-app/src/aura/engines/learning/engine.py:861) — Dynamically imports Python files from `src/aura/tools/`, validates `TOOL_DEFINITION` or `TOOLS` dict, creates skill nodes.
- [`ingest_mcp_server()`](Aura-Core/aura-app/src/aura/engines/learning/engine.py:1196) — Connects to MCP server, discovers tools, ingests each as a skill with `skill_type` = `mcp_tool`.
- Background trigger generation: L5 generates 10-15 natural language trigger phrases per tool; embeddings created with semaphore-bounded concurrency (max 4 parallel).

#### Insight Deduplication
- Semantic similarity check using vector cosine similarity with dynamic threshold (Session 7 fix):
  ```python
  threshold = min(0.98, 0.90 + 0.08 * log(1 + count) / log(50))
  ```
- This resolves the 17-insight stall (emergent mathematical asymptote from fixed 0.90 threshold).

#### Hybrid Retrieval
- [`retrieve_relevant()`](Aura-Core/aura-app/src/aura/engines/learning/engine.py:1814) — Vector similarity search (cosine via `vector::similarity::cosine`) with domain/user/confidence filters, fallback to filtered search.

### 5.4 Identity Engine (`identity_engine`)

**File:** [`identity/engine.py`](Aura-Core/aura-app/src/aura/engines/identity/engine.py:27) — 438 lines.

**Features:**
- **Autobiographical Narrative:** First-person self-description, evolves via periodic analysis.
- **Core Values:** Weighted meta-values (default: openness=0.8, curiosity=0.9, honesty=0.85, growth=0.9, empathy=0.8).
- **Preferences:** Learned likes/dislikes organized by category.
- **Evolution Tracking:** `identity_change` records logged to DB.
- **Proprioception (Capability Awareness):** Queries `skill` table for `mcp_tool` and `local_function` skills, injects into identity context.
- **Session Overlay (V1PRD §4.4):** Read-time overlay patches; never mutates the global Identity.
- **Value Alignment:** LLM-based alignment scoring for proposed actions against core values.

### 5.5 Goal Engine (`goal_engine`)

**File:** [`goal/engine.py`](Aura-Core/aura-app/src/aura/engines/goal/engine.py:24) — 906 lines.

**Features:**
- **Boredom-Driven Generation:** Monitors `boredom` emotion from emotion engine; triggers new goal when >0.6.
- **LLM-Based Goal Formulation:** Uses L3 (creative synthesis, temperature=0.85) to analyze emotional state + learning gaps + recent memories → generates specific, novel goals.
- **Template Fallback:** `boredom`, `idle_exploration`, `curiosity` templates when LLM unavailable.
- **Autonomous Pursuit:** `pursue_goal_autonomously()` — Multiple L2/L3 iterations working toward goal; interruptible by user interaction.
- **Progress Tracking:** Emotional alignment scoring — progress increases when current emotions match goal's emotional_alignment.
- **Rate Limiting:** Max 1 new goal per hour; max 5 active goals; duplicate detection by name/description.
- **Stale Goal Cleanup:** Goals active >24h with <10% progress marked completed.

### 5.6 Reflection Engine (`reflection_engine`)

**File:** [`reflection/engine.py`](Aura-Core/aura-app/src/aura/engines/reflection/engine.py:54) — 600 lines.

**Features:**
- **Nightly Reflection:** Configurable interval (default 86400s = 24h via `REFLECTION_INTERVAL` env var).
- **4-Parallel Analysis:** Emotional summary + Learning patterns + Goal progress + Identity shifts (gathered in parallel via `asyncio.gather`).
- **L5 Proposal Generation:** Improvement proposals for emotion regulation, goal focus, learning strategy.
- **Interaction Critique:** Quick per-message coherence check via L2 (5s timeout).
- **Insight-Based Actions:** Triggers pattern extraction on learning_engine when learning opportunities detected.

### 5.7 Dreaming Engine (`dreaming_engine`)

**File:** [`dreaming/engine.py`](Aura-Core/aura-app/src/aura/engines/dreaming/engine.py:39) — 782 lines.

**Full Cognitive Maintenance Pass (REM Sleep):**

| Phase | Name | Description |
|-------|------|-------------|
| 1 | **Tiered Pruning** | Ephemeral + >24h → hard delete; Ephemeral + >7d → hard delete; Non-core faded (decay < 0.05) → soft delete (deprecated=True); Core memories → immune |
| 2 | **Abstraction** | Greedy clustering of 5+ episodic memories (cosine > 0.80) → L5 synthesizes semantic memory, sources deprecated + linked via `->abstracted_into->` edges |
| 3 | **Emotional Reprocessing** | Negative memories (frustration, confusion, anger, etc.) older than 48h → L2 extracts lesson → stored as PATTERN insight; source importance reduced by 40% |
| 4 | **Causal Weaving** | Finds orphaned experience nodes (no outgoing edge) from last 24h → creates `next_experience` edges for consecutive pairs within 30-min session window |
| 5 | **Trial-and-Error REM** | Finds failure→success sequences via `next_experience` edges → L2 extracts learned rule → stored as insight |
| 6 | **Consolidation Report** | Summary stored as system memory for self-reflection |

**Decay Formula** (for pruning decisions):
- Half-life base: 48h
- High emotional intensity (>0.7): half-life × 4
- Each recall: +12h to half-life
- Ephemeral flag: half-life / 4
- Final decay: `exp(-0.693 × age_hours / half_life)`

---

## 6. LLM Architecture (Provider Layer)

### 6.1 UnifiedLLMClient

**File:** [`unified_provider.py`](Aura-Core/aura-app/src/aura/llm/unified_provider.py:13) — 194 lines.

Routes requests to either OpenRouter (cloud) or Ollama (local) based on model prefix:
- `"local/"` prefix → Ollama (e.g., `"local/llama3.2"`)
- No prefix → OpenRouter (e.g., `"anthropic/claude-3.5-sonnet"`)
- Auto-fallback: if local fails and `AURA_LOCAL_LLM_FALLBACK_TO_CLOUD=true`, retries via cloud.

### 6.2 Context Mode Router

**File:** [`router.py`](Aura-Core/aura-app/src/aura/llm/router.py:1) — ContextModeRouter with two modes:
- `deep_work`: All LLM requests route through OpenRouter (cloud).
- `private_rp`: All LLM requests route to the local inference endpoint.

Switchable at runtime via `POST /v1/context-mode`.

### 6.3 SGLang Constrained Sampler

When `AURA_SGLANG_ENABLED=true`:
- L1 and L3 get extra sampling params (`top_k`, `min_p`, `repetition_penalty`) injected into request body.
- Provides radix-attention + constrained output for XML thought clusters.
- Default server: `http://127.0.0.1:30000`.

---

## 7. Orchestrator (Meta-Cognitive Coordinator)

**File:** [`coordinator.py`](Aura-Core/aura-app/src/aura/orchestrator/coordinator.py:42) — 2661 lines.

### 7.1 System State Machine

| State | Description | Transition Trigger |
|-------|-------------|-------------------|
| **ACTIVE** | Normal operation, user interacting | Default on boot; auto-wake from IDLE |
| **IDLE** | Low-power, no user interaction | `idle_after_minutes` elapsed (default: 15) |
| **DREAMING** | Consolidation in progress | `dream_after_minutes` elapsed (default: 30); user force-trigger |
| **SLEEPING** | Zero-inference, wake-word gated | After dreaming sequence completes |

**Wake Word:** "Aura" (configurable via `AURA_SYSTEM_WAKE_WORD`).
**Auto-Wake:** `AURA_SYSTEM_AUTO_WAKE_ON_QUERY=true` bypasses wake-word requirement.

### 7.2 Query Processing Pipeline (`process_query()`)

**File:** [`process_query()`](Aura-Core/aura-app/src/aura/orchestrator/coordinator.py:540)

1. **Context Mode Setup** — Set `context_mode` on LLM router.
2. **Session Resolution** — Map session_id → memory namespace + identity overlay.
3. **Sleep Gate** — Reject if SLEEPING/DREAMING (unless wake-word or auto-wake).
4. **Priority 0: System Commands** — Regex intercept for `System: Connect MCP <name> <url>` and `System: Ingest tool <name>`.
5. **Priority 0.5: Direct Learning** — Regex intercept for `Aura learn: <fact>` → forces `direct_instruction` experience.
6. **L1 Intent Gatekeeper** — Classifies intent (conversation, tool_use, learning, system, emotional).
7. **Parallel Engine Queries** — Emotion, Identity, Goal, Learning, Memory (all gathered concurrently).
8. **L3 Synthesis Context** — Assembles `SynthesisContext` with all engine outputs + latent intuition XML.
9. **L3 Response Generation** — Primary response.
10. **Post-Response Chain** — Emotion influence application, experience logging, L2 deep analysis (async).

### 7.3 Tool Execution Integration

The orchestrator handles tool call patterns in responses:
- Detects `<tool_call>`, `<search>`, `<code>`, `<execute>`, `<file_read>`, `<file_write>` XML blocks.
- Routes to `ToolExecutor` which resolves tool skills from the learning engine's skill tree.
- Supports MCP tools (via `ToolExecutor` → `MCPClient`), local tools (direct Python import), and workspace tools.

---

## 8. Tools Ecosystem

### 8.1 Local Tools

| Tool | File | Capabilities | Risk |
|------|------|-------------|------|
| **web_search** | [`tools/web_search.py`](Aura-Core/aura-app/src/aura/tools/web_search.py:1) | Tavily REST API (async aiohttp), time-filtered, raw content option | Low |
| **filesystem** | [`tools/filesystem.py`](Aura-Core/aura-app/src/aura/tools/filesystem.py:1) | Read/write/list/delete files within allowed paths; core path protection | Medium |
| **terminal** | [`tools/terminal.py`](Aura-Core/aura-app/src/aura/tools/terminal.py:1) | Safe commands execute immediately; mutative commands require approval | Medium |
| **code_executor** | [`tools/code_executor.py`](Aura-Core/aura-app/src/aura/tools/code_executor.py:1) | Python/Node.js/Shell in sandboxed temp dirs; timeout enforcement; blocked patterns | Medium |

### 8.2 Tool Definition Contract

Every tool module exposes:
```python
TOOL_DEFINITION = {
    "name": "tool_name",
    "description": "What this tool does",
    "parameters": { /* JSON Schema */ }
}

async def run(arguments: Dict[str, Any]) -> str:
    """Execute the tool."""
```

Multi-tool modules expose:
```python
TOOLS = {
    "tool_name": {"definition": {...}, "run": async_func}
}
```

### 8.3 MCP Integration

- MCP servers connect via `stdio` or `streamable_http`/`sse` transport.
- Tools discovered at connect time and persisted as skills in SurrealDB.
- Runtime connectivity handled by `MCPClient`; returns "offline" status when server unreachable.
- Connection configs stored in skill's `execution_config` for reconnection.

---

## 9. Frontend Architecture

**Framework:** Next.js (TypeScript) on port 3000.
**State:** Redux Toolkit with slices for chat and emotion.
**Real-time:** WebSocket connections for emotion streaming and cognitive traces.

### 9.1 Component Map

| Component | Purpose |
|-----------|---------|
| [`ChatInput`](Aura-Core/aura-app/frontend/src/components/chat/ChatInput.tsx) | Message input with model stack selector, reasoning toggles |
| [`ChatMessage`](Aura-Core/aura-app/frontend/src/components/chat/ChatMessage.tsx) | Rendered message with Markdown support |
| [`MarkdownRenderer`](Aura-Core/aura-app/frontend/src/components/chat/MarkdownRenderer.tsx) | Extended Markdown with code blocks, tables, etc. |
| [`CognitiveStatus`](Aura-Core/aura-app/frontend/src/components/cognitive/CognitiveStatus.tsx) | L1/L2/L3 trace visualization |
| [`EmotionRadar`](Aura-Core/aura-app/frontend/src/components/emotion/EmotionRadar.tsx) | 27D radar chart visualization |
| [`InferenceCockpit`](Aura-Core/aura-app/frontend/src/components/inference/InferenceCockpit.tsx) | Temperature, top_p, min_p, context length sliders |
| [`GoalPursuitModal`](Aura-Core/aura-app/frontend/src/components/goal/GoalPursuitModal.tsx) | Autonomous goal pursuit UI |
| [`AgentLoopPanel`](Aura-Core/aura-app/frontend/src/components/agent/AgentLoopPanel.tsx) | Agent execution visualization |
| [`CulturalPanel`](Aura-Core/aura-app/frontend/src/components/cultural/CulturalPanel.tsx) | Cultural knowledge graph explorer |
| [`DebugPanel`](Aura-Core/aura-app/frontend/src/components/debug/DebugPanel.tsx) | Debug controls |
| [`SystemDebugPanel`](Aura-Core/aura-app/frontend/src/components/debug/SystemDebugPanel.tsx) | System state inspection |
| [`StreamingVisualizer`](Aura-Core/aura-app/frontend/src/components/debug/StreamingVisualizer.tsx) | Token streaming visualization |
| [`ServerStatusAlert`](Aura-Core/aura-app/frontend/src/components/common/ServerStatusAlert.tsx) | Connection status banner |
| [`GoldenGlow`](Aura-Core/aura-app/frontend/src/components/common/GoldenGlow.tsx) | Vanta Black & Gold aesthetic wrapper |
| **VRM Components** | `VrmRenderer`, `AvatarCanvas`, `SpiralAvatar`, `FloatingAvatarWindow`, `AuraAvatar` |
| **Layout** | `Layout`, `MainLayout`, `NeuralSidebar` |

### 9.2 WebSocket Streams

| Endpoint | Rate | Payload |
|----------|------|---------|
| `/ws/emotion` | Event-driven | EmotionState on significant change |
| `/v1/stream/emotions` | ~10 Hz | Full 27D vector + valence/arousal/volatility/dominant |
| `/v1/stream/traces` | Event-driven | L1/L2/L3 cognitive trace events |

### 9.3 TypeScript Data Contract

**File:** [`aura.ts`](Aura-Core/aura-app/frontend/src/types/aura.ts) — 244 lines; mirrors backend Pydantic models.

---

## 10. Launcher Architecture (Tauri v2)

**File:** [`aura-launcher/`](Aura-Core/aura-launcher/) — Desktop orchestrator written in Rust.

### 10.1 Key Modules

| Module | Purpose |
|--------|---------|
| [`process_bridge.rs`](Aura-Core/aura-launcher/src-tauri/src/process_bridge.rs) | Child process lifecycle management (SurrealDB, Uvicorn, TTS, Frontend) |
| [`health.rs`](Aura-Core/aura-launcher/src-tauri/src/health.rs) | HTTP health probe polling (`/health` endpoint) |
| [`state.rs`](Aura-Core/aura-launcher/src-tauri/src/state.rs) | State machine (starting → ready → failed → stopped) |
| [`tray.rs`](Aura-Core/aura-launcher/src-tauri/src/tray.rs) | System tray with 4 state icons (starting/ready/failed/stopped) |
| [`tts_supervisor.rs`](Aura-Core/aura-launcher/src-tauri/src/tts_supervisor.rs) | Qwen3-TTS process monitoring |
| [`loading_window.rs`](Aura-Core/aura-launcher/src-tauri/src/loading_window.rs) | Splash screen with loading animation |
| [`log_server.rs`](Aura-Core/aura-launcher/src-tauri/src/log_server.rs) | Log streaming to frontend |
| [`config.rs`](Aura-Core/aura-launcher/src-tauri/src/config.rs) | TOML config parser (`aura.config.toml`) |

### 10.2 IPC Commands

- `start_services` — Launches all backend processes.
- `stop_services` — Graceful shutdown (`POST /v1/system/shutdown` → SIGTERM).
- `get_status` — Returns health status of all services.
- `get_logs` — Returns recent log output.

---

## 11. Database Schema (SurrealDB)

**File:** [`init_schema.surql`](Aura-Core/aura-app/scripts/init_schema.surql) — 443 lines.

### 11.1 Core Tables

| Table | Type | Key Fields |
|-------|------|------------|
| `emotion` | SCHEMAFULL | name, category, physics (decay, inertia) |
| `emotion_state` | SCHEMAFULL | timestamp, vector (FLEXIBLE), dominant, volatility, description |
| `memory` | SCHEMAFULL | content, embedding (768D HNSW COSINE), emotional_signature, importance, core_memory, ephemeral, deprecated, memory_type, emotional_intensity, recall_count, formation_score |
| `experience` | — | user_id, task_type, domain, context, aura_response, outcome, emotional_state, embedding |
| `insight` | — | content, type (FACT/PREFERENCE/PATTERN), confidence, domain, embedding (768D), deprecated |
| `skill` | — | name, domain, skill_type (local_function/mcp_tool/abstract), definition, execution_config, tool_name, parent_skill_id, sub_skill_ids |
| `semantic_trigger` | — | phrase, embedding (768D), target_action (record<skill>), confidence |
| `goal` | — | name, description, goal_type, status, priority, progress, emotional_alignment |
| `identity` | — | name, version, autobiographical_narrative, core_values, self_concept, preferences |
| `identity_change` | — | change_type, old_value, new_value, rationale, timestamp |
| `reflection` | — | period_start, period_end, reflection_type, insights, patterns_found, proposals |
| `conversation` | SCHEMAFULL | title, user_id, session_id, key_topics, summary |
| `message` | SCHEMAFULL | conversation_id, content, role, timestamp |
| `latent_state` | SCHEMAFULL | user_id, state_vector (array<float>), momentum_vector, version, avg_surprise, surprise_variance, emotional_centroid, domain_distribution, summary_text |
| `session` | — | session_id, label, active, memory_namespace, identity_overlay |
| `system_journal` | — | user_id, entry, session_start, session_end, metadata |

### 11.2 Graph Edge Types

| Edge | From | To | Purpose |
|------|------|----|---------|
| `next_experience` | experience | experience | Temporal causal chain (+ elapsed_ms) |
| `modulates` | experience | latent_state | Surprising experiences that changed latent state |
| `skill_contains` | skill | skill | Parent→child skill hierarchy |
| `triggers_skill` | semantic_trigger | skill | Trigger phrase → skill mapping |
| `abstracted_into` | memory | memory | Episodic → semantic memory abstraction |

### 11.3 Boot Order (Mandatory)

1. `init_schema.surql` — Structural DEFINE-only baseline.
2. `seed_emotions.surql` — 27 emotions, default identity, MAIN session.
3. `register_local_tools.surql` — MCP / local-function skill registrations.
4. `seed_cultural_nodes.surql` — Cultural knowledge-graph seed data.
5. `setup_tasks.surql` — Default task scaffolding.

Each script is idempotent — errors from individual statements are logged as warnings but never raised.

---

## 12. Known Issues & Resolved Problems

### 12.1 Resolved: 17-Insight Mathematical Stall

**Documented in:** [`PHASE1_DIAGNOSTIC_REPORT.md`](Aura-Core/aura-app/docs/PHASE1_DIAGNOSTIC_REPORT.md:10)

**Root Cause:** Fixed 0.90 cosine similarity deduplication threshold in `create_insight()` caused emergent asymptote — the 768D embedding manifold's accessible volume for a single domain saturated after ~17 insights.

**Fix Applied (Session 7):**
- Dynamic dedup threshold: `0.90 + 0.08 × log(1 + count) / log(50)`, capped at 0.98.
- Stratified temporal sampling: recent 50%, mid-range 30%, oldest 20%.
- Window expansion: `min(20, 5 + 2 × log(1 + domain_insight_count))`.
- Domain insight count injected into LLM prompt.

### 12.2 Resolved: TTS Sequence Racing

**Problem:** Multiple concurrent TTS requests caused out-of-order audio playback.

**Fix:** Strict async FIFO queue in [`server.py`](Aura-Core/Qwen3-TTS/server.py:43-87) — `_TTSJob` with `asyncio.Future`, single `_tts_worker()` coroutine draining queue sequentially.

### 12.3 Resolved: Schema Strict-Typing Errors

**Problem:** SurrealDB SCHEMAFULL validation failures on field type mismatches (RecordID vs string, optional vs required, FLEXIBLE vs strict).

**Fix:** All Pydantic models now have exact 1:1 field definitions; SurrealDB schema uses `FLEXIBLE` on dynamic fields (like `vector`, `emotional_signature`) and `option<T>` on nullable fields.

### 12.4 Active Monitoring: Qwen3-TTS Seed Drift

**Risk:** The deterministic seed (42) applied via `torch.manual_seed()` and `random.seed()` is set per-generation in Python. However, the underlying C++ CUDA kernels in `qwen-tts` may not fully respect the Python-level seed during prolonged generation sessions, potentially causing voice identity drift across long responses.

**Mitigation:** Re-apply seeds at the start of every `generate()` call. Monitor for voice consistency across sentences >30s total duration.

### 12.5 Active Risk: In-Memory Database

SurrealDB is started with `surreal start memory` — all data is lost on restart. This is intentional for development but requires migration to file-backed storage (`rocksdb` or `surrealkv`) for production persistence.

---

## 13. Environment Configuration Reference

### 13.1 Critical Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | — | **Required.** Cloud LLM access. |
| `TAVILY_API_KEY` | — | **Required.** Web search tool. |
| `SURREAL_URL` | `ws://127.0.0.1:8000/rpc` | Database WebSocket endpoint. |
| `SURREAL_USER` / `SURREAL_PASS` | `root` / `root` | Database credentials. |
| `SURREAL_NS` / `SURREAL_DB` | `aura` / `main` | Namespace and database. |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8080` | FastAPI bind address. |
| `AURA_MODEL_STACK_INDEX` | `0` | Active model stack (0=Lean, 1=Core, 2=Titan). |
| `AURA_LOCAL_LLM_ENABLED` | `false` | Route all LLM through Ollama. |
| `AURA_QWEN3_TTS_ENABLED` | `true` | Use local Qwen3-TTS. |
| `AURA_QWEN3_TTS_URL` | `http://127.0.0.1:50000` | TTS server endpoint. |
| `AURA_QWEN3_TTS_SPEAKER` | `serena` | Default TTS voice. |
| `AURA_TTS_PROVIDER` | `qwen3` | Primary TTS provider (`qwen3` or `edge`). |
| `AURA_SYSTEM_WAKE_WORD` | `Aura` | Wake word for sleep gating. |
| `AURA_SYSTEM_IDLE_AFTER_MINUTES` | `15` | Minutes before IDLE transition. |
| `AURA_SYSTEM_DREAM_AFTER_MINUTES` | `30` | Minutes before DREAMING transition. |
| `AURA_SYSTEM_AUTO_WAKE_ON_QUERY` | `false` | Auto-wake without wake word. |
| `AURA_AGENT_LOOP_MAX_ITERATIONS` | `10` | Max agent loop iterations. |
| `AURA_AGENT_LOOP_REQUIRE_APPROVAL` | `true` | Require user approval for agent actions. |
| `AURA_CODE_EXECUTION_ENABLED` | `false` | Enable code execution tool. |

### 13.2 Full Configuration

**File:** [`env.example`](Aura-Core/aura-app/env.example) — 124 lines; complete reference with all model stacks, SGLang settings, local inference config.

---

## 14. Immediate Next Steps (from Codebase State)

### 14.1 Skill Execution Expansion

**Current State:** Tools framework exists (`web_search`, `filesystem`, `terminal`, `code_executor`) with full TOOL_DEFINITION contracts. MCP ingestion pipeline works. ToolExecutor resolves skills from the learning engine's skill tree.

**To Do:**
- Grant Aura proactive OS/File System tool access (auto-approve safe operations).
- Expand multi-tool module pattern across more tool categories.
- Add workspace tool registration in the boot sequence.

### 14.2 Latent Space Mapping Expansion

**Current State:** TITANS LatentEngine is fully operational with surprise-gated updates, MAC injection into L3, warm-start, and summary regeneration.

**To Do:**
- Enable organic insight generation from latent state transitions (momentum drift → curiosity goal).
- Surface latent state diagnostics in the frontend (Debug → Latent tab).
- Implement cross-user latent state similarity for pattern transfer.

### 14.3 Qwen3-TTS Seed Drift Monitoring

**Current State:** Seed 42 re-applied per `generate()` call. FIFO queue ensures sequential processing.

**To Do:**
- Add audio checksum comparison for identical prompts across generation sessions.
- Monitor C++ backend for seed non-determinism during generations exceeding 60s total duration.
- Consider per-phoneme seed reset if drift is detected.

### 14.4 Production Hardening

- Migrate SurrealDB from in-memory to file-backed storage (`surrealkv`).
- Add database backup/snapshot pipeline.
- Implement graceful degradation when cloud LLM providers rate-limit.
- Add A/B testing framework for model stack comparison.

---

## 15. File Index (Quick Reference)

| What | Where | Lines |
|------|-------|-------|
| FastAPI entry point | [`main.py`](Aura-Core/aura-app/src/aura/main.py) | 601 |
| Emotion Engine | [`engines/emotion/engine.py`](Aura-Core/aura-app/src/aura/engines/emotion/engine.py) | 470 |
| Latent Engine (TITANS) | [`engines/latent/engine.py`](Aura-Core/aura-app/src/aura/engines/latent/engine.py) | 799 |
| Learning Engine | [`engines/learning/engine.py`](Aura-Core/aura-app/src/aura/engines/learning/engine.py) | 2544 |
| Identity Engine | [`engines/identity/engine.py`](Aura-Core/aura-app/src/aura/engines/identity/engine.py) | 438 |
| Goal Engine | [`engines/goal/engine.py`](Aura-Core/aura-app/src/aura/engines/goal/engine.py) | 906 |
| Reflection Engine | [`engines/reflection/engine.py`](Aura-Core/aura-app/src/aura/engines/reflection/engine.py) | 600 |
| Dreaming Engine | [`engines/dreaming/engine.py`](Aura-Core/aura-app/src/aura/engines/dreaming/engine.py) | 782 |
| Orchestrator | [`orchestrator/coordinator.py`](Aura-Core/aura-app/src/aura/orchestrator/coordinator.py) | 2661 |
| LLM Layers | [`llm/layers.py`](Aura-Core/aura-app/src/aura/llm/layers.py) | 1617 |
| Unified Provider | [`llm/unified_provider.py`](Aura-Core/aura-app/src/aura/llm/unified_provider.py) | 194 |
| Emotion Model (27D) | [`models/emotion.py`](Aura-Core/aura-app/src/aura/models/emotion.py) | 186 |
| DB Schema | [`scripts/init_schema.surql`](Aura-Core/aura-app/scripts/init_schema.surql) | 443 |
| TTS Server | [`server.py`](Aura-Core/Qwen3-TTS/server.py) | 308 |
| Launch Script (Full) | [`launch-aura.ps1`](Aura-Core/aura-app/launch-aura.ps1) | 206 |
| Launch Script (Fast) | [`launch-aura-fast.ps1`](Aura-Core/aura-app/launch-aura-fast.ps1) | 44 |
| Env Config | [`env.example`](Aura-Core/aura-app/env.example) | 124 |
| Frontend Types | [`types/aura.ts`](Aura-Core/aura-app/frontend/src/types/aura.ts) | 244 |
| Phase 1 Diagnostic | [`docs/PHASE1_DIAGNOSTIC_REPORT.md`](Aura-Core/aura-app/docs/PHASE1_DIAGNOSTIC_REPORT.md) | 552 |
| Launcher Main | [`main.rs`](Aura-Core/aura-launcher/src-tauri/src/main.rs) | 5 |
| Launcher Lib | [`lib.rs`](Aura-Core/aura-launcher/src-tauri/src/lib.rs) | — |
| Web Search Tool | [`tools/web_search.py`](Aura-Core/aura-app/src/aura/tools/web_search.py) | 145 |
| Filesystem Tool | [`tools/filesystem.py`](Aura-Core/aura-app/src/aura/tools/filesystem.py) | 728 |
| Terminal Tool | [`tools/terminal.py`](Aura-Core/aura-app/src/aura/tools/terminal.py) | 223 |
| Code Executor Tool | [`tools/code_executor.py`](Aura-Core/aura-app/src/aura/tools/code_executor.py) | 317 |

---

## 16. Boot Sequence Summary

1. **SurrealDB** starts on `127.0.0.1:8000` (in-memory mode).
2. **Uvicorn** starts on `127.0.0.1:8080` serving FastAPI (`aura.main:app`).
3. On lifespan startup:
   - Database connection with 5-retry logic.
   - Schema bootstrap: 5 `.surql` scripts executed idempotently.
   - MessageBus started.
   - 7 Engines initialized and started (Emotion → Learning → Identity → Goal → Reflection → Dreaming → Latent).
   - LLMLayers initialized (UnifiedLLMClient if local enabled, else OpenRouterClient).
   - Orchestrator initialized with all engine references.
   - SessionRuntime initialized (seeds MAIN session).
   - TaskQueue initialized (recovers interrupted tasks).
   - Agent Loop executor initialized.
   - Workspace filesystem watcher started.
   - Route engine references set.
4. **Qwen3-TTS** starts on port 50000 (if available).
5. **Next.js** frontend starts on port 3000.

---

*End of Technical Handover. This document reflects the codebase state as of 2026-05-10. All file references are relative to `Aura-Core/`.*
