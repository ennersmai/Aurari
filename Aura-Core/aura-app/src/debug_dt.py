import asyncio
from aura.db.client import get_db_client
import uuid
from datetime import datetime, timezone

async def main():
    db = get_db_client()
    await db.connect()
    
    memory_id = f"memory:{uuid.uuid4().hex[:12]}"
    
    # Try with python datetime
    data1 = {
        "content": "Test with python datetime",
        "timestamp": datetime.now(timezone.utc),
        "formation_score": 0.8,
        "emotional_signature": {"joy": 0.5},
        "importance": 0.9,
        "ephemeral": False,
        "core_memory": False,
        "deprecated": False,
    }
    
    # Try with isoformat + Z
    memory_id2 = f"memory:{uuid.uuid4().hex[:12]}"
    data2 = data1.copy()
    data2["timestamp"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    
    print(f"Creating {memory_id} (python datetime)...")
    res1 = await db.create(memory_id, data1)
    print("Res1:", res1)
    
    print(f"Creating {memory_id2} (isoformat + Z)...")
    res2 = await db.create(memory_id2, data2)
    print("Res2:", res2)

if __name__ == "__main__":
    asyncio.run(main())
