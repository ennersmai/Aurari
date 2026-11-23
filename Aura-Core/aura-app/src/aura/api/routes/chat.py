"""Chat API with full orchestration."""

from typing import Any, Literal
from datetime import datetime
import json

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from aura.db.client import get_db_client
from aura.tiers import DEPRECATED_REASONING_FIELDS, note_deprecated_reasoning_controls

router = APIRouter()

# Global orchestrator reference (will be set by main.py)
_orchestrator: Any = None


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


class ChatMessage(BaseModel):
    """Chat message model."""

    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatRequest(BaseModel):
    """Request model for chat endpoint."""

    message: str = Field(..., description="User message")
    user_id: str = Field(default="default")
    conversation_history: list[ChatMessage] = Field(default_factory=list)
    stream: bool = Field(default=False, description="Stream response")
    
    # Optional context for persistence
    conversation_id: str | None = Field(default=None, description="Conversation ID to save to")
    session_id: str = Field(default="main", description="Session this chat runs under (V1PRD §4)")

    # Context mode routing (Sovereign Orchestrator)
    # "deep_work" → cloud (OpenRouter)  |  "private_rp" → local inference endpoint
    context_mode: str = Field(
        default="deep_work",
        description="Inference routing mode: 'deep_work' (cloud) or 'private_rp' (local)",
        pattern="^(deep_work|private_rp)$",
    )

    # Advanced options (from frontend settings)
    context_limit: int | None = Field(default=None, ge=5, le=999, description="Max conversation history")
    # P2-42: deprecated and IGNORED. Still accepted so old clients do not get a 422.
    # How much Aura thinks comes from the tier slider and the L1 route only.
    enable_l2: bool | None = Field(default=None, description="Deprecated, ignored (P2-42)")
    enable_l2_analysis: bool | None = Field(default=None, description="Deprecated, ignored (P2-42)")
    reasoning_enabled: bool | None = Field(default=None, description="Deprecated, ignored (P2-42)")
    l2_reasoning_enabled: bool | None = Field(default=None, description="Deprecated, ignored (P2-42)")
    deep_analysis_enabled: bool | None = Field(default=None, description="Deprecated, ignored (P2-42)")

    def note_deprecated_fields(self) -> None:
        """Log one deprecation line per process if an old client sent any of them."""
        note_deprecated_reasoning_controls(
            [n for n in DEPRECATED_REASONING_FIELDS if getattr(self, n) is not None]
        )


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    success: bool
    response: str
    emotional_state: dict[str, Any] = Field(default_factory=dict)
    learning_applied: bool = False
    # P2-42: whether this turn used deep (L3) reasoning, the active tier, the L1 route.
    deep_reasoning: bool = False
    tier: str = "lean"
    route: str | None = None


