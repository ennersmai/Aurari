import asyncio
from aura.db.client import get_db_client

async def main():
    db = get_db_client()
    await db.connect()
    
    queries = """
    DEFINE FIELD formation_score ON memory TYPE float DEFAULT 0.5;
    DEFINE FIELD ephemeral ON memory TYPE bool DEFAULT false;
    DEFINE FIELD core_memory ON memory TYPE bool DEFAULT false;
    DEFINE FIELD deprecated ON memory TYPE bool DEFAULT false;
    DEFINE FIELD memory_type ON memory TYPE string DEFAULT "episodic";
    DEFINE FIELD emotional_intensity ON memory TYPE float DEFAULT 0.0;
    DEFINE FIELD recall_count ON memory TYPE int DEFAULT 0;
    DEFINE FIELD last_recalled_at ON memory TYPE option<datetime>;
    DEFINE FIELD OVERWRITE formation_context ON memory TYPE object FLEXIBLE DEFAULT {};
    """
    
    print("Applying schema updates to memory table...")
    try:
        # Run each line
        for q in queries.strip().split(";"):
            if q.strip():
                print(f"Executing: {q.strip()}")
                await db.query(q.strip() + ";")
        print("Schema updated successfully!")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    asyncio.run(main())
