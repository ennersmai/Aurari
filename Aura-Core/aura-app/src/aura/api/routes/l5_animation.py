"""
L5 Animation Selector API

Provides dedicated endpoints for L5-based animation selection and
movement command detection.

The L5 model (google/gemini-flash-latest) receives the 27D emotion vector
and recent conversation context, then selects the most appropriate VRMA
animation from the available set.

This implements the fast L1→L5 route: L1 classifies intent, then L5
selects animation before L3 streams the text response.

NEW: Movement command detection — /detect-movement scans user text for
explicit movement keywords and broadcasts an animation_command event over
WebSocket for instant avatar response.
"""

import json
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from aura.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/l5", tags=["l5-animation"])

# ---- Available animations (must match frontend VRMA files) ----

AVAILABLE_ANIMATIONS = [
    # Original animations
    {"file": "/vrm-assets/dance.vrma", "description": "Happy dance, energetic bouncing"},
    {"file": "/vrm-assets/greeting.vrma", "description": "Wave hello, warm greeting"},
    {"file": "/vrm-assets/idle_loop.vrma", "description": "Idle standing, subtle swaying"},
    {"file": "/vrm-assets/modelPose.vrma", "description": "Lean in, model pose, attentive"},
    {"file": "/vrm-assets/peaceSign.vrma", "description": "Peace sign, relaxed gesture"},
    {"file": "/vrm-assets/shoot.vrma", "description": "Shooting gesture, aggressive"},
    {"file": "/vrm-assets/showFullBody.vrma", "description": "Defensive stance, full body"},
    {"file": "/vrm-assets/spin.vrma", "description": "Spin around, excited twirl"},
    {"file": "/vrm-assets/squat.vrma", "description": "Squat down, dejected posture"},
    # Generated variants — dance
    {"file": "/vrm-assets/dance_fast.vrma", "description": "Fast energetic dance, high excitement"},
    {"file": "/vrm-assets/dance_slow.vrma", "description": "Slow graceful dance, calm joy"},
    {"file": "/vrm-assets/dance_subtle.vrma", "description": "Subtle sway dance, mild happiness"},
    # Generated variants — greeting
    {"file": "/vrm-assets/greeting_enthusiastic.vrma", "description": "Enthusiastic wave, big greeting"},
    {"file": "/vrm-assets/greeting_shy.vrma", "description": "Shy timid wave, hesitant greeting"},
    {"file": "/vrm-assets/greeting_left.vrma", "description": "Left-handed wave, quirky greeting"},
    # Generated variants — idle
    {"file": "/vrm-assets/idle_energetic.vrma", "description": "Energetic idle bounce, restless"},
    {"file": "/vrm-assets/idle_relaxed.vrma", "description": "Relaxed slow idle, calm presence"},
    {"file": "/vrm-assets/idle_curious.vrma", "description": "Curious leaning idle, attentive"},
    # Generated variants — peace sign
    {"file": "/vrm-assets/peaceSign_double.vrma", "description": "Double peace sign, extra friendly"},
    {"file": "/vrm-assets/peaceSign_slow.vrma", "description": "Slow graceful peace, serene gesture"},
    # Generated variants — spin
    {"file": "/vrm-assets/spin_fast.vrma", "description": "Rapid excited spin, overwhelming joy"},
    {"file": "/vrm-assets/spin_slow.vrma", "description": "Slow dreamy spin, peaceful twirl"},
    # Generated variants — model pose
    {"file": "/vrm-assets/modelPose_confident.vrma", "description": "Confident model pose, proud stance"},
    {"file": "/vrm-assets/modelPose_shy.vrma", "description": "Shy pose, hesitant but curious"},
    # Generated variants — squat
    {"file": "/vrm-assets/squat_deep.vrma", "description": "Deep dejected squat, very sad"},
    {"file": "/vrm-assets/squat_quick.vrma", "description": "Quick crouch, startled reaction"},
    # Generated variants — shoot
    {"file": "/vrm-assets/shoot_double.vrma", "description": "Double shoot, intense anger"},
    # Generated variants — show full body
    {"file": "/vrm-assets/showFullBody_confident.vrma", "description": "Confident full body display, proud"},
    # New animations from GitHub pack (VRMA format)
    {"file": "/vrm-assets/greeting2.vrma", "description": "Alternative greeting, friendly wave variant"},
    {"file": "/vrm-assets/hello.vrma", "description": "Hello gesture, warm welcome"},
    {"file": "/vrm-assets/motion_pose.vrma", "description": "Motion pose, dynamic stance"},
    {"file": "/vrm-assets/peace sign.vrma", "description": "Peace sign gesture (variant)"},
    {"file": "/vrm-assets/show full body.vrma", "description": "Show full body gesture (variant)"},
]

