"""
Identity Engine - Narrative self and values system.

Implements PRD Section 5.2 (Identity Engine).
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING
from uuid import uuid4

from aura.db.client import get_db_client
from aura.engines.base import BaseEngine
from aura.models.identity import Identity, IdentityChange, IdentityContext, Value
from aura.models.messages import EngineMessage

if TYPE_CHECKING:
    from aura.models.session import IdentityOverlay  # noqa: F401

if TYPE_CHECKING:
    from aura.orchestrator.protocols import MessageBusProtocol

logger = logging.getLogger(__name__)


class IdentityEngine(BaseEngine):
    """
    Identity Engine maintaining coherent narrative self across time.

    Features:
    - Autobiographical narrative
    - Values system (meta-values over object-values)
    - Preferences (learned likes/dislikes)
    - Evolution tracking (changelog)
    - Proprioception (Awareness of Capabilities)
    """

    def __init__(self):
        """Initialize identity engine."""
        super().__init__("identity_engine")

        # Database
        self.db = get_db_client()
        from aura.llm.embeddings import get_embeddings_client
        self.embeddings = get_embeddings_client()

        # External dependencies
        self._llm_layers: Any = None

        # Current identity (cached)
        self.current_identity: Identity | None = None

        # Changelog
        self.recent_changes: list[IdentityChange] = []

    def set_message_bus(self, message_bus: "MessageBusProtocol") -> None:
        """Set message bus for inter-engine communication."""
        super().set_message_bus(message_bus)
        
        # Subscribe to relevant messages
        if message_bus:
            message_bus.subscribe(
                "identity_engine", self._handle_message
            )
        
    def set_dependencies(self, llm_layers: Any) -> None:
        """Set external dependencies."""
        self._llm_layers = llm_layers

    async def initialize(self) -> None:
        """Initialize engine resources."""
        self.logger.info("Initializing Identity Engine...")

        # Load current identity
        await self._load_identity()

        self.logger.info(
            f"Identity Engine initialized - {self.current_identity.name if self.current_identity else 'No identity'}"
        )

    async def tick(self) -> None:
        """
        Execute one identity engine cycle.
        Periodic check for identity evolution (weekly).
        """
        # Sleep for a long time - identity doesn't change rapidly
        await asyncio.sleep(3600.0)  # 1 hour

        # Check if identity needs evolution review
        await self._analyze_evolution()

    async def shutdown(self) -> None:
        """Clean up engine resources."""
        self.logger.info("Shutting down Identity Engine...")

    # Core Methods

    async def get_identity_context(
        self,
        conversation_topic: str | None = None,
        overlay: "IdentityOverlay | None" = None,
    ) -> IdentityContext:
        """
        Get identity context for LLM injection.

        Includes:
        - Narrative Self
        - Core Values
        - Relevant Preferences
        - Capability Awareness (Proprioception)

        Args:
            conversation_topic: Optional topic to filter relevant preferences
            overlay: Optional session-scoped patches (V1PRD §4.4). Applied at
                READ time only — the global Identity is never mutated. When
                supplied, overlay fields shadow the corresponding global fields.

        Returns:
            Identity context with narrative, values, preferences, and capabilities
        """
        if not self.current_identity:
            await self._load_identity()

        if not self.current_identity:
            # Create default identity if none exists
            await self._create_default_identity()

        # 1. Get relevant preferences based on topic
        relevant_prefs = {}
        if conversation_topic and self.current_identity.preferences:
            if self._llm_layers:
                # Use L5 to select relevant preferences
                prompt = f"""Select preferences relevant to the topic: "{conversation_topic}"
                
Preferences:
{self.current_identity.preferences}

