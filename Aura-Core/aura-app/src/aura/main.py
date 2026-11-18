"""FastAPI application entry point."""

import asyncio
import logging
import os
import signal
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi import APIRouter, status

from aura.api.routes import chat as chat_routes
from aura.api.routes import conversations as conversations_routes
from aura.api.routes import emotion as emotion_routes
from aura.api.routes import goal as goal_routes
from aura.api.routes import learning as learning_routes
from aura.api.routes import memory as memory_routes
from aura.api.routes import system_state as system_state_routes
from aura.api.routes import voice as voice_routes
from aura.api.routes import local_ai as local_ai_routes
from aura.api.routes import agent as agent_routes
from aura.api.routes import cultural as cultural_routes
from aura.api.routes import sessions as session_routes
from aura.api.routes import school as school_routes
from aura.api.routes import tasks as task_routes
from aura.api.routes import workspace as workspace_routes
from aura.api.routes import cognition as cognition_routes
from aura.api.routes import inference_config as inference_config_routes
from aura.api.routes import l5_animation as l5_animation_routes
from aura.api.routes import discord as discord_routes
from aura.discord.bot import bot_instance as discord_bot
from aura.executor.task_queue import get_task_queue
from aura.orchestrator.session_runtime import get_session_runtime
from aura.logging_config import setup_logging_filters
from aura.api.websocket import emotion_stream_endpoint
from aura.api.trace_socket_manager import get_trace_manager
from aura.config import settings
from aura.db.client import get_db_client
from aura.engines.dreaming.engine import DreamingEngine
from aura.engines.emotion.engine import EmotionEngine
from aura.engines.goal.engine import GoalEngine
from aura.engines.identity.engine import IdentityEngine
from aura.engines.learning.engine import LearningEngine
from aura.engines.reflection.engine import ReflectionEngine
from aura.llm.layers import LLMLayers
from aura.llm.unified_provider import UnifiedLLMClient
from aura.executor.tool_executor import ToolExecutor
from aura.orchestrator.coordinator import Orchestrator
from aura.orchestrator.message_bus import MessageBus

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Log model configuration at startup
logger.info("=" * 60)
logger.info("MODEL CONFIGURATION (from .env / environment variables):")
logger.info(f"  L1 Model: {settings.l1_model}")
logger.info(f"  L2 Model: {settings.l2_model}")
logger.info(f"  L3 Model: {settings.l3_model}")
logger.info(f"  L4 Model: {settings.l4_model}")
logger.info(f"  L5 Model: {settings.l5_model}")
logger.info("=" * 60)

# Global engine references
emotion_engine: EmotionEngine | None = None
learning_engine: LearningEngine | None = None
identity_engine: IdentityEngine | None = None
goal_engine: GoalEngine | None = None
reflection_engine: ReflectionEngine | None = None
dreaming_engine: DreamingEngine | None = None
message_bus: MessageBus | None = None
orchestrator: Orchestrator | None = None


