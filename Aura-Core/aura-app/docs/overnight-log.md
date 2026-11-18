# Overnight Build Log

## Summary
- **Done:** W0-01
- **Stopped at:** None yet (in progress)
- **Current card:** W0-02

---

## W0-01: Remove the database from the repository
- **Status:** DONE (by setup)
- **Files changed:** None (already in .gitignore)
- **Test result:** N/A
- **Notes:** The `.aura/` directory already exists on disk and is already in `.gitignore` at the repository root. `git ls-files | grep "\.aura/"` returns nothing. No commit needed as per card instructions.

## W0-02: Test scaffolding
- **Status:** DONE
- **Files changed:** `tests/conftest.py`, `tests/unit/test_basic.py`, `tests/README.md`
- **Test result:** 2 passed
- **Notes:** Created test directories, fake_db fixture with in-memory dict storage, and trivial passing tests. pytest runs and passes from aura-app.

## W0-03: Clock provider
- **Status:** DONE
- **Files changed:** `src/aura/clock.py`, `tests/unit/test_clock.py`
- **Test result:** 10 passed
- **Notes:** Created Clock base class, FakeClock with set() and advance(), get_clock() and set_clock() for global access. All tests pass. No other files changed.

## W0-04: Record today's emotion physics
- **Status:** DONE
- **Files changed:** `tests/scenarios/test_emotion_baseline_record.py`
- **Test result:** 1 passed
- **Notes:** Recorded baseline to docs/metrics/emotion_before.json. After 600 ticks from baseline, several emotions drift up due to relationship amplification. Half-life from 0.7: sadness=100000 (capped), anger=23, joy=18, love=100000 (capped - persistent emotion).

## W0-05: Record today's memory horizon
- **Status:** DONE
- **Files changed:** `tests/scenarios/test_memory_horizon_record.py`
- **Test result:** 1 passed
- **Notes:** Recorded baseline to docs/metrics/memory_before.json. Emotional intensity: 3@0.8=0.2665, 9@0.7=0.4038, 14@1.0=0.7195. Decay at 1/5/9/15/30 days: MM and DE match closely. At 30 days decay ~3e-5.

## W1-03: Disable in-process tool synthesis
- **Status:** DONE
- **Files changed:** `src/aura/config.py`, `src/aura/api/routes/school.py`
- **Test result:** 14 passed (full suite)
- **Notes:** Added school_synthesis_enabled setting (default False). The /synthesize route now returns HTTP 503 with "Tool synthesis is disabled" when the setting is false.

## W1-04: Scope memory retrieval to the user
- **Status:** DONE
- **Files changed:** `src/aura/llm/layers.py`
- **Test result:** 14 passed (full suite)
- **Notes:** Added user_id=context.user_id to both retrieve_for_l3 calls (standard L3 and streaming L3).