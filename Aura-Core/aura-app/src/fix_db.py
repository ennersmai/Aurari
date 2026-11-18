import asyncio
from aura.db.client import get_db_client

async def fix_insights():
    db = get_db_client()
    await db.connect()
    
    # Update the "My name is Mai" to a 3rd person objective fact
    result = await db.query(
        "UPDATE insight SET content = 'The user is named Mai' WHERE content = 'My name is Mai'"
    )
    print(f"Update result: {result}")
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(fix_insights())