async def _apply_surql_file(db, file_name: str, label: str):
    """Execute a .surql script file against the database.

    Comment-only lines are stripped before splitting on ``;`` so that
    commented-out semicolons don't break statement detection.

    Errors from individual statements are logged as warnings but *never*
    raised — this makes the function safe for idempotent re-runs where
    ``DEFINE TABLE`` may fail because the table already exists in
    file-backed storage mode.
    """
    from pathlib import Path

    script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / file_name
    )
    if not script_path.exists():
        logger.warning(f"{label} script not found at {script_path}")
        return

    raw = script_path.read_text(encoding="utf-8")
    # Strip line comments and block comments before splitting
    cleaned = "\n".join(
        line for line in raw.splitlines()
        if line.strip() and not line.strip().startswith("--")
    )
    # Remove block comments /* ... */
    import re as _re
    cleaned = _re.sub(r'/\*.*?\*/', '', cleaned, flags=_re.DOTALL)
    statements = [s.strip() for s in cleaned.split(";") if s.strip()]
    applied = 0
    for stmt in statements:
        try:
            await db.query(stmt)
            applied += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"{label} step failed (continuing): {exc}")
    logger.info(f"✓ {label} applied ({applied}/{len(statements)} stmts)")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager."""
    global emotion_engine, learning_engine, identity_engine, goal_engine, reflection_engine, dreaming_engine, message_bus, orchestrator

    logger.info("Starting Aura Backend v0.3.0 - PHASE 2+ (Higher Cognition)...")
    
    # Set up logging filters (silence health check spam)
    setup_logging_filters()

    # Initialize database connection with retry logic
    db = get_db_client()
    max_retries = 5
    retry_delay = 2  # seconds
    
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting database connection (attempt {attempt + 1}/{max_retries})...")
            await db.connect()
            logger.info("Database connection established")
            break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Database connection failed: {e}. Retrying in {retry_delay}s...")
                await asyncio.sleep(retry_delay)
            else:
                logger.error(f"Failed to connect to database after {max_retries} attempts")
                raise

    # --- Schema Bootstrap (runs on every boot — idempotent) ---
    #
    # Execution order is mandatory:
    #   1. init_schema.surql         – structural DEFINE-only baseline.
    #   2. seed_emotions.surql       – 27 emotions, default identity, main session.
    #   3. register_local_tools.surql – MCP / local-function skill registrations.
    #   4. seed_cultural_nodes.surql  – cultural knowledge-graph seed data.
    #   5. setup_tasks.surql          – default task scaffolding.
    #
    # In memory mode this creates everything from scratch on every boot.

    for surql_file, label in [
        ("init_schema.surql",          "Core schema (structural)"),
        ("seed_emotions.surql",         "Emotion + identity seeds"),
        ("register_local_tools.surql",  "Local tool registrations"),
        ("seed_cultural_nodes.surql",   "Cultural node seeds"),
        ("setup_tasks.surql",           "Task scaffolding"),
    ]:
        try:
            await _apply_surql_file(db, surql_file, label)
        except Exception as e:  # noqa: BLE001
            logger.error(f"[{label}] loader failed (non-fatal): {e}")

    # Initialize message bus
    message_bus = MessageBus()
    await message_bus.start()
    logger.info("Message bus started")

    # Initialize and start Emotion Engine
    emotion_engine = EmotionEngine()
    emotion_engine.set_message_bus(message_bus)
    await emotion_engine.start()
    logger.info("✓ Emotion Engine started")

    # Initialize and start Learning Engine
    learning_engine = LearningEngine()
    learning_engine.set_message_bus(message_bus)
    await learning_engine.start()
    logger.info("✓ Learning Engine started")

    # Initialize and start Identity Engine
    identity_engine = IdentityEngine()
    identity_engine.set_message_bus(message_bus)
    await identity_engine.start()
    logger.info("✓ Identity Engine started")

    # Initialize and start Goal Engine
    goal_engine = GoalEngine()
    goal_engine.set_message_bus(message_bus)
    await goal_engine.start()
    logger.info("✓ Goal Engine started")

    # Initialize and start Reflection Engine
    reflection_engine = ReflectionEngine()
    reflection_engine.set_message_bus(message_bus)
    await reflection_engine.start()
    logger.info("✓ Reflection Engine started")

    # Initialize and start Dreaming Engine
    dreaming_engine = DreamingEngine()
    dreaming_engine.set_message_bus(message_bus)
    await dreaming_engine.start()
    logger.info("✓ Dreaming Engine started")

    # Initialize LLM Layers and Orchestrator
    # Use UnifiedLLMClient if local LLM is enabled (routes to Ollama or OpenRouter per model)
    if settings.local_llm_enabled:
        unified_client = UnifiedLLMClient()
        llm_layers = LLMLayers(client=unified_client)
        local_ai_routes.set_unified_client(unified_client)
        logger.info("✓ Unified LLM Client (Local + Cloud) initialized")
    else:
        llm_layers = LLMLayers()
        # Still create a unified client for the API status endpoint
        unified_client = UnifiedLLMClient()
        local_ai_routes.set_unified_client(unified_client)
        logger.info("✓ Cloud-only LLM Client initialized (local LLM disabled)")
    
    # Set LLM layers for Learning Engine (for background analysis)
    learning_engine.set_llm_layers(llm_layers)
    
    # Set Identity Engine dependencies
    identity_engine.set_dependencies(llm_layers)
    
    # Set Reflection Engine dependencies
    reflection_engine.set_dependencies(llm_layers)
    
    # Set Dreaming Engine dependencies
    dreaming_engine.set_dependencies(
        llm_layers=llm_layers,
        learning_engine=learning_engine,
    )

    # Initialize and start Latent Engine (TITANS — Session 7)
    try:
        from aura.engines.latent.engine import get_latent_engine
        latent_engine = get_latent_engine()
        latent_engine.set_llm_layers(llm_layers)
        await latent_engine.initialize()
        logger.info("✓ Latent Engine (TITANS) started")
    except Exception as e:
        logger.warning(f"Latent Engine initialization failed (non-critical): {e}")

    # Set goal engine dependencies for LLM-based goal generation
    goal_engine.set_dependencies(
        llm_layers=llm_layers,
        emotion_engine=emotion_engine,
        learning_engine=learning_engine,
        identity_engine=identity_engine,
    )
    
    orchestrator = Orchestrator(
        emotion_engine=emotion_engine,
        learning_engine=learning_engine,
        identity_engine=identity_engine,
        goal_engine=goal_engine,
        reflection_engine=reflection_engine,
        message_bus=message_bus,
        llm_layers=llm_layers,
    )
    # Subscribe orchestrator to message bus
    message_bus.subscribe("orchestrator", orchestrator._handle_message)
    logger.info("✓ Orchestrator initialized")

    # Initialize SessionRuntime (V1PRD §4) — seeds MAIN session, hydrates persisted ones
    session_runtime = get_session_runtime()
    await session_runtime.initialise()
    logger.info("✓ SessionRuntime initialized (MAIN session ready)")

    # Initialize Task Queue and recover interrupted tasks (must be before agent loop)
    task_queue = get_task_queue()
    interrupted = await task_queue.recover_interrupted_tasks()
    if interrupted:
        logger.warning(f"Recovered {len(interrupted)} interrupted task(s) from previous run")
    task_routes.set_dependencies(task_queue)
    workspace_routes.set_task_queue(task_queue)
    logger.info("✓ Task Queue initialized")

    # Initialize Agent Loop dependencies (after task queue so it can persist)
    tool_executor = ToolExecutor()
    tool_executor.set_llm_layers(llm_layers)  # L5 self-healing for agent loop
    agent_routes.set_dependencies(llm_layers, tool_executor, task_queue, emotion_engine)
    logger.info("✓ Agent Loop executor initialized")

    # Start workspace filesystem watcher for live WebSocket updates
    workspace_routes.start_workspace_watcher()
    logger.info("✓ Workspace filesystem watcher started")

    # Set engine references in routes
    emotion_routes.set_emotion_engine(emotion_engine)
    learning_routes.set_learning_engine(learning_engine)
    school_routes.set_dependencies(learning_engine, llm_layers)
    goal_routes.set_goal_engine(goal_engine)
    chat_routes.set_orchestrator(orchestrator)
    system_state_routes.set_orchestrator(orchestrator)
    memory_routes.set_dreaming_engine(dreaming_engine)

    # --- Discord Bot Integration ---
    discord_routes.set_bot(discord_bot)
    discord_bot.set_orchestrator(orchestrator)

    if settings.discord_enabled and settings.discord_bot_token:
        logger.info("Starting Discord bot (AURA_DISCORD_ENABLED=true)...")
        try:
            success = await discord_bot.start()
            if success:
                logger.info(f"✓ Discord bot connected as {discord_bot.bot_user}")
            else:
                logger.warning("Discord bot failed to start – check AURA_DISCORD_BOT_TOKEN")
        except Exception as exc:
            logger.warning(f"Discord bot start failed (non-critical): {exc}")
    else:
        logger.info("Discord bot NOT started (AURA_DISCORD_ENABLED=false or no token set)")
        if settings.discord_enabled and not settings.discord_bot_token:
            logger.warning("  → AURA_DISCORD_ENABLED=true but AURA_DISCORD_BOT_TOKEN is empty!")

    logger.info("=" * 60)
    logger.info("🧠 AURA v0.3.0 - HIGHER COGNITION FULLY OPERATIONAL")
    logger.info("=" * 60)
    logger.info("Engines Active:")
    logger.info("  • Emotion (27D Physics + Translation)")
    logger.info("  • Learning (Experience Capture + Skill Trees)")
    logger.info("  • Identity (Narrative Self + Values)")
    logger.info("  • Goal (Autonomous Formation + Boredom Detection)")
    logger.info("  • Reflection (Nightly Analysis + Pattern Detection)")
    logger.info("  • Dreaming (Graph Consolidation + Memory Pruning)")
    logger.info("  • Orchestrator (Meta-Cognitive Coordination)")
    logger.info("=" * 60)

    yield

    # Shutdown
    logger.info("Shutting down Aura Backend...")

    # Stop Discord bot
    if discord_bot:
        try:
            await discord_bot.stop()
            logger.info("Discord bot stopped")
        except Exception as e:
            logger.warning(f"Failed to stop Discord bot cleanly: {e}")

    # Stop orchestrator state machine tasks
    if orchestrator:
        try:
            await orchestrator.stop_state_machine()
        except Exception as e:
            logger.warning(f"Failed to stop orchestrator state machine cleanly: {e}")

    # Close LLM client
    await llm_layers.close()

    # Stop engines (in reverse order)
    if dreaming_engine:
        await dreaming_engine.stop()
        logger.info("Dreaming Engine stopped")

    if reflection_engine:
        await reflection_engine.stop()
        logger.info("Reflection Engine stopped")

    if goal_engine:
        await goal_engine.stop()
        logger.info("Goal Engine stopped")

    if identity_engine:
        await identity_engine.stop()
        logger.info("Identity Engine stopped")

    if learning_engine:
        await learning_engine.stop()
        logger.info("Learning Engine stopped")

    if emotion_engine:
        await emotion_engine.stop()
        logger.info("Emotion Engine stopped")

    # Stop message bus
    if message_bus:
        await message_bus.stop()
        logger.info("Message bus stopped")

    # Close database
    await db.close()
    logger.info("Database connection closed")


# Create FastAPI app
app = FastAPI(
    title="Aura AGI Backend",
    description="Local AGI Companion with Emotional Intelligence",
    version="0.3.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Root endpoint
@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {
        "name": "Aura AGI Backend",
        "version": "0.3.0",
        "status": "operational",
        "documentation": "/docs",
    }


# Health check
@app.get("/health")
async def health_check() -> JSONResponse:
    """Health check endpoint."""
    db = get_db_client()
    db_healthy = db.is_connected

    status = "healthy" if db_healthy else "unhealthy"
    status_code = 200 if db_healthy else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": status,
            "database": "connected" if db_healthy else "disconnected",
            "version": "0.3.0",
        },
    )


# ---------------------------------------------------------------------------
# System management endpoints (Tauri orchestrator IPC)
# ---------------------------------------------------------------------------

system_router = APIRouter()


@system_router.post("/v1/system/shutdown", status_code=status.HTTP_200_OK)
async def system_shutdown():
    """
    HTTP IPC endpoint for the Tauri orchestrator.

    Sends SIGTERM to the current process.  Uvicorn intercepts this signal
    and begins a graceful worker shutdown: active requests are drained,
    database connection pools are closed, and file handles are flushed.
    """
    logger.info("Shutdown signal received from Tauri orchestrator — "
                 "initiating graceful teardown via SIGTERM")
    os.kill(os.getpid(), signal.SIGTERM)
    return {"status": "shutdown_initiated",
            "message": "Graceful teardown in progress."}


# Register route modules
app.include_router(system_router, tags=["system"])
app.include_router(emotion_routes.router, prefix="/emotion", tags=["emotion"])
app.include_router(learning_routes.router, prefix="/learning", tags=["learning"])
app.include_router(goal_routes.router, prefix="/goal", tags=["goal"])
app.include_router(chat_routes.router, prefix="/chat", tags=["chat"])
app.include_router(memory_routes.router, prefix="/memory", tags=["memory"])
app.include_router(system_state_routes.router, prefix="/system", tags=["system"])
app.include_router(conversations_routes.router, prefix="/api/conversations", tags=["conversations"])
app.include_router(voice_routes.router, tags=["voice"])
app.include_router(local_ai_routes.router, tags=["local-ai"])
app.include_router(agent_routes.router, tags=["agent"])
app.include_router(cultural_routes.router, tags=["cultural"])
app.include_router(task_routes.router, tags=["tasks"])
app.include_router(workspace_routes.router, tags=["workspace"])
app.include_router(session_routes.router, tags=["sessions"])
app.include_router(school_routes.router, prefix="/school", tags=["school"])
app.include_router(cognition_routes.router, tags=["cognition"])
app.include_router(inference_config_routes.router, prefix="/system", tags=["inference-config"])
app.include_router(l5_animation_routes.router, tags=["l5-animation"])
app.include_router(discord_routes.router, tags=["discord"])

# WebSocket endpoints
@app.websocket("/ws/emotion")
async def websocket_emotion_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time emotion streaming."""
    await emotion_stream_endpoint(websocket, emotion_engine)


