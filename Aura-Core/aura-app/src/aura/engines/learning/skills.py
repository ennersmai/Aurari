"""
Skill tree management (Learning FRD FR-ST-001).

Hierarchical organization of knowledge: Skills → Sub-skills → Experiences
"""

import logging
from datetime import datetime
from typing import Any
from uuid import uuid4

from aura.db.client import get_db_client
from aura.models.learning import Skill

logger = logging.getLogger(__name__)


class SkillTreeManager:
    """Manage hierarchical skill tree structure."""

    def __init__(self):
        """Initialize skill tree manager."""
        self.db = get_db_client()

    async def create_skill(
        self,
        name: str,
        domain: str,
        parent_skill_id: str | None = None,
        emotional_signature: dict[str, float] | None = None,
    ) -> str:
        """
        Create a new skill node.

        Args:
            name: Skill name
            domain: Domain of knowledge
            parent_skill_id: Parent skill (for hierarchy)
            emotional_signature: Emotional association

        Returns:
            skill_id
        """
        skill_id = f"skill:{uuid4().hex[:12]}"

        try:
            skill = Skill(
                skill_id=skill_id,
                name=name,
                domain=domain,
                parent_skill_id=parent_skill_id,
                emotional_signature=emotional_signature or {},
            )

            # CRITICAL FIX: SurrealDB create() needs the full record ID, not just table name
            # Use skill_id (e.g., "skill:abc123") instead of "skill"
            skill_data = skill.model_dump()
            # Remove skill_id from data since it's in the thing parameter
            skill_data.pop("skill_id", None)
            
            # CRITICAL FIX: Convert parent_skill_id string to RecordID if present
            # SurrealDB schema expects option<record<skill>>, not a plain string
            if skill_data.get("parent_skill_id"):
                from surrealdb import RecordID
                parent_id_str = skill_data["parent_skill_id"]
                # Parse the string like "skill:abc123" into a RecordID
                if ":" in parent_id_str:
                    table, record_id = parent_id_str.split(":", 1)
                    skill_data["parent_skill_id"] = RecordID(table, record_id)
                    logger.debug(f"🔧 Converted parent_skill_id from string '{parent_id_str}' to RecordID")
                else:
                    logger.warning(f"⚠️ parent_skill_id '{parent_id_str}' doesn't match expected format 'table:id'")
            
            logger.info(f"🔧 Creating skill in database: {skill_id} with data keys: {list(skill_data.keys())}")
            try:
                create_result = await self.db.create(skill_id, skill_data)
                from aura.logging_config import sanitize_log_payload
                logger.info(f"🔧 Create result type: {type(create_result)}, value: {sanitize_log_payload(create_result)}")
                
                # Immediately verify the skill was created
                import asyncio
                await asyncio.sleep(0.1)  # Small delay for SurrealDB to commit
                verify = await self.db.select(skill_id)
                if verify and len(verify) > 0:
                    logger.info(f"✅ Skill {skill_id} verified in database immediately after create")
                else:
                    logger.error(f"❌ Skill {skill_id} NOT found in database immediately after create!")
                    logger.error(f"❌ Create result was: {create_result}")
            except Exception as create_error:
                logger.error(f"❌ Database create() call failed: {create_error}", exc_info=True)
                raise

            logger.info(f"Skill created: {skill_id} ({name})")
            return skill_id

        except Exception as e:
            logger.error(f"Failed to create skill: {e}")
            raise


    async def calculate_mastery(self, skill_id: str) -> float:
        """
        Calculate mastery level for a skill.

        Based on Learning FRD FR-ST-002:
        - Sub-skill mastery (if any)
        - Recent application success rate
        """
        try:
            skill_result = await self.db.select(skill_id)

            if not skill_result:
                return 0.0

            skill_data = skill_result[0]

            # Get sub-skills
            sub_skill_ids = skill_data.get("sub_skill_ids", [])

            mastery_components = []

            # Sub-skill mastery (recursive)
            if sub_skill_ids:
                sub_masteries = []
                for sub_id in sub_skill_ids:
                    sub_mastery = await self.calculate_mastery(sub_id)
                    sub_masteries.append(sub_mastery)

                avg_sub_mastery = (
                    sum(sub_masteries) / len(sub_masteries) if sub_masteries else 0.0
                )
                mastery_components.append(("sub_skills", avg_sub_mastery, 1.0))

            # Calculate mastery from sub-skills only
            if mastery_components:
                total_weight = sum(weight for _, _, weight in mastery_components)
                weighted_sum = sum(
                    value * weight for _, value, weight in mastery_components
                )
                mastery = weighted_sum / total_weight
            else:
                mastery = 0.0

            # Update skill mastery in database
            await self.db.merge(skill_id, {"mastery_level": mastery})

            return mastery

        except Exception as e:
            logger.error(f"Failed to calculate mastery: {e}")
            return 0.0

    async def get_skill_tree(self, root_skill_id: str) -> dict[str, Any]:
        """
        Get complete skill tree starting from root.

        Returns hierarchical structure with all sub-skills.
        """
        try:
            skill_result = await self.db.select(root_skill_id)

            if not skill_result:
                return {}

            skill_data = skill_result[0]

            tree = {
                "skill_id": root_skill_id,
                "name": skill_data.get("name"),
                "domain": skill_data.get("domain"),
                "mastery_level": skill_data.get("mastery_level", 0.0),
                "sub_skills": [],
            }

            # Recursively get sub-skills
            sub_skill_ids = skill_data.get("sub_skill_ids", [])
            for sub_id in sub_skill_ids:
                sub_tree = await self.get_skill_tree(sub_id)
                tree["sub_skills"].append(sub_tree)

            return tree

        except Exception as e:
            logger.error(f"Failed to get skill tree: {e}")
            return {}

    async def get_all_skills(self, domain: str | None = None) -> list[dict[str, Any]]:
        """Get all skills, optionally filtered by domain."""
        try:
            if domain:
                query = f"SELECT * FROM skill WHERE domain = '{domain}'"
            else:
                query = "SELECT * FROM skill"

            result = await self.db.query(query)

            if not result:
                return []

            return result

        except Exception as e:
            logger.error(f"Failed to get skills: {e}")
            return []

    async def delete_skill(self, skill_id: str) -> bool:
        """
        Delete a skill from the database.
        
        This will remove the skill record and any associated relationships.
        Note: This does not recursively delete sub-skills. If you want to delete
        a skill tree, you should delete sub-skills first.
        
        Args:
            skill_id: The ID of the skill to delete
            
        Returns:
            True if the skill was successfully deleted, False otherwise
        """
        try:
            # First, verify the skill exists
            skill_result = await self.db.select(skill_id)
            
            if not skill_result:
                logger.warning(f"Skill not found for deletion: {skill_id}")
                return False
            
            skill_data = skill_result[0]
            skill_name = skill_data.get("name", "Unknown")
            
            # Remove parent references if this skill has a parent
            parent_skill_id = skill_data.get("parent_skill_id")
            if parent_skill_id:
                try:
                    parent_result = await self.db.select(parent_skill_id)
                    if parent_result:
                        parent_data = parent_result[0]
                        sub_skill_ids = parent_data.get("sub_skill_ids", [])
                        if skill_id in sub_skill_ids:
                            sub_skill_ids.remove(skill_id)
                            await self.db.merge(parent_skill_id, {"sub_skill_ids": sub_skill_ids})
                            logger.debug(f"Removed {skill_id} from parent {parent_skill_id}'s sub_skill_ids")
                except Exception as e:
                    logger.warning(f"Failed to update parent skill references: {e}")
            
            # Note: Graph relationships (edges) may be automatically cleaned up by SurrealDB
            # when the record is deleted, or they may need separate cleanup if needed
            
            # Delete the skill record
            await self.db.delete(skill_id)
            
            logger.info(f"Successfully deleted skill: {skill_id} ({skill_name})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete skill {skill_id}: {e}", exc_info=True)
            return False