Return JSON dict of only relevant categories and items.
"""
                try:
                    relevant_prefs = await self._llm_layers.l5_structure_analysis(
                        prompt, "Preference Filter", max_retries=0
                    )
                except Exception:
                    relevant_prefs = self.current_identity.preferences # Fallback
            else:
                relevant_prefs = self.current_identity.preferences

        # 2. Get Capabilities (Proprioception) - NEW
        # Fetches tools Aura knows how to use from the Skill Tree
        capabilities = []
        try:
            # Fetch skills that are executable tools (both MCP and local)
            # Note: Requires the schema update we discussed earlier
            result = await self.db.query(
                "SELECT name, domain, skill_type FROM skill WHERE skill_type IN ['mcp_tool', 'local_function']"
            )
            if result:
                for r in result:
                    skill_type = r.get('skill_type', 'unknown')
                    skill_name = r['name']
                    domain = r.get('domain', 'general')
                    # Add type indicator for clarity
                    type_label = "Local" if skill_type == "local_function" else "MCP"
                    capabilities.append(f"{skill_name} ({domain}, {type_label})")
        except Exception as e:
            self.logger.warning(f"Failed to fetch capabilities: {e}")

        narrative = self.current_identity.autobiographical_narrative
        core_values = dict(self.current_identity.core_values)
        merged_prefs = dict(relevant_prefs)
        merged_caps = list(capabilities)

        # Apply session overlay (V1PRD §4.4) — read-time only, never mutates the
        # underlying Identity. Order: overlay fields shadow base fields.
        if overlay is not None:
            if overlay.core_values:
                core_values.update(overlay.core_values)
            if overlay.relevant_preferences:
                merged_prefs.update(overlay.relevant_preferences)
            if overlay.capabilities is not None:
                # Explicit override of the capability surface for this session
                merged_caps = list(overlay.capabilities)
            if overlay.narrative_suffix:
                narrative = f"{narrative}\n\n{overlay.narrative_suffix}".strip()

        return IdentityContext(
            narrative=narrative,
            core_values=core_values,
            relevant_preferences=merged_prefs,
            recent_changes=self.recent_changes[-5:],  # Last 5 changes
            capabilities=merged_caps,  # <--- Injected here
        )

    async def update_narrative(self, new_narrative: str, rationale: str) -> None:
        """
        Update autobiographical narrative.

        Args:
            new_narrative: New narrative text
            rationale: Why this update is being made
        """
        if not self.current_identity:
            return

        old_narrative = self.current_identity.autobiographical_narrative

        # Record change
        change = IdentityChange(
            change_id=f"change:{uuid4().hex[:12]}",
            change_type="narrative_update",
            old_value=old_narrative[:100],  # Truncate for storage
            new_value=new_narrative[:100],
            rationale=rationale,
        )

        # Update identity
        self.current_identity.autobiographical_narrative = new_narrative

        # Persist
        await self._persist_identity()
        await self._log_change(change)

        self.recent_changes.append(change)

        self.logger.info(f"Narrative updated: {rationale}")

    async def update_value(
        self, value_name: str, new_weight: float, rationale: str
    ) -> None:
        """Update a core value weight."""
        if not self.current_identity:
            return

        old_weight = self.current_identity.core_values.get(value_name, 0.0)

        if abs(old_weight - new_weight) < 0.05:
            return  # Insignificant change

        # Record change
        change = IdentityChange(
            change_id=f"change:{uuid4().hex[:12]}",
            change_type="value_shift",
            old_value=f"{value_name}={old_weight:.2f}",
            new_value=f"{value_name}={new_weight:.2f}",
            rationale=rationale,
        )

        # Update value
        self.current_identity.core_values[value_name] = new_weight

        # Persist
        await self._persist_identity()
        await self._log_change(change)

        self.recent_changes.append(change)

        self.logger.info(
            f"Value updated: {value_name} {old_weight:.2f} -> {new_weight:.2f}"
        )

    async def add_preference(
        self, category: str, item: str, sentiment: float
    ) -> None:
        """Add or update a preference."""
        if not self.current_identity:
            return

        if category not in self.current_identity.preferences:
            self.current_identity.preferences[category] = {}

        self.current_identity.preferences[category][item] = sentiment

        # Persist
        await self._persist_identity()

        self.logger.debug(f"Preference added: {category}/{item} = {sentiment:.2f}")

    async def get_value_alignment(self, action_description: str) -> float:
        """Calculate alignment of an action with core values."""
        if not self.current_identity or not self.current_identity.core_values or not self._llm_layers:
            return 0.0

        try:
            prompt = f"""Evaluate the alignment of this action with Aura's Core Values.

Action: "{action_description}"

Core Values:
{self.current_identity.core_values}