@app.websocket("/v1/stream/emotions")
async def websocket_emotion_stream_v1(websocket: WebSocket) -> None:
    """
    V1 emotion streaming endpoint for VRM avatar animation.

    Continuously pushes the full 27D emotion vector at ~10 Hz for
    driving VRM blendshape animations in the frontend.

    Connect: ws://127.0.0.1:8080/v1/stream/emotions
    """
    import asyncio as _asyncio

    await websocket.accept()
    logger.info("VRM emotion stream connected (v1)")

    try:
        while True:
            try:
                if emotion_engine is None:
                    await websocket.send_json({"type": "error", "message": "Emotion engine not initialized"})
                    await _asyncio.sleep(1.0)
                    continue

                state = await emotion_engine.get_current_state()
                vector = state.vector.model_dump()

                # Auxiliary metrics for the translation matrix
                pos = sum(vector.get(e, 0) for e in ["joy", "love", "trust", "interest", "serenity", "gratitude", "beauty", "compassion"]) / 8
                neg = sum(vector.get(e, 0) for e in ["fear", "sadness", "anger", "disgust", "shame", "envy", "boredom", "melancholy"]) / 8
                valence = pos - neg
                arousal = (vector.get("surprise", 0) + vector.get("fear", 0) + vector.get("anger", 0) + vector.get("joy", 0)) / 4

                await websocket.send_json({
                    "type": "emotion_vector",
                    "timestamp": state.timestamp.isoformat(),
                    "vector": vector,
                    "dominant": state.dominant[0],
                    "dominant_intensity": state.dominant[1],
                    "valence": round(valence, 4),
                    "arousal": round(arousal, 4),
                    "volatility": state.volatility,
                    "description": state.description,
                })

                await _asyncio.sleep(0.1)

            except _asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"VRM emotion stream error: {e}")
                await _asyncio.sleep(1.0)

    except _asyncio.CancelledError:
        raise
    except Exception:
        pass
    finally:
        logger.info("VRM emotion stream disconnected (v1)")


