import asyncio
from aura.db.client import get_db_client
from aura.models.memory import Memory
import uuid

async def main():
    db = get_db_client()
    await db.connect()
    
    memory_id = f"memory:{uuid.uuid4().hex[:12]}"
    mem = Memory(
        memory_id=memory_id,
        content="Final test memory.",
        timestamp=None, # will use default
        importance=0.9,
        formation_score=0.8,
        ephemeral=False,
        core_memory=False,
    )
    data = mem.model_dump()
    data.pop("memory_id", None)
    
    print(f"Creating memory: {memory_id}...")
    try:
        res = await db.create(memory_id, data)
        print("Create SUCCESS:", res)
    except Exception as e:
        print("Create exception:", e)
        
    print("Checking memory table contents...")
    memories = await db.select("memory")
    print("Memories count:", len(memories))
    if memories:
        print("First memory ID:", memories[0].get("id"))

if __name__ == "__main__":
    asyncio.run(main())
