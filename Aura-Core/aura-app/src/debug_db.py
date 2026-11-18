import asyncio
from aura.db.client import get_db_client

async def main():
    db = get_db_client()
    await db.connect()
    
    # Try select
    res = await db.select("memory")
    print(f"SELECT MEMORIES [{len(res)}]")
    
    # Try getting an ID directly if it was inserted with ID
    # Usually in SurrealDB when you query SELECT * FROM memory, it fetches all ID's that start with `memory:`
    # Also I will check if tables exist
    info = await db.query("INFO FOR DB;")
    print("DB INFO:", info)

if __name__ == "__main__":
    asyncio.run(main())