@app.websocket("/v1/stream/traces")
async def websocket_trace_stream(websocket: WebSocket) -> None:
    """
    Cognitive trace streaming endpoint for the Telemetry Widget.

    Pushes lightweight L1/L2/L3 trace events emitted by the Orchestrator
    to any connected frontend client.  The connection is kept alive by the
    server; the client only needs to listen.

    Connect: ws://127.0.0.1:8080/v1/stream/traces
    Event schema:
      { "layer": "L1"|"L2"|"L3",
        "event": "<label>",
        "ts": "<ISO-8601>",
        ... extra key/value pairs ... }
    """
    import asyncio as _asyncio
    manager = get_trace_manager()
    await manager.connect(websocket)
    try:
        # Keep-alive: drain any pings from the client but never block the loop
        while True:
            try:
                await _asyncio.wait_for(websocket.receive_text(), timeout=30.0)
            except _asyncio.TimeoutError:
                # Send a heartbeat ping so the client knows the pipe is live
                try:
                    await websocket.send_json({"type": "ping"})
                except Exception:
                    break
            except Exception:
                break
    finally:
        await manager.disconnect(websocket)
        logger.info("Trace stream client disconnected")


# ---------------------------------------------------------------------------
# Context Mode management endpoint
# ---------------------------------------------------------------------------
from pydantic import BaseModel, Field


class ContextModeRequest(BaseModel):
    context_mode: str = Field(
        default="deep_work",
        pattern="^(deep_work|private_rp)$",
        description="Inference routing mode",
    )


@app.post("/v1/context-mode")
async def set_context_mode(request: ContextModeRequest) -> dict[str, str]:
    """
    Set the active context mode for inference routing.

    - ``deep_work``: All LLM requests route through OpenRouter (cloud).
    - ``private_rp``: All LLM requests route to the local inference endpoint.

    This affects all subsequent L1/L2/L3 generation calls until changed.
    """
    global orchestrator
    if orchestrator is None:
        return {"status": "error", "message": "Orchestrator not initialized"}
    orchestrator.llm_layers.context_mode = request.context_mode  # type: ignore[assignment]
    logger.info(f"Context mode set to: {request.context_mode}")
    return {"status": "ok", "context_mode": request.context_mode}


@app.get("/v1/context-mode")
async def get_context_mode() -> dict[str, str]:
    """Get the active context mode."""
    global orchestrator
    if orchestrator is None:
        return {"status": "error", "message": "Orchestrator not initialized"}
    mode = orchestrator.llm_layers.context_mode
    return {"status": "ok", "context_mode": mode}


logger.info("Aura Backend routes registered")

