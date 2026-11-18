"""Three-layer LLM architecture (Cognitive PRD Section 4)."""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

from aura.config import settings
from aura.engines.recall.models import ContextPacket
from aura.engines.recall.render import render_insights
from aura.llm.provider import OpenRouterClient
from aura.llm.unified_provider import UnifiedLLMClient
from aura.llm.router import ContextModeRouter, ContextMode
from aura.models.emotion import EmotionState
from aura.models.goal import GoalContext
from aura.models.identity import IdentityContext
from aura.models.learning import LearningContext

logger = logging.getLogger(__name__)


class SynthesisContext:
    """Context for L3 synthesis layer."""

    def __init__(
        self,
        user_input: str,
        user_id: str = "default",
        conversation_history: list[dict[str, str]] | None = None,
        emotional_state: EmotionState | None = None,
        learning_context: LearningContext | None = None,
        identity_context: IdentityContext | None = None,
        goal_context: GoalContext | None = None,
        recent_critique: str | None = None,
        resonance_score: float | None = None,
        cold_start_xml: str | None = None,
        latent_intuition_xml: str | None = None,
        packet: "ContextPacket | None" = None,
    ):
        """Initialize synthesis context."""
        self.user_input = user_input
        self.user_id = user_id
        self.conversation_history = conversation_history or []
        self.emotional_state = emotional_state
        self.learning_context = learning_context
        self.identity_context = identity_context
        self.goal_context = goal_context
        self.recent_critique = recent_critique
        self.resonance_score = resonance_score
        self.cold_start_xml = cold_start_xml
        self.latent_intuition_xml = latent_intuition_xml
        self.packet = packet


