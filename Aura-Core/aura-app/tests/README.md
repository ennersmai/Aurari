# Aura Test Suite

## Structure

- `unit/` - Unit tests for individual components, using `fake_db` fixture
- `scenarios/` - Scenario/integration tests that record baseline metrics

## Running Tests

```bash
cd Aura-Core/aura-app
.venv\Scripts\python.exe -m pytest
```

## Fixtures

- `fake_db` - In-memory stand-in for `DatabaseClient` with `query`, `create`, `merge`, `delete`, `select` methods. Stores rows in dictionaries. Unsupported queries raise `NotImplementedError`.

## Notes

- Unit tests MUST NOT start a real SurrealDB instance
- The `fake_db` fixture provides a fresh instance per test
- Global singletons are reset between tests via `reset_singletons` autouse fixture