@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatRequest) -> ChatResponse:
    """
    Send message to Aura with full cognitive orchestration.

    This endpoint coordinates:
    - Emotion Engine (emotional state coloring)
    - Learning Engine (retrieved rules and patterns)
    - LLM Layers (L3 synthesis with context)

    Returns emotionally-aware, learned response.
    """
    orchestrator = get_orchestrator()
    request.note_deprecated_fields()
    turn_meta: dict[str, Any] = {}

    try:
        # Convert conversation history to dict format
        history = [
            {"role": msg.role, "content": msg.content}
            for msg in request.conversation_history
        ]

        # Process through orchestrator with optional settings
        # user_id should be the commander identity from frontend (e.g., "Mai")
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[CHAT] Processing message - conversation_id: {request.conversation_id}, user_id: {request.user_id}")
        
        response = await orchestrator.process_query(
            user_input=request.message,
            user_id=request.user_id,  # Commander identity from frontend settings
            conversation_history=history,
            context_limit=request.context_limit,
            conversation_id=request.conversation_id,
            session_id=request.session_id,
            context_mode=request.context_mode,
            turn_meta=turn_meta,
        )

        # Get current emotional state for response
        emotional_state = await orchestrator.emotion_engine.get_current_state()

        # Save to database if conversation_id is provided
        if request.conversation_id:
            db = get_db_client()
            now = datetime.utcnow().isoformat()
            
            # 1. Save User Message
            user_msg_id = f"message:{int(datetime.utcnow().timestamp() * 1000)}"
            await db.create(
                user_msg_id,
                {
                    "conversation_id": request.conversation_id,
                    "content": request.message,
                    "role": "user",
                    "timestamp": now,
                },
            )
            
            # 2. Save Aura Response
            aura_msg_id = f"message:{int(datetime.utcnow().timestamp() * 1000) + 1}"
            await db.create(
                aura_msg_id,
                {
                    "conversation_id": request.conversation_id,
                    "content": response,
                    "role": "assistant",
                    "timestamp": now,
                },
            )
            
            # 3. Get current conversation to check message count
            conv_result = await db.select(request.conversation_id)
            current_count = 0
            current_summary = ""
            
            if conv_result and len(conv_result) > 0:
                current_count = conv_result[0].get("message_count", 0)
                current_summary = conv_result[0].get("summary", "")
            
            # 4. Update Conversation (count + timestamp + emotion)
            update_data = {
                "message_count": current_count + 2,
                "updated_at": now,
                "final_emotion": {
                    "dominant": emotional_state.dominant[0],
                    "description": emotional_state.description
                }
            }
            
            # 5. Generate summary if this is the first exchange (and no summary exists)
            if current_count == 0 and not current_summary:
                # Use first 60 chars of user message as placeholder summary
                summary = request.message[:60]
                if len(request.message) > 60:
                    summary += "..."
                update_data["summary"] = summary
            
            # Update conversation metadata
            await db.merge(
                request.conversation_id,
                {
                    "message_count": update_data["message_count"],
                    "updated_at": now,
                    "final_emotion": update_data["final_emotion"],
                    "summary": update_data.get("summary", current_summary),
                    "last_message": response
                }
            )

        return ChatResponse(
            success=True,
            response=response,
            emotional_state={
                "dominant": emotional_state.dominant[0],
                "intensity": emotional_state.dominant[1],
                "description": emotional_state.description,
            },
            learning_applied=True,
            deep_reasoning=bool(turn_meta.get("deep_reasoning", False)),
            tier=str(turn_meta.get("tier", "lean")),
            route=turn_meta.get("route"),
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process message: {str(e)}",
        )


async def _persist_streamed_response(orchestrator: Any, request: ChatRequest, full_response: str) -> None:
    """Persist streamed response to the database (called synchronously after stream completes)."""
    if not request.conversation_id or not full_response:
        if not request.conversation_id:
            print("[PERSISTENCE] No conversation_id provided, skipping persistence")
        elif not full_response:
            print("[PERSISTENCE] Empty response, skipping persistence")
        return

    try:
        print(f"[PERSISTENCE] Attempting to save conversation {request.conversation_id}")
        print(f"[PERSISTENCE] Full response length: {len(full_response)} chars")

        db = get_db_client()
        now = datetime.utcnow().isoformat()

        # Get current emotional state for persistence
        emotional_state = await orchestrator.emotion_engine.get_current_state()

        # 1. Save User Message
        user_msg_id = f"message:{int(datetime.utcnow().timestamp() * 1000)}"
        await db.create(
            user_msg_id,
            {
                "conversation_id": request.conversation_id,
                "content": request.message,
                "role": "user",
                "timestamp": now,
            },
        )
        print(f"[PERSISTENCE] User message saved: {user_msg_id}")

        # 2. Save Aura Response
        aura_msg_id = f"message:{int(datetime.utcnow().timestamp() * 1000) + 1}"
        await db.create(
            aura_msg_id,
            {
                "conversation_id": request.conversation_id,
                "content": full_response,
                "role": "assistant",
                "timestamp": now,
            },
        )
        print(f"[PERSISTENCE] Aura message saved: {aura_msg_id}")

        # 3. Get current conversation to check message count
        conv_result = await db.select(request.conversation_id)
        current_count = 0
        current_summary = ""

        if conv_result and len(conv_result) > 0:
            current_count = conv_result[0].get("message_count", 0)
            current_summary = conv_result[0].get("summary", "")

        # 4. Update Conversation (count + timestamp + emotion)
        update_data = {
            "message_count": current_count + 2,
            "updated_at": now,
            "final_emotion": {
                "dominant": emotional_state.dominant[0],
                "description": emotional_state.description
            }
        }

        # 5. Generate summary if this is the first exchange (and no summary exists)
        if current_count == 0 and not current_summary:
            # Use first 60 chars of user message as placeholder summary
            summary = request.message[:60]
            if len(request.message) > 60:
                summary += "..."
            update_data["summary"] = summary

        # 6. Update in database using merge
        await db.merge(
            request.conversation_id,
            {
                "message_count": update_data["message_count"],
                "updated_at": now,
                "final_emotion": update_data["final_emotion"],
                "summary": update_data.get("summary", current_summary)
            }
        )
        print(f"[PERSISTENCE] Successfully persisted conversation {request.conversation_id}")
    except Exception as db_e:
        print(f"[PERSISTENCE] Failed to save streamed conversation: {db_e}")
        import traceback
        traceback.print_exc()


