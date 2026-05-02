# CLI And TUI Spec

read_when: changing CLI commands, slash-command metadata, command completion,
headless mode, local-mode execution, flow preview commands, or future TUI
layout.

Status: current-vs-target CLI contract. "Current behavior" means shipped in
this repository now. "Target behavior" is direction only.

## Current Behavior

- Installed CLI entrypoints are `ml-junior` and the compatibility alias
  `ml-intern`.
- Interactive CLI commands currently include `/help`, `/undo`, `/compact`,
  `/model [id]`, `/effort [level]`, `/yolo`, `/status`, `/quit`, `/exit`,
  `/flows`, `/flow preview <id>`, `/runs [filter]`, `/run show <id>`,
  `/metrics [run]`, `/artifacts [filter]`, `/evidence [query]`, and
  `/decisions [query]`, `/handoff preview`, and `/doctor local-inference`.
- `/flows` and `/flow preview <id>` are implemented read-only renderers backed
  by `backend.flow_templates`.
- `/runs [filter]` and `/artifacts [filter]` are implemented read-only
  renderers over the current local CLI session's recorded
  `experiment.run_recorded` and `artifact_ref.recorded` events. They do not
  call backend routes, providers, filesystems, or artifact storage.
- `/run show <id>` is an implemented read-only renderer for the latest matching
  current-session `experiment.run_recorded` event. It does not call backend
  routes, compare or fork runs, ingest metrics/logs, or mutate workflow state.
- `/metrics [run]` is an implemented read-only renderer over metrics already
  present in current-session `experiment.run_recorded` events. It does not
  ingest metrics, call Trackio/providers, or read logs/artifacts.
- `/evidence [query]` is an implemented read-only renderer over the active
  local CLI session's `WorkflowState.evidence_summary` projection. It includes
  event-backed artifact, metric, log, explicit evidence item, claim link,
  decision card, proof bundle, and verifier verdict rows already present in the
  session log. It does not call backend routes or durable stores, create/link
  evidence, verify claims, sign/export proof bundles, read blobs/log bodies, or
  infer evidence from artifacts.
- `/decisions [query]` is an implemented read-only renderer over the active
  local CLI session's decision-card rows already present in
  `WorkflowState.evidence_summary`. It does not call backend routes or durable
  stores, create/edit decisions, sign/export proof bundles, inspect artifacts
  or logs, or infer decisions from chat.
- `/handoff preview` is an implemented read-only stdout renderer over the active
  local CLI session. It reconstructs redacted current-session events, builds a
  `WorkflowState`, runs the pure handoff summary projection, and prints status,
  phase, next action, counts, blockers, pending approvals, active jobs,
  decisions, evidence, artifacts, failures, and risks. It does not emit
  `handoff.summary_created`, write files, export paths, call backend routes,
  read durable stores, invoke LLM summarization, or mutate session state.
- `/doctor local-inference [runtime] [model]` is an implemented read-only
  renderer for local Ollama/llama.cpp endpoint metadata. It resolves local
  config, shows intended `/v1/models` URLs, reports config errors, and does not
  probe daemons or call providers.
- Slash-command parsing and completions include implemented and planned command
  metadata: group, risk level, mutating/read-only status, aliases, and required
  backend capability.
- Planned commands registered for help/completion print a capability-required
  message instead of executing.
- `/doctor` without the `local-inference` subcommand is planned only.
- Headless mode is `ml-junior "prompt text"` or `ml-intern "prompt text"`.
  Approval-gated tools stop the run and print pending approvals unless
  `--yolo` or `--auto-approve` is passed.
- CLI interactive and headless paths use local mode, so `bash`, `read`, `write`,
  and `edit` operate on the local filesystem under local guardrails.

Current limitations:

- There is no shipped multi-pane TUI.
- `ml-junior run <flow>` and `ml-junior project <command>` are target command
  families, not current entrypoints.
- `/flow start`, `/flow pause`, `/flow resume`, `/flow fork`, `/phase`,
  `/plan`, `/handoff [path]`, remaining experiment commands such as
  `/run compare` and `/run fork`, approval-center commands, remaining evidence
  commands, code commands, and publish commands are planned only unless
  `docs/CURRENT_ARCHITECTURE.md` says otherwise.

## Target Behavior

The CLI should act as a terminal command center for ML projects with three
families:

- `ml-junior`: interactive TUI for live work.
- `ml-junior run <flow>`: scripted/headless flow execution.
- `ml-junior project <command>`: project and session management.

The future interactive TUI should show:

- Left or tabbed pane: project, selected flow, phase, blockers, and status.
- Center pane: conversation, summaries, decisions, and handoff notes.
- Right or tabbed pane: active tools, jobs, approvals, budgets, and artifacts.
- Bottom composer: slash-command input with fuzzy completion.

Slash-command completion should show command name, description, arguments, risk
level, mutating/read-only state, required backend capability, and shortcut when
available.

## Target Command Groups

Project commands:

- `/new`, `/open`, `/status`, `/handoff`, `/export`, `/doctor`,
  `/doctor local-inference`

Flow and planning commands:

- `/flows`, `/flow preview <id>`, `/flow start <id>`, `/flow pause`,
  `/flow resume`, `/flow fork`, `/phase`, `/plan`

Experiment and artifact commands:

- `/experiments`, `/runs`, `/run show <id>`, `/run compare <id> <id>`,
  `/run fork <id>`, `/metrics`, `/artifacts`

Tooling, approval, and policy commands:

- `/tools`, `/jobs`, `/approve`, `/deny`, `/permissions`, `/budget`

Context and evidence commands:

- `/evidence`, `/decisions`, `/assumptions`, `/compact`, `/memory`,
  `/ledger`, `/ledger verify`, `/proof bundle`, `/share-traces`

Code and publishing commands:

- `/diff`, `/test`, `/rollback`, `/commit`, `/pr`, `/package`

## Autonomy Model

Target autonomy levels should be explicit:

- `observe`: read-only state inspection.
- `assist`: propose plans and code; user executes.
- `edit`: edit files; ask before commands.
- `run`: run safe commands and experiments within budget.
- `publish`: publish only after explicit final approval.

## Local Inference Setup

Target local model ids use explicit local prefixes:

- `local/ollama/<model>` resolves to an OpenAI-compatible Ollama `/v1`
  endpoint. Default base URL is the local Ollama daemon
  (`http://localhost:11434/v1`) unless overridden by local inference config or
  environment.
- `local/llamacpp/<alias>` resolves to an OpenAI-compatible llama.cpp server
  `/v1` endpoint. Default base URL is a local llama.cpp server
  (`http://localhost:8080/v1`) unless overridden by local inference config or
  environment.

Setup contract:

- Users start and manage Ollama or llama.cpp themselves. The CLI must not start,
  install, update, or stop local inference daemons.
- Configuration should accept localhost, container-host aliases, and private IP
  addresses only. Public remote inference endpoints are provider endpoints, not
  local inference.
- The resolved endpoint uses a dummy local API key for OpenAI-compatible client
  wiring. It must not require or reuse remote provider credentials.
- Local setup docs and diagnostics must avoid printing full URLs with embedded
  credentials, local user paths, request bodies, or model prompts.

## `/doctor local-inference` Target Contract

`/doctor local-inference` is a read-only diagnostic command. Current behavior
renders local metadata without daemon probes. Target behavior:

- Resolve configured Ollama and llama.cpp base URLs for requested local model
  ids.
- Validate URL scheme, host class, and `/v1` compatibility shape without
  mutating config.
- Report provider kind, model alias, base URL host class, intended `/v1/models`
  probe URL, and remediation hints.
- Redact secrets, auth headers, token query parameters, local user paths,
  prompts, and response bodies in all terminal output, events, and logs.
- Classify daemon responses supplied by the caller/test harness, including
  success, connection refused, timeout, malformed JSON, incompatible schema, and
  model-not-found.

Non-goals for the command:

- No daemon startup, package installation, model pull/download, or config write.
- No remote/provider fallback when a local daemon is missing.
- No sandbox, HF, MCP, telemetry, or internet calls.

## `/runs`, `/run show`, `/metrics`, And `/artifacts` Target Contract

`/runs [filter]`, `/run show <id>`, `/metrics [run]`, and
`/artifacts [filter]` are read-only current-session index commands. Current
behavior:

- Reconstruct recorded event envelopes from the active CLI session log and
  metadata, then project with the shared backend ledger helpers.
- If `MLJ_BACKEND_BASE_URL` and `MLJ_BACKEND_SESSION_ID` are both set, the same
  commands use opt-in backend index mode and read only
  `GET /api/session/{session_id}/runs`,
  `GET /api/session/{session_id}/runs/{run_id}`, and
  `GET /api/session/{session_id}/artifacts`. `MLJ_BACKEND_BEARER_TOKEN` adds an
  optional bearer token for production auth, and
  `MLJ_BACKEND_TIMEOUT_SECONDS` controls the short HTTP timeout.
- `/runs` lists run id, status, phase, first metrics, runtime provider, created
  time, and hypothesis.
- `/run show <id>` renders the latest matching run id with status, hypothesis,
  phase, runtime, config keys, metrics, nested artifact refs, log refs, and
  external tracking refs.
- `/metrics [run]` lists run id, metric name/value, source, optional step, unit,
  and recorded time for metrics already attached to recorded runs.
- `/artifacts` lists artifact id, type, source, lifecycle, stable artifact ref,
  and label when present.
- Optional filters are case-insensitive substring matches across visible ids
  and labels/status text.

Non-goals for the commands:

- Default local mode does not call backend routes or durable storage.
- Backend index mode does not read files/blobs, download artifacts, probe
  storage, compare runs, fork runs, call providers/Trackio, ingest metrics or
  logs, submit messages, replay sessions, or emit events.

## Contributor Rules

- Keep CLI command metadata in sync with implemented behavior and required
  backend capability.
- New commands should share backend session, event, workflow, approval, and
  policy contracts rather than creating a separate agent runtime.
- Mark planned commands as unimplemented until their backend capability exists.

## `/evidence` Current Contract

`/evidence [query]` is a read-only current-session evidence summary command.
Current behavior:

- Reconstruct redacted event envelopes from the active CLI session log for the
  event types that already project into `WorkflowState.evidence_summary`.
- Render event-backed artifact refs, standalone metrics, log refs, explicit
  evidence items, evidence claim links, decision cards, proof bundles, and
  verifier verdict rows.
- Apply an optional case-insensitive substring filter across projected row
  fields.
- Use latest-by-id and append semantics from the existing workflow projection
  rather than defining a CLI-specific duplicate policy.

Non-goals for the command:

- No backend route call, durable store read, evidence creation/linking, claim
  verification, proof-bundle signing/export, artifact/blob/log body read,
  provider/Trackio call, metric ingestion, event emission, or inferred evidence
  from files or tool output.

## `/decisions` Current Contract

`/decisions [query]` is a read-only current-session decision-card index.
Current behavior:

- Reconstruct redacted event envelopes from the active CLI session log for the
  event types that already project into `WorkflowState.evidence_summary`.
- Render only projected decision-card rows with status, source event sequence,
  linked evidence/claims/artifacts/proof bundles, title, decision, and
  rationale when present.
- Apply an optional case-insensitive substring filter across projected decision
  fields.

Non-goals for the command:

- No backend route call, durable store read, decision creation/editing,
  assumption inference, proof-bundle signing/export, artifact/blob/log body
  read, provider/Trackio call, event emission, or inferred decisions from chat
  or files.

## `/assumptions` Current Contract

`/assumptions [query]` is a read-only current-session assumption index.
Current behavior:

- Reconstruct redacted event envelopes from the active CLI session log for the
  event types that already project into `WorkflowState.evidence_summary`.