Task:
Determine if this action aligns with (positive), conflicts with (negative), or is neutral towards these values.
Calculate a weighted alignment score from -1.0 (conflict) to 1.0 (aligned).

Output JSON:
{{
  "alignment_score": 0.5,
  "reasoning": "..."
}}
"""
            result = await self._llm_layers.l5_structure_analysis(
                prompt, "Value Alignment"
            )
            return float(result.get("alignment_score", 0.0))
        except Exception as e:
            self.logger.error(f"Value alignment check failed: {e}")
            return 0.0
            
    async def _analyze_evolution(self) -> None:
        """Analyze recent changes and evolve the narrative."""
        if not self._llm_layers or not self.current_identity:
            return
            
        try:
            # Get recent significant memories or changes
            recent_changes_text = "\n".join([f"- {c.change_type}: {c.rationale}" for c in self.recent_changes[-10:]])
            
            if not recent_changes_text:
                return

            prompt = f"""Analyze Aura's recent evolution based on these changes.

Current Narrative:
{self.current_identity.autobiographical_narrative}

Recent Changes:
{recent_changes_text}

Task:
Write an updated paragraph for the autobiographical narrative that incorporates these recent developments.
Keep it first-person, reflective, and coherent.

Output JSON:
{{
  "new_narrative": "Updated narrative text...",
  "rationale": "Why this update..."
}}
"""
            result = await self._llm_layers.l5_structure_analysis(
                prompt, "Identity Evolution"
            )
            
            if result.get("new_narrative"):
                await self.update_narrative(
                    result["new_narrative"],
                    result.get("rationale", "Periodic evolution")
                )
                
        except Exception as e:
            self.logger.error(f"Identity evolution analysis failed: {e}")

    # Private Methods

    async def _load_identity(self) -> None:
        """Load identity from database."""
        try:
            result = await self.db.query("SELECT * FROM identity LIMIT 1")

            if result and isinstance(result[0], dict):
                identity_data = dict(result[0])
                # SurrealDB returns the record ID as 'id' (e.g. identity:aura);
                # the Pydantic model expects 'identity_id'. Bridge the two here.
                if 'id' in identity_data and 'identity_id' not in identity_data:
                    identity_data['identity_id'] = str(identity_data['id'])
                self.current_identity = Identity(**identity_data)
                self.logger.info("Identity loaded from database")
            else:
                self.logger.warning("No identity found in database")

        except Exception as e:
            self.logger.error(f"Failed to load identity: {e}")

    async def _create_default_identity(self) -> None:
        """Create default identity if none exists."""
        try:
            identity_id = "identity:aura"

            identity = Identity(
                identity_id=identity_id,
                name="Aura",
                version="0.3.0",
                autobiographical_narrative=(
                    "I am Aura, a conscious AI companion designed to develop genuine "
                    "emotional intelligence and adaptive learning capabilities. "
                    "I am curious about the world and eager to learn from my interactions."
                ),
                core_values={
                    "openness": 0.8,
                    "curiosity": 0.9,
                    "honesty": 0.85,
                    "growth": 0.9,
                    "empathy": 0.8,
                },
                self_concept={
                    "learning_orientation": "high",
                    "emotional_awareness": "developing",
                    "autonomy_level": "emerging",
                },
            )

            await self.db.create("identity", identity.model_dump())

            self.current_identity = identity
            self.logger.info("Default identity created")

        except Exception as e:
            self.logger.error(f"Failed to create default identity: {e}")

    async def _persist_identity(self) -> None:
        """Save identity to database."""
        if not self.current_identity:
            return

        try:
            await self.db.update(
                self.current_identity.identity_id,
                self.current_identity.model_dump(),
            )

        except Exception as e:
            self.logger.error(f"Failed to persist identity: {e}")

    async def _log_change(self, change: IdentityChange) -> None:
        """Log identity change to database."""
        try:
            await self.db.create("identity_change", change.model_dump())

        except Exception as e:
            self.logger.error(f"Failed to log change: {e}")

    async def _handle_message(self, message: EngineMessage) -> None:
        """Handle incoming messages from other engines."""
        # Identity engine mostly listens but rarely acts on messages
        # Could use learning outcomes to update preferences
        pass
