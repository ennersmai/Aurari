#!/usr/bin/env python3
"""Quick fix to update skill_type field to include local_function."""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.config import settings
from aura.db.client import DatabaseClient


async def main():
    """Update skill_type field definition."""
    print("Updating skill_type field to include 'local_function'...")
    print(f"Connecting to: {settings.surreal_url}")
    print(f"Namespace: {settings.surreal_ns}, Database: {settings.surreal_db}")
    
    db = DatabaseClient()
    await db.connect()
    
    # First, remove the existing field definition
    print("Step 1: Removing existing skill_type field definition...")
    try:
        remove_query = "REMOVE FIELD skill_type ON skill;"
        result = await db.query(remove_query)
        print(f"   Remove result: {result}")
    except Exception as e:
        print(f"   Warning: Could not remove field (might not exist): {e}")
    
    # Then redefine it with the correct assertion
    print("Step 2: Redefining skill_type field with 'local_function'...")
    update_query = """
    DEFINE FIELD skill_type ON skill TYPE string DEFAULT "abstract" 
        ASSERT $value IN ["abstract", "mcp_tool", "local_function", "python_script"];
    """
    
    try:
        result = await db.query(update_query)
        print(f"   Define result: {result}")
        print("✅ skill_type field updated successfully!")
        
        # Verify it worked by checking the schema
        print("Step 3: Verifying schema update...")
        verify_query = "INFO FOR TABLE skill;"
        info_result = await db.query(verify_query)
        print(f"   Schema info: {info_result}")
        
    except Exception as e:
        print(f"❌ Error updating field: {e}")
        import traceback
        traceback.print_exc()
    
    await db.close()


if __name__ == "__main__":
    asyncio.run(main())

