# Evals Bootstrap

Read when: changing offline golden traces, verifier verdict fixtures, or the
first evaluator interface.

This directory is the CI-safe eval bootstrap for ML Junior. It validates local
JSON fixtures only. It must not open sockets, call providers, require a GPU,
read Hugging Face tokens, download datasets, or call production ledger/verifier
APIs.

Run:

```sh
UV_CACHE_DIR=/tmp/ml-junior-uv-cache uv run --extra dev pytest evals
```

## Fixtures

- `fixtures/golden_traces/*.json`: deterministic event traces with
  `schema_version`, `name`, `mode`, `inputs`, `events`, `expected`, and
  `ignore_fields`.
- `fixtures/verifier_verdicts/*.json`: verifier verdicts with `claims`,
  `evidence`, `checks`, `verdict`, and `reason`.

Golden traces compare normalized structured fields. Generated ids, timestamps,
raw LLM text, and other unstable values belong in `ignore_fields` or out of the
fixture.

## Evaluator Interface

`OfflineFixtureEvaluator` sketches the future plugin contract:

- `prepare()`
- `evaluate(run_id)`
- `report()`

It is fixture-backed only until ledger and verifier APIs exist.

## Non-CI Markers

Reserved marker names for later opt-in evals:

- `scheduled`
- `network`
- `gpu`
- `requires_hf_token`

Do not use these in the default offline bootstrap unless the runner explicitly
opts in.
