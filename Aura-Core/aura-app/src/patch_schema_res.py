import asyncio
from aura.db.client import get_db_client

async def main():
    db = get_db_client()
    await db.connect()
    
    query = 'DEFINE FIELD resonance_score ON memory TYPE option<float>;'
    await db.query(query)
    print("Schema updated successfully with resonance_score!")
    
if __name__ == "__main__":
    asyncio.run(main())
