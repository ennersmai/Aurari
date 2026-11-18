#!/usr/bin/env python3
"""
Script to wipe all skills from the database.

Usage:
    python scripts/wipe_skills.py

This will delete ALL skills from the database. Use with caution!
"""

import asyncio
import sys
import os

# Add src to path so we can import aura modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from aura.db.client import get_db_client
from aura.config import settings

async def wipe_all_skills():
    """Delete all skills from the database."""
    db = get_db_client()
    
    try:
        # Connect to database
        await db.connect()
        print("✅ Connected to database")
        
        # Get all skills
        print("📋 Fetching all skills...")
        skills = await db.query("SELECT id, name FROM skill")
        
        if not skills or len(skills) == 0:
            print("ℹ️  No skills found in database")
            return
        
        print(f"⚠️  Found {len(skills)} skill(s) to delete:")
        for skill in skills:
            skill_id = skill.get("id", "unknown")
            skill_name = skill.get("name", "Unknown")
            print(f"   - {skill_id}: {skill_name}")
        
        # Confirm deletion
        print("\n⚠️  WARNING: This will delete ALL skills from the database!")
        response = input("Type 'DELETE ALL' to confirm: ")
        
        if response != "DELETE ALL":
            print("❌ Deletion cancelled")
            return
        
        # STEP 1: Delete semantic triggers FIRST (they reference skills)
        print("\n🧹 Step 1: Cleaning up semantic triggers...")
        try:
            triggers = await db.query("SELECT id FROM semantic_trigger")
            if triggers:
                print(f"   Found {len(triggers)} semantic trigger(s)")
                trigger_count = 0
                for trigger in triggers:
                    trigger_id = trigger.get("id")
                    try:
                        await db.delete(trigger_id)
                        trigger_count += 1
                    except Exception as e:
                        print(f"   ⚠️  Failed to delete trigger {trigger_id}: {e}")
                print(f"   ✅ Deleted {trigger_count} semantic trigger(s)")
            else:
                print("   ℹ️  No semantic triggers found")
        except Exception as e:
            print(f"   ⚠️  Error cleaning up triggers: {e}")
        
        # STEP 2: Delete edge relationships
        print("\n🧹 Step 2: Cleaning up edge relationships...")
        try:
            # Delete triggers_skill edges
            triggers_skill_edges = await db.query("SELECT id FROM triggers_skill")
            if triggers_skill_edges:
                print(f"   Found {len(triggers_skill_edges)} triggers_skill edge(s)")
                for edge in triggers_skill_edges:
                    try:
                        await db.delete(edge.get("id"))
                    except Exception as e:
                        print(f"   ⚠️  Failed to delete edge {edge.get('id')}: {e}")
                print("   ✅ triggers_skill edges cleaned up")
            
            # Delete skill_contains edges
            skill_contains_edges = await db.query("SELECT id FROM skill_contains")
            if skill_contains_edges:
                print(f"   Found {len(skill_contains_edges)} skill_contains edge(s)")
                for edge in skill_contains_edges:
                    try:
                        await db.delete(edge.get("id"))
                    except Exception as e:
                        print(f"   ⚠️  Failed to delete edge {edge.get('id')}: {e}")
                print("   ✅ skill_contains edges cleaned up")
        except Exception as e:
            print(f"   ⚠️  Error cleaning up edges: {e}")
        
        # STEP 3: Clear parent/sub-skill references in skills
        print("\n🧹 Step 3: Clearing skill references...")
        try:
            for skill in skills:
                skill_id = skill.get("id")
                try:
                    # Clear parent and sub-skill references
                    await db.merge(skill_id, {
                        "parent_skill_id": None,
                        "sub_skill_ids": [],
                        "rule_ids": []  # Also clear rule_ids if they exist
                    })
                except Exception as e:
                    print(f"   ⚠️  Failed to clear references for {skill_id}: {e}")
            print("   ✅ Skill references cleared")
        except Exception as e:
            print(f"   ⚠️  Error clearing references: {e}")
        
        # STEP 4: Delete all skills
        print("\n🗑️  Step 4: Deleting skills...")
        deleted_count = 0
        errors = []
        
        for skill in skills:
            skill_id = skill.get("id")
            skill_name = skill.get("name", "Unknown")
            
            try:
                await db.delete(skill_id)
                deleted_count += 1
                print(f"   ✅ Deleted: {skill_id} ({skill_name})")
            except Exception as e:
                error_msg = f"Failed to delete {skill_id}: {e}"
                errors.append(error_msg)
                print(f"   ❌ {error_msg}")
        
        # Summary
        print(f"\n✅ Successfully deleted {deleted_count} skill(s)")
        if errors:
            print(f"⚠️  {len(errors)} error(s) occurred:")
            for error in errors:
                print(f"   - {error}")
        
        # STEP 5: Verify deletion
        print("\n🔍 Step 5: Verifying deletion...")
        try:
            remaining_skills = await db.query("SELECT id FROM skill")
            if remaining_skills and len(remaining_skills) > 0:
                print(f"   ⚠️  WARNING: {len(remaining_skills)} skill(s) still exist:")
                for skill in remaining_skills:
                    print(f"      - {skill.get('id')}")
            else:
                print("   ✅ All skills successfully deleted")
        except Exception as e:
            print(f"   ⚠️  Error verifying deletion: {e}")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await db.close()
        print("\n✅ Database connection closed")

if __name__ == "__main__":
    asyncio.run(wipe_all_skills())