# ---- Valid animation files set (for validation) ----
VALID_ANIMATION_FILES = {a["file"] for a in AVAILABLE_ANIMATIONS}

# ---- Movement keyword → animation mapping (must mirror frontend MOVEMENT_KEYWORD_MAP) ----

MOVEMENT_KEYWORDS: dict[str, str] = {
    # Sorted by length descending (longer phrases match first)
    "wave hello": "/vrm-assets/greeting_enthusiastic.vrma",
    "wave at me": "/vrm-assets/greeting_enthusiastic.vrma",
    "dance for me": "/vrm-assets/dance.vrma",
    "do a dance": "/vrm-assets/dance.vrma",
    "dance fast": "/vrm-assets/dance_fast.vrma",
    "dance slow": "/vrm-assets/dance_slow.vrma",
    "spin around": "/vrm-assets/spin.vrma",
    "spin fast": "/vrm-assets/spin_fast.vrma",
    "peace sign": "/vrm-assets/peaceSign.vrma",
    "peace out": "/vrm-assets/peaceSign_double.vrma",
    "turn around": "/vrm-assets/spin.vrma",
    "model pose": "/vrm-assets/modelPose_confident.vrma",
    "strike a pose": "/vrm-assets/modelPose_confident.vrma",
    "show yourself": "/vrm-assets/showFullBody.vrma",
    "show me you": "/vrm-assets/showFullBody.vrma",
    "full body": "/vrm-assets/showFullBody_confident.vrma",
    "stand still": "/vrm-assets/idle_loop.vrma",
    "be idle": "/vrm-assets/idle_loop.vrma",
    "sit down": "/vrm-assets/squat_deep.vrma",
    "say hello": "/vrm-assets/greeting.vrma",
    "v sign": "/vrm-assets/peaceSign.vrma",
    "say hi": "/vrm-assets/greeting.vrma",
    "curtsy": "/vrm-assets/greeting_shy.vrma",
    "crouch": "/vrm-assets/squat_quick.vrma",
    "twirl": "/vrm-assets/spin_slow.vrma",
    "greet": "/vrm-assets/greeting.vrma",
    "dance": "/vrm-assets/dance.vrma",
    "wave": "/vrm-assets/greeting.vrma",
    "spin":  "/vrm-assets/spin.vrma",
    "peace": "/vrm-assets/peaceSign.vrma",
    "sway": "/vrm-assets/dance_subtle.vrma",
    "twirl": "/vrm-assets/spin_slow.vrma",
    "pose": "/vrm-assets/modelPose.vrma",
    "model": "/vrm-assets/modelPose_confident.vrma",
    "relax": "/vrm-assets/idle_relaxed.vrma",
    "squat": "/vrm-assets/squat.vrma",
    "bow": "/vrm-assets/greeting_shy.vrma",
    # New keywords from GitHub pack
    "hello": "/vrm-assets/hello.vrma",
    "motion pose": "/vrm-assets/motion_pose.vrma",
}


# ---- Singleton LLMLayers instance to avoid re-creating on every request ----
_llm_layers_instance: Any = None


def _get_llm_layers() -> Any:
    """Get or create a singleton LLMLayers instance."""
    global _llm_layers_instance
    if _llm_layers_instance is None:
        from aura.llm.layers import LLMLayers
        _llm_layers_instance = LLMLayers()
    return _llm_layers_instance


def detect_movement_keyword(text: str) -> str | None:
    """
    Detect movement keywords in text and return the matching animation file.

    Matches are case-insensitive. Longer phrases take priority over shorter ones
    (keywords are checked in length-descending order).

    Returns the animation file path, or None if no keyword matched.
    """
    lower = text.lower()
    # Sort keywords by length descending so multi-word phrases win
    sorted_keywords = sorted(MOVEMENT_KEYWORDS.keys(), key=len, reverse=True)
    for keyword in sorted_keywords:
        if keyword in lower:
            return MOVEMENT_KEYWORDS[keyword]
    return None