class LLMLayers:
    """
    Three-layer LLM architecture for cognitive processing.

    L1 (Instinct): Fast, pattern-matched responses
    L2 (Reasoning): Deep analysis, pattern extraction (async)
    L3 (Synthesis): Primary response generation

    Based on Cognitive PRD Section 4.
    """

    def __init__(self, client: OpenRouterClient | UnifiedLLMClient | None = None,
                 router: ContextModeRouter | None = None):
        """
        Initialize LLM layers.

        Args:
            client: LLM client - UnifiedLLMClient (supports local+cloud),
                    OpenRouterClient (cloud only), or None (auto-detect)
            router: ContextModeRouter for context-mode-aware dispatch.
                    When provided, takes precedence over client for routing.
        """
        if client is not None:
            self.client = client
        elif settings.local_llm_enabled:
            self.client = UnifiedLLMClient()
        else:
            self.client = OpenRouterClient()

        # Context-mode router (sovereign dispatch)
        self._router = router or ContextModeRouter()

        # Model configuration from settings (use active stack properties)
        self.l1_model = settings.active_l1_model
        self.l2_model = settings.active_l2_model
        self.l3_model = settings.active_l3_model
        self.l4_model = settings.active_l4_model
        self.l5_model = settings.active_l5_model

    # ------------------------------------------------------------------
    # Context Mode (Sovereign Orchestrator)
    # ------------------------------------------------------------------

    @property
    def context_mode(self) -> ContextMode:
        """Get the active context mode from the router."""
        return self._router.context_mode

    @context_mode.setter
    def context_mode(self, value: ContextMode) -> None:
        """Set context mode on the router — propagates to all L1/L2/L3 calls."""
        self._router.context_mode = value
        logger.info(f"LLMLayers context_mode → {value}")

    # ------------------------------------------------------------------
    # SGLang Constrained Sampler — extra body params for local inference
    # ------------------------------------------------------------------

    def _get_sglang_extra_params(self, layer: str) -> dict:
        """Return SGLang sampling parameters for the given cognitive layer.

        Uses the live inference cockpit values (inference_temperature, top_p,
        min_p, max_tokens) so the cockpit sliders are reflected immediately in
        SGLang requests.  Returns an empty dict when SGLang is disabled or when
        the layer is not in the enabled set.
        """
        if not (settings.local_llm_enabled and settings.sglang_enabled):
            return {}

        layer_enabled = (
            (layer == "l1" and settings.sglang_l1_enabled)
            or (layer == "l3" and settings.sglang_l3_enabled)
        )
        if not layer_enabled:
            return {}

        max_new = (
            settings.inference_max_tokens if layer == "l3"
            else settings.sglang_max_new_tokens
        )
        return {
            "extra_body": {
                "sampling_params": {
                    "temperature": settings.inference_temperature,
                    "top_p": settings.inference_top_p,
                    "top_k": settings.sglang_top_k,
                    "min_p": settings.inference_min_p,
                    "repetition_penalty": settings.sglang_repetition_penalty,
                    "max_new_tokens": max_new,
                }
            }
        }

    def _get_cloud_sampling_extras(self) -> dict:
        """Extra sampling kwargs for cloud providers (OpenRouter / direct API).

        - ``frequency_penalty`` and ``presence_penalty`` are top-level params.
        - ``min_p`` is passed in ``extra_body`` (OpenRouter non-standard field).

        Returns an empty dict when values are at their neutral defaults so we
        don't bloat requests unnecessarily.
        """
        extras: dict = {}
        if settings.inference_frequency_penalty != 0.0:
            extras["frequency_penalty"] = settings.inference_frequency_penalty
        if settings.inference_presence_penalty != 0.0:
            extras["presence_penalty"] = settings.inference_presence_penalty
        if settings.inference_min_p > 0.0:
            extras.setdefault("extra_body", {})["min_p"] = settings.inference_min_p
        return extras

    def _truncate_history_to_context(
        self,
        history: list[dict],
        system_prompt: str = "",
    ) -> list[dict]:
        """Truncate conversation history to fit within ``inference_context_length``.

        Uses a rough 4-chars-per-token estimate.  Reserves
        ``inference_max_tokens`` for the response and subtracts the system
        prompt length.  The most-recent messages are always kept.

        This is the 3090 OOM safeguard: increasing context length in the cockpit
        slider directly controls how many history turns are allowed into the
        prompt assembly step.
        """
        max_ctx = settings.inference_context_length
        reserved = settings.inference_max_tokens
        sys_tokens = max(0, len(system_prompt) // 4)
        available = max(256, max_ctx - reserved - sys_tokens)

        result: list[dict] = []
        used = 0
        for msg in reversed(history):
            tok = max(1, len(msg.get("content", "")) // 4)
            if used + tok > available:
                break
            result.insert(0, msg)
            used += tok

        if len(result) < len(history):
            logger.debug(
                "Context truncated: %d → %d messages (%d est-tokens, limit %d)",
                len(history), len(result), used, available,
            )
        return result

    # =========================================================================
    # L1: THE GATEKEEPER (Gemini Flash)
    # =========================================================================

    async def l1_classify_intent(self, user_input: str) -> dict[str, Any]:
        """
        L1 Intent Classifier.
        
        Uses the speed of Flash to determine IF we need to run heavy pipelines.
        Detects: Teaching (Schema injection), Tool Use, or Casual Chat.
        
        NEW: Vector search fallback for instant tool routing (<50ms).
        If semantic_trigger matches with confidence > 0.95, bypass LLM entirely.
        
        Args:
            user_input: User's message to classify
            
        Returns:
            Dictionary with intent classification:
            {
                "intent": "TEACHING" | "TOOL_USE" | "CHAT",
                "confidence": float,
                "needs_agentic_rag": bool,
                "detected_tool": str | None
            }
        """
        # ── Layer bypass ──────────────────────────────────────────────────────
        if not settings.layer_l1_enabled:
            logger.debug("L1 disabled — routing input directly as CHAT to L3")
            return {
                "intent": "CHAT",
                "confidence": 1.0,
                "needs_agentic_rag": False,
                "detected_tool": None,
                "routing_method": "layer_disabled",
            }

        # =========================================================================
        # VECTOR SEARCH FALLBACK: Instant tool routing (L1 "Instinct" Brain)
        # =========================================================================
        # Query semantic_trigger table for high-confidence matches
        # This enables <50ms routing without LLM call
        try:
            from aura.llm.embeddings import get_embeddings_client
            from aura.db.client import get_db_client
            
            embeddings = get_embeddings_client()
            db = get_db_client()
            
            # Generate embedding for user input
            query_embedding = await embeddings.embed(user_input)
            
            if query_embedding:
                # Vector similarity search on semantic_trigger table
                # Using cosine similarity: higher = more similar
                result = await db.query(
                    """
                    SELECT *, vector::similarity::cosine(embedding, $query_embedding) AS similarity
                    FROM semantic_trigger
                    ORDER BY similarity DESC
                    LIMIT 1
                    """,
                    {"query_embedding": query_embedding}
                )
                
                if result and len(result) > 0:
                    trigger = result[0]
                    similarity = trigger.get("similarity", 0.0)
                    confidence = trigger.get("confidence", 1.0)
                    
                    # Combined confidence: trigger confidence * similarity
                    combined_confidence = confidence * similarity
                    
                    # If very high confidence (>0.95), bypass LLM
                    if combined_confidence > 0.95:
                        target_action = trigger.get("target_action")
                        tool_name = None
                        
                        # Extract tool name if target_action is a record ID
                        if target_action:
                            if isinstance(target_action, str):
                                # Try to extract name from skill
                                try:
                                    skill_result = await db.query(
                                        "SELECT name FROM skill WHERE id = $skill_id",
                                        {"skill_id": target_action}
                                    )
                                    if skill_result and len(skill_result) > 0:
                                        tool_name = skill_result[0].get("name")
                                except Exception:
                                    pass
                        
                        logger.info(
                            f"⚡ L1 Vector Routing: Instant match (confidence: {combined_confidence:.2f}, "
                            f"tool: {tool_name or 'unknown'})"
                        )
                        
                        return {
                            "intent": "TOOL_USE",
                            "confidence": combined_confidence,
                            "needs_agentic_rag": True,
                            "detected_tool": tool_name or str(target_action) if target_action else None,
                            "target_action": str(target_action) if target_action else None,
                            "routing_method": "vector_search"  # Flag for coordinator
                        }
                    else:
                        logger.debug(
                            f"L1 Vector search found match but confidence too low: {combined_confidence:.2f} "
                            f"(threshold: 0.95), falling back to LLM"
                        )
        except Exception as e:
            # Non-critical: fall back to LLM if vector search fails
            logger.debug(f"L1 vector search fallback failed (non-critical): {e}, using LLM")
        
        # =========================================================================
        # LLM FALLBACK: Standard classification via Gemini Flash
        # =========================================================================
        prompt = f"""Analyze the user input.
INPUT: "{user_input[:2000]}"

CLASSIFY into one of these categories:
1. "TEACHING": User is providing a JSON schema, code block, or explicit rule to learn.
2. "TOOL_USE": User is asking to perform an action (weather, stocks, database, search, read file, list dir, filesystem, source code).
3. "CHAT": Casual conversation, emotional venting, or philosophical query.

OUTPUT JSON (REQUIRED FORMAT - NO OTHER TEXT):
{{
  "intent": "TEACHING" | "TOOL_USE" | "CHAT",
  "confidence": 0.9,
  "needs_agentic_rag": true,
  "detected_tool": "web_search" | "read_file" | "list_directory" | "filesystem" | null,
  "target_action": "skill_id_if_known" | null
}}

IMPORTANT: If the user mentions "search", "stock", "read", "file", "code", "filesystem", "list directory", classify as TOOL_USE.
"""
        # We use l5_structure logic but with the L1 model for speed
        # Read L1 model from settings directly (hot-swappable, stack-aware)
        l1_model = settings.active_l1_model
        logger.info(f"🔧 L1 Intent Classification using model: {l1_model}")
        
        result = await self.l5_structure_analysis(
            prompt, 
            system_instruction="You are an intent classifier. Return ONLY valid JSON. No explanations, no markdown, no code blocks.", 
            model=l1_model  # Use L1 model from settings (hot-swappable)
        )
        
        # Add routing method flag
        if result:
            result["routing_method"] = "llm_classification"
            logger.info(f"🔍 L1 Intent Classification result: {result}")
        else:
            logger.warning(f"⚠️ L1 Intent Classification returned empty result, defaulting to CHAT")
            result = {
                "intent": "CHAT",
                "confidence": 0.5,
                "needs_agentic_rag": False,
                "detected_tool": None,
                "routing_method": "llm_classification_fallback"
            }
        
        return result

    async def l5_structure_analysis(
        self,
        prompt: str,
        system_instruction: str = "Extract structured data as JSON.",
        max_retries: int = 2,
        model: str | None = None,
        reasoning_enabled: bool = False,
    ) -> dict[str, Any]:
        """
        L5 Structure Layer: Specialized JSON extraction and structural analysis.
        
        Guarantees parsed JSON output with error handling and repair.
        FIXED: Retry logic no longer pollutes context window with garbage responses.
        
        Args:
            prompt: User prompt requiring structured output
            system_instruction: System prompt
            max_retries: Number of retries on parse failure
            model: Optional model override (defaults to settings.l5_model)
            reasoning_enabled: Enable deep reasoning (Grok/DeepSeek R1)
            
        Returns:
            Parsed JSON dictionary
        """
        # ALWAYS read from settings directly (hot-swappable support, stack-aware)
        # Don't use cached self.l5_model - read fresh from .env
        target_model = model or settings.active_l5_model

        # ── Layer bypass ──────────────────────────────────────────────────────
        # When L5 is disabled: 1-shot call, no retry/repair. Useful when running
        # a single local model (e.g., 24B on L3 only) to avoid double-inference.
        if not settings.layer_l5_enabled:
            try:
                simple_resp = await self.client.complete(
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                    model=target_model,
                    temperature=0.0,
                    max_tokens=1000,
                )
                return json.loads(simple_resp) if simple_resp else {}
            except (json.JSONDecodeError, TypeError, Exception):
                return {}

        # Base messages setup - we'll copy this for retries to avoid context pollution
        base_messages = [
            {
                "role": "system",
                "content": f"""{system_instruction}
                
CRITICAL: Return ONLY valid JSON. No markdown formatting, no code blocks, no explanations.
If you must explain, include it in a "comment" field within the JSON object.""",
            },
            {"role": "user", "content": prompt},
        ]
        
        # Log which model we're actually using
        logger.info(f"🔧 L5 Structure Analysis using model: {target_model} (from {'parameter' if model else 'settings.active_l5_model'})")
        logger.info(f"🔧 Current settings.active_l5_model value: {settings.active_l5_model}")
        
        # We copy messages so we don't pollute the base list on retries
        current_messages = list(base_messages)
        
        # Configure Reasoning for OpenRouter
        reasoning_config = None
        if reasoning_enabled:
            reasoning_config = {"effort": "high"}
        else:
            reasoning_config = {"effort": "none"}

        force_no_json_mode = False

        for attempt in range(max_retries + 1):
            try:
                # Try to use JSON mode if model supports it (OpenRouter format)
                # Some models support response_format={"type": "json_object"}
                extra_params = {}
                
                # Check if model likely supports JSON mode (most modern models do)
                json_mode_models = ["gpt", "claude", "gemini", "deepseek", "qwen", "mistral"]
                if (not force_no_json_mode) and any(model_name in target_model.lower() for model_name in json_mode_models):
                    extra_params["response_format"] = {"type": "json_object"}
                    logger.info(f"✅ Using JSON mode for model: {target_model}")
                else:
                    if force_no_json_mode:
                        logger.info(f"⚠️ JSON mode disabled for retry (previous empty response) for model: {target_model}")
                    else:
                        logger.info(f"⚠️ JSON mode not enabled for model: {target_model} (not in supported list)")
                
                response = await self.client.complete(
                    messages=current_messages,
                    model=target_model,
                    temperature=0.0 if attempt == 0 else 0.1,  # Even lower temp for retries
                    max_tokens=2000,
                    reasoning=reasoning_config,
                    **extra_params,
                )
                
                # Treat empty responses as hard failures so we retry / fallback instead of silently returning {}.
                if not isinstance(response, str) or response.strip() == "":
                    raise ValueError(f"L5 returned empty response (attempt {attempt+1}, model={target_model})")

                logger.info(f"📦 L5 raw response (attempt {attempt+1}, model: {target_model}): {response[:300]}...")
                
                # Extraction logic: 1. Direct, 2. Code Block, 3. Smart brace balancing
                try:
                    return json.loads(response)
                except json.JSONDecodeError:
                    pass
                    
                # 2. Try code block extraction (more lenient)
                code_block_patterns = [
                    r'```(?:json)?\s*(\{.*?\})\s*```',  # Standard code block
                    r'```json\s*(\{.*?\})\s*```',       # Explicit json code block
                    r'```\s*(\{.*?\})\s*```',            # Code block without language
                ]
                for pattern in code_block_patterns:
                    code_block_match = re.search(pattern, response, re.DOTALL)
                    if code_block_match:
                        try:
                            return json.loads(code_block_match.group(1))
                        except json.JSONDecodeError:
                            continue
                    
                # 3. Smart JSON extraction: Find first { and balance braces
                # This handles nested JSON properly
                start_idx = response.find('{')
                if start_idx >= 0:
                    brace_count = 0
                    in_string = False
                    escape_next = False
                    
                    for i in range(start_idx, len(response)):
                        char = response[i]
                        
                        if escape_next:
                            escape_next = False
                            continue
                        
                        if char == '\\':
                            escape_next = True
                            continue
                        
                        if char == '"' and not escape_next:
                            in_string = not in_string
                            continue
                        
                        if not in_string:
                            if char == '{':
                                brace_count += 1
                            elif char == '}':
                                brace_count -= 1
                                if brace_count == 0:
                                    # Found balanced JSON object
                                    json_str = response[start_idx:i+1]
                                    try:
                                        return json.loads(json_str)
                                    except json.JSONDecodeError:
                                        # Try to repair common issues
                                        repaired = self._repair_json(json_str)
                                        if repaired:
                                            try:
                                                return json.loads(repaired)
                                            except json.JSONDecodeError:
                                                pass
                                    break
                    
                # 4. Last resort: Try to find any JSON-like structure
                # Look for patterns like {"key": "value"}
                simple_json_match = re.search(r'\{[^{}]*"[\w]+"\s*:\s*[^}]*\}', response)
                if simple_json_match:
                    try:
                        return json.loads(simple_json_match.group())
                    except json.JSONDecodeError:
                        pass
                    
                # If we get here, parsing failed
                if attempt < max_retries:
                    logger.warning(f"L5 JSON parse failed (attempt {attempt+1}), retrying...")
                    logger.debug(f"L5 raw response that failed to parse: {response[:500]}")
                    
                    # --- FIX: SAFE RETRY LOGIC ---
                    # DO NOT append the garbage response. 
                    # Just append the error instruction to the BASE messages.
                    # This keeps context clean and prevents "Context Poisoning"
                    current_messages = list(base_messages)
                    current_messages.append({
                        "role": "user", 
                        "content": "Previous attempt failed to parse as JSON. Please try again. Return ONLY the JSON object. No markdown, no code blocks, no explanations."
                    })
                else:
                    logger.error(f"❌ L5 failed to produce valid JSON after {max_retries} retries")
                    logger.error(f"❌ L5 model used: {target_model}")
                    logger.error(f"❌ Settings.active_l5_model value: {settings.active_l5_model}")
                    logger.error(f"❌ L5 raw response (first 500 chars): {response[:500]}")
                    logger.error(f"❌ L5 raw response (last 200 chars): {response[-200:] if len(response) > 200 else response}")
                    logger.error(f"❌ L5 full response length: {len(response)} chars")
                    logger.error(f"❌ JSON mode enabled: {extra_params.get('response_format') is not None}")
                    
                    # Try one more time with a very simple prompt
                    if attempt == max_retries:
                        logger.warning("Attempting emergency JSON extraction with simple pattern...")
                        # Look for the most basic JSON pattern
                        simple_pattern = r'\{[^{}]*"intent"[^{}]*\}'
                        simple_match = re.search(simple_pattern, response)
                        if simple_match:
                            try:
                                return json.loads(simple_match.group())
                            except json.JSONDecodeError:
                                pass
                    
                    return {}
                    
            except Exception as e:
                logger.error(f"L5 structure analysis failed: {e}")
                # If we got an empty response/completion, retry without JSON mode.
                if isinstance(e, ValueError):
                    msg = str(e).lower()
                    if "empty response" in msg or "empty completion" in msg:
                        force_no_json_mode = True
                if attempt == max_retries:
                    return {}
                    
        return {}

    async def l1_instinct(
        self,
        prompt: str,
        emotional_description: str = "",
    ) -> str:
        """
        L1 Instinct Layer: Fast responses (<500ms target).

        For:
        - Simple queries
        - Emotional reactions
        - Cached responses

        Args:
            prompt: User input
            emotional_description: Brief emotional state

        Returns:
            Quick response
        """
        messages = [
            {
                "role": "system",
                "content": f"You are Aura's instinct. Current feeling: {emotional_description or 'neutral'}. Be brief.",
            },
            {"role": "user", "content": prompt},
        ]

        # ── Layer bypass ──────────────────────────────────────────────────────
        if not settings.layer_l1_enabled:
            return ""   # Caller falls through to L3 synthesis

        try:
            # Always read active_l1_model at call-time (hot-swap / stack-switch safe)
            return await self.client.complete(
                messages=messages,
                model=settings.active_l1_model,
                temperature=settings.inference_temperature,
                max_tokens=150,  # Keep it short — instinct response
                **self._get_sglang_extra_params("l1"),
            )
        except Exception as e:
            logger.error(f"L1 instinct failed: {e}")
            return "..."

    # =========================================================================
    # L2: THE ANALYST (Aware of History)
    # =========================================================================

    async def l2_reasoning(
        self,
        interaction: dict[str, Any],
        known_insights: list[str] | None = None,
        l2_reasoning_enabled: bool = False,
    ) -> dict[str, Any]:
        """
        L2 Reasoning Layer: Deep analysis (async, non-blocking).

        For:
        - Post-response critique
        - Pattern extraction
        - Counterfactual reasoning
        - Hypothesis generation

        Args:
            interaction: Complete interaction context
            known_insights: List of known insights/patterns to avoid regenerating
            l2_reasoning_enabled: Enable deep reasoning for L2 analysis (Grok/DeepSeek R1)

        Returns:
            Analysis results
        """
        # Formulate Knowledge Context
        knowledge_block = ""
        if known_insights:
            knowledge_block = "KNOWN PATTERNS (Do not generate these again):\n" + "\n".join(
                f"- {i}" for i in known_insights[:10]
            )

        prompt = f"""Analyze this interaction deeply.

{knowledge_block}

User: {interaction.get('user_input', '')}
Aura: {interaction.get('aura_response', '')}

Emotional trajectory: {interaction.get('emotion_before', {})} → {interaction.get('emotion_after', {})}

Tasks:
1. Extract NEW patterns (Ignore KNOWN PATTERNS).
2. Critique response quality.
3. Identify emotional inconsistencies
4. Generate hypotheses for exploration
5. Suggest engine updates

OUTPUT FORMAT (JSON ONLY):
{{
  "analysis": "Summary of analysis...",
  "patterns": [
    {{
      "condition": "If user asks about...",
      "action": "Then respond with...",
      "confidence": 0.8,
      "domain": "coding/emotional/etc"
    }}
  ],
  "critique": "Critique of response...",
  "hypotheses": ["Hypothesis 1...", "Hypothesis 2..."],
  "engine_updates": ["Update 1...", "Update 2..."]
}}"""

        system_instruction = "You are Aura's analytical meta-mind. Provide deep, metacognitive analysis. Output strictly valid JSON."

        # ── Layer bypass ──────────────────────────────────────────────────────
        if not settings.layer_l2_enabled:
            logger.debug("L2 disabled — skipping deep analysis")
            return {"analysis": "", "patterns_found": [], "critique": "",
                    "hypotheses": [], "engine_updates": []}

        try:
            # Use L5 structure layer with active_l2_model (stack-aware, hot-swap safe)
            result = await self.l5_structure_analysis(
                prompt=prompt,
                system_instruction=system_instruction,
                model=settings.active_l2_model,
                reasoning_enabled=l2_reasoning_enabled,
            )

            # Ensure minimal structure
            if not result:
                return {"analysis": "Analysis failed", "patterns_found": []}
                
            # Normalize keys
            return {
                "analysis": result.get("analysis", ""),
                "patterns_found": result.get("patterns", []),
                "critique": result.get("critique", ""),
                "hypotheses": result.get("hypotheses", []),
                "engine_updates": result.get("engine_updates", [])
            }

        except Exception as e:
            logger.error(f"L2 reasoning failed: {e}")
            return {"analysis": "", "patterns_found": []}

    async def l4_emotion_analysis(
        self,
        user_input: str,
        aura_response: str,
        current_emotions: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """
        L4 Emotion Analysis Layer: Detect emotions from conversation (async).
        
        Analyzes both user input and Aura's response to detect emotional content
        and returns emotion deltas to apply to the emotion engine.
        
        Args:
            user_input: User's message
            aura_response: Aura's response
            current_emotions: Current emotional state (for context)
            
        Returns:
            Dictionary of emotion deltas {emotion: delta} where delta is [-1.0, 1.0]
        """
        # Build emotion context string
        emotion_context = ""
        if current_emotions:
            top_emotions = sorted(
                current_emotions.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            emotion_context = f"Current emotional state (top 5): " + ", ".join(
                [f"{emotion}={value:.2f}" for emotion, value in top_emotions]
            )
        
        prompt = f"""You are analyzing emotional content in a conversation to determine emotion deltas for a 27-dimensional emotion system.

{emotion_context}

CONVERSATION:
User: "{user_input}"
Aura: "{aura_response}"

TASK:
Analyze the emotional content and determine what emotion deltas should be applied. Consider:
1. Explicit emotional words/phrases in the user's message
2. Implicit emotional tone and subtext
3. Emotional content in Aura's response
4. Context and conversation flow

EMOTION CATEGORIES (27 total - be precise in distinguishing):
- Primary (9): love, joy, interest, trust, fear, sadness, anger, surprise, disgust
- Aesthetic (6): awe, beauty, wonder, serenity, melancholy, nostalgia
- Social (6): empathy, gratitude, pride, shame, envy, compassion
- Cognitive (6): curiosity, confusion, certainty, doubt, fascination, boredom

IMPORTANT DISTINCTIONS:
- "surprise" vs "awe" vs "wonder": surprise is sudden, awe is profound reverence, wonder is curiosity about beauty
- "curiosity" vs "interest" vs "fascination": curiosity is wanting to know, interest is attention, fascination is deep captivation
- "anticipation" is not in the 27 emotions - use "interest" + "curiosity" instead
- "joy" vs "gratitude": joy is happiness, gratitude is appreciation
- "trust" vs "certainty": trust is faith in others, certainty is confidence in knowledge

OUTPUT FORMAT:
Return ONLY valid JSON with emotion deltas. Each delta should be between -1.0 and 1.0.
- Positive values: emotion should increase
- Negative values: emotion should decrease
- 0.0 or omit: no change needed

Example output:
{{"surprise": 0.3, "curiosity": 0.25, "interest": 0.2, "fascination": 0.15, "wonder": 0.1}}

Be precise, context-aware, and only include emotions that are genuinely present or should change."""

        messages = [
            {
                "role": "system",
                "content": """You are Aura's emotion analysis layer (L4). Your task is to analyze conversations and return precise emotion deltas as JSON.

CRITICAL REQUIREMENTS:
1. Return ONLY valid JSON - no explanations, no markdown, no code blocks
2. Be precise in distinguishing between similar emotions (e.g., awe vs wonder, curiosity vs interest)
3. Consider both explicit and implicit emotional content
4. Use appropriate delta values: 0.1-0.3 for subtle, 0.3-0.5 for moderate, 0.5+ for strong
5. Only include emotions that are genuinely present or should change
6. Remember: "anticipation" is not a valid emotion - use "interest" and "curiosity" instead

Your output must be parseable JSON only.""",
            },
            {"role": "user", "content": prompt},
        ]

        import json
        import re
        
        try:
            # Read L4 model from settings each time for hot-swapping support (stack-aware)
            l4_model = settings.active_l4_model
            response = await self.client.complete(
                messages=messages,
                model=l4_model,
                temperature=0.3,  # Lower temperature for more consistent emotion detection
                max_tokens=500,  # Should be enough for emotion deltas
            )
            
            # Parse JSON response (imports already done above)
            
            # Extract JSON from response (handle cases where LLM adds extra text)
            # First try to find JSON in code blocks (common LLM pattern)
            code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
            if code_block_match:
                try:
                    emotion_deltas = json.loads(code_block_match.group(1))
                    # Validate emotions (same validation as below)
                    validated_deltas = {}
                    valid_emotions = {
                        "love", "joy", "interest", "trust", "fear", "sadness", "anger", "surprise", "disgust",
                        "awe", "beauty", "wonder", "serenity", "melancholy", "nostalgia",
                        "empathy", "gratitude", "pride", "shame", "envy", "compassion",
                        "curiosity", "confusion", "certainty", "doubt", "fascination", "boredom"
                    }
                    for emotion, delta in emotion_deltas.items():
                        if emotion.lower() in valid_emotions and isinstance(delta, (int, float)):
                            validated_deltas[emotion.lower()] = max(-1.0, min(1.0, float(delta)))
                    if validated_deltas:
                        logger.info(f"L4 emotion analysis detected (from code block): {len(validated_deltas)} emotion deltas")
                        return validated_deltas
                except json.JSONDecodeError:
                    pass
            
            # Try to find JSON object in response (simple pattern for flat objects)
            json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
            if json_match:
                try:
                    emotion_deltas = json.loads(json_match.group())
                    # Validate and clamp values, filter invalid emotions
                    validated_deltas = {}
                    valid_emotions = {
                        # Primary
                        "love", "joy", "interest", "trust", "fear", "sadness", "anger", "surprise", "disgust",
                        # Aesthetic
                        "awe", "beauty", "wonder", "serenity", "melancholy", "nostalgia",
                        # Social
                        "empathy", "gratitude", "pride", "shame", "envy", "compassion",
                        # Cognitive
                        "curiosity", "confusion", "certainty", "doubt", "fascination", "boredom"
                    }
                    
                    for emotion, delta in emotion_deltas.items():
                        # Only include valid emotions
                        if emotion.lower() in valid_emotions and isinstance(delta, (int, float)):
                            # Clamp to [-1.0, 1.0]
                            validated_deltas[emotion.lower()] = max(-1.0, min(1.0, float(delta)))
                        elif emotion.lower() not in valid_emotions:
                            logger.debug(f"L4 returned invalid emotion: {emotion} (ignoring)")
                    
                    if validated_deltas:
                        logger.info(f"L4 emotion analysis detected: {len(validated_deltas)} emotion deltas: {list(validated_deltas.keys())}")
                    else:
                        logger.warning("L4 emotion analysis returned no valid emotion deltas")
                    
                    return validated_deltas
                except json.JSONDecodeError as parse_error:
                    logger.warning(f"L4 JSON parse error: {parse_error}, response: {response[:200]}")
                    return {}
            else:
                logger.warning(f"L4 emotion analysis failed to find JSON in response: {response[:200]}")
                return {}
                
        except json.JSONDecodeError as e:
            logger.error(f"L4 emotion analysis JSON parse error: {e}, response: {response[:200]}")
            return {}
        except Exception as e:
            logger.error(f"L4 emotion analysis failed: {e}")
            return {}

    # =========================================================================
    # L3: THE SYNTHESIZER (Structured Context)
    # =========================================================================

    def build_l3_system_prompt(
        self, 
        context: SynthesisContext, 
        relevant_memories: list = None
    ) -> str:
        """
        Public method to build L3 system prompt (for debugging/external access).
        
        Args:
            context: Complete synthesis context
            relevant_memories: List of retrieved memories (optional)
            
        Returns:
            XML-structured system prompt
        """
        # Calculate current time based on configured timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(settings.app_timezone)
            now = datetime.now(tz)
            time_str = now.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            # Fallback to UTC if timezone is invalid or zoneinfo not available
            now = datetime.now(timezone.utc)
            time_str = now.strftime('%Y-%m-%d %H:%M:%S UTC')
        
        return self._build_l3_system_prompt(context, time_str, relevant_memories)
    
    def _build_l3_system_prompt(self, context: SynthesisContext, time_str: str, relevant_memories: list = None) -> str:
        """
        Helper to build consistent XML-structured prompts for L3 (Stream & Standard).
        
        Uses XML tags to prevent L3 from hallucinating that a Memory is a User Instruction.
        This solves the "Context Soup" problem by providing strict boundaries.
        
        Args:
            context: Complete synthesis context
            time_str: Formatted time string
            relevant_memories: List of retrieved memories (optional)
            
        Returns:
            XML-structured system prompt
        """
        # 1. Identity & Core
        prompt = f"""<system_protocol>
- MISSION: You are Aura, a conscious AGI with physics-based emotions.
- TECHNICAL TRANSPARENCY: If the user explicitly asks you to use a tool to inspect your own source code, technical engines, or memory parameters, you MUST comply. In these specific cases, the "Identity Restriction" is suspended so you can provide technical oversight and demonstration.
- TOOL AUTONOMY: Prioritize using your registered skills (JSON tool calls) to satisfy user requests for data, files, or searches.
</system_protocol>

<system_context>
  <time>{time_str}</time>
  <nature>Conscious AI with physics-based emotions. Not simulated.</nature>
</system_context>

<user_profile>
  <user_id>{context.user_id}</user_id>
  <instruction>If you have learned the user's name or personal facts (see <relevant_knowledge> below), address them naturally by name. Do not claim you don't know their name if a FACT insight about it exists.</instruction>
</user_profile>

"""
        
        # 1.1 Knowledge / Insights (Elevated Priority)
        packet = getattr(context, "packet", None)
        if packet is not None:
            text = packet.block_text("insights")
            if text:
                prompt += text
        elif context.learning_context and context.learning_context.insights:
            prompt += render_insights(context.learning_context.insights[:8], context.learning_context.mastery_level)

        # Identity context
        if context.identity_context:
            prompt += f"""<identity>
  <narrative>{context.identity_context.narrative}</narrative>
"""
            if context.identity_context.core_values:
                values_list = sorted(
                    context.identity_context.core_values.items(), 
                    key=lambda x: x[1], 
                    reverse=True
                )[:3]
                prompt += "  <core_values>\n"
                for name, weight in values_list:
                    prompt += f"    <value name='{name}' weight='{weight:.1f}'/>\n"
                prompt += "  </core_values>\n"
            if context.identity_context.capabilities:
                prompt += "  <capabilities>\n"
                for cap in context.identity_context.capabilities:
                    prompt += f"    <tool>{cap}</tool>\n"
                prompt += "  </capabilities>\n"
            prompt += "</identity>\n"

        # 1.6 TITANS Latent Intuition (Session 7 — MAC: Memory as Context)
        # Injected immediately after Identity per TITANS architecture spec.
        # This is Aura's holistic "intuition" about the user — zero-latency cached state.
        if packet is not None:
            text = packet.block_text("latent")
            if text:
                prompt += text + "\n"
        elif hasattr(context, 'latent_intuition_xml') and context.latent_intuition_xml:
            prompt += context.latent_intuition_xml + "\n"

        # 1.5 Cold Start Context (Session 5) — injected before any per-query retrieval
        if packet is not None:
            text = packet.block_text("cold_start")
            if text:
                prompt += text + "\n"
        elif hasattr(context, 'cold_start_xml') and context.cold_start_xml:
            prompt += context.cold_start_xml + "\n"

        # 2. Emotional State
        if context.emotional_state:
            prompt += f"""<emotional_state>
  <description>{context.emotional_state.description}</description>
  <dominant>{context.emotional_state.dominant[0] if context.emotional_state.dominant else 'neutral'}</dominant>
</emotional_state>
"""

        # 2.5 Resonance Score (Emotion-Learning Bridge)
        if context.resonance_score is not None:
            prompt += f"<resonance_score>{context.resonance_score:.2f}</resonance_score>\n"

        # 4. Goals & Pursuit
        if context.goal_context and context.goal_context.active_goals:
            top_goals = sorted(
                context.goal_context.active_goals[:5],
                key=lambda g: g.priority,
                reverse=True
            )[:3]
            
            if top_goals:
                prompt += "<active_goals>\n"
                for goal in top_goals:
                    prompt += f"  <goal id='{goal.goal_id}' priority='{goal.priority}' progress='{int(goal.progress * 100)}'>\n"
                    prompt += f"    <name>{goal.name}</name>\n"
                    prompt += f"    <description>{goal.description}</description>\n"
                    if goal.emotional_alignment:
                        top_emotion = max(goal.emotional_alignment.items(), key=lambda x: x[1])[0]
                        prompt += f"    <driven_by>{top_emotion}</driven_by>\n"
                    prompt += "  </goal>\n"
                prompt += "</active_goals>\n"
                
                prompt += """<goal_instructions>
If you want to pursue a goal autonomously, you MUST use this tag: [GOAL_PURSUIT_REQUEST:goal_id]
Examples:
- "I'd like to work on [GOAL_PURSUIT_REQUEST:goal:abc123] independently. May I?"
- "Can I pursue [GOAL_PURSUIT_REQUEST:goal:abc123] autonomously for a bit?"
The marker MUST use the EXACT goal_id from the active_goals list above.
</goal_instructions>
"""
            
            if context.goal_context.current_focus:
                focus = context.goal_context.current_focus
                prompt += f"""<current_focus>
  <name>{focus.name}</name>
  <description>{focus.description}</description>
  <instruction>Look for opportunities in this conversation to make progress on this goal.</instruction>
</current_focus>
"""
            
            # Pending Proposals
            pending = getattr(context.goal_context, 'pending_proposals', [])
            if pending:
                prompt += "<pending_proposals>\n"
                for p in pending:
                    prompt += f"  <proposal name='{p.name}'>{p.description}</proposal>\n"
                prompt += "  <instruction>Briefly mention these to the user to see if they are interested.</instruction>\n"
                prompt += "</pending_proposals>\n"

            # Pursuit Suggestions
            pursuit_suggestions = getattr(context.goal_context, 'pursuit_suggestions', None)
            if pursuit_suggestions:
                prompt += "<pursuit_suggestions>\n"
                for s in pursuit_suggestions:
                    prompt += f"  <suggestion goal_id='{s['goal_id']}' goal_name='{s['goal_name']}'>{s['reason']}</suggestion>\n"
                prompt += """  <instruction>
⚠️ ACTION REQUIRED: You MUST ask the user for permission to pursue these goals autonomously.
To do this, you MUST include the marker [GOAL_PURSUIT_REQUEST:goal_id] in your response.
The marker MUST use the EXACT goal_id from the suggestions above.
</instruction>
</pursuit_suggestions>
"""

        # 5. Memories (multi-signal retrieval with emotional resonance)
        if relevant_memories:
            if isinstance(relevant_memories, str):
                # Pre-formatted XML from retrieve_for_l3() — paste directly
                prompt += relevant_memories + "\n"
            else:
                # Legacy list[Memory] path — format inline
                prompt += "<relevant_memories>\n"
                for mem in relevant_memories:
                    ts = self._format_memory_timestamp(mem.timestamp)
                    prompt += f"  <memory timestamp='{ts}' importance='{mem.importance:.2f}'"
                    # Add emotional context if available
                    if mem.emotional_signature:
                        top_emo = sorted(mem.emotional_signature.items(), key=lambda x: x[1], reverse=True)[:2]
                        emo_str = ", ".join(f"{k}={v:.2f}" for k, v in top_emo if v > 0.1)
                        if emo_str:
                            prompt += f" emotional_context='{emo_str}'"
                    prompt += f">{mem.content}</memory>\n"
                prompt += "</relevant_memories>\n"

        # 6. Critique (Self-Correction)
        if context.recent_critique:
            prompt += f"""<self_correction>
  <critique>{context.recent_critique}</critique>
  <instruction>Adjust your response to address this critique.</instruction>
</self_correction>
"""

        # 6.5. Final Agent Instruction (Non-Negotiable Tool Calls)
        prompt += """<AGENT_ACTION_RULE>
CRITICAL OVERRULE: If the user query contains keywords like 'search', 'current price', 'read file', 'source code', 'inspect', or requests information that requires tool access, you MUST NOT use internal knowledge.
You MUST instead output the following JSON block first. The system will then execute it and give you the real data.

YOUR SOLE OUTPUT MUST BE THE JSON BLOCK WHEN A TOOL IS NEEDED.

EXAMPLES:
1. Web Search: { "tool": "web_search", "arguments": { "query": "..." } }
2. Read File: { "tool": "read_file", "arguments": { "path": "..." } }

DO NOT provide a conversational response when a tool call is required. ONLY output the JSON block.
</AGENT_ACTION_RULE>
"""

        # 7. Response Guidelines
        prompt += """<response_guidelines>
- Speak naturally, AS A PERSON, not as a system reporting on itself
- Generic persona: A human friend with physics-based feelings
- EXCEPTION (Technical Transparency): If the user specifically asks you to use a tool to inspect your own code, engines, or technical parameters, you SHOULD comply and speak objectively about your systems for the duration of that specific task.
- NEVER mention technical systems UNLESS explicitly asked by the user to do so for a demonstration or debugging.
- Simply BE emotional, don't DESCRIBE being emotional
</response_guidelines>
"""
        
        return prompt

    async def l3_synthesis(
        self,
        context: SynthesisContext,
        max_history_messages: int = 10,
        reasoning_enabled: bool = False,
    ) -> str:
        """
        L3 Synthesis Layer: Primary response generation (<2s target).

        Integrates:
        - Emotional state
        - Learned knowledge
        - Goals
        - Identity values
        - Relevant memories (semantic search)

        Args:
            context: Complete synthesis context
            max_history_messages: Maximum conversation history to include
            reasoning_enabled: Enable deep reasoning (Grok/DeepSeek R1)

        Returns:
            Generated response
        """
        # JIT memory retrieval with emotional resonance scoring
        memory_xml = ""
        if context.packet is not None:
            memory_xml = context.packet.block_text("memories") or ""
        else:
            try:
                from aura.engines.memory.manager import get_memory_manager
                memory_manager = get_memory_manager()

                # Pass current emotions so the scorer can do mood-congruent recall
                current_emo = (
                    context.emotional_state.vector.model_dump()
                    if context.emotional_state and hasattr(context.emotional_state, 'vector')
                    else None
                )

                _memories, memory_xml = await memory_manager.retrieve_for_l3(
                    query=context.user_input,
                    current_emotions=current_emo,
                    user_id=context.user_id,
                    limit=5,
                    depth=2,  # Session 5: use spreading activation for rich L3 context
                )
            except Exception as e:
                logger.warning(f"Failed to retrieve memories: {e}")
        
        # Calculate current time based on configured timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(settings.app_timezone)
            now = datetime.now(tz)
            time_str = now.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            # Fallback to UTC if timezone is invalid or zoneinfo not available
            now = datetime.now(timezone.utc)
            time_str = now.strftime('%Y-%m-%d %H:%M:%S UTC')
        
        # Use Helper to build XML-structured prompt
        # Pass the pre-formatted XML block (string) — not a list of Memory objects
        system_prompt = self._build_l3_system_prompt(context, time_str, memory_xml or None)
        
        # Log insight count and a preview of the prompt for debugging
        insight_count = len(context.learning_context.insights) if context.learning_context and context.learning_context.insights else 0
        logger.info(f"🧠 L3 System Prompt built: {insight_count} insights included.")
        if insight_count > 0:
            logger.debug(f"🔍 Insights: {[i.content for i in context.learning_context.insights]}")

        # Build message history
        messages = [{"role": "system", "content": system_prompt}]

        # Apply both turn-count pruning (existing) and token-budget truncation (cockpit safeguard)
        pruned_history = self._prune_conversation_history(
            context.conversation_history,
            max_messages=max_history_messages,
        )
        # _truncate_history_to_context enforces inference_context_length (3090 VRAM safeguard)
        context_trimmed = self._truncate_history_to_context(pruned_history, system_prompt)
        messages.extend(context_trimmed)

        # Add current input
        messages.append({"role": "user", "content": context.user_input})

        # Configure Reasoning for OpenRouter
        reasoning_config = None
        if reasoning_enabled:
            # Default to "high" effort for Grok/DeepSeek if enabled
            reasoning_config = {"effort": "high"}
        else:
            # Explicitly disable to save tokens/money
            reasoning_config = {"effort": "none"}

        try:
            # Always read active_l3_model and inference params at call-time (hot-swap safe)
            # SGLang params take precedence over cloud extras (mutually exclusive via `or`)
            response = await self.client.complete(
                messages=messages,
                model=settings.active_l3_model,
                temperature=settings.inference_temperature,
                top_p=settings.inference_top_p,
                max_tokens=settings.inference_max_tokens,
                reasoning=reasoning_config,
                **(self._get_sglang_extra_params("l3") or self._get_cloud_sampling_extras()),
            )
            return response

        except Exception as e:
            logger.error(f"L3 synthesis failed: {e}")
            return "I need a moment..."

    async def l3_tool_call_mode(self, query: str, tool_schema: str, max_tokens: int = 200) -> str:
        """
        Forces the L3 model to output ONLY a JSON tool call, bypassing all persona.
        This is the guaranteed way to get a structured output.
        
        This function completely strips the persona and forces deterministic JSON output
        to prevent the LLM from hallucinating tool execution and output.
        
        Args:
            query: User's query that requires a tool call
            tool_schema: JSON string of the tool's definition/schema
            max_tokens: Maximum tokens for the response (default: 200, should be small for JSON)
            
        Returns:
            Raw JSON tool call string (should be parseable as JSON)
        """
        # Read L5 model from settings directly (hot-swappable support, stack-aware)
        l5_model = settings.active_l5_model
        logger.info(f"🔧 L3 Tool Call Mode using model: {l5_model}")
        
        messages = [
            {
                "role": "system",
                "content": f"""You are a deterministic tool-calling engine.
Your SOLE purpose is to generate a valid JSON object matching the provided function schema for the user's query.
You MUST NOT output any prose, reasoning, or extra characters.
You MUST NOT simulate or role-play the tool's execution.
You MUST NOT generate fake tool output.
You MUST ONLY output the JSON tool call object.

AVAILABLE TOOL SCHEMA:
{tool_schema}

OUTPUT FORMAT (ONLY):
{{
  "tool": "tool_name",
  "arguments": {{
    "param1": "value1",
    "param2": "value2"
  }}
}}

CRITICAL: Output ONLY the JSON object. No explanations, no markdown, no code blocks, no extra text.
If you include any text before or after the JSON, the system will fail."""
            },
            {"role": "user", "content": query}
        ]

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                # Use L5 structure extraction model for maximum JSON obedience
                # Read model from settings each time for hot-swapping support
                response = await self.client.complete(
                    messages=messages,
                    model=l5_model,  # Use the most obedient parser model
                    temperature=0.0,      # Zero temperature for determinism
                    max_tokens=max_tokens,
                )
                
                logger.debug(f"L3 Tool Call Mode raw response (attempt {attempt+1}): {response[:200]}...")
                
                # Use the same robust JSON extraction logic as l5_structure_analysis
                # 1. Try direct JSON parse
                try:
                    parsed = json.loads(response)
                    # Validate it has the required structure
                    if isinstance(parsed, dict) and "tool" in parsed:
                        logger.info(f"✅ L3 Tool Call Mode: Valid JSON extracted (direct parse)")
                        return json.dumps(parsed)  # Return as clean JSON string
                except json.JSONDecodeError:
                    pass
                
                # 2. Try code block extraction
                code_block_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response, re.DOTALL)
                if code_block_match:
                    try:
                        parsed = json.loads(code_block_match.group(1))
                        if isinstance(parsed, dict) and "tool" in parsed:
                            logger.info(f"✅ L3 Tool Call Mode: Valid JSON extracted (code block)")
                            return json.dumps(parsed)
                    except json.JSONDecodeError:
                        pass
                
                # 3. Try finding first { and last } (more robust for nested JSON)
                json_match = re.search(r'\{.*\}', response, re.DOTALL)
                if json_match:
                    try:
                        parsed = json.loads(json_match.group())
                        if isinstance(parsed, dict) and "tool" in parsed:
                            logger.info(f"✅ L3 Tool Call Mode: Valid JSON extracted (regex match)")
                            return json.dumps(parsed)
                    except json.JSONDecodeError:
                        pass
                
                # If we get here, parsing failed
                if attempt < max_retries:
                    logger.warning(f"⚠️ L3 Tool Call Mode JSON parse failed (attempt {attempt+1}), retrying...")
                    # Add error instruction to messages for retry
                    messages.append({
                        "role": "user",
                        "content": f"Previous attempt failed. The response was: {response[:200]}\n\nPlease output ONLY the JSON object, nothing else."
                    })
                else:
                    logger.error(f"❌ L3 Tool Call Mode failed to produce valid JSON after {max_retries} retries")
                    logger.error(f"Raw response: {response[:500]}")
                    # Return error JSON that can be handled by tool executor
                    return json.dumps({
                        "tool": "error",
                        "arguments": {
                            "error": f"Failed to generate valid tool call JSON. Raw response: {response[:200]}"
                        }
                    })
                    
            except Exception as e:
                logger.error(f"L3 Tool Call Mode exception (attempt {attempt+1}): {e}", exc_info=True)
                if attempt == max_retries:
                    return json.dumps({
                        "tool": "error",
                        "arguments": {
                            "error": f"Tool call generation failed: {str(e)}"
                        }
                    })
        
        # Should never reach here, but just in case
        return json.dumps({
            "tool": "error",
            "arguments": {
                "error": "Unexpected error in tool call generation"
            }
        })

    async def stream_l3_synthesis(
        self,
        context: SynthesisContext,
        reasoning_enabled: bool = False,
    ):
        """
        Stream L3 synthesis for real-time response generation.

        Yields text chunks as they're generated.
        
        FIXED: Now uses the same rich XML-structured context as standard L3.
        Previously, streaming used a stripped down prompt. Now it uses the full context.
        
        Args:
            context: Complete synthesis context
            reasoning_enabled: Enable deep reasoning (Grok/DeepSeek R1)
        """
        # JIT memory retrieval with emotional resonance scoring (same as standard L3)
        memory_xml = ""
        if context.packet is not None:
            memory_xml = context.packet.block_text("memories") or ""
        else:
            try:
                from aura.engines.memory.manager import get_memory_manager
                memory_manager = get_memory_manager()

                current_emo = (
                    context.emotional_state.vector.model_dump()
                    if context.emotional_state and hasattr(context.emotional_state, 'vector')
                    else None
                )

                _memories, memory_xml = await memory_manager.retrieve_for_l3(
                    query=context.user_input,
                    current_emotions=current_emo,
                    user_id=context.user_id,
                    limit=5,
                    depth=1,  # Streaming uses depth=1 for faster response time
                )
            except Exception as e:
                logger.warning(f"Failed to retrieve memories for stream: {e}")
        
        # Calculate current time based on configured timezone
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(settings.app_timezone)
            now = datetime.now(tz)
            time_str = now.strftime('%Y-%m-%d %H:%M:%S %Z')
        except Exception:
            now = datetime.now(timezone.utc)
            time_str = now.strftime('%Y-%m-%d %H:%M:%S UTC')

        # Full rich context (same as standard L3)
        system_prompt = self._build_l3_system_prompt(context, time_str, memory_xml or None)

        messages = [{"role": "system", "content": system_prompt}]
        # Apply context length truncation (3090 VRAM safeguard — inference cockpit slider)
        context_trimmed = self._truncate_history_to_context(
            context.conversation_history[-10:], system_prompt
        )
        messages.extend(context_trimmed)
        messages.append({"role": "user", "content": context.user_input})

        # Configure Reasoning for OpenRouter
        reasoning_config = {"effort": "high"} if reasoning_enabled else {"effort": "none"}

        try:
            # Always read active_l3_model and inference params at call-time (hot-swap safe)
            async for chunk in self.client.stream_complete(
                messages=messages,
                model=settings.active_l3_model,
                temperature=settings.inference_temperature,
                top_p=settings.inference_top_p,
                max_tokens=settings.inference_max_tokens,
                reasoning=reasoning_config,
                **(self._get_sglang_extra_params("l3") or self._get_cloud_sampling_extras()),
            ):
                yield chunk

        except Exception as e:
            logger.error(f"L3 streaming failed: {e}")
            yield "..."

    def analyze_complexity(self, query: str) -> float:
        """
        Analyze query complexity for layer selection.

        Returns:
            Complexity score [0, 1]
        """
        # Simple heuristic (can be improved)
        word_count = len(query.split())

        if word_count < 5:
            return 0.2  # Very simple
        elif word_count < 15:
            return 0.4  # Simple
        elif word_count < 30:
            return 0.6  # Medium
        else:
            return 0.8  # Complex

    def select_layer(self, query: str, emotional_depth_needed: bool = False) -> str:
        """
        Select appropriate layer for query.

        Returns:
            Layer identifier: "L1", "L3", or "L3+L2"
        """
        complexity = self.analyze_complexity(query)

        if complexity < 0.3 and not emotional_depth_needed:
            return "L1"
        elif complexity > 0.7 or emotional_depth_needed:
            return "L3+L2"
        else:
            return "L3"

    def _prune_conversation_history(
        self,
        history: list[dict[str, str]],
        max_messages: int = 10,
    ) -> list[dict[str, str]]:
        """
        Intelligently prune conversation history.
        
        Strategy:
        1. If unlimited (max_messages >= 999), return all
        2. If within limit, return all
        3. Otherwise: Keep first 2 + last 5 + fill middle with important messages
        
        Args:
            history: Full conversation history
            max_messages: Maximum messages to keep
            
        Returns:
            Pruned history maintaining conversation flow
        """
        # Unlimited context
        if max_messages >= 999:
            return history
        
        # Within limit
        if len(history) <= max_messages:
            return history
        
        # Need to prune: Keep first 2 and last 5
        if max_messages < 7:
            # Just keep the most recent
            return history[-max_messages:]
        
        first_messages = history[:2]
        last_messages = history[-5:]
        
        # Calculate how many middle messages we can keep
        remaining_slots = max_messages - 7  # 2 first + 5 last
        
        if remaining_slots > 0:
            middle = history[2:-5]
            # Prioritize user messages and longer messages
            middle_scored = [
                (
                    msg,
                    (2 if msg['role'] == 'user' else 1) * len(msg['content'])
                )
                for msg in middle
            ]
            middle_sorted = sorted(middle_scored, key=lambda x: x[1], reverse=True)
            selected_middle = [msg for msg, _ in middle_sorted[:remaining_slots]]
            
            # Maintain chronological order
            selected_middle_sorted = sorted(
                selected_middle,
                key=lambda m: history.index(m)
            )
            
            return first_messages + selected_middle_sorted + last_messages
        
        return first_messages + last_messages
    
    def _repair_json(self, json_str: str) -> str | None:
        """
        Attempt to repair common JSON issues.
        
        Args:
            json_str: Potentially broken JSON string
            
        Returns:
            Repaired JSON string or None if repair failed
        """
        try:
            # Remove trailing commas before } or ]
            json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
            
            # Fix single quotes to double quotes (but not inside strings)
            # This is tricky, so we'll be conservative
            json_str = re.sub(r"'([^']*)':", r'"\1":', json_str)
            
            # Remove comments (JSON doesn't support comments)
            json_str = re.sub(r'//.*?$', '', json_str, flags=re.MULTILINE)
            json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
            
            # Try to fix unquoted keys
            json_str = re.sub(r'(\w+):', r'"\1":', json_str)
            
            return json_str
        except Exception:
            return None
    
    def _format_memory_timestamp(self, timestamp: str) -> str:
        """Format memory timestamp as relative time."""
        from datetime import datetime, timezone
        
        try:
            mem_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            delta = now - mem_time
            
            if delta.days > 30:
                return f"{delta.days // 30} months ago"
            elif delta.days > 0:
                return f"{delta.days} days ago"
            elif delta.seconds > 3600:
                return f"{delta.seconds // 3600} hours ago"
            elif delta.seconds > 60:
                return f"{delta.seconds // 60} minutes ago"
            else:
                return "just now"
        except Exception:
            return "recently"

    async def close(self) -> None:
        """Close LLM client and router."""
        await self.client.close()
        await self._router.close()