@router.post("/stream")
async def stream_message(request: ChatRequest) -> StreamingResponse:
    """
    Stream message response in real-time.

    Returns Server-Sent Events stream of text chunks.
    
    Persistence happens synchronously inside generate() after the stream completes
    but before [DONE] is yielded — eliminating the race condition from background tasks.
    """
    orchestrator = get_orchestrator()
    request.note_deprecated_fields()

    async def generate():
        full_response = ""
        turn_meta: dict[str, Any] = {}
        try:
            # Convert conversation history
            history = [
                {"role": msg.role, "content": msg.content}
                for msg in request.conversation_history
            ]

            # Stream through orchestrator
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[CHAT STREAM] Processing stream - conversation_id: {request.conversation_id}, user_id: {request.user_id}")

            async for chunk in orchestrator.stream_query(
                user_input=request.message,
                user_id=request.user_id,
                conversation_history=history,
                conversation_id=request.conversation_id,  # Pass conversation_id to orchestrator
                session_id=request.session_id,
                context_mode=request.context_mode,
                turn_meta=turn_meta,
            ):
                full_response += chunk
                # JSON-encode the chunk to handle newlines/special chars safely
                yield f"data: {json.dumps(chunk)}\n\n"

            # PERSISTENCE: Save to database right after stream completes, before [DONE]
            await _persist_streamed_response(orchestrator, request, full_response)

            # P2-42: turn metadata as a JSON object (chunks are JSON strings).
            yield f"data: {json.dumps({'type': 'turn_meta', **turn_meta})}\n\n"

            yield "data: [DONE]\n\n"

        except Exception as e:
            # JSON-encode error
            error_msg = json.dumps(f"Error: {str(e)}")
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


class OutcomeRequest(BaseModel):
    """Owner thumbs on one reply (B1-03). One of experience_id / message_id."""

    experience_id: str | None = None
    message_id: str | None = None
    signal: Literal["up", "down"]
    # No route has a role check (the app API is unauthenticated, the owner's own UI), so
    # the caller states its role; anything but "owner" is refused.
    requester_role: str = "owner"


async def _experience_for_message(db: Any, message_id: str) -> str | None:
    """The experience of an assistant message: ``meta.experience_id`` when stored, else the
    newest experience whose logged response equals the message text. (The experience is
    logged in a background task after the reply, so the message cannot carry the id.)"""
    rows = await db.select(message_id)
    msg = rows[0] if rows else None
    if not isinstance(msg, dict) or msg.get("role") != "assistant":
        return None
    meta = msg.get("meta")
    if isinstance(meta, dict) and meta.get("experience_id"):
        return str(meta["experience_id"])
    found = await db.query(
        "SELECT experience_id FROM experience WHERE aura_response.response = $text "
        "ORDER BY timestamp DESC LIMIT 1",
        {"text": msg.get("content", "")},
    )
    for row in found:
        if isinstance(row, dict) and row.get("experience_id"):
            return str(row["experience_id"])
    return None