# ---- Request / Response models ------------------------------------------


class L5AnimationRequest(BaseModel):
    """Request for L5 animation selection."""

    emotion: dict[str, Any] = Field(
        default_factory=dict,
        description="27D emotion vector with values 0..1",
    )
    context: list[str] = Field(
        default_factory=list,
        description="Recent conversation messages for context",
        max_length=10,
    )
    upcoming_text: str | None = Field(
        default=None,
        description="Text about to be spoken / user's message (for semantic alignment)",
        max_length=500,
    )
    previous_animation: str | None = Field(
        default=None,
        description="Animation played in previous turn (for avoiding repetition)",
        max_length=200,
    )


class L5AnimationResponse(BaseModel):
    """Response from L5 animation selector."""

    animation: str = Field(description="Selected animation file path")
    confidence: float = Field(description="Confidence [0, 1]", ge=0, le=1)
    reasoning: str = Field(description="Human-readable reasoning")


class MovementCommandRequest(BaseModel):
    """Request for movement command detection."""

    text: str = Field(description="User message text to scan for movement keywords", max_length=2000)
    broadcast: bool = Field(
        default=True,
        description="If True, broadcast animation_command event over WebSocket",
    )


class MovementCommandResponse(BaseModel):
    """Response from movement command detection."""

    detected: bool = Field(description="Whether a movement keyword was found")
    animation: str | None = Field(default=None, description="Matched animation file path")
    keyword: str | None = Field(default=None, description="The matched keyword")
    broadcast_sent: bool = Field(default=False, description="Whether a WebSocket broadcast was sent")


# ---- Prompt builder -----------------------------------------------------


def _build_animation_prompt(
    emotion: dict[str, Any],
    context: list[str],
    upcoming_text: str | None,
    previous_animation: str | None = None,
) -> str:
    """Build the prompt for L5 animation selection."""

    # Extract dominant emotions
    sorted_emotions = sorted(
        [(k, v) for k, v in emotion.items()
         if isinstance(v, (int, float)) and k not in (
             "valence", "arousal", "entropy", "current_state",
             "dominant", "timestamp", "description",
         )],
        key=lambda x: x[1],
        reverse=True,
    )[:5]
    emotion_str = ", ".join(f"{name}={val:.2f}" for name, val in sorted_emotions)

    meta = {
        "dominant": emotion.get("dominant", "neutral"),
        "valence": emotion.get("valence", 0),
        "arousal": emotion.get("arousal", 0.5),
    }

    anim_list = "\n".join(
        f"- {a['file']}: {a['description']}" for a in AVAILABLE_ANIMATIONS
    )

    context_str = "\n".join(context[-6:]) if context else "(no recent context)"

    # Add previous animation context
    prev_anim_context = ""
    if previous_animation:
        prev_anim_context = f"\nPREVIOUS ANIMATION: {previous_animation}\nNOTE: Avoid repeating the same animation unless contextually appropriate."

    prompt = f"""You are Aura's animation selector (L5). Choose the best animation for the avatar.

EMOTIONAL STATE:
- Dominant: {meta['dominant']}
- Valence: {meta['valence']:.2f} (negative=sad/angry, positive=happy)
- Arousal: {meta['arousal']:.2f} (low=calm, high=energetic)
- Top emotions: {emotion_str}

RECENT CONVERSATION:
{context_str}

UPCOMING TEXT / USER MESSAGE:
{upcoming_text or "(no text yet)"}
{prev_anim_context}

AVAILABLE ANIMATIONS:
{anim_list}

TASK: Select the SINGLE most appropriate animation.
Consider:
1. Emotional state (match energy/valence to animation)
2. Conversation context (what's being discussed)
3. Upcoming text / user message (what Aura is about to respond to)
   - If the user is asking Aura to dance, wave, spin, etc., select that animation directly.
   - If the user is asking a deep question, select a thoughtful pose.
   - If the user is greeting, select a greeting animation.
4. Previous animation (avoid repetition unless contextually appropriate)
5. Semantic appropriateness (match action to conversation flow)

OUTPUT FORMAT (JSON ONLY):
{{
  "animation": "/vrm-assets/dance.vrma",
  "confidence": 0.85,
  "reasoning": "High joy (0.72) and arousal (0.68) match the energetic dance. The upcoming text is excited."
}}

IMPORTANT: Return ONLY valid JSON. No markdown, no code blocks, no explanations outside the JSON."""
    return prompt


