import asyncio
import json
from aura.db.client import get_db_client

async def test_retrieval():
    db = get_db_client()
    await db.connect()
    
    from aura.llm.embeddings import get_embeddings_client
    emb = get_embeddings_client()
    
    query = "what's my name?"
    embedding = await emb.embed(query)
    print(f"Got embedding: {len(embedding)} dims")
    
    # Simulate Strategy 1: Vector search with user_id filter
    result = await db.query(
        """
        SELECT *, vector::similarity::cosine(embedding, $query_embedding) AS similarity
        FROM insight
        WHERE deprecated = false AND user_id = $user_id
        ORDER BY similarity DESC, confidence DESC
        LIMIT 10
        """,
        {"query_embedding": embedding, "user_id": "Mai"}
    )
    print(f"\n=== Strategy 1 (vector + user_id=Mai): {len(result)} results ===")
    for r in result:
        print(f"  [{r.get('type')}] {r.get('content')} (similarity={r.get('similarity', 'N/A'):.4f}, conf={r.get('confidence')})")
    
    # Check without user_id
    result2 = await db.query(
        """
        SELECT *, vector::similarity::cosine(embedding, $query_embedding) AS similarity
        FROM insight
        WHERE deprecated = false
        ORDER BY similarity DESC, confidence DESC
        LIMIT 10
        """,
        {"query_embedding": embedding}
    )
    print(f"\n=== Strategy 1 (no user_id filter): {len(result2)} results ===")
    for r in result2:
        print(f"  [{r.get('type')}] {r.get('content')} (similarity={r.get('similarity', 'N/A'):.4f}, conf={r.get('confidence')})")
    
    await db.close()

if __name__ == "__main__":
    asyncio.run(test_retrieval())
