import asyncio
from typing import Any
from aura.db.client import get_db_client
from aura.models.learning import Insight

async def test_validation():
    db = get_db_client()
    await db.connect()
    
    # Fetch exactly what Strategy 1 does
    result = await db.query("SELECT * FROM insight WHERE string::lowercase(content) CONTAINS 'mai' LIMIT 1")
    if not result:
        print("No insight found via query")
        return
        
    data = result[0]
    print(f"Raw data from DB: {data}")
    
    try:
        insight = Insight.model_validate(data)
        print(f"Validation success! insight_id: {insight.insight_id}")
    except Exception as e:
        print(f"Validation FAILED: {e}")
        
    await db.close()

if __name__ == "__main__":
    asyncio.run(test_validation())