# ---- Routes -------------------------------------------------------------


@router.post("/select-animation", response_model=L5AnimationResponse)
async def select_animation(request: L5AnimationRequest) -> L5AnimationResponse:
    """
    L5 Animation Selector — Fast route for semantically-aware animation selection.

    Priority 1: If upcoming_text contains a movement keyword, return that animation
    directly without calling the LLM (sub-1ms response, highest confidence).

    Priority 2: Call the L5 model to semantically select based on emotion +
    conversation context + upcoming text.

    Priority 3: Fallback based on arousal/valence heuristics.
    """
    # ---- Priority 1: Movement keyword fast path (no LLM needed) ----
    if request.upcoming_text:
        keyword_anim = detect_movement_keyword(request.upcoming_text)
        if keyword_anim:
            logger.info(f"L5 fast path: movement keyword detected → {keyword_anim}")
            return L5AnimationResponse(
                animation=keyword_anim,
                confidence=0.98,
                reasoning=f"Direct movement command detected in user message: '{request.upcoming_text[:60]}'",
            )

    prompt = _build_animation_prompt(
        request.emotion,
        request.context,
        request.upcoming_text,
        request.previous_animation,
    )

    try:
        layers = _get_llm_layers()
        l5_model = settings.active_l5_model

        logger.info(f"L5 Animation Selector using model: {l5_model}")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an animation selector for a 3D avatar. "
                    "Choose the best animation file from the provided list. "
                    "Return ONLY valid JSON. No markdown, no code blocks."
                ),
            },
            {"role": "user", "content": prompt},
        ]

        # Use L5 with JSON mode for reliable structured output
        extra_params: dict[str, Any] = {}
        if any(m in l5_model.lower() for m in ("gemini", "gpt", "claude", "deepseek", "qwen")):
            extra_params["response_format"] = {"type": "json_object"}

        raw = await layers.client.complete(
            messages=messages,
            model=l5_model,
            temperature=0.2,
            max_tokens=300,
            **extra_params,
        )

        logger.debug(f"L5 animation raw response: {raw[:300]}")

        # Parse JSON from response
        parsed = _extract_json(raw)

        if not parsed:
            # Fallback: pick based on arousal
            fallback = _fallback_select(request.emotion)
            logger.warning(f"L5 JSON parse failed, using fallback: {fallback}")
            return L5AnimationResponse(
                animation=fallback,
                confidence=0.3,
                reasoning="Fallback: L5 response was not valid JSON",
            )

        # Validate the animation file exists
        animation = parsed.get("animation", "")
        if animation not in VALID_ANIMATION_FILES:
            # Try partial match
            for valid in VALID_ANIMATION_FILES:
                if animation in valid or valid in animation:
                    animation = valid
                    break
            else:
                animation = _fallback_select(request.emotion)

        return L5AnimationResponse(
            animation=animation,
            confidence=float(parsed.get("confidence", 0.5)),
            reasoning=str(parsed.get("reasoning", "No reasoning provided")),
        )

    except Exception as e:
        logger.error(f"L5 animation selection failed: {e}", exc_info=True)
        fallback = _fallback_select(request.emotion)
        return L5AnimationResponse(
            animation=fallback,
            confidence=0.1,
            reasoning=f"Error: {str(e)[:100]}. Using fallback.",
        )


@router.post("/detect-movement", response_model=MovementCommandResponse)
async def detect_movement(request: MovementCommandRequest) -> MovementCommandResponse:
    """
    Movement Command Detector — scan user text for explicit movement keywords.

    If a movement keyword is detected AND broadcast=True, sends an
    animation_command WebSocket event to all connected avatar clients so
    the avatar responds instantly (bypassing all emotion-based cooldowns).

    This endpoint is called by the orchestrator after processing user input —
    it provides the backend-driven path for movement detection, complementing
    the frontend keyword shortcut in chat.tsx.
    """
    animation = detect_movement_keyword(request.text)

    if not animation:
        return MovementCommandResponse(detected=False)

    # Find the matched keyword for logging
    lower = request.text.lower()
    matched_keyword = next(
        (kw for kw in sorted(MOVEMENT_KEYWORDS.keys(), key=len, reverse=True) if kw in lower),
        None,
    )

    broadcast_sent = False
    if request.broadcast and animation:
        try:
            from aura.api.websocket import broadcast_animation_command
            await broadcast_animation_command(
                animation=animation,
                source="user_command",
                reasoning=f"Movement keyword '{matched_keyword}' detected in: '{request.text[:80]}'",
            )
            broadcast_sent = True
            logger.info(f"Movement command broadcast: {animation} (keyword='{matched_keyword}')")
        except Exception as e:
            logger.warning(f"Failed to broadcast movement command: {e}")

    return MovementCommandResponse(
        detected=True,
        animation=animation,
        keyword=matched_keyword,
        broadcast_sent=broadcast_sent,
    )


