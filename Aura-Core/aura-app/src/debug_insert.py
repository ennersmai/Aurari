import asyncio
from aura.db.client import get_db_client
import uuid
from datetime import datetime

async def main():
    db = get_db_client()
    await db.connect()
    
    memory_id = f"memory:{uuid.uuid4().hex[:12]}"
    data = {
        "content": "This is a test memory from the debug script.",
        "timestamp": datetime.utcnow().isoformat(),
        "emotional_signature": {"joy": 0.5},
        "importance": 0.9,
        "learned_from": False,
        "tags": ["test"],
        "metadata": {},
        "formation_score": 0.8,
        "ephemeral": False,
        "core_memory": False,
        "deprecated": False,
        "memory_type": "episodic",
        "emotional_intensity": 0.5,
        "recall_count": 0,
        "user_id": "test_user"
    }
    
    print(f"Creating {memory_id}...")
    try:
        res = await db.create(memory_id, data)
        print("Create response:", res)
    except Exception as e:
        print("Create exception:", e)
        
    print("Checking memory table contents...")
    try:
        memories = await db.select("memory")
        print("Memories count:", len(memories))
        if memories:
            print("First memory ID:", memories[0].get("id"))
    except Exception as e:
        print("Select exception:", e)

if __name__ == "__main__":
    asyncio.run(main())
