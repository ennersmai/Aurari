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