@router.get("/available-animations")
async def get_available_animations() -> dict[str, Any]:
    """Get the list of available VRMA animations."""
    return {
        "success": True,
        "animations": AVAILABLE_ANIMATIONS,
        "count": len(AVAILABLE_ANIMATIONS),
    }


@router.get("/movement-keywords")
async def get_movement_keywords() -> dict[str, Any]:
    """Get the movement keyword → animation mapping (for debugging)."""
    return {
        "success": True,
        "keywords": MOVEMENT_KEYWORDS,
        "count": len(MOVEMENT_KEYWORDS),
    }


# ---- Helpers ------------------------------------------------------------


def _extract_json(text: str) -> dict[str, Any] | None:
    """Extract JSON from LLM response text."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try code block
    code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if code_match:
        try:
            return json.loads(code_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try brace matching
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    return None


def _fallback_select(emotion: dict[str, Any]) -> str:
    """
    Simple fallback: select animation based on arousal, valence, and dominant emotion.
    Covers all 27 emotion dimensions via heuristic rules.
    """
    arousal = float(emotion.get("arousal", 0.5))
    valence = float(emotion.get("valence", 0))
    dominant = str(emotion.get("dominant", "")).lower()

    # Explicit dominant emotion routing
    dominant_map = {
        "joy": "/vrm-assets/dance.vrma",
        "love": "/vrm-assets/peaceSign_slow.vrma",
        "interest": "/vrm-assets/idle_curious.vrma",
        "trust": "/vrm-assets/greeting.vrma",
        "fear": "/vrm-assets/showFullBody.vrma",
        "sadness": "/vrm-assets/squat.vrma",
        "anger": "/vrm-assets/shoot.vrma",
        "surprise": "/vrm-assets/spin.vrma",
        "disgust": "/vrm-assets/showFullBody.vrma",
        "awe": "/vrm-assets/spin_slow.vrma",
        "beauty": "/vrm-assets/modelPose.vrma",
        "wonder": "/vrm-assets/spin_slow.vrma",
        "serenity": "/vrm-assets/peaceSign.vrma",
        "melancholy": "/vrm-assets/squat.vrma",
        "nostalgia": "/vrm-assets/modelPose.vrma",
        "empathy": "/vrm-assets/greeting.vrma",
        "gratitude": "/vrm-assets/peaceSign.vrma",
        "pride": "/vrm-assets/modelPose_confident.vrma",
        "shame": "/vrm-assets/greeting_shy.vrma",
        "envy": "/vrm-assets/squat.vrma",
        "compassion": "/vrm-assets/greeting.vrma",
        "curiosity": "/vrm-assets/modelPose.vrma",
        "confusion": "/vrm-assets/showFullBody.vrma",
        "certainty": "/vrm-assets/modelPose_confident.vrma",
        "doubt": "/vrm-assets/showFullBody.vrma",
        "fascination": "/vrm-assets/spin.vrma",
        "boredom": "/vrm-assets/squat.vrma",
    }

    if dominant in dominant_map:
        return dominant_map[dominant]

    # Arousal/valence heuristics
    if arousal > 0.65 and valence > 0.2:
        return "/vrm-assets/dance_fast.vrma"
    if arousal > 0.55 and valence > 0.15:
        return "/vrm-assets/dance.vrma"
    if arousal > 0.55 and valence < -0.15:
        return "/vrm-assets/shoot.vrma"
    if arousal < 0.3 and valence < -0.1:
        return "/vrm-assets/squat.vrma"
    if valence > 0.3:
        return "/vrm-assets/greeting_enthusiastic.vrma"
    if valence > 0.2:
        return "/vrm-assets/greeting.vrma"

    return "/vrm-assets/idle_loop.vrma"
