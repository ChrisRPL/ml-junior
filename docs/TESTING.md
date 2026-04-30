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

## Local Inference And Doctor Tests

Local inference tests must stay offline. Endpoint resolution for Ollama and
llama.cpp should be tested as pure config validation: input model id and config
in, resolved provider metadata or validation error out.

`/doctor local-inference` is target behavior only until implemented. Tests for
that contract should use fake-server fixtures or caller-supplied payloads/errors
instead of opening sockets. Cover:

- Ollama and llama.cpp local model ids;
- localhost, container-host alias, private IP, and rejected public-host cases;
- intended `/v1/models` probe descriptor generation without a network call;
- success, connection refused, timeout, malformed JSON, incompatible schema,
  and model-not-found classifications;
- redaction of auth headers, token query params, local user paths, prompts, and
  response bodies in output, events, and logs.

Do not add daemon probes, internet calls, model downloads, Ollama/llama.cpp
process management, or remote provider fallback to the default test gate.
