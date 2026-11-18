
## W2-29: Add record ID conversion helper and update boost_on_recall
- **Status:** DONE
- **Files changed:** `src/aura/db/query_utils.py`, `src/aura/engines/memory/manager.py`, `tests/scenarios/test_boost_on_recall_embedded.py`, `tests/unit/test_to_record_id.py`
- **Test result:** 4 passed (unit tests for to_record_id, boost functionality, and related helpers)
- **Notes:** Added `to_record_id()` helper to convert `"table:id"` strings to typed `RecordID` objects. Updated `MemoryManager.boost_on_recall` to bind `to_record_id(memory_id)` instead of the raw string, fixing the embedded SurrealDB engine error. Added comprehensive tests covering conversion logic and the two-boost recall count advancement. No other code changes.