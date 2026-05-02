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

`/doctor local-inference` is implemented as a read-only metadata renderer. Tests
for the command and helper contract should use fake-server fixtures or
caller-supplied payloads/errors instead of opening sockets. Cover:

- Ollama and llama.cpp local model ids;
- localhost, container-host alias, private IP, and rejected public-host cases;
- intended `/v1/models` probe descriptor generation without a network call;
- success, connection refused, timeout, malformed JSON, incompatible schema,
  and model-not-found classifications;
- redaction of auth headers, token query params, local user paths, prompts, and
  response bodies in output, events, and logs.

Do not add daemon probes, internet calls, model downloads, Ollama/llama.cpp
process management, or remote provider fallback to the default test gate.

## Policy Approval Audit Contract Tests

Policy approval audit contracts are pure metadata for planned trust-sensitive
commands. Tests should call `build_policy_audit_contract(...)` without command
dispatch, backend routes, provider calls, durable audit writes, signing,
verification, or export. Cover:

- `/share-traces public` and `/share-traces private` require approval, HF
  credential metadata, remote visibility side effects, rollback guidance,
  opt-in/private-by-default preconditions, and required audit fields;
- `/share-traces` status remains read-only and does not require audit;
- `/ledger verify [bundle]` is read-only but auditable if a verdict is
  persisted or shared;
- `/proof bundle [run]` requires approval before local bundle/provenance writes
  and does not imply remote export approval;
- redaction requirements include secrets, auth headers, private dataset rows,
  local paths, private URLs, artifact blobs, and log bodies;
- `policy.audit_intent_recorded` and `policy.audit_result_recorded` schemas
  accept required future audit fields, normalize whitespace, redact sensitive
  values in copies, and reject unknown fields;
- unknown commands or unsupported trust-sensitive arguments fail closed.
- pure policy audit builders require explicit actor/session/approval/request/
  correlation metadata, preserve contract metadata, normalize copied text,
  reject missing stage-specific audit fields, reject protected/unknown payload
  fields, reject non-auditable status contracts, enforce public trace
  acknowledgement and redaction, validate result-to-intent correlation, return
  redacted event drafts, and still do not append events, call network/HF, write
  files, or execute commands.
- `MLJ-TPS-014d` adds pure `AgentEvent` envelope builders. Tests feed
  already-built policy audit drafts and assert validated, redacted envelopes,
  policy-event-type fail-closed behavior, invalid envelope rejection, and
  projection compatibility only; do not cover durable appends/writes, command
  dispatch, backend routes, UI/TUI, or provider/HF/network calls.

## Policy Audit Ledger Tests

Policy audit ledger helpers are inert projection utilities for future durable
audit records. Tests should build `AgentEvent` fixtures and call the helpers
directly without command dispatch, backend routes, durable writes, provider
calls, HF calls, verification, signing, or export. Cover:

- intent/result payload helpers round-trip through strict record models;
- `policy_audit_*_from_event` rejects wrong event types and session mismatch;
- projections filter other sessions, order by sequence/id, and reject duplicate
  audit ids;
- result projections reject duplicate `intent_audit_id` values;
- combined projection rejects result records that reference missing intent ids;
- `pending_intents` excludes intents with a correlated result;
- duplicate decision/evidence/artifact refs fail closed;
- redacted payload helpers scrub secrets and strengthen `redaction_status`.

## CLI Index Command Tests

`/runs`, `/run show`, `/metrics`, and `/artifacts` are read-only
current-session renderers by default, with an explicit env-gated backend index
mode. Default-mode tests should build fake session logs from `AgentEvent`
envelopes and assert projection behavior without backend route calls, storage
reads, artifact downloads, provider calls, metric ingestion, or event emission.
Backend-mode tests should use fake `httpx` transports only. Cover:

- event ordering and session-scoped projection;
- latest artifact ref selection by artifact id;
- latest run detail selection by run id;
- metric rows and run/substring filtering;
- opt-in backend env parsing, read-only route paths, auth header wiring,
  401/403/404/timeout handling, and no default backend use;
- empty sessions and active-session-missing output;
- case-insensitive filter behavior;
- redaction-sensitive output;
- main slash-command dispatch and registry implemented/planned metadata.

## CLI Evidence Command Tests

`/evidence [query]` is a read-only current-session renderer over existing
`WorkflowState.evidence_summary` rows. Tests should build fake session logs
from `AgentEvent` envelopes and assert projection behavior without backend
route calls, durable store reads, evidence creation/linking, verifier
execution, proof export/signing, artifact/log/blob reads, provider calls,
metric ingestion, or event emission. Cover:

- empty sessions and active-session-missing output;
- filtering across projected row fields;
- event-backed artifact, metric, log, evidence item, claim link, decision,
  proof, and verifier rows where relevant;
- existing workflow projection ordering and latest-by-id semantics;
- redaction-sensitive output and redacted filter echo;
- main slash-command dispatch and registry/completion metadata.

## CLI Decisions Command Tests

`/decisions [query]` is a read-only current-session renderer over decision-card
rows already projected into `WorkflowState.evidence_summary`. Tests should
build fake session logs from `AgentEvent` envelopes and assert behavior without
backend route calls, durable store reads, decision creation/editing, assumption
inference, proof export/signing, artifact/log/blob reads, provider calls, or
event emission. Cover:

- empty sessions and active-session-missing output;
- filtering across decision id, status, refs, title, decision, and rationale;
- redaction-sensitive output and redacted filter echo;
- evidence/claim/artifact/proof refs rendered from recorded decision cards;
- main slash-command dispatch and registry/completion metadata.

## CLI Assumptions Command Tests

`/assumptions [query]` is a read-only current-session renderer over explicit
assumption rows already projected into `WorkflowState.evidence_summary`. Tests
should build fake session logs from `AgentEvent` envelopes and assert behavior
without backend route calls, durable store reads, assumption creation/editing,
automatic chat inference, proof export/signing, artifact/log/blob reads,
provider calls, or event emission. Cover:

- empty sessions and active-session-missing output;
- filtering across assumption id, status, confidence, refs, title, statement,
  rationale, and validation notes;
- redaction-sensitive output and redacted filter echo;
- phase/run ids and decision/evidence/claim/artifact/proof refs rendered from
  recorded assumption rows;
- main slash-command dispatch and registry/completion metadata.

## Assumption Ledger Tests

`assumption.recorded` is an inert, explicit event/projection contract. Tests
should assert schema and projection behavior without runtime producers,
automatic chat inference, backend routes, proof signing/export,
artifact/log/blob reads, provider calls, or event emission. Cover:

- payload round-trip and closed-schema validation;
- wrong event type, session mismatch, duplicate `assumption_id`, and duplicate
  refs;
- redacted payload helpers and `AgentEvent.redacted_copy()` behavior;
- workflow `evidence_summary` projection with `assumption_count`, stable
  ordering, and unchanged empty placeholder shape;
- `/evidence` and `/assumptions` can display projected assumption rows without
  creating or inferring assumptions.

## CLI Ledger Command Tests

`/ledger [query]` is a read-only current-session renderer over redacted
`AgentEvent` envelope metadata. Tests should build fake session logs from
`AgentEvent` envelopes and assert behavior without backend route calls, durable
store reads, event appends, verification, proof export/signing,
artifact/log/blob reads, provider calls, or event emission. Cover:

- sequence ordering, event id/type, timestamp, schema version, redaction status,
  safe refs, and sorted top-level payload keys;
- filtering across redacted visible event metadata and refs;
- redaction-sensitive output and redacted filter echo;
- empty sessions and active-session-missing output;
- main slash-command dispatch and registry/completion metadata;
- `/ledger verify [bundle]` remains planned and is not treated as a
  `/ledger` query.

## CLI Handoff Preview Tests

`/handoff preview` is a read-only current-session renderer over
`WorkflowState` plus pure handoff-summary projection. Tests should build fake
session logs from `AgentEvent` envelopes and assert preview behavior without
backend route calls, durable store reads/writes, `handoff.summary_created`
emission, file export, checkpoint/fork creation, LLM summarization,
artifact/log/blob reads, provider calls, workflow start/resume/fork, or state
mutation. Cover:

- no active session, empty/stale session, and extra-argument usage output;
- current phase, completed phases, blockers, pending approvals, active jobs,
  decisions, evidence, artifacts, failures, and risks where relevant;
- use of existing workflow/handoff projection behavior rather than
  command-specific duplicate policy;
- redaction-sensitive output;
- main slash-command dispatch and registry/completion metadata, including
  `/handoff [path]` remaining planned/mutating.

## Backend Run Projection Tests

Artifact and run projection APIs should stay read-only and event-backed. Tests
for `/api/session/{session_id}/artifacts`,
`/api/session/{session_id}/artifacts/{artifact_id}`,
`/api/session/{session_id}/runs`, and
`/api/session/{session_id}/runs/{run_id}` should use fake durable sessions plus
`SQLiteEventStore.append()` so route payloads exercise normal event redaction.
Cover:

- session access checks and missing session/run/artifact status codes;
- closed durable sessions;
- event ordering and cross-session filtering;
- latest projected record for duplicate run/artifact ids on detail reads;
- no execution, file/blob reads, provider calls, run comparison/fork, artifact
  inspection/download, or event emission.