@router.post("/outcome")
async def post_outcome(request: OutcomeRequest) -> dict[str, Any]:
    """Record an explicit up/down on a reply; beats any implicit outcome (B1-03)."""
    from aura.config import settings

    if not settings.outcome_signals_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if request.requester_role != "owner":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner only")
    if bool(request.experience_id) == bool(request.message_id):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Give exactly one of experience_id or message_id",
        )
    orchestrator = get_orchestrator()
    experience_id = request.experience_id
    if not experience_id:
        experience_id = await _experience_for_message(get_db_client(), request.message_id or "")
        if not experience_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No experience for that message"
            )

    from aura.engines.learning.outcomes import apply_explicit_outcome

    on_outcome = None
    if settings.skills_v2_enabled and settings.skill_attribution_enabled:

        async def on_outcome(eid: str, signal: str) -> None:
            from aura.engines.learning.skill_stats import apply_outcome_for_turn
            from aura.engines.learning.skill_store import SkillStore

            await apply_outcome_for_turn(SkillStore(orchestrator.db), eid, signal)

    stored = await apply_explicit_outcome(
        orchestrator.learning_engine, experience_id, request.signal, on_outcome
    )
    return {"experience_id": experience_id, "signal": stored, "source": "explicit"}


@router.get("/task-reports")
async def get_task_reports(conversation_id: str, since: str | None = None) -> dict[str, Any]:
    """Task graph report messages of a conversation, oldest first (P2-11).

    There is no server push channel to the chat, so the page polls this while
    ``running`` is true. ``since`` is an exclusive ISO timestamp.
    """
    db = get_db_client()
    sql = "SELECT * FROM message WHERE conversation_id = $conv AND meta.task_graph != NONE"
    params: dict[str, Any] = {"conv": conversation_id}
    if since:
        sql += " AND timestamp > $since"
        params["since"] = since
    sql += " ORDER BY timestamp ASC"
    rows = await db.query(sql, params)
    messages = [
        {
            "id": str(m.get("id", "")),
            "conversationId": conversation_id,
            "content": m.get("content", ""),
            "role": m.get("role", "assistant"),
            "timestamp": m.get("timestamp", ""),
            "meta": m.get("meta"),
        }
        for m in rows if isinstance(m, dict)
    ]
    graphs = await db.query(
        "SELECT id FROM task_graph WHERE conversation_id = $conv AND status IN $live",
        {"conv": conversation_id, "live": ["planned", "running"]},
    )
    running = any(isinstance(g, dict) for g in graphs)
    return {"messages": messages, "running": running}


@router.get("/debug/last_context/{user_id}")
async def get_last_system_context(user_id: str) -> dict[str, Any]:
    """
    Retrieves the raw System Prompt injected into L3/Grok for the last turn.
    
    This is a powerful debugging tool that shows the complete context block
    (<emotional_state>, <capabilities>, <active_goals>) that was sent to the LLM.
    
    Args:
        user_id: User identifier to retrieve context for
        
    Returns:
        Dictionary containing the last system prompt for this user
    """
    orchestrator = get_orchestrator()
    
    try:
        # Get the cached system prompt for this user
        prompt = orchestrator._last_system_prompt.get(user_id, None)
        
        if prompt is None:
            return {
                "success": True,
                "user_id": user_id,
                "context": "No context recorded for this user yet. Send a message first.",
                "has_context": False
            }
        
        return {
            "success": True,
            "user_id": user_id,
            "context": prompt,
            "has_context": True
        }
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to retrieve last system context: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not retrieve system context: {str(e)}"
        )
