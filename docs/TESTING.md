# Testing

## Local Python Test Gate

Run the offline Python test suite with the project dependencies and dev test
tools enabled:

```bash
UV_CACHE_DIR=/tmp/ml-junior-uv-cache uv run --extra dev pytest
```

The explicit `UV_CACHE_DIR` keeps the command independent from local cache
permissions. It can be omitted on machines where the default `uv` cache is
writable.

## Phase 0 Harness

The test harness config lives in `pyproject.toml` and `tests/conftest.py`.

It provides:

- repository and backend import paths;
- coroutine test execution without a required pytest async plugin;
- shared event queue helpers;
- a fake tool router for offline agent-loop tests;
- bounded default `Config` fixture for loop characterization.

Phase 0 tests must not make network calls. Mock LLM, Hugging Face, MCP, and
tool execution boundaries.

The harness blocks socket connections by default. If a future test is an
intentional network smoke, mark it with `@pytest.mark.allow_network` and keep it
out of the default offline gate.