- Render only projected assumption rows with status, confidence, source event
  sequence, phase/run ids, linked decisions/evidence/claims/artifacts/proof
  bundles, title, statement, rationale, and validation notes when present.
- Apply an optional case-insensitive substring filter across projected
  assumption fields.

Non-goals for the command:

- No backend route call, durable store read, assumption creation/editing,
  automatic chat inference, proof-bundle signing/export, artifact/blob/log body
  read, provider/Trackio call, event emission, or inferred assumptions from
  chat or files.

## `/ledger` Current Contract

`/ledger [query]` is a read-only current-session event-envelope index. Current
behavior:

- Reconstruct redacted `AgentEvent` envelopes from the active CLI session log
  and metadata.
- Render event metadata only: sequence, event id, event type, timestamp, schema
  version, redaction status, safe top-level refs, and sorted top-level payload
  keys.
- Apply an optional case-insensitive substring filter across redacted visible
  event metadata and refs.
- Keep `/ledger verify [bundle]` planned. The parser's longest-command match
  prevents `/ledger verify` from being treated as a `/ledger` query.

Non-goals for the command:

- No backend route call, durable store read, event append, verification,
  signing/export, proof-bundle creation, full payload/body/blob/log display,
  provider/Trackio call, workflow mutation, TUI pane, or demo data.

## Trust-Sensitive Planned Command Contracts

Policy approval audit contracts are implemented for `/share-traces
public|private`, `/ledger verify [bundle]`, and `/proof bundle [run]`.
Current behavior:

- The contracts define risk, approval copy, side effects, rollback guidance,
  credential usage, privacy defaults, audit event names, required audit fields,
  redaction requirements, preconditions, and notes.
- Closed `policy.audit_intent_recorded` and `policy.audit_result_recorded`
  payload schemas exist for future durable audit records; no writer emits them
  yet.
- Pure policy audit ledger helpers can validate intent/result events, produce
  redacted payload copies, project session-scoped audit records, correlate
  result records back to intent records, and report pending intents. No CLI/TUI
  command consumes them yet.
- Pure policy audit event builders can create validated, redacted intent/result
  draft payloads from contracts plus explicit caller metadata. No CLI/TUI
  command consumes those builders, and no writer emits their drafts yet.
- Pure `MLJ-TPS-014d` `AgentEvent` envelope builders wrap already-built policy
  audit drafts into validated, redacted envelopes. No CLI/TUI command consumes
  them, and no writer appends their envelopes yet.
- `/share-traces public|private` is opt-in and approval-gated in the contract,
  with private-by-default destination and public-sharing warnings.
- `/ledger verify [bundle]` is read-only but auditable before any persisted or
  shared verifier verdict.
- `/proof bundle [run]` requires approval before local provenance bundle writes
  and does not grant remote export approval.

Non-goals:

- These contracts do not dispatch commands, mutate Hub visibility, verify
  ledgers, create proof bundles, sign/export artifacts, build or emit audit
  events into a runtime session, append envelopes, write durable audit rows,
  call providers/HF/network, add routes/UI/TUI, or enable public trace sharing.

## `/handoff preview` Current Contract

`/handoff preview` is a read-only current-session handoff preview command.
Current behavior:

- Reconstruct redacted event envelopes from the active CLI session log.
- Build `WorkflowState` with the same workflow projection helper used by the
  backend, then call the pure `generate_handoff_summary(...)` helper.
- Render status, last event sequence, goal, current phase, next action, counts,
  and compact sections for completed phases, blockers, pending approvals,
  active jobs, decisions, evidence, artifacts, failures, and risks.
- Reject extra arguments with `Usage: /handoff preview` so the command cannot be
  confused with path/export behavior.

Non-goals for the command:

- No `handoff.summary_created` event, event append, backend route call, durable
  store read/write, file export, checkpoint/fork creation, LLM summarization,
  provider/HF/Trackio/network call, artifact/log body read, workflow
  start/resume/fork, or mutation of session state.
- `/handoff [path]` remains planned and mutating until its durable write/export
  contract is explicit.
