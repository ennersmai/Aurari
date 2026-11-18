"""Chat API with full orchestration."""

from typing import Any
from datetime import datetime
import json

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from aura.db.client import get_db_client

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
    enable_l2: bool | None = Field(default=None, description="Enable L2 post-analysis (deprecated, use deep_analysis_enabled)")
    reasoning_enabled: bool = Field(default=False, description="Enable deep reasoning for L3 (Grok/DeepSeek R1)")
    l2_reasoning_enabled: bool = Field(default=False, description="Enable deep reasoning for L2 analysis (Grok/DeepSeek R1)")
    deep_analysis_enabled: bool = Field(default=True, description="Enable L2 background analysis (async)")


class ChatResponse(BaseModel):
    """Response model for chat endpoint."""

    success: bool
    response: str
    emotional_state: dict[str, Any] = Field(default_factory=dict)
    learning_applied: bool = False


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
        
        # Use deep_analysis_enabled (defaults to True), but allow enable_l2 to override for backward compatibility
        deep_analysis = request.enable_l2 if request.enable_l2 is not None else request.deep_analysis_enabled
        
        response = await orchestrator.process_query(
            user_input=request.message,
            user_id=request.user_id,  # Commander identity from frontend settings
            conversation_history=history,
            context_limit=request.context_limit,
            enable_l2_analysis=request.enable_l2,  # Keep for backward compatibility
            conversation_id=request.conversation_id,
            reasoning_enabled=request.reasoning_enabled,
            l2_reasoning_enabled=request.l2_reasoning_enabled,
            deep_analysis_enabled=deep_analysis,
            session_id=request.session_id,
            context_mode=request.context_mode,
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

    async def generate():
        full_response = ""
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

            # Use deep_analysis_enabled (defaults to True), but allow enable_l2 to override for backward compatibility
            deep_analysis = request.enable_l2 if request.enable_l2 is not None else request.deep_analysis_enabled

            async for chunk in orchestrator.stream_query(
                user_input=request.message,
                user_id=request.user_id,
                conversation_history=history,
                conversation_id=request.conversation_id,  # Pass conversation_id to orchestrator
                reasoning_enabled=request.reasoning_enabled,
                l2_reasoning_enabled=request.l2_reasoning_enabled,
                deep_analysis_enabled=deep_analysis,
                session_id=request.session_id,
                context_mode=request.context_mode,
            ):
                full_response += chunk
                # JSON-encode the chunk to handle newlines/special chars safely
                yield f"data: {json.dumps(chunk)}\n\n"

            # PERSISTENCE: Save to database right after stream completes, before [DONE]
            await _persist_streamed_response(orchestrator, request, full_response)

            yield "data: [DONE]\n\n"

        except Exception as e:
            # JSON-encode error
            error_msg = json.dumps(f"Error: {str(e)}")
            yield f"data: {error_msg}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )


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
