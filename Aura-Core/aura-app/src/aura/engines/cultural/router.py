"""
Cultural Router - Context detection and node selection for cultural reasoning.

Detects cultural context from user language, location, or explicit preference,
selects the appropriate CulturalNode, and logs the routing decision.

This is data architecture and routing metadata only — no actual reasoning
modification is applied to LLM context yet (deferred to a future session).

Designed with multi-Aura federation in mind: routing decisions are serialisable
so remote instances can query and sync cultural context via API endpoints.
"""

import logging
from datetime import datetime
from typing import Any

from aura.db.client import get_db_client
from aura.models.cultural import CulturalNode, CulturalRoutingDecision

logger = logging.getLogger(__name__)

# Default node when no cultural context is detected
DEFAULT_NODE_CODE = "USA"


class CulturalRouter:
    """
    Selects a CulturalNode per turn based on detected context.

    Responsibilities:
    - Load available nodes from SurrealDB
    - Detect cultural context from user signals
    - Select the best-fit node
    - Log every routing decision for audit / federation
    - Expose the currently active node
    """

    def __init__(self) -> None:
        self.db = get_db_client()
        self._nodes_cache: dict[str, CulturalNode] = {}
        self._active_node: str | None = None
        self._last_decision: CulturalRoutingDecision | None = None

    # =========================================================================
    # NODE MANAGEMENT
    # =========================================================================

    async def load_nodes(self) -> dict[str, CulturalNode]:
        """Load all cultural nodes from SurrealDB into the in-memory cache."""
        try:
            result = await self.db.query("SELECT * FROM cultural_node")
            if result:
                self._nodes_cache = {}
                for row in result:
                    try:
                        node = CulturalNode(**row)
                        self._nodes_cache[node.code] = node
                    except Exception as e:
                        logger.warning(f"Skipping malformed cultural node: {e}")
                logger.info(f"Loaded {len(self._nodes_cache)} cultural nodes")
            else:
                logger.warning("No cultural nodes found in database")
        except Exception as e:
            logger.error(f"Failed to load cultural nodes: {e}")
        return self._nodes_cache

    async def get_all_nodes(self) -> list[CulturalNode]:
        """Return all loaded nodes (refreshes cache if empty)."""
        if not self._nodes_cache:
            await self.load_nodes()
        return list(self._nodes_cache.values())

    async def get_node(self, code: str) -> CulturalNode | None:
        """Get a specific node by code."""
        if not self._nodes_cache:
            await self.load_nodes()
        return self._nodes_cache.get(code)

    # =========================================================================
    # ROUTING
    # =========================================================================

    async def route(
        self,
        user_id: str | None = None,
        language: str | None = None,
        location: str | None = None,
        explicit_preference: str | None = None,
    ) -> CulturalRoutingDecision:
        """
        Detect cultural context and select a node.

        Priority order:
        1. Explicit user preference (highest)
        2. User language hint
        3. Location hint
        4. Default fallback

        Returns:
            CulturalRoutingDecision with the selected node and rationale.
        """
        if not self._nodes_cache:
            await self.load_nodes()

        selected_code: str = DEFAULT_NODE_CODE
        method: str = "default"
        confidence: float = 0.3
        reason: str = "No cultural signal detected; using default node"

        # Priority 1: Explicit preference
        if explicit_preference and explicit_preference.upper() in self._nodes_cache:
            selected_code = explicit_preference.upper()
            method = "explicit"
            confidence = 1.0
            reason = f"User explicitly selected {selected_code}"

        # Priority 2: Language hint
        elif language:
            lang_map = self._language_to_node_map()
            lang_key = language.lower().strip()
            if lang_key in lang_map:
                selected_code = lang_map[lang_key]
                method = "language"
                confidence = 0.7
                reason = f"Detected language '{language}' → node {selected_code}"

        # Priority 3: Location
        elif location:
            loc_key = location.upper().strip()
            if loc_key in self._nodes_cache:
                selected_code = loc_key
                method = "location"
                confidence = 0.6
                reason = f"Location '{location}' matched node {selected_code}"

        # Build decision
        decision = CulturalRoutingDecision(
            timestamp=datetime.utcnow(),
            selected_node=selected_code,
            detection_method=method,
            confidence=confidence,
            reason=reason,
            user_id=user_id,
        )

        self._active_node = selected_code
        self._last_decision = decision

        # Persist the routing decision
        await self._log_decision(decision)

        logger.info(
            f"Cultural route: {selected_code} (method={method}, confidence={confidence:.2f})"
        )
        return decision

    async def set_active_node(self, code: str) -> CulturalRoutingDecision | None:
        """Manual override — set the active node directly."""
        if not self._nodes_cache:
            await self.load_nodes()
        if code.upper() not in self._nodes_cache:
            logger.warning(f"Node '{code}' not found in cache")
            return None

        decision = CulturalRoutingDecision(
            selected_node=code.upper(),
            detection_method="explicit",
            confidence=1.0,
            reason=f"Manual override to {code.upper()}",
        )
        self._active_node = code.upper()
        self._last_decision = decision
        await self._log_decision(decision)
        return decision

    def get_active(self) -> dict[str, Any]:
        """Return the currently active node code and last routing decision."""
        node = self._nodes_cache.get(self._active_node or "") if self._active_node else None
        return {
            "active_node": self._active_node,
            "node": node.model_dump() if node else None,
            "last_decision": self._last_decision.model_dump() if self._last_decision else None,
        }

    # =========================================================================
    # INTERNAL HELPERS
    # =========================================================================

    @staticmethod
    def _language_to_node_map() -> dict[str, str]:
        """Map common language identifiers to cultural node codes."""
        return {
            "ja": "JP", "japanese": "JP",
            "ru": "RU", "russian": "RU",
            "zh": "CN", "chinese": "CN", "mandarin": "CN",
            "en": "USA", "english": "USA",
            "pt": "BRA", "portuguese": "BRA",
            "es": "SPA", "spanish": "SPA",
            "hi": "IN", "hindi": "IN",
            "ko": "KR", "korean": "KR",
            "de": "EU", "german": "EU",
            "fr": "EU", "french": "EU",
        }

    async def _log_decision(self, decision: CulturalRoutingDecision) -> None:
        """Persist routing decision to SurrealDB for audit / federation."""
        try:
            await self.db.create(
                "cultural_routing_log",
                decision.model_dump(),
            )
        except Exception as e:
            logger.warning(f"Failed to log cultural routing decision: {e}")


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------
_cultural_router: CulturalRouter | None = None


def get_cultural_router() -> CulturalRouter:
    """Get or create the global CulturalRouter singleton."""
    global _cultural_router
    if _cultural_router is None:
        _cultural_router = CulturalRouter()
    return _cultural_router
