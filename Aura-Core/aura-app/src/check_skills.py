import asyncio
import json
from aura.db.client import get_db_client

async def check_skills():
    db = get_db_client()
    try:
        await db.connect()
        results = await db.query("SELECT name, tool_name FROM skill")
        print(json.dumps(results, indent=2))
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if db.is_connected:
            await db.close()

if __name__ == "__main__":
    asyncio.run(check_skills())
