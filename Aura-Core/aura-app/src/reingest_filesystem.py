import asyncio
import json
from aura.engines.learning.engine import LearningEngine

async def reingest():
    le = LearningEngine()
    # Mocking LLMLayers if needed (not needed for simple tool ingest)
    
    print("Ingesting filesystem tools...")
    try:
        # Ingest local tool module
        # Note: ingest_local_tool_module is an internal helper in engine.py
        # Wait, let's check if it exists or if I should use the public API.
        result = await le.ingest_local_tool_module("filesystem")
        print(f"Result: {result}")
    except Exception as e:
        print(f"Ingest failed: {e}")
    
    # Verify
    from aura.db.client import get_db_client
    db = get_db_client()
    await db.connect()
    skills = await db.query("SELECT name, tool_name FROM skill")
    print(f"Indexed skills: {json.dumps(skills, indent=2)}")
    await db.close()

if __name__ == "__main__":
    asyncio.run(reingest())
