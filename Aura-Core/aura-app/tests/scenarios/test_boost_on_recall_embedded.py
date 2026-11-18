@pytest.mark.asyncio
async def test_boost_on_recall_advances_recall_count_by_two():
    """Two ``boost_on_recall`` calls raise ``recall_count`` by exactly two.

    Stores one memory through ``store_memory``, reads its ``recall_count``
    with a parameterised ``SELECT`` bound to a ``RecordID``, calls
    ``boost_on_recall`` twice with the *string* id the manager returns,
    and asserts the count went from 0 to 2.
    """
    db = EmbeddedSurrealDB()
    await db.connect()
    try:
        manager = _build_manager(db)

        # Store one memory.  ``store_memory`` returns the string record id
        # it created (``"memory:<hex>"``).  W2-27 fixed the embedding stub's
        # hash slice, so real (non-empty) text embeds and stores offline
        # without needing the real embedding model.
        memory_id = await manager.store_memory(
            content="I like hiking in the mountains",
            user_id="alice",
            conversation_id="conv-1",
            emotional_signature={},
            importance=0.5,
            tags=["conversation", "interaction"],
            resonance_score=None,
            formation_context=None,
            response_length=0,
        )
        assert isinstance(memory_id, str) and memory_id.startswith("memory:")

        # Bind a RecordID when reading the row back.
        rid = RecordID("memory", memory_id.split(":", 1)[1])
        rows = await db.query("SELECT recall_count FROM $rid", {"rid": rid})
        before = rows[0]["recall_count"] if rows else None
        assert before == 0, f"expected recall_count 0 before boosting, got {before!r}"

        # Call boost_on_recall with the *string* id (the app's call shape).
        await manager.boost_on_recall(memory_id, boost=0.05)
        await manager.boost_on_recall(memory_id, boost=0.05)

        rows_after = await db.query("SELECT recall_count FROM $rid", {"rid": rid})
        after = rows_after[0]["recall_count"] if rows_after else None
        assert after == 2, f"expected recall_count 2 after two boosts, got {after!r}"
    finally:
        await db.close()