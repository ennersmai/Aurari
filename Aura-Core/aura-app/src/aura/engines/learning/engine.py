"""
Learning Engine - Adaptive pattern extraction and skill acquisition.

Implements Learning FRD Section 3.1 (Core Learning Loop).
Refactored for V0.3.0: One-Shot Tool Learning & Instructional Bypass.
"""

import json
import logging
import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Deque, TYPE_CHECKING
from uuid import uuid4
from collections import deque

from aura.db.client import get_db_client
from aura.engines.base import BaseEngine
from aura.llm.embeddings import get_embeddings_client
from aura.models.learning import Experience, LearningContext, Insight, Skill
from aura.models.messages import EngineMessage, MessagePriority, MessageType

if TYPE_CHECKING:
    from aura.orchestrator.protocols import MessageBusProtocol
    from aura.llm.layers import LLMLayers

logger = logging.getLogger(__name__)


def smoothed_confidence(success_count: float, application_count: float) -> float:
    """Smoothed success rate ``(successes + 1) / (total + 2)`` (insight confidence)."""
    return (success_count + 1) / (application_count + 2)


class LearningEngine(BaseEngine):
    """
    Learning Engine implementing 6-phase learning cycle.

    Phases: Capture → Extract → Abstract → Integrate → Transfer → Validate
    Based on Learning FRD FR-LL-001.
    """

    def __init__(self):
        """Initialize learning engine."""
        super().__init__("learning_engine")

        # Database
        self.db = get_db_client()

        # Embeddings client for semantic search
        self.embeddings = get_embeddings_client()

        # External dependencies
        self.llm_layers: "LLMLayers | None" = None
        
        # Queues
        self.pattern_extraction_queue: Deque[Experience] = deque(maxlen=1000)
        # Track background tasks (trigger generation, insights) for cleanup/visibility
        self._background_tasks: set[asyncio.Task] = set()
        
        # Lock for atomic insight creation (prevents race conditions)
        self._insight_creation_lock = asyncio.Lock()

        # Counters
        self.experiences_logged = 0
        self.insights_created = 0
        
        # Graph chain: Track last experience per user for temporal linking
        # Maps user_id -> (experience_id, timestamp)
        self._last_experience_cache: dict[str, tuple[str, datetime]] = {}

    def set_message_bus(self, message_bus: "MessageBusProtocol") -> None:
        """Set message bus for inter-engine communication."""
        super().set_message_bus(message_bus)
        if message_bus:
            message_bus.subscribe("learning_engine", self._handle_message)

    def _add_background_task(self, coro: "asyncio.Future", task_name: str = "") -> None:
        """Track background tasks and log exceptions."""
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)

        def _cleanup(fut: asyncio.Task) -> None:
            self._background_tasks.discard(fut)
            if fut.cancelled():
                return
            exc = fut.exception()
            if exc:
                self.logger.warning(f"Background task{f' [{task_name}]' if task_name else ''} failed: {exc}", exc_info=True)

        task.add_done_callback(_cleanup)
        return None

    def set_llm_layers(self, llm_layers: "LLMLayers") -> None:
        """Set LLM layers for background analysis."""
        self.llm_layers = llm_layers

    async def initialize(self) -> None:
        """Initialize engine resources."""
        self.logger.info("Initializing Learning Engine...")

        # Load statistics
        try:
            # Optimized stats loading
            # 'value' is a reserved keyword in SurrealDB 2.0+ in some contexts or requires escaping
            stats_result = await self.db.query("SELECT * FROM stats WHERE key = 'total_experiences'")
            if stats_result and isinstance(stats_result[0], dict):
                self.experiences_logged = stats_result[0].get("value", 0)
            else:
                # Fallback if stats not initialized
                # GROUP ALL is correct for aggregation
                exp_result = await self.db.query("SELECT count() FROM experience GROUP ALL")
                if exp_result and isinstance(exp_result[0], dict):
                    self.experiences_logged = exp_result[0].get("count", 0)

            insight_result = await self.db.query("SELECT count() FROM insight GROUP ALL")
            if insight_result and isinstance(insight_result[0], dict):
                self.insights_created = insight_result[0].get("count", 0)
        except Exception as e:
            self.logger.warning(f"Could not load statistics: {e}")

        # Initialize temporal chain cache: Load last experience per user
        # This ensures the graph chain continues across server restarts
        try:
            await self._load_last_experiences()
        except Exception as e:
            self.logger.warning(f"Could not load last experiences for temporal chain: {e}")

        self.logger.info(
            f"Learning Engine initialized - "
            f"Experiences: {self.experiences_logged}, Insights: {self.insights_created}"
        )

    async def tick(self) -> None:
        """
        Execute learning engine cycles.
        Check queue frequently (1s) instead of blocking for 60s.
        """
        while True:
            # Process pattern extraction queue
            if self.pattern_extraction_queue and self.llm_layers:
                # Process one batch (up to 5 items)
                batch_size = min(5, len(self.pattern_extraction_queue))
                batch = [self.pattern_extraction_queue.popleft() for _ in range(batch_size)]
                
                if batch:
                    self.logger.debug(f"Processing batch of {len(batch)} items from queue")
                    for experience in batch:
                        await self._process_pattern_extraction(experience)
            
            await asyncio.sleep(1.0)

    # =========================================================================
    # CORE PIPELINE: Pattern & Skill Extraction
    # =========================================================================

    async def _process_pattern_extraction(self, experience: Experience) -> None:
        """
        Router for processing experiences.
        Splits between Skill Compilation (One-Shot) and Behavior Analysis (Pattern).
        """
        try:
            # --- ROUTE A: Direct Fact Learning (God Mode) ---
            if experience.task_type == "direct_instruction":
                await self._process_direct_instruction(experience)
                return

            # --- ROUTE B: Skill/Tool Compilation ---
            if experience.task_type == "instruction" or experience.metadata.get("intent") == "teaching":
                await self._compile_new_skill(experience)
                return
                
            # --- ROUTE C: Behavioral Analysis (The original logic) ---
            await self._analyze_behavioral_patterns(experience)

        except Exception as e:
            self.logger.error(f"❌ Background extraction failed: {e}", exc_info=True)
            # Re-raise so the caller knows it failed
            raise

    async def _process_direct_instruction(self, experience: Experience) -> None:
        """
        Handle 'God Mode' learning.
        Bypasses LLM analysis and writes facts/rules directly to Insight memory.
        """
        try:
            forced_insight = (experience.metadata or {}).get("forced_insight", {}) or {}
            content = forced_insight.get("content") or experience.context.get("source") or experience.context.get("user_query")

            if not content:
                self.logger.warning(
                    f"Direct instruction missing content: {experience.experience_id}"
                )
                return

            insight_data = {
                "content": content,
                "type": forced_insight.get("type", "FACT"),
                "confidence": 1.0,  # Absolute certainty
                "domain": experience.domain,
                "user_id": experience.user_id,
                "source_experiences": [experience.experience_id],
                "emotional_signature": {"trust": 1.0},  # We trust the user explicitly
            }

            insight_id = await self.create_insight(insight_data)
            self.logger.info(f"⚡ Direct instruction memorized: {insight_id}")

        except Exception as e:
            self.logger.error(f"Failed to process direct instruction: {e}", exc_info=True)

    async def _compile_new_skill(self, experience: Experience) -> None:
        """
        Compiles raw user instruction (JSON/Code) into an executable Skill + Triggers.
        """
        self.logger.info(f"Compiling new skill from experience {experience.experience_id}...")
        
        user_input = experience.context.get("user_query", "")
        metadata = experience.metadata or {}
        
        # Check if this is a local tool file ingestion
        is_local_tool = metadata.get("source") == "local_file"
        original_tool_definition = metadata.get("original_tool_definition")
        tool_name = metadata.get("tool_name")
        module_path = metadata.get("module_path_for_execution")
        
        self.logger.debug(f"🔧 _compile_new_skill metadata check: is_local_tool={is_local_tool}, has_definition={original_tool_definition is not None}, tool_name={tool_name}, definition_type={type(original_tool_definition) if original_tool_definition else None}")
        if original_tool_definition:
            self.logger.debug(f"🔧 original_tool_definition keys: {list(original_tool_definition.keys()) if isinstance(original_tool_definition, dict) else 'not a dict'}")
        
        if is_local_tool and original_tool_definition and tool_name:
            # Direct path: Use the original TOOL_DEFINITION from the file
            self.logger.info(f"📦 Compiling local tool '{tool_name}' with original definition")
            
            from aura.engines.learning.skills import SkillTreeManager
            skill_manager = SkillTreeManager()
            
            # Get or create parent "Tools" skill for organization
            tools_parent_id = await self._get_or_create_tools_parent_skill()
            # Ensure it's a string (not RecordID)
            if tools_parent_id and not isinstance(tools_parent_id, str):
                tools_parent_id = str(tools_parent_id)
            
            # Use tool_name as the skill name (normalize to readable format)
            readable_name = tool_name.replace("_", " ").title()
            domain = original_tool_definition.get("domain", "general") if isinstance(original_tool_definition, dict) else "general"
            description = original_tool_definition.get("description", "") if isinstance(original_tool_definition, dict) else ""
            
            # Create the skill with the tool_name (so ingestion can find it)
            # Link it to the parent "Tools" skill
            self.logger.info(f"🔧 Creating skill '{readable_name}' (tool_name: {tool_name}) with parent: {tools_parent_id}")
            try:
                skill_id = await skill_manager.create_skill(
                    name=readable_name,  # Use readable format but we'll also store tool_name
                    domain=domain,
                    parent_skill_id=tools_parent_id,  # Link to parent "Tools" skill
                    # Start curious, unproven competence; can be updated after real usage
                    emotional_signature={"curiosity": 0.8, "competence": 0.0}
                )
                self.logger.info(f"✅ Skill created successfully: {skill_id}")
                
                # CRITICAL: Verify the skill actually exists in the database
                verify_skill = await self.db.select(skill_id)
                if not verify_skill or len(verify_skill) == 0:
                    self.logger.error(f"❌ CRITICAL: Skill {skill_id} was created but not found in database!")
                    raise RuntimeError(f"Skill {skill_id} creation failed - skill not persisted to database")
                else:
                    self.logger.info(f"✅ Verified skill {skill_id} exists in database: {verify_skill[0].get('name')}")
            except Exception as skill_error:
                self.logger.error(f"❌ Failed to create skill '{readable_name}': {skill_error}", exc_info=True)
                raise  # Re-raise so the error is visible
            
            # Update parent skill's sub_skill_ids and create edge relationship
            if tools_parent_id:
                try:
                    parent_skill = await self.db.select(tools_parent_id)
                    if parent_skill and len(parent_skill) > 0:
                        parent_data = parent_skill[0]
                        sub_skill_ids = parent_data.get("sub_skill_ids", [])
                        
                        # Keep sub_skill_ids consistent as strings to avoid RecordID JSON serialization issues.
                        sub_skill_ids_str = [str(sid) for sid in sub_skill_ids]
                        skill_id_str = str(skill_id)
                        
                        if skill_id_str not in sub_skill_ids_str:
                            sub_skill_ids_str.append(skill_id_str)
                            await self.db.merge(
                                tools_parent_id, {"sub_skill_ids": sub_skill_ids_str}
                            )
                            self.logger.debug(f"Added {skill_id} to parent Tools skill's sub_skill_ids")
                        
                        # Create edge relationship for graph traversal
                        try:
                            await self.db.query(
                                "RELATE $parent->skill_contains->$child",
                                {"parent": tools_parent_id, "child": skill_id}
                            )
                            self.logger.debug(f"Created skill_contains edge: {tools_parent_id} -> {skill_id}")
                        except Exception as edge_error:
                            # Non-critical - direct parent_skill_id field still works
                            self.logger.debug(f"Edge creation failed (non-critical): {edge_error}")
                except Exception as e:
                    self.logger.warning(f"Failed to update parent Tools skill: {e}")
            
            # Store the original TOOL_DEFINITION directly
            desc_embedding = await self.embeddings.embed(description)
            
            # Determine risk level based on tool capabilities
            # Local tools are generally low risk, but could be medium if they modify system state
            risk_level = "low"  # Default for local tools (read-only operations like web_search)
            if "delete" in tool_name.lower() or "modify" in tool_name.lower() or "write" in tool_name.lower():
                risk_level = "medium"
            
            # Validate that we have actual data to store
            if not original_tool_definition or (isinstance(original_tool_definition, dict) and len(original_tool_definition) == 0):
                # Fallback: load TOOL_DEFINITION directly from module to avoid empty merges
                try:
                    mod = module_path or f"aura.tools.{tool_name}"
                    import importlib
                    m = importlib.import_module(mod)
                    if hasattr(m, "TOOL_DEFINITION"):
                        original_tool_definition = getattr(m, "TOOL_DEFINITION")
                        self.logger.warning(f"⚠️ original_tool_definition missing/empty; loaded TOOL_DEFINITION from module {mod}")
                    else:
                        self.logger.error(f"❌ original_tool_definition missing and module {mod} has no TOOL_DEFINITION")
                        raise ValueError(f"Cannot compile skill without tool definition")
                except Exception as e:
                    self.logger.error(f"❌ Failed fallback load of TOOL_DEFINITION for {tool_name}: {e}")
                    raise ValueError(f"Cannot compile skill without tool definition")
            
            # Prepare merge data (minimal, tool-specific payload to avoid clobbering other fields)
            # Use execution_config from metadata if provided (supports multi-tool modules with tool_key)
            execution_config = metadata.get("execution_config")
            if not execution_config:
                execution_config = {
                    "module": module_path or f"aura.tools.{tool_name}",
                    "function": "run",
                }
            
            merge_data = {
                "skill_type": "local_function",
                "definition": original_tool_definition,  # Store the original TOOL_DEFINITION JSON schema
                "execution_config": execution_config,
                "risk_level": risk_level,
                "description_embedding": desc_embedding,
                "tool_name": tool_name,
            }
            
            # CRITICAL: Re-check if skill already has definition and execution_config
            # This can happen if ingest_local_tool_module already updated the skill
            # We check RIGHT BEFORE merging to avoid race conditions
            # Add a small delay to give ingest_local_tool_module time to merge if it's going to
            await asyncio.sleep(0.3)  # Give ingest_local_tool_module time to merge (it waits 0.5s between checks)
            
            existing_skill = await self.db.select(skill_id)
            skip_merge = False
            if existing_skill and len(existing_skill) > 0:
                existing_data = existing_skill[0]
                existing_definition = existing_data.get("definition")
                existing_exec_config = existing_data.get("execution_config")
                
                # Check if both fields exist and are non-empty
                has_valid_definition = existing_definition is not None and (
                    (isinstance(existing_definition, dict) and len(existing_definition) > 0) or
                    (not isinstance(existing_definition, dict) and existing_definition)
                )
                has_valid_exec_config = existing_exec_config is not None and (
                    (isinstance(existing_exec_config, dict) and len(existing_exec_config) > 0) or
                    (not isinstance(existing_exec_config, dict) and existing_exec_config)
                )
                
                if has_valid_definition and has_valid_exec_config:
                    self.logger.info(f"✅ Skill {skill_id} already has definition and execution_config - skipping merge to avoid overwriting")
                    # Still continue to generate triggers and edges, but skip the merge
                    skip_merge = True
            
            # Only merge if we need to (skill doesn't already have the data)
            if skip_merge:
                self.logger.info(f"⏭️ Skipping merge for {skill_id} - skill already has definition and execution_config")
            else:
                # Final validation: ensure we have valid data before merging
                if not merge_data.get("definition") or (isinstance(merge_data.get("definition"), dict) and len(merge_data.get("definition")) == 0):
                    self.logger.warning(f"⚠️ Cannot merge - definition is empty. Skill may have been updated by ingest_local_tool_module. Skipping merge.")
                    skip_merge = True
                else:
                    self.logger.info(f"🔧 Merging skill data into {skill_id}: skill_type={merge_data['skill_type']}, module={merge_data['execution_config']['module']}")
                    self.logger.debug(f"🔧 Merge data keys: {list(merge_data.keys())}, definition type: {type(merge_data.get('definition'))}, definition keys: {list(merge_data.get('definition', {}).keys()) if isinstance(merge_data.get('definition'), dict) else 'N/A'}")
                    self.logger.debug(f"🔧 Definition content preview: {str(original_tool_definition)[:200] if original_tool_definition else 'NONE'}")
            
            try:
                # Hard guard: do not write empty payloads
                if not skip_merge:
                    def_val = merge_data.get("definition")
                    exec_val = merge_data.get("execution_config")
                    def_empty = def_val is None or (isinstance(def_val, dict) and len(def_val) == 0)
                    exec_empty = exec_val is None or (isinstance(exec_val, dict) and len(exec_val) == 0)
                    if def_empty or exec_empty:
                        self.logger.error(
                            f"❌ Abort skill write: empty definition/exec_config for {skill_id}. def_empty={def_empty}, exec_empty={exec_empty}"
                        )
                        raise RuntimeError("Refusing to write skill with empty definition/execution_config")

                    # Log payload size and current state before write
                    self.logger.debug(f"[DB WRITE] skill={skill_id} payload keys={list(merge_data.keys())} def_len={(len(def_val) if isinstance(def_val, dict) else 'N/A')} exec_len={(len(exec_val) if isinstance(exec_val, dict) else 'N/A')}")
                    pre_state = await self.db.select(skill_id)
                    if pre_state and len(pre_state) > 0:
                        ps = pre_state[0]
                        self.logger.debug(f"[DB BEFORE] skill={skill_id} has_def={(ps.get('definition') is not None)} has_exec={(ps.get('execution_config') is not None)} def_len={(len(ps.get('definition')) if isinstance(ps.get('definition'), dict) else 'N/A')} exec_len={(len(ps.get('execution_config')) if isinstance(ps.get('execution_config'), dict) else 'N/A')}")

                if skip_merge:
                    # Skip the merge, but still verify the skill has the data
                    merge_result = None
                else:
                    # Use MERGE (non-destructive). UPDATE in Surreal's Python client can behave like a record replace,
                    # which is how we end up with empty / missing fields when the payload isn't complete.
                    merge_result = await self.db.merge(skill_id, merge_data)
                
                # CRITICAL: Check if merge_result is an error string (only if we actually merged/updated)
                if merge_result is not None:
                    # SurrealDB returns error messages as strings when validation fails
                    if isinstance(merge_result, str):
                        error_indicators = ["error", "failed", "must conform", "assert", "found", "but field"]
                        if any(indicator in merge_result.lower() for indicator in error_indicators):
                            self.logger.error(f"❌ Merge returned error string: {merge_result}")
                            raise RuntimeError(f"Database merge failed: {merge_result}")
                    
                    from aura.logging_config import sanitize_log_payload
                    self.logger.info(f"✅ Merge call completed. Result type: {type(merge_result)}, value: {sanitize_log_payload(merge_result)}")
                    # Longer delay to ensure SurrealDB commits the merge and any concurrent operations complete
                    await asyncio.sleep(0.5)
                elif skip_merge:
                    # If we skipped merge, still wait a bit for ingest_local_tool_module to finish if it's running
                    await asyncio.sleep(0.3)
                
                # Verify the skill was updated correctly (with retry in case of timing issues)
                verify_skill = None
                for retry in range(3):
                    verify_skill = await self.db.select(skill_id)
                    if verify_skill and len(verify_skill) > 0:
                        verified_data = verify_skill[0]
                        # Check if we have the data we need
                        if verified_data.get("definition") and verified_data.get("execution_config"):
                            break
                    if retry < 2:  # Don't sleep on last attempt
                        await asyncio.sleep(0.2)
                if verify_skill and len(verify_skill) > 0:
                    verified_data = verify_skill[0]
                    self.logger.debug(f"🔧 Verified skill data keys: {list(verified_data.keys())}")
                    
                    # Check if fields exist AND have actual content (not empty dicts)
                    definition_val = verified_data.get("definition")
                    exec_config_val = verified_data.get("execution_config")
                    has_definition = definition_val is not None and (
                        (isinstance(definition_val, dict) and len(definition_val) > 0) or
                        (not isinstance(definition_val, dict) and definition_val)
                    )
                    has_exec_config = exec_config_val is not None and (
                        (isinstance(exec_config_val, dict) and len(exec_config_val) > 0) or
                        (not isinstance(exec_config_val, dict) and exec_config_val)
                    )
                    has_tool_name = verified_data.get("tool_name") is not None
                    skill_type_actual = verified_data.get("skill_type")
                    
                    self.logger.info(
                        f"✅ Skill verification: definition={has_definition} (type: {type(definition_val)}, len: {len(definition_val) if isinstance(definition_val, dict) else 'N/A'}), "
                        f"execution_config={has_exec_config} (type: {type(exec_config_val)}, len: {len(exec_config_val) if isinstance(exec_config_val, dict) else 'N/A'}), "
                        f"tool_name={has_tool_name}, skill_type={skill_type_actual}"
                    )
                    
                    # Recovery path: if verification failed but we have good merge_data, force a second merge once
                    if (not has_definition or not has_exec_config or skill_type_actual != "local_function") and not skip_merge:
                        if merge_data.get("definition") and merge_data.get("execution_config"):
                            self.logger.warning("⚠️ Verification failed after merge; attempting forced re-merge with full data")
                            try:
                                await self.db.merge(skill_id, merge_data)
                                await asyncio.sleep(0.5)
                                verify_retry = await self.db.select(skill_id)
                                if verify_retry and len(verify_retry) > 0:
                                    vd = verify_retry[0]
                                    def_ok = vd.get("definition") and (not isinstance(vd.get("definition"), dict) or len(vd.get("definition")) > 0)
                                    exec_ok = vd.get("execution_config") and (not isinstance(vd.get("execution_config"), dict) or len(vd.get("execution_config")) > 0)
                                    tool_ok = vd.get("tool_name") is not None
                                    type_ok = vd.get("skill_type") == "local_function"
                                    if def_ok and exec_ok and tool_ok and type_ok:
                                        self.logger.info("✅ Forced re-merge succeeded; verification passed after retry")
                                        has_definition, has_exec_config, has_tool_name, skill_type_actual = def_ok, exec_ok, tool_ok, vd.get("skill_type")
                                        verified_data = vd
                                    else:
                                        self.logger.warning(f"⚠️ Forced re-merge retry still missing fields: def={def_ok}, exec={exec_ok}, tool={tool_ok}, type={vd.get('skill_type')}")
                                else:
                                    self.logger.warning("⚠️ Forced re-merge retry could not load skill for verification")
                            except Exception as force_err:
                                self.logger.error(f"❌ Forced re-merge during verification failed: {force_err}", exc_info=True)
                    
                    if not has_definition or not has_exec_config or skill_type_actual != "local_function":
                        self.logger.error(f"❌ Skill merge failed - missing critical fields or wrong type!")
                        self.logger.error(f"❌ Expected: skill_type=local_function, definition=non-empty dict, exec_config=non-empty dict, tool_name=string")
                        self.logger.error(f"❌ Actual: skill_type={skill_type_actual}, definition={has_definition} (value: {definition_val}), exec_config={has_exec_config} (value: {exec_config_val}), tool_name={has_tool_name}")
                        self.logger.error(f"❌ Actual skill data: {verified_data}")
                        raise RuntimeError(f"Skill merge verification failed - data not stored correctly")
                else:
                    self.logger.error(f"❌ Skill {skill_id} not found after merge!")
                    raise RuntimeError(f"Skill {skill_id} not found after merge")
            except Exception as merge_error:
                self.logger.error(f"❌ Failed to merge skill data into {skill_id}: {merge_error}", exc_info=True)
                raise
            
            # Generate triggers and embeddings in the background (fire and forget)
            # This allows the tool to be available immediately while triggers are generated
            self._add_background_task(
                self._generate_triggers_background(skill_id, tool_name, description),
                task_name=f"triggers:{tool_name}"
            )
            
            # Create insight (also in background to not block)
            self._add_background_task(
                self._create_skill_insight_background(
                    readable_name, description, domain, experience.user_id, experience.experience_id
                ),
                task_name=f"insight:{tool_name}"
            )
            
            # Final verification: Check that skill exists and has all required fields
            final_check = await self.db.select(skill_id)
            if final_check and len(final_check) > 0:
                final_data = final_check[0]
                has_definition = final_data.get("definition") is not None
                has_exec_config = final_data.get("execution_config") is not None
                has_tool_name = final_data.get("tool_name") is not None
                skill_type = final_data.get("skill_type")
                
                if has_definition and has_exec_config and has_tool_name and skill_type == "local_function":
                    self.logger.info(f"✅ SKILL COMPILED: {tool_name} (ID: {skill_id}) - All fields verified")
                else:
                    self.logger.error(
                        f"❌ SKILL COMPILATION INCOMPLETE: {tool_name} (ID: {skill_id}) - "
                        f"definition={has_definition}, exec_config={has_exec_config}, "
                        f"tool_name={has_tool_name}, skill_type={skill_type}"
                    )
            else:
                self.logger.error(f"❌ CRITICAL: Skill {skill_id} not found in database after compilation!")
            
            return
    
    async def _generate_triggers_background(self, skill_id: str, tool_name: str, description: str) -> None:
        """
        Generate semantic triggers and embeddings in the background.
        This allows the tool to be available immediately while triggers are generated.
        """
        try:
            if not self.llm_layers or not self.embeddings:
                self.logger.warning(f"[Background] Skipping trigger generation for {tool_name} - dependencies not ready")
                return

            self.logger.info(f"🔗 [Background] Generating semantic triggers for {tool_name}...")
            
            # Generate triggers using LLM
            prompt = f"""
            Generate 10-15 natural language phrases users might say to invoke this tool.
            
            Tool Name: {tool_name}
            Description: {description}
            
            Return ONLY a JSON array of trigger phrases, no other text:
            ["phrase 1", "phrase 2", ...]
            """
            
            triggers = []
            try:
                triggers_result = await self.llm_layers.l5_structure_analysis(
                    prompt=prompt,
                    system_instruction="You are a trigger phrase generator. Return only a JSON array of strings.",
                    # Use L5 model for structured output / JSON extraction.
                    # Passing the L2 model here disables L5 fallback routing and has proven flaky for triggers.
                    model=None,
                )
                
                # Handle different response formats
                if isinstance(triggers_result, list):
                    triggers = triggers_result
                elif isinstance(triggers_result, dict):
                    # Try various possible keys
                    if "triggers" in triggers_result:
                        triggers = triggers_result["triggers"]
                    elif "trigger_phrases" in triggers_result:
                        triggers = triggers_result["trigger_phrases"]
                    elif "phrases" in triggers_result:
                        triggers = triggers_result["phrases"]
                    elif "result" in triggers_result:
                        triggers = triggers_result["result"] if isinstance(triggers_result["result"], list) else []
                    else:
                        self.logger.warning(
                            f"Unexpected trigger format: dict with keys {list(triggers_result.keys())}. "
                            f"Expected 'triggers', 'trigger_phrases', 'phrases', or 'result'"
                        )
                        triggers = []
                else:
                    self.logger.warning(f"Unexpected trigger format: {type(triggers_result)}")
                    triggers = []
                    
                # Validate triggers are strings
                triggers = [t for t in triggers if isinstance(t, str)][:15]
                
            except Exception as e:
                self.logger.warning(f"Failed to generate triggers: {e}, using defaults")
                triggers = []

            # Ensure we always have 15 triggers even if the LLM returns empty / invalid output.
            if not triggers:
                base = tool_name.replace("_", " ").strip()
                triggers = [
                    f"use {tool_name}",
                    f"use {base}",
                    f"run {tool_name}",
                    f"run {base}",
                    f"search the web for {base}",
                    f"web search: {base}",
                    "search the web for",
                    "search online for",
                    "look up",
                    "find information about",
                    "get the latest on",
                    "what's the latest about",
                    "check current info on",
                    "find current events about",
                    "look up documentation for",
                ]
                self.logger.info(f"⚠️ [Background] Using fallback triggers for {tool_name} ({len(triggers)}): {triggers}")
            elif len(triggers) < 15:
                # Top up with deterministic phrases (deduped) to reach 15.
                base = tool_name.replace("_", " ").strip()
                fallback_pool = [
                    f"use {tool_name}",
                    f"use {base}",
                    f"run {tool_name}",
                    f"run {base}",
                    "search the web for",
                    "search online for",
                    "look up",
                    "find information about",
                    "get the latest on",
                    "check current info on",
                    "look up documentation for",
                ]
                seen = set()
                normalized: list[str] = []
                for t in triggers:
                    if not isinstance(t, str):
                        continue
                    key = t.strip().lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    normalized.append(t.strip())
                for t in fallback_pool:
                    if len(normalized) >= 15:
                        break
                    key = t.strip().lower()
                    if key and key not in seen:
                        seen.add(key)
                        normalized.append(t.strip())
                triggers = normalized[:15]
            
            # Create semantic triggers with embeddings
            if triggers:
                self.logger.info(f"🔗 [Background] Generating embeddings for {len(triggers)} semantic triggers for {tool_name}...")
                created_count = 0
                sem = asyncio.Semaphore(4)
                # Surreal schema expects record<skill> for semantic_trigger.target_action.
                # Passing a plain string can fail schema validation (and Surreal may return an error string).
                skill_ref: object = skill_id
                try:
                    from surrealdb import RecordID
                    if isinstance(skill_id, str) and ":" in skill_id:
                        table, rid = skill_id.split(":", 1)
                        skill_ref = RecordID(table, rid)
                except Exception:
                    skill_ref = skill_id

                async def process_trigger(idx: int, phrase: str) -> None:
                    nonlocal created_count
                    try:
                        async with sem:
                            self.logger.debug(f"   [Background] Embedding trigger {idx}/{len(triggers)}: '{phrase}'")
                            vec = await self.embeddings.embed(phrase)
                        trigger_data = {
                            "phrase": phrase,
                            "embedding": vec,
                            "target_action": skill_ref,
                            "confidence": 1.0
                        }
                        trigger_record = await self.db.create("semantic_trigger", trigger_data)
                        # Surreal sometimes returns error messages as strings on schema violations.
                        if isinstance(trigger_record, str):
                            err_lower = trigger_record.lower()
                            if any(x in err_lower for x in ["error", "failed", "found", "expected", "assert"]):
                                raise RuntimeError(f"semantic_trigger create failed: {trigger_record}")
                        created_count += 1

                        trigger_id = None
                        try:
                            if isinstance(trigger_record, list) and trigger_record:
                                record = trigger_record[0]
                                trigger_id = record.get("id") if isinstance(record, dict) else str(record)
                            elif isinstance(trigger_record, dict):
                                trigger_id = trigger_record.get("id")
                            else:
                                trigger_id = str(trigger_record) if trigger_record else None

                            if trigger_id:
                                await self.db.query(
                                    "RELATE $trigger->triggers_skill->$skill",
                                    {"trigger": trigger_id, "skill": skill_id}
                                )
                                self.logger.debug(f"   [Background] ✅ Created trigger edge: {trigger_id} -> {skill_id}")
                        except Exception as edge_error:
                            self.logger.debug(f"   [Background] ⚠️  Edge creation failed (non-critical): {edge_error}")

                        self.logger.debug(f"   [Background] ✅ Created trigger: '{phrase}'")
                    except Exception as e:
                        self.logger.warning(f"   [Background] ❌ Failed to create trigger '{phrase}': {e}")

                await asyncio.gather(*(process_trigger(i, phrase) for i, phrase in enumerate(triggers, 1)))
                self.logger.info(f"✅ [Background] Created {created_count}/{len(triggers)} semantic triggers for {tool_name}")
            else:
                self.logger.warning(f"⚠️ [Background] No triggers generated for {tool_name}")
        except Exception as e:
            self.logger.error(f"❌ [Background] Failed to generate triggers for {tool_name}: {e}", exc_info=True)
    
    async def _create_skill_insight_background(self, readable_name: str, description: str, domain: str, user_id: str | None, experience_id: str | None) -> None:
        """Create insight for the skill in the background."""
        try:
            insight_data = {
                "content": f"To use {readable_name}: {description}",
                "type": "SKILL_MANUAL",
                "domain": domain,
                "confidence": 1.0,
                "user_id": user_id or "system",
                "source_experiences": [experience_id] if experience_id else []
            }
            await self.create_insight(insight_data)
            self.logger.debug(f"[Background] Created insight for skill: {readable_name}")
        except Exception as e:
            self.logger.warning(f"[Background] Failed to create insight for {readable_name}: {e}")
    
    async def _get_or_create_tools_parent_skill(self) -> str | None:
        """
        Get or create the parent "Tools" skill to organize all tool skills.
        
        Returns:
            The skill_id of the "Tools" parent skill, or None if creation fails
        """
        try:
            # Try to find existing "Tools" skill
            tools_skills = await self.db.query(
                "SELECT id FROM skill WHERE name = 'Tools' AND skill_type = 'abstract' LIMIT 1"
            )
            
            if tools_skills and len(tools_skills) > 0:
                tools_id = tools_skills[0].get("id")
                # Convert RecordID to string if needed
                if tools_id and not isinstance(tools_id, str):
                    tools_id = str(tools_id)
                self.logger.debug(f"Found existing Tools parent skill: {tools_id}")
                return tools_id
            
            # Create new "Tools" parent skill
            from aura.engines.learning.skills import SkillTreeManager
            skill_manager = SkillTreeManager()
            
            tools_id = await skill_manager.create_skill(
                name="Tools",
                domain="system",
                emotional_signature={"competence": 0.9, "curiosity": 0.7}
            )
            
            # Mark it as abstract parent skill
            await self.db.merge(tools_id, {
                "skill_type": "abstract",
                "description": "Parent skill for organizing all executable tools and functions"
            })
            
            self.logger.info(f"Created Tools parent skill: {tools_id}")
            return tools_id
            
        except Exception as e:
            self.logger.warning(f"Failed to get or create Tools parent skill: {e}")
            return None
        
        # Original path: Parse from instruction text (for non-local tools)
        # 1. The L4 "Architect" Prompt
        # We use the L2 model (smart) via the L5 structure layer
        prompt = f"""
        You are the Aura Cognitive Architect. The user has provided a Tool Definition, MCP Schema, or Instruction.
        
        INPUT CONTEXT:
        {user_input}
        
        YOUR GOAL:
        1. Extract the JSON Schema / Tool Definition / Rule.
        2. Generate 'Synthetic Triggers' (10+ phrases users might say to invoke this).
        3. Identify Constraints & Risks.
        
        OUTPUT JSON:
        {{
            "skill_name": "short_snake_case_name",
            "readable_name": "Human Readable Name",
            "domain": "coding/finance/etc",
            "description": "What this tool does",
            "tool_definition": {{ ... extracted json schema ... }},
            "execution_config": {{ "type": "mcp", "requires_auth": true/false }},
            "triggers": ["phrase 1", "phrase 2", "phrase 3"],
            "risk_level": "low/medium/high", 
            "operational_insight": "One sentence rule on how to use this correctly"
        }}
        """

        result = await self.llm_layers.l5_structure_analysis(
            prompt=prompt, 
            system_instruction="Skill Compiler",
            model=self.llm_layers.l2_model  # Use the smart model
        )
        
        if not result:
            self.logger.error("Failed to compile skill: LLM returned no structure")
            return

        # 2. Lazy Import Skill Manager
        from aura.engines.learning.skills import SkillTreeManager
        skill_manager = SkillTreeManager()
        
        # 3. Create the Base Skill Node
        skill_id = await skill_manager.create_skill(
            name=result.get("readable_name", result.get("skill_name")),
            domain=result.get("domain", "general"),
            emotional_signature={"curiosity": 0.8, "competence": 0.5} 
        )
        
        # 4. Save the Definition, Config, & Embeddings to SurrealDB
        # We need to embed the description for Semantic Search
        desc_embedding = await self.embeddings.embed(result.get("description", ""))
        
        await self.db.merge(skill_id, {
            "skill_type": "mcp_tool",
            "definition": result.get("tool_definition"),
            "execution_config": result.get("execution_config"),
            "risk_level": result.get("risk_level", "low"),
            "description_embedding": desc_embedding
        })
        
        # 5. Populate Semantic Triggers & insight in the background (non-blocking)
        tool_name = result.get("skill_name") or result.get("readable_name") or "tool"
        description = result.get("description", "")
        domain = result.get("domain", "general")
        self._add_background_task(
            self._generate_triggers_background(skill_id, tool_name, description),
            task_name=f"triggers:{tool_name}"
        )
        self._add_background_task(
            self._create_skill_insight_background(result.get("readable_name", tool_name), description, domain, experience.user_id, experience.experience_id),
            task_name=f"insight:{tool_name}"
        )
        
        self.logger.info(f"✅ SKILL COMPILED: {tool_name} (ID: {skill_id}) - triggers/insight generating in background")

    async def ingest_local_tool_module(self, module_name: str) -> str:
        """
        Dynamically imports a local Python file from src/aura/tools/
        and learns it as a skill.
        
        Supports two patterns:
        1. Single tool: TOOL_DEFINITION constant + run() function
        2. Multiple tools: TOOLS dict with {"name": {"definition": ..., "run": ...}}
        """
        import importlib.util
        import os
        
        try:
            # 1. Dynamic Import
            current_file_dir = os.path.dirname(os.path.abspath(__file__))
            aura_root = os.path.dirname(os.path.dirname(current_file_dir))
            tools_dir = os.path.join(aura_root, "tools")
            file_path = os.path.join(tools_dir, f"{module_name}.py")
            
            if not os.path.exists(file_path):
                raise ValueError(f"Tool module file not found: {file_path}")
            
            spec = importlib.util.spec_from_file_location(
                f"aura.tools.{module_name}", 
                file_path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            # 2. Detect pattern: TOOLS dict (multi) or TOOL_DEFINITION (single)
            if hasattr(module, "TOOLS"):
                # Multiple tools pattern
                tools_dict = module.TOOLS
                if not isinstance(tools_dict, dict):
                    raise ValueError(f"TOOLS must be a dict, got {type(tools_dict)}")
                
                ingested_count = 0
                for tool_name, tool_spec in tools_dict.items():
                    if not isinstance(tool_spec, dict):
                        self.logger.warning(f"Skipping invalid tool spec for {tool_name}")
                        continue
                    
                    schema = tool_spec.get("definition")
                    run_func = tool_spec.get("run")
                    
                    if not schema or not run_func:
                        self.logger.warning(f"Tool {tool_name} missing definition or run function")
                        continue
                    
                    # Ingest this tool
                    await self._ingest_single_tool(
                        tool_name=tool_name,
                        schema=schema,
                        module_path=f"aura.tools.{module_name}",
                        is_multi_tool=True  # Flag for later reference
                    )
                    ingested_count += 1
                
                return f"Successfully imported {ingested_count} tools from module: {module_name}"
            
            elif hasattr(module, "TOOL_DEFINITION"):
                # Single tool pattern (existing behavior)
                schema = module.TOOL_DEFINITION
                
                if not isinstance(schema, dict) or "name" not in schema:
                    raise ValueError(f"TOOL_DEFINITION must be a dict with 'name' field")
                
                tool_name = schema.get("name")
                
                # Ingest single tool
                await self._ingest_single_tool(
                    tool_name=tool_name,
                    schema=schema,
                    module_path=f"aura.tools.{module_name}",
                    is_multi_tool=False
                )
                
                return f"Successfully imported tool: {tool_name}"
            
            else:
                raise ValueError(
                    f"Module {module_name} must export either TOOLS dict or TOOL_DEFINITION constant"
                )
        
        except Exception as e:
            self.logger.error(f"Failed to ingest local tool module '{module_name}': {e}", exc_info=True)
            raise

    async def _ingest_single_tool(
        self, 
        tool_name: str, 
        schema: dict, 
        module_path: str,
        is_multi_tool: bool = False
    ) -> str:
        """
        Internal helper to ingest a single tool into the skill tree.
        
        Args:
            tool_name: Name of the tool
            schema: TOOL_DEFINITION dict
            module_path: Python module path (e.g., "aura.tools.filesystem")
            is_multi_tool: True if this tool is part of a multi-tool module
        
        Returns:
            skill_id
        """
        description = schema.get("description", "")
        
        # Check if skill already exists
        normalized_tool_name = tool_name.replace("_", " ").lower()
        existing_skills = await self.db.query(
            """
            SELECT id FROM skill 
            WHERE string::lowercase(name) = string::lowercase($name) 
               OR string::lowercase(string::replace(name, '_', ' ')) = $normalized
               OR tool_name = $name
            LIMIT 1
            """,
            {"name": tool_name, "normalized": normalized_tool_name}
        )
        
        if existing_skills and len(existing_skills) > 0:
            # Update existing skill
            skill_id = existing_skills[0].get("id")
            self.logger.info(f"📝 Updating existing skill {skill_id} with tool definition")
            
            desc_embedding = await self.embeddings.embed(description)
            tools_parent_id = await self._get_or_create_tools_parent_skill()
            if tools_parent_id and not isinstance(tools_parent_id, str):
                tools_parent_id = str(tools_parent_id)
            
            # For multi-tool modules, store the tool-specific function name
            execution_config = {
                "module": module_path,
                "function": "run"
            }
            
            if is_multi_tool:
                # Store reference to the specific tool within TOOLS dict
                execution_config["tool_key"] = tool_name
            
            update_data = {
                "skill_type": "local_function",
                "definition": schema,
                "execution_config": execution_config,
                "tool_name": tool_name,
                "risk_level": "low",
                "description_embedding": desc_embedding
            }
            
            # Link to Tools parent if needed
            if tools_parent_id:
                skill_data = await self.db.select(skill_id)
                if skill_data and len(skill_data) > 0:
                    existing_parent = skill_data[0].get("parent_skill_id")
                    if existing_parent and not isinstance(existing_parent, str):
                        existing_parent = str(existing_parent)
                    if not existing_parent or existing_parent != tools_parent_id:
                        update_data["parent_skill_id"] = tools_parent_id
                        # Also update parent's sub_skill_ids
                        try:
                            parent_skill = await self.db.select(tools_parent_id)
                            if parent_skill and len(parent_skill) > 0:
                                parent_data = parent_skill[0]
                                sub_skill_ids = parent_data.get("sub_skill_ids", [])
                                
                                sub_skill_ids_str = [str(sid) for sid in sub_skill_ids]
                                skill_id_str = str(skill_id)
                                
                                if skill_id_str not in sub_skill_ids_str:
                                    sub_skill_ids_str.append(skill_id_str)
                                    await self.db.merge(
                                        tools_parent_id, {"sub_skill_ids": sub_skill_ids_str}
                                    )
                                
                                try:
                                    await self.db.query(
                                        "RELATE $parent->skill_contains->$child",
                                        {"parent": tools_parent_id, "child": skill_id}
                                    )
                                    self.logger.debug(f"Created skill_contains edge: {tools_parent_id} -> {skill_id}")
                                except Exception as edge_error:
                                    self.logger.debug(f"Edge creation failed (non-critical): {edge_error}")
                        except Exception as e:
                            self.logger.warning(f"Failed to update Tools parent skill: {e}")
            
            await self.db.merge(skill_id, update_data)
            
            # Regenerate triggers
            self._add_background_task(
                self._generate_triggers_background(skill_id, tool_name, description),
                task_name=f"triggers:{tool_name}:update"
            )
            self._add_background_task(
                self._create_skill_insight_background(tool_name, description, schema.get("domain", "general"), "system", None),
                task_name=f"insight:{tool_name}:update"
            )
            
            return str(skill_id)
        
        else:
            # Create new skill via experience pipeline
            self.logger.info(f"🆕 Creating new skill for tool '{tool_name}' via experience pipeline")
            
            instruction_text = (
                f"Learn this local tool. Name: {tool_name}. "
                f"Description: {description}. "
                f"Schema: {json.dumps(schema.get('parameters', {}), indent=2)}"
            )
            
            tool_domain = schema.get("domain", "general") if isinstance(schema, dict) else "general"
            
            # For multi-tool modules, create execution config with tool_key
            execution_config = {
                "module": module_path,
                "function": "run"
            }
            
            if is_multi_tool:
                execution_config["tool_key"] = tool_name
            
            experience_id = await self.log_experience({
                "user_id": "system",
                "task_type": "instruction",
                "domain": tool_domain,
                "context": {"user_query": instruction_text},
                "metadata": {
                    "intent": "teaching",
                    "source": "local_file",
                    "tool_name": tool_name,
                    "original_tool_definition": schema,
                    "module_path_for_execution": module_path,
                    "execution_config": execution_config,
                    "is_multi_tool": is_multi_tool
                }
            })
            
            # Wait for skill creation
            import asyncio
            max_attempts = 10
            skill_id = None
            
            for attempt in range(max_attempts):
                await asyncio.sleep(0.5)
                
                skills = await self.db.query(
                    """
                    SELECT id FROM skill 
                    WHERE string::lowercase(name) = string::lowercase($name) 
                       OR string::lowercase(string::replace(name, '_', ' ')) = $normalized
                       OR tool_name = $name
                    LIMIT 1
                    """,
                    {"name": tool_name, "normalized": normalized_tool_name}
                )
                
                if skills and len(skills) > 0:
                    skill_id = skills[0].get("id")
                    break
            
            if skill_id:
                # Ensure execution config is set correctly for multi-tool
                merge_data = {
                    "skill_type": "local_function",
                    "definition": schema,
                    "execution_config": execution_config,
                    "tool_name": tool_name
                }
                
                await self.db.merge(skill_id, merge_data)
                
                # Verify the merge worked
                await asyncio.sleep(0.1)
                verify = await self.db.select(skill_id)
                if verify and len(verify) > 0:
                    verified = verify[0]
                    definition_val = verified.get("definition")
                    exec_config_val = verified.get("execution_config")
                    has_def = definition_val is not None and (
                        (isinstance(definition_val, dict) and len(definition_val) > 0) or
                        (not isinstance(definition_val, dict) and definition_val)
                    )
                    has_exec = exec_config_val is not None and (
                        (isinstance(exec_config_val, dict) and len(exec_config_val) > 0) or
                        (not isinstance(exec_config_val, dict) and exec_config_val)
                    )
                    has_tool = verified.get("tool_name") is not None
                    self.logger.info(
                        f"✅ Ingest merge verification: definition={has_def}, "
                        f"exec_config={has_exec}, tool_name={has_tool}"
                    )
                    if not has_def or not has_exec:
                        raise RuntimeError(
                            f"Ingest merge wrote empty definition/execution_config for skill {skill_id}. "
                            f"definition={definition_val} execution_config={exec_config_val}"
                        )
                
                self.logger.info(
                    f"✅ Local tool '{tool_name}' registered as skill {skill_id} "
                    f"(multi_tool: {is_multi_tool})"
                )
                return str(skill_id)
            else:
                self.logger.warning(
                    f"Tool '{tool_name}' was learned but skill record not found"
                )
                return ""

    # =========================================================================
    # MCP INGESTION
    # =========================================================================

    def _map_mcp_input_schema_to_tool_definition(
        self, *, name: str, description: str, input_schema: dict[str, Any] | None
    ) -> dict[str, Any]:
        """
        Map MCP Tool.{name, description, inputSchema} to Aura's TOOL_DEFINITION format.

        Aura's internal TOOL_DEFINITION convention (see local tools) is:
        {
          "name": "...",
          "description": "...",
          "parameters": {JSON Schema object}
        }
        """
        schema = input_schema or {}
        if not isinstance(schema, dict) or not schema:
            schema = {"type": "object", "properties": {}}
        return {
            "name": name,
            "description": description or "",
            "parameters": schema,
        }

    async def ingest_mcp_server(self, server_name: str, connection_config: dict[str, Any]) -> str:
        """
        Connect to an MCP server, discover its tools, and ingest them as Skills.

        Notes:
        - Skills persist in the DB even if the server goes down.
        - Runtime connectivity is handled by ToolExecutor (returns "offline" when unavailable).
        """
        from aura.connections.mcp_client import MCPClientError, get_mcp_connection_manager
        from aura.engines.learning.skills import SkillTreeManager

        if not server_name:
            raise ValueError("server_name is required")

        mgr = await get_mcp_connection_manager()

        try:
            client = await mgr.connect(server_name, connection_config)
            tools = await client.discover_tools()
        except MCPClientError as e:
            self.logger.error(f"❌ MCP connect/discover failed for '{server_name}': {e}")
            raise

        if not tools:
            return f"MCP server '{server_name}' connected, but returned 0 tools."

        tools_parent_id = await self._get_or_create_tools_parent_skill()
        if tools_parent_id and not isinstance(tools_parent_id, str):
            tools_parent_id = str(tools_parent_id)

        skill_manager = SkillTreeManager()
        ingested = 0
        updated = 0

        for tool in tools:
            tool_name = str(tool.get("name") or "").strip()
            description = str(tool.get("description") or "")
            input_schema = tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else None
            if not tool_name:
                continue

            tool_definition = self._map_mcp_input_schema_to_tool_definition(
                name=tool_name, description=description, input_schema=input_schema
            )

            # Risk heuristic
            risk_level = "low"
            lower = tool_name.lower()
            if any(k in lower for k in ["delete", "remove", "write", "update", "create", "exec", "run", "shell"]):
                risk_level = "medium"

            normalized_tool_name = tool_name.replace("_", " ").lower()
            existing = await self.db.query(
                """
                SELECT id FROM skill
                WHERE tool_name = $tool
                   OR string::lowercase(name) = string::lowercase($tool)
                   OR string::lowercase(string::replace(name, '_', ' ')) = $normalized
                LIMIT 1
                """,
                {"tool": tool_name, "normalized": normalized_tool_name},
            )

            readable_name = tool_name.replace("_", " ").title()
            if existing and len(existing) > 0:
                skill_id = existing[0].get("id")
                if skill_id and not isinstance(skill_id, str):
                    skill_id = str(skill_id)
                updated += 1
            else:
                skill_id = await skill_manager.create_skill(
                    name=readable_name,
                    domain="system",
                    parent_skill_id=tools_parent_id,
                    emotional_signature={"curiosity": 0.8, "competence": 0.0},
                )
                ingested += 1

                # Parent bookkeeping (non-critical)
                if tools_parent_id:
                    try:
                        parent_skill = await self.db.select(tools_parent_id)
                        if parent_skill and len(parent_skill) > 0:
                            parent_data = parent_skill[0]
                            sub_skill_ids = [str(sid) for sid in (parent_data.get("sub_skill_ids", []) or [])]
                            if str(skill_id) not in sub_skill_ids:
                                sub_skill_ids.append(str(skill_id))
                                await self.db.merge(tools_parent_id, {"sub_skill_ids": sub_skill_ids})
                            await self.db.query(
                                "RELATE $parent->skill_contains->$child",
                                {"parent": tools_parent_id, "child": str(skill_id)},
                            )
                    except Exception as e:
                        self.logger.debug(f"Non-critical Tools parent update failed for MCP tool '{tool_name}': {e}")

            desc_embedding = await self.embeddings.embed(description)

            # Tagging requested by spec: store metadata inside execution_config (skill table is schemafull).
            execution_config = {
                "type": "mcp",
                "source": "mcp",
                "server": server_name,
                "transport": connection_config.get("transport") or connection_config.get("type") or "stdio",
                "connection": dict(connection_config),
                "status": "online",
            }

            await self.db.merge(
                str(skill_id),
                {
                    "skill_type": "mcp_tool",
                    "definition": tool_definition,
                    "execution_config": execution_config,
                    "risk_level": risk_level,
                    "description_embedding": desc_embedding,
                    "tool_name": tool_name,
                },
            )

            self._add_background_task(
                self._generate_triggers_background(str(skill_id), tool_name, description),
                task_name=f"triggers:mcp:{server_name}:{tool_name}",
            )
            self._add_background_task(
                self._create_skill_insight_background(readable_name, description, "system", "system", None),
                task_name=f"insight:mcp:{server_name}:{tool_name}",
            )

        return (
            f"MCP server '{server_name}' connected. "
            f"Ingested {ingested} new tool(s), updated {updated} existing tool(s)."
        )

    async def _analyze_behavioral_patterns(self, experience: Experience) -> None:
        """Original logic: analyze similar experiences to find patterns.
        
        Session 7 upgrade: Stratified temporal sampling.
        Instead of a static LIMIT 5, we sample from different time buckets
        to maximize diversity and reduce redundant insight extraction.
        """
        try:
            # --- SESSION 7 FIX: Stratified temporal sampling ---
            # Count existing insights for this domain to determine window size
            domain_insight_count = 0
            try:
                count_result = await self.db.query(
                    """
                    SELECT count() FROM insight
                    WHERE domain = $domain AND user_id = $user_id AND deprecated = false
                    GROUP ALL
                    """,
                    {"domain": experience.domain, "user_id": experience.user_id}
                )
                if count_result and isinstance(count_result[0], dict):
                    domain_insight_count = count_result[0].get("count", 0)
            except Exception:
                pass

            # Expand window logarithmically as insights accumulate
            import math
            window_size = min(20, 5 + int(2 * math.log(1 + domain_insight_count)))

            # Stratified sampling: recent (50%), mid-range (30%), oldest (20%)
            recent_limit = max(2, int(window_size * 0.5))
            mid_limit = max(1, int(window_size * 0.3))
            old_limit = max(1, window_size - recent_limit - mid_limit)

            # Fetch recent experiences (highest temporal relevance)
            recent = await self.db.query(
                """
                SELECT * FROM experience
                WHERE domain = $domain AND task_type = $task_type AND user_id = $user_id
                ORDER BY timestamp DESC
                LIMIT $lim
                """,
                {"domain": experience.domain, "task_type": experience.task_type,
                 "user_id": experience.user_id, "lim": recent_limit}
            ) or []

            # Fetch mid-range experiences (skip the recent ones)
            mid = await self.db.query(
                """
                SELECT * FROM experience
                WHERE domain = $domain AND task_type = $task_type AND user_id = $user_id
                ORDER BY timestamp DESC
                LIMIT $lim
                START $offset
                """,
                {"domain": experience.domain, "task_type": experience.task_type,
                 "user_id": experience.user_id, "lim": mid_limit, "offset": recent_limit}
            ) or []

            # Fetch oldest experiences (maximum temporal diversity)
            old = await self.db.query(
                """
                SELECT * FROM experience
                WHERE domain = $domain AND task_type = $task_type AND user_id = $user_id
                ORDER BY timestamp ASC
                LIMIT $lim
                """,
                {"domain": experience.domain, "task_type": experience.task_type,
                 "user_id": experience.user_id, "lim": old_limit}
            ) or []

            # Combine and deduplicate
            seen_ids = set()
            similar = []
            for exp in recent + mid + old:
                exp_id = str(exp.get("id", ""))
                if exp_id and exp_id not in seen_ids:
                    seen_ids.add(exp_id)
                    similar.append(exp)

            if not similar or len(similar) < 3:
                return

            # Construct prompt for L5
            context_str = "\n".join([
                f"- User: {e.get('context', {}).get('user_query', '')} | Aura: {e.get('aura_response', {}).get('response', '')[:100]}... | Outcome: {e.get('outcome', {})}"
                for e in similar
            ])
            
            prompt = f"""Analyze these interactions to extract learned knowledge.

Domain: {experience.domain}
Task Type: {experience.task_type}
User ID: {experience.user_id}
Existing insights in this domain: {domain_insight_count}

Interactions ({len(similar)} sampled across time range):
{context_str}

Task:
Extract distinct Facts, User Preferences, or Behavioral Patterns from these interactions.

FACT: Concrete information about the user or context
  Example: "User's name is Mai", "User works with Python frequently"

PREFERENCE: User likes/dislikes, communication style
  Example: "Prefers detailed explanations", "Dislikes verbose responses"

PATTERN: Recurring behavioral pattern
  Example: "Often asks follow-up questions", "Works on projects late at night"

Output JSON (each insight must have content, type, and confidence):
{{
  "insights": [
    {{
      "content": "User prefers technical depth over brevity",
      "type": "PREFERENCE",
      "confidence": 0.85
    }},
    {{
      "content": "User's name is Mai",
      "type": "FACT",
      "confidence": 0.95
    }}
  ]
}}

IMPORTANT: Output an array of insight objects, not nested dicts.
"""
            # Use L5 structure analysis
            result = await self.llm_layers.l5_structure_analysis(
                prompt=prompt, 
                system_instruction="Knowledge Extractor"
            )
            
            # Validate result structure - handle both dict and list responses
            if not result:
                self.logger.warning("LLM returned no result for insight extraction")
                return
            
            # Handle case where result might be a list directly
            if isinstance(result, list):
                insights_data = result
            elif isinstance(result, dict) and result.get("insights"):
                insights_data = result["insights"]
            else:
                self.logger.warning(f"Unexpected result format from LLM: {type(result)}")
                return
            
            # Ensure insights_data is a list
            if not isinstance(insights_data, list):
                self.logger.warning(f"insights_data is not a list: {type(insights_data)}")
                return
                
            # Convert RecordID objects to strings for source_experiences
            source_exp_ids = []
            for e in similar:
                if isinstance(e, dict):
                    exp_id = e.get("id", "")
                    if hasattr(exp_id, '__str__'):
                        source_exp_ids.append(str(exp_id))
                    elif isinstance(exp_id, str):
                        source_exp_ids.append(exp_id)
            
            # First, deduplicate insights within the batch itself
            import re
            seen_normalized = set()
            unique_insights = []
            
            for insight_item in insights_data:
                # Skip non-dict items (lists, strings, etc.)
                if not isinstance(insight_item, dict):
                    self.logger.debug(f"Skipping non-dict insight item: {type(insight_item)}")
                    continue
                    
                # Ensure it has required content field
                if not insight_item.get("content"):
                    self.logger.debug(f"Skipping insight item without content: {insight_item}")
                    continue
                    
                content = insight_item["content"]
                # Ensure content is a string
                if not isinstance(content, str):
                    self.logger.debug(f"Skipping insight with non-string content: {type(content)}")
                    continue
                    
                normalized = re.sub(r'[^\w\s]', '', content.lower().strip())
                
                # Skip if we've seen this normalized content in this batch
                if normalized not in seen_normalized:
                    seen_normalized.add(normalized)
                    unique_insights.append(insight_item)
                else:
                    self.logger.debug(f"Skipping duplicate insight in batch: {content[:50]}...")
            
            # Now create insights (already deduplicated within batch)
            for insight_item in unique_insights:
                # Double-check it's still a dict (defensive programming)
                if not isinstance(insight_item, dict):
                    self.logger.warning(f"Skipping invalid insight item in final loop: {type(insight_item)}")
                    continue
                    
                insight_data = {
                    "content": insight_item.get("content", ""),
                    "type": insight_item.get("type", "PATTERN"),
                    "confidence": insight_item.get("confidence", 0.5),
                    "domain": experience.domain,
                    "user_id": experience.user_id,
                    "source_experiences": source_exp_ids
                }
                
                # Validate insight_data before creating
                if not insight_data["content"]:
                    self.logger.warning("Skipping insight with empty content")
                    continue
                    
                await self.create_insight(insight_data)
                
        except Exception as e:
            self.logger.error(f"Background insight extraction failed: {e}")

    async def shutdown(self) -> None:
        """Clean up engine resources."""
        self.logger.info("Shutting down Learning Engine...")
        self.logger.info(f"Final stats - Experiences: {self.experiences_logged}, Insights: {self.insights_created}")
        if self._background_tasks:
            self.logger.info(f"Cancelling {len(self._background_tasks)} background tasks...")
            for task in list(self._background_tasks):
                task.cancel()
            await asyncio.gather(*self._background_tasks, return_exceptions=True)

    # Phase 1: Experience Capture

    async def log_experience(self, experience_data: dict) -> str:
        """
        Log an interaction experience with semantic embedding.

        Args:
            experience_data: Experience details (user_id, task_type, context, etc.)

        Returns:
            experience_id
        """
        experience_id = f"experience:{uuid4().hex[:12]}"

        try:
            # Ensure required fields
            experience = Experience(
                experience_id=experience_id,
                user_id=experience_data.get("user_id", "default"),
                task_type=experience_data.get("task_type", "unknown"),
                domain=experience_data.get("domain", "general"),
                context=experience_data.get("context", {}),
                aura_response=experience_data.get("aura_response", {}),
                outcome=experience_data.get("outcome", {}),
                emotional_state=experience_data.get("emotional_state", {}),
                metadata=experience_data.get("metadata", {}),
            )

            # Generate embedding for semantic clustering (Background)
            context_text = str(experience.context.get("user_query", ""))
            if context_text:
                asyncio.create_task(self._generate_embedding_later(experience_id, context_text))

            # Store in database
            await self.db.create("experience", experience.model_dump())

            self.experiences_logged += 1
            
            # Persist stats periodically
            if self.experiences_logged % 100 == 0:
                try:
                    await self.db.query(
                        "INSERT INTO stats (key, value) VALUES ('total_experiences', $value) ON DUPLICATE KEY UPDATE value = $value",
                        {"value": self.experiences_logged}
                    )
                except Exception as e:
                    self.logger.warning(f"Failed to update stats: {e}")

            self.logger.info(f"Experience logged: {experience_id} ({experience.task_type})")

            # =========================================================================
            # GRAPH CHAIN: Create temporal link to previous experience
            # =========================================================================
            # This enables L2 to analyze "Cause and Effect" by traversing the timeline
            await self._create_temporal_link(experience.user_id, experience_id, experience.timestamp)

            # =========================================================================
            # ROUTE A (SYNC): Direct Fact Learning (God Mode)
            # =========================================================================
            # Direct instructions should create an Insight immediately so the UI can reflect
            # the new fact without relying on the background extraction queue/tick loop.
            if experience.task_type == "direct_instruction":
                forced_insight = (experience.metadata or {}).get("forced_insight", {}) or {}
                content = (
                    forced_insight.get("content")
                    or experience.context.get("source")
                    or experience.context.get("user_query")
                )
                if not content:
                    raise ValueError("direct_instruction missing content")

                insight_data = {
                    "content": content,
                    "type": forced_insight.get("type", "FACT"),
                    "confidence": 1.0,  # Absolute certainty
                    "domain": experience.domain,
                    "user_id": experience.user_id,
                    "source_experiences": [experience.experience_id],
                    "emotional_signature": {"trust": 1.0},  # We trust the user explicitly
                }

                insight_id = await self.create_insight(insight_data)
                self.logger.info(
                    f"⚡ Direct instruction memorized (sync): {insight_id}"
                )
                return experience_id

            # Check for pattern extraction opportunity
            await self._check_pattern_extraction(experience)

            return experience_id

        except Exception as e:
            self.logger.error(f"Failed to log experience: {e}")
            raise

    async def set_experience_outcome(self, experience_id: str, outcome: dict) -> None:
        """Merge ``outcome`` into a logged experience's outcome (parameterised, one statement)."""
        await self.db.query(
            "UPDATE experience MERGE { outcome: $outcome } WHERE experience_id = $eid",
            {"eid": experience_id, "outcome": outcome},
        )

    async def _generate_embedding_later(self, exp_id: str, text: str) -> None:
        """Generate and save embedding in background."""
        try:
            embedding = await self.embeddings.embed(text)
            if embedding:
                await self.db.merge(exp_id, {"embedding": embedding})
                self.logger.debug(f"Generated embedding for experience {exp_id}")
        except Exception as e:
            self.logger.error(f"Failed to generate background embedding: {e}")

    async def _load_last_experiences(self) -> None:
        """
        Load the most recent experience per user from database.
        
        This initializes the temporal chain cache so the graph chain
        continues across server restarts.
        """
        try:
            # Query for the most recent experience per user
            # SurrealDB: GROUP BY user_id, get the latest timestamp
            result = await self.db.query("""
                SELECT user_id, id, timestamp
                FROM experience
                ORDER BY timestamp DESC
            """)
            
            if result:
                # Group by user_id and keep only the most recent per user
                seen_users = set()
                for exp in result:
                    user_id = exp.get("user_id", "default")
                    if user_id not in seen_users:
                        exp_id = str(exp.get("id", ""))
                        exp_timestamp = exp.get("timestamp")
                        
                        # Parse timestamp if it's a string
                        if isinstance(exp_timestamp, str):
                            try:
                                # Try datetime.fromisoformat first (Python 3.7+)
                                exp_timestamp = datetime.fromisoformat(exp_timestamp.replace('Z', '+00:00'))
                            except Exception:
                                # Fallback: try parsing common formats
                                try:
                                    # Try ISO format without timezone
                                    exp_timestamp = datetime.fromisoformat(exp_timestamp)
                                except Exception:
                                    self.logger.warning(f"Could not parse timestamp for {exp_id}, skipping")
                                    continue
                        
                        if isinstance(exp_timestamp, datetime):
                            # Normalize to UTC-aware before caching
                            exp_timestamp = self._normalize_datetime_to_utc(exp_timestamp)
                            self._last_experience_cache[user_id] = (exp_id, exp_timestamp)
                            seen_users.add(user_id)
                            self.logger.debug(f"Loaded last experience for user {user_id}: {exp_id}")
            
            self.logger.info(f"Initialized temporal chain cache for {len(self._last_experience_cache)} users")
        except Exception as e:
            self.logger.warning(f"Failed to load last experiences: {e}")

    def _normalize_datetime_to_utc(self, dt: datetime) -> datetime:
        """
        Normalize a datetime to UTC timezone-aware format.
        
        Handles both naive and timezone-aware datetimes by converting to UTC.
        
        Args:
            dt: Datetime object (may be naive or timezone-aware)
            
        Returns:
            Timezone-aware datetime in UTC
        """
        if dt is None:
            return dt
        
        if isinstance(dt, datetime):
            # If naive (no timezone), assume UTC
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            # If timezone-aware, convert to UTC
            return dt.astimezone(timezone.utc)
        
        return dt

    @staticmethod
    def _str_to_record_id(record_str: str):
        """
        Convert a string like 'experience:abc123' to a SurrealDB RecordID object.
        
        This is necessary because SurrealDB's RELATE and CREATE operations
        require RecordID objects, not plain strings, for record<...> fields.
        
        Args:
            record_str: String in format 'table_name:record_id'
            
        Returns:
            RecordID object
        """
        from surrealdb import RecordID  # noqa: PYLANCE (resolved at runtime)
        if ":" in record_str:
            table, record_id = record_str.split(":", 1)
            return RecordID(table, record_id)
        # If no colon, treat the whole string as record_id with unknown table
        return RecordID("experience", record_str)

    async def _create_temporal_link(
        self, user_id: str, new_experience_id: str, new_timestamp: datetime
    ) -> None:
        """
        Create next_experience edge from previous experience to new one.
        
        This enables temporal reasoning: L2 can traverse the graph to analyze
        "I did X, then Y happened" causal chains.
        
        Args:
            user_id: User identifier
            new_experience_id: ID of the newly logged experience
            new_timestamp: Timestamp of the new experience (datetime object)
        """
        try:
            # Check cache for last experience
            if user_id in self._last_experience_cache:
                prev_experience_id, prev_timestamp = self._last_experience_cache[user_id]
                
                # Calculate elapsed time in milliseconds
                # Normalize both timestamps to UTC-aware before subtraction
                if isinstance(prev_timestamp, datetime) and isinstance(new_timestamp, datetime):
                    prev_utc = self._normalize_datetime_to_utc(prev_timestamp)
                    new_utc = self._normalize_datetime_to_utc(new_timestamp)
                    elapsed_ms = int((new_utc - prev_utc).total_seconds() * 1000)
                    
                    # Create the next_experience edge using RELATE
                    # SurrealDB RELATE syntax: RELATE <in> ->edge_name-> <out> SET ...
                    # Convert string IDs to RecordID objects for SurrealDB compatibility
                    from surrealdb import RecordID
                    prev_rec_id = self._str_to_record_id(prev_experience_id)
                    new_rec_id = self._str_to_record_id(new_experience_id)
                    try:
                        # Use parameterized query for safety
                        await self.db.query(
                            """
                            RELATE $prev_exp ->next_experience-> $new_exp
                            SET elapsed_ms = $elapsed_ms
                            """,
                            {
                                "prev_exp": prev_rec_id,
                                "new_exp": new_rec_id,
                                "elapsed_ms": elapsed_ms
                            }
                        )
                        self.logger.debug(
                            f"Created temporal link: {prev_experience_id} -> {new_experience_id} "
                            f"({elapsed_ms}ms elapsed)"
                        )
                    except Exception as rel_error:
                        # Fallback: Try direct CREATE if RELATE fails (some SurrealDB versions)
                        self.logger.warning(f"RELATE failed, trying CREATE: {rel_error}")
                        try:
                            await self.db.create("next_experience", {
                                "in": prev_rec_id,
                                "out": new_rec_id,
                                "elapsed_ms": elapsed_ms
                            })
                            self.logger.debug(
                                f"Created temporal link via CREATE: {prev_experience_id} -> {new_experience_id}"
                            )
                        except Exception as create_error:
                            self.logger.error(f"Failed to create temporal link: {create_error}")
                else:
                    self.logger.warning(
                        f"Timestamp type mismatch: prev={type(prev_timestamp)}, new={type(new_timestamp)}"
                    )
            
            # Update cache with new experience (normalize to UTC-aware)
            normalized_timestamp = self._normalize_datetime_to_utc(new_timestamp)
            self._last_experience_cache[user_id] = (new_experience_id, normalized_timestamp)
            
        except Exception as e:
            # Don't fail the entire experience logging if temporal link fails
            self.logger.warning(f"Failed to create temporal link (non-critical): {e}")

    # Phase 5: Transfer (Rule Retrieval)

    async def retrieve_relevant(
        self,
        context: str,
        domain: str | None = None,
        confidence_min: float = 0.5,
        user_id: str | None = None,
        limit: int = 10,
        use_semantic_search: bool = True,
    ) -> list[Insight]:
        """
        Retrieve relevant insights using hybrid search (semantic + filters).

        Args:
            context: Context description
            domain: Filter by domain
            confidence_min: Minimum confidence threshold
            user_id: Filter for user-specific insights
            limit: Maximum insights to return
            use_semantic_search: Use vector similarity (requires context embedding)

        Returns:
            List of relevant insights sorted by relevance
        """
        try:
            # Strategy 1: Semantic search if context provided
            if use_semantic_search and context:
                # Generate embedding for context
                context_embedding = await self.embeddings.embed(context)

                if context_embedding:
                    # Use vector similarity search (cosine distance via <->)
                    # Lower distance = higher similarity
                    
                    # Parameterized query construction
                    query_params = {
                        "query_embedding": context_embedding,
                        "domain": domain, 
                        "user_id": user_id,
                        "confidence_min": confidence_min
                    }
                    
                    filter_conditions = ["deprecated = false"]
                    if domain:
                        filter_conditions.append("domain = $domain")
                    if user_id:
                        filter_conditions.append("user_id = $user_id")
                    
                    filter_clause = " AND ".join(filter_conditions)
                    
                    # Using vector similarity function for cosine similarity
                    query = f"""
                        SELECT *, vector::similarity::cosine(embedding, $query_embedding) AS similarity
                        FROM insight
                        WHERE {filter_clause}
                        ORDER BY similarity DESC, confidence DESC
                        LIMIT {limit}
                    """
                    
                    result = await self.db.query(query, query_params)
                    
                    if result:
                        # Filter out invalid rules during parsing
                        # Use model_validate to trigger custom validation that converts id -> rule_id
                        insights = []
                        for insight_data in result:
                            try:
                                insights.append(Insight.model_validate(insight_data))
                            except Exception as parse_err:
                                self.logger.warning(f"Skipping invalid insight record: {parse_err}")
                                continue
                        
                        self.logger.debug(f"Retrieved {len(insights)} insights via vector search")
                        return insights
                    
                    self.logger.debug("Vector search returned no results, falling back to filtered search")

            # Strategy 2: Filtered search (fallback or when no context)
            query_params = {
                "confidence_min": confidence_min,
                "domain": domain,
                "user_id": user_id
            }
            
            conditions = ["confidence >= $confidence_min", "deprecated = false"]

            if domain:
                conditions.append("domain = $domain")

            if user_id:
                conditions.append("user_id = $user_id")

            where_clause = " AND ".join(conditions)

            query = f"""
                SELECT * FROM insight
                WHERE {where_clause}
                ORDER BY confidence DESC, application_count DESC
                LIMIT {limit}
            """

            result = await self.db.query(query, query_params)

            if not result:
                return []

            # Filter out invalid insights during parsing
            # Use model_validate to trigger custom validation that converts id -> insight_id
            insights = []
            for insight_data in result:
                try:
                    insights.append(Insight.model_validate(insight_data))
                except Exception as parse_err:
                    self.logger.warning(f"Skipping invalid insight record in fallback search: {parse_err}")
                    continue

            self.logger.debug(f"Retrieved {len(insights)} insights for context")
            return insights

        except Exception as e:
            self.logger.error(f"Failed to retrieve insights: {e}")
            return []

    async def _mark_insights_used(self, insights: list[Insight]) -> None:
        """
        Mark insights as "used" by incrementing application_count and setting last_used.

        IMPORTANT: Only call this when insights are actually injected into an LLM context
        (e.g., via get_learning_context). Do NOT call this for UI listing endpoints.
        """
        if not insights:
            return

        last_used = datetime.utcnow()
        ids = [i.insight_id for i in insights if i and getattr(i, "insight_id", None)]
        if not ids:
            return

        try:
            # Update each insight. Keep this resilient: failure to update stats should
            # never break response generation.
            async def _bump_one(insight_id: str) -> None:
                try:
                    current = await self.db.select(insight_id)
                    if not current:
                        return
                    row = current[0] or {}
                    application_count = int(row.get("application_count", 0)) + 1
                    await self.db.merge(
                        insight_id,
                        {"application_count": application_count, "last_used": last_used},
                    )
                except Exception as e:
                    self.logger.debug(f"Failed to mark insight used {insight_id}: {e}")

            await asyncio.gather(*[_bump_one(iid) for iid in ids])
        except Exception as e:
            self.logger.debug(f"Failed to mark insights used: {e}")

    async def get_learning_context(
        self,
        context: str,
        domain: str | None = None,
        user_id: str | None = None,
    ) -> LearningContext:
        """
        Get complete learning context for LLM injection.

        Args:
            context: Task context
            domain: Domain filter
            user_id: User ID for personalized insights

        Returns:
            Learning context with insights, confidence, mastery
        """
        insights = await self.retrieve_relevant(
            context=context, domain=domain, user_id=user_id
        )

        # Usage tracking: the fact that we retrieved these insights here means they're
        # being injected into the LLM context (L3/L2). Update usage stats asynchronously
        # to avoid adding latency to chat responses.
        self._add_background_task(
            self._mark_insights_used(insights),
            task_name="insights:mark_used",
        )

        # Calculate overall confidence and mastery
        if insights:
            avg_confidence = sum(i.confidence for i in insights) / len(insights)
            mastery_level = self._calculate_mastery_from_insights(insights)
        else:
            avg_confidence = 0.0
            mastery_level = 0.0

        return LearningContext(
            insights=insights,
            confidence_level=avg_confidence,
            mastery_level=mastery_level,
        )

    # Insight Management

    async def create_insight(self, insight_data: dict) -> str:
        """
        Create a new learned insight with semantic embedding.
        
        Checks for duplicates before creating - if similar insight exists,
        updates confidence instead of creating duplicate.
        
        Uses lock to prevent race conditions when multiple insights are created in parallel.

        Args:
            insight_data: Insight specification

        Returns:
            insight_id (existing or new)
        """
        # Use lock to prevent race conditions
        async with self._insight_creation_lock:
            try:
                content = insight_data["content"]
                insight_type = insight_data.get("type", "PATTERN")
                domain = insight_data.get("domain", "general")
                user_id = insight_data.get("user_id", "default")
                new_confidence = insight_data.get("confidence", 0.5)
            
                # Normalize content for identity facts to prevent "My name is..." ambiguity
                # Convert "My name is [X]" to "The user's name is [X]"
                if insight_type == "FACT":
                    content = re.sub(r"(?i)^my name is\s+", "The user's name is ", content)
                    content = re.sub(r"(?i)^i am\s+", "The user is ", content)
                    content = re.sub(r"(?i)^i'm\s+", "The user is ", content)
                    insight_data["content"] = content

                # Normalize content for exact matching (strip punctuation, lowercase)
                normalized_content = re.sub(r'[^\w\s]', '', content.lower().strip())
                
                # First check for exact/near-exact text matches (more aggressive)
                existing_insights = await self.db.query(
                """
                SELECT * FROM insight
                WHERE type = $type AND domain = $domain AND user_id = $user_id AND deprecated = false
                """,
                    {
                        "type": insight_type,
                        "domain": domain,
                        "user_id": user_id
                    }
                )
                
                # Check for exact or near-exact matches first
                for existing in existing_insights:
                    existing_content = existing.get("content", "")
                    existing_normalized = re.sub(r'[^\w\s]', '', existing_content.lower().strip())
                    
                    # Exact match (normalized)
                    if normalized_content == existing_normalized:
                        existing_id = existing.get("id", "")
                        existing_confidence = existing.get("confidence", 0.5)
                        
                        # Use the higher confidence value
                        updated_confidence = max(existing_confidence, new_confidence)
                        
                        # Update existing insight with higher confidence
                        await self.db.merge(str(existing_id), {
                            "confidence": updated_confidence,
                            "last_used": datetime.utcnow()
                        })
                        
                        self.logger.info(
                            f"Exact duplicate insight detected. "
                            f"Updated existing {existing_id} confidence: {existing_confidence:.2f} -> {updated_confidence:.2f}"
                        )
                        return str(existing_id)
                    
                    # Check if one is a substring of the other (catches "User's name is Mai" vs "User's name is Mai.")
                    if normalized_content in existing_normalized or existing_normalized in normalized_content:
                        # If one is contained in the other, they're likely duplicates
                        existing_id = existing.get("id", "")
                        existing_confidence = existing.get("confidence", 0.5)
                        
                        # Use the higher confidence and longer content
                        if len(content) > len(existing_content):
                            # New content is longer, update existing with new content
                            updated_confidence = max(existing_confidence, new_confidence)
                            await self.db.merge(str(existing_id), {
                                "content": content,  # Use longer version
                                "confidence": updated_confidence,
                                "last_used": datetime.utcnow()
                            })
                        else:
                            # Existing is longer, just update confidence
                            updated_confidence = max(existing_confidence, new_confidence)
                            await self.db.merge(str(existing_id), {
                                "confidence": updated_confidence,
                                "last_used": datetime.utcnow()
                            })
                        
                        self.logger.info(
                            f"Near-duplicate insight detected (substring match). "
                            f"Updated existing {existing_id} confidence: {existing_confidence:.2f} -> {updated_confidence:.2f}"
                        )
                        return str(existing_id)
                
                # If no exact match, check semantic similarity as fallback
                embedding = await self.embeddings.embed(content)
                # PRD F5: when a similar FACT is found above the dedup threshold and its
                # normalised content differs, the old record is superseded by a new one.
                # Set here so the "create new" path below can pick it up.
                supersede_old_id: str | None = None
                if embedding and existing_insights:
                    # --- SESSION 7 FIX: Dynamic deduplication threshold ---
                    # As insights accumulate, raise the bar for what counts as "duplicate"
                    # This prevents the 17-insight manifold saturation stall.
                    domain_count = len(existing_insights)
                    import math
                    dedup_threshold = self._dynamic_dedup_threshold(domain_count)
                    
                    # Check semantic similarity for remaining insights
                    similar_insights = await self.db.query(
                        """
                        SELECT *, vector::similarity::cosine(embedding, $query_embedding) AS similarity
                        FROM insight
                        WHERE type = $type AND domain = $domain AND user_id = $user_id AND deprecated = false
                        ORDER BY similarity DESC
                        LIMIT 10
                        """,
                        {
                            "query_embedding": embedding,
                            "type": insight_type,
                            "domain": domain,
                            "user_id": user_id
                        }
                    )
                    
                    # If we find a very similar insight above the DYNAMIC threshold, update it instead
                    # (For FACT insights whose normalised content differs, the old one is superseded
                    # by a new record instead — see memory PRD F5.)
                    for similar in similar_insights:
                        similarity = similar.get("similarity", 0.0)
                        if similarity > dedup_threshold:  # Dynamic threshold (was fixed 0.90)
                            existing_id = similar.get("id", "")
                            existing_confidence = similar.get("confidence", 0.5)

                            # FACT supersession (PRD F5): a changed fact replaces the old one.
                            # The new fact is stored as a new record; the old one is marked
                            # ``deprecated`` and points at its replacement via ``superseded_by``.
                            # Exact/substring matches were already handled above, so a differing
                            # normalised content here means the fact genuinely changed.
                            if insight_type == "FACT":
                                existing_content = similar.get("content", "")
                                existing_normalized = re.sub(r'[^\w\s]', '', existing_content.lower().strip())
                                if normalized_content != existing_normalized:
                                    supersede_old_id = str(existing_id)
                                    break  # fall through to "create new" below

                            # Other types (or identical content): keep today's behaviour —
                            # bump the existing insight's confidence and return it.
                            updated_confidence = max(existing_confidence, new_confidence)

                            # Update existing insight with higher confidence
                            await self.db.merge(str(existing_id), {
                                "confidence": updated_confidence,
                                "last_used": datetime.utcnow()
                            })

                            self.logger.info(
                                f"Semantically similar insight detected (similarity: {similarity:.2f}). "
                                f"Updated existing {existing_id} confidence: {existing_confidence:.2f} -> {updated_confidence:.2f}"
                            )
                            return str(existing_id)
                
                # No similar insight found, create new one
                insight_id = f"insight:{uuid4().hex[:12]}"
                
                insight = Insight(
                    insight_id=insight_id,
                    content=content,
                    type=insight_type,
                    confidence=new_confidence,
                    domain=domain,
                    user_id=user_id,
                    emotional_signature=insight_data.get("emotional_signature", {}),
                    source_experiences=insight_data.get("source_experiences", []),
                    embedding=embedding,
                )

                # Create insight in database with proper record ID
                await self.db.create(insight_id, insight.model_dump())

                # FACT supersession (PRD F5): if this new fact replaced a semantically
                # similar old one, deprecate the old record and link it to its replacement.
                if supersede_old_id is not None:
                    await self.db.merge(supersede_old_id, {
                        "deprecated": True,
                        "superseded_by": insight_id,
                    })
                    self.logger.info(
                        f"Superseded fact {supersede_old_id} -> {insight_id} "
                        f"(deprecated, superseded_by set)"
                    )

                self.insights_created += 1
                self.logger.info(f"Insight created: {insight_id} - {insight.type}: {insight.content[:50]}...")

                # Broadcast insight creation
                if self._message_bus:
                    message = EngineMessage.create_state_update(
                        source="learning_engine",
                        data={"insight_id": insight_id, "type": insight.type, "confidence": insight.confidence},
                        targets=["orchestrator", "emotion_engine"],
                        priority=MessagePriority.NORMAL,
                    )
                    await self._message_bus.publish(message)

                return insight_id

            except Exception as e:
                self.logger.error(f"Failed to create insight: {e}")
                raise

    async def consolidate_memory(self, user_id: str) -> str:
        """
        The 'Dreaming' Process.
        Finds semantically similar insights and merges them into stronger single truths.

        Note: This is intended as a maintenance/cron style job (offline consolidation),
        not the online inference path.
        """
        try:
            self.logger.info(f"💤 Starting memory consolidation for {user_id}...")

            # 1. Fetch all active insights for user
            insights = await self.db.query(
                """
                SELECT * FROM insight
                WHERE user_id = $uid AND deprecated = false
                ORDER BY confidence DESC
                """,
                {"uid": user_id},
            )

            if not insights or len(insights) < 2:
                return "Not enough memories to dream."

            import math

            def cosine_similarity(v1: list[float], v2: list[float]) -> float:
                if not v1 or not v2 or len(v1) != len(v2):
                    return 0.0
                dot = 0.0
                n1 = 0.0
                n2 = 0.0
                for a, b in zip(v1, v2):
                    dot += a * b
                    n1 += a * a
                    n2 += b * b
                if n1 <= 0.0 or n2 <= 0.0:
                    return 0.0
                return dot / (math.sqrt(n1) * math.sqrt(n2))

            merged_count = 0
            processed_ids: set[str] = set()
            threshold = 0.88  # "same meaning, different words"
            now = datetime.utcnow().isoformat()

            # 2. Greedy merge: highest confidence absorbs lower-confidence duplicates
            for i, primary in enumerate(insights):
                primary_id = str(primary.get("id") or primary.get("insight_id") or "")
                if not primary_id or primary_id in processed_ids:
                    continue

                primary_embedding = primary.get("embedding")
                if not primary_embedding:
                    continue

                primary_conf = float(primary.get("confidence", 0.5) or 0.5)

                duplicate_ids: list[str] = []
                for j, candidate in enumerate(insights):
                    if i == j:
                        continue

                    candidate_id = str(candidate.get("id") or candidate.get("insight_id") or "")
                    if not candidate_id or candidate_id in processed_ids or candidate_id == primary_id:
                        continue

                    candidate_embedding = candidate.get("embedding")
                    if not candidate_embedding:
                        continue

                    # Only absorb lower-confidence candidates (greedy by confidence ordering)
                    candidate_conf = float(candidate.get("confidence", 0.5) or 0.5)
                    if candidate_conf > primary_conf:
                        continue

                    sim = cosine_similarity(primary_embedding, candidate_embedding)
                    if sim > threshold:
                        duplicate_ids.append(candidate_id)

                if not duplicate_ids:
                    continue

                # 3. MERGE PROCESS
                self.logger.info(f"Merging {len(duplicate_ids)} insights into {primary_id}")

                # Boost primary confidence a bit, capped
                new_conf = min(1.0, primary_conf + (0.05 * len(duplicate_ids)))

                # Deprecate duplicates
                for dup_id in duplicate_ids:
                    await self.db.merge(
                        dup_id,
                        {
                            "deprecated": True,
                            "merged_into": primary_id,
                            "last_consolidated": now,
                        },
                    )
                    processed_ids.add(dup_id)

                # Update primary
                await self.db.merge(
                    primary_id,
                    {
                        "confidence": new_conf,
                        "consolidation_count": int(primary.get("consolidation_count", 0) or 0) + 1,
                        "last_consolidated": now,
                    },
                )

                merged_count += len(duplicate_ids)

            return f"Dream cycle complete. Merged {merged_count} redundant memories."

        except Exception as e:
            self.logger.error(f"Failed to consolidate memory for {user_id}: {e}", exc_info=True)
            return f"Dream cycle failed: {e}"

    async def update_insight_confidence(
        self, insight_id: str, success: bool
    ) -> None:
        """
        Update insight confidence based on application outcome.

        Args:
            insight_id: Insight identifier
            success: Whether insight application succeeded
        """
        try:
            # Get current insight
            result = await self.db.select(insight_id)

            if not result:
                return

            insight_data = result[0]

            # Update counts
            application_count = insight_data.get("application_count", 0) + 1
            success_count = insight_data.get("success_count", 0) + (1 if success else 0)

            # Bayesian update of confidence
            # Simple formula: (successes + 1) / (total + 2)
            new_confidence = smoothed_confidence(success_count, application_count)

            updates = {
                "application_count": application_count,
                "success_count": success_count,
                "confidence": new_confidence,
                "last_used": datetime.utcnow(),
            }

            await self.db.merge(insight_id, updates)

            self.logger.debug(
                f"Insight {insight_id} updated: confidence={new_confidence:.2f}, "
                f"success_rate={success_count}/{application_count}"
            )

            # Check for deprecation
            if new_confidence < 0.3 and application_count > 10:
                await self.db.merge(insight_id, {"deprecated": True})
                self.logger.info(f"Insight {insight_id} deprecated (low confidence)")

        except Exception as e:
            self.logger.error(f"Failed to update insight confidence: {e}")

    # Skill Tree

    async def get_skill(self, skill_id: str) -> Skill | None:
        """Get skill by ID."""
        try:
            result = await self.db.select(skill_id)

            if not result:
                return None

            return Skill(**result[0])

        except Exception as e:
            self.logger.error(f"Failed to get skill: {e}")
            return None

    async def get_skills_by_domain(self, domain: str) -> list[Skill]:
        """Get all skills in a domain."""
        try:
            result = await self.db.query(
                f"SELECT * FROM skill WHERE domain = '{domain}'"
            )

            if not result:
                return []

            return [Skill(**s) for s in result]

        except Exception as e:
            self.logger.error(f"Failed to get skills: {e}")
            return []

    # Private methods

    async def _check_pattern_extraction(self, experience: Experience) -> None:
        """
        Check if extraction should run.
        UPDATED: Supports 'Fast Lane' for explicit instructions.
        """
        try:
            # Prevent duplicates in queue
            if any(e.experience_id == experience.experience_id for e in self.pattern_extraction_queue):
                return
            
            # --- 1. FAST LANE: Instructional Intent ---
            # If L1 detected this as teaching, we skip the repetition counter
            if experience.task_type == "instruction" or experience.metadata.get("intent") == "teaching":
                self.logger.info(f"🚀 Fast Lane: Immediate learning triggered for {experience.experience_id}")
                self.pattern_extraction_queue.append(experience)
                return

            # --- 2. SLOW LANE: Inductive Pattern Recognition ---
            # Check for recurring behaviors over time
            result = await self.db.query(
                """
                SELECT count() FROM experience
                WHERE domain = $domain AND task_type = $task_type
                GROUP ALL
                """,
                {"domain": experience.domain, "task_type": experience.task_type},
            )

            if result:
                count = result[0].get("count", 0)
                # Trigger on multiples of 5
                if count >= 5 and count % 5 == 0:
                    self.logger.info(f"Pattern threshold met: {count} experiences")
                    self.pattern_extraction_queue.append(experience)

        except Exception as e:
            self.logger.error(f"Failed to check pattern extraction: {e}")

    @staticmethod
    def _dynamic_dedup_threshold(domain_insight_count: int) -> float:
        """
        Session 7: Logarithmic deduplication threshold decay.
        
        As insights accumulate in a domain, the similarity threshold for
        deduplication INCREASES (making it harder to trigger dedup), which
        allows genuinely novel insights through even as the semantic manifold
        fills up.
        
        This fixes the 17-insight stall caused by fixed 0.90 threshold
        saturating the ~60D effective embedding manifold.
        
        At 0 insights:  threshold = 0.90 (baseline — easy dedup)
        At 17 insights: threshold ≈ 0.955 (tighter — allows more novelty)
        At 50 insights: threshold = 0.98 (very tight — only true duplicates)
        Capped at 0.98 to prevent identical duplicates from slipping through.
        """
        import math
        base = 0.90
        growth = 0.08  # maximum additional threshold
        # Logarithmic growth: fast initial rise, then levels off
        scale = math.log(1 + domain_insight_count) / math.log(50)
        return min(0.98, base + growth * min(1.0, scale))

    def _calculate_mastery_from_insights(self, insights: list[Insight]) -> float:
        """Calculate overall mastery level from retrieved insights."""
        if not insights:
            return 0.0

        # Weight by confidence and success rate
        total_weight = 0.0
        weighted_sum = 0.0

        for insight in insights:
            if insight.application_count > 0:
                success_rate = insight.success_count / insight.application_count
                weight = insight.confidence * success_rate
                weighted_sum += weight
                total_weight += 1.0

        return weighted_sum / total_weight if total_weight > 0 else 0.0

    async def _handle_message(self, message: EngineMessage) -> None:
        """Handle incoming messages from other engines."""
        # Use message_type which is an Enum, compare with string value
        if message.message_type == "propose_insight" or (
            message.message_type == MessageType.PROPOSAL and message.data.get("type") == "insight"
        ):
            # Process proposed insight from L2/Orchestrator
            payload = message.data
            content = payload.get("content", "")
            
            if not content:
                self.logger.warning("Received insight proposal with no content, skipping")
                return
            
            self.logger.info(f"Received insight proposal: {content[:50]}...")
            
            try:
                # Create the insight immediately (deduplication happens inside create_insight)
                # For now, we trust L2's high confidence patterns
                insight_data = {
                    "content": content,
                    "type": payload.get("insight_type", "PATTERN"),
                    "confidence": payload.get("confidence", 0.5),
                    "domain": payload.get("domain", "general"),
                    "user_id": payload.get("user_id", "default"),
                    "source_experiences": [], # No direct experience link in this flow yet
                }
                # create_insight has built-in deduplication with lock, so duplicates will be caught
                await self.create_insight(insight_data)
            except Exception as e:
                self.logger.error(f"Failed to create proposed insight: {e}")
        
        elif message.message_type == "trigger_extraction" or (
             message.message_type == MessageType.QUERY and message.data.get("action") == "extract_patterns"
        ):
            # Trigger manual pattern extraction (e.g. from Reflection Engine)
            # Query recent experiences respecting domain
            try:
                domain = message.data.get("domain")
                query = "SELECT * FROM experience "
                params = {}
                
                if domain:
                    query += "WHERE domain = $domain "
                    params["domain"] = domain
                
                query += "ORDER BY timestamp DESC LIMIT 5"
                
                recent_exps = await self.db.query(query, params)

                if recent_exps:
                    for exp_data in recent_exps:
                        exp = Experience(**exp_data)
                        self.pattern_extraction_queue.append(exp)
                    self.logger.info(f"Triggered manual pattern extraction for recent experiences (domain: {domain})")
            except Exception as e:
                self.logger.error(f"Failed to trigger extraction: {e}")
