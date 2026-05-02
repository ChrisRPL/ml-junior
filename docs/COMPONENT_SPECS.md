# Component Specs

read_when: changing component boundaries, backend session behavior, agent loop
contracts, tool policy, event streaming, durable stores, workflow projection, or
frontend chat transport.

Status: current-vs-target contract snapshot. "Current behavior" means code in
this repository today. "Target behavior" is direction, not a shipped guarantee.

## Session Manager And Queues

Current behavior:

- Responsibilities: owns process-local `AgentSession` objects, creates a
  per-session `Session`, `ToolRouter`, submission queue, event queue, and
  background run task.
- Inputs: authenticated user id, optional HF token, optional model id, and
  queued `Operation` objects for user input, approval, undo, compact, shutdown,
  interrupt, and truncate.
- Outputs: session ids, session info, queued operation records, event broadcasts,
  workflow projections, and redacted operation/session metadata APIs.
- Persistence: live execution state is in memory. SQLite stores persist durable
  session metadata, operation records, and event envelopes under `session_logs`
  unless overridden by `MLJ_*_STORE_PATH` env vars.
- Failure modes: capacity limits return errors; constructor/network work can
  delay session creation; backend restart loses live queues, pending approvals,
  and live context even when durable metadata remains; sandbox cleanup can fail
  non-fatally.
- Tests: `tests/unit/test_backend_session_sse.py`,
  `tests/unit/test_backend_operation_routes.py`,
  `tests/unit/test_session_store.py`, `tests/unit/test_operation_store.py`,
  `tests/unit/test_event_store.py`, and `tests/unit/test_workflow_state.py`.

Target behavior:

- Durable session replay should restore enough queued/event state to resume
  work after restart.
- Capacity should account for provider rate limits, live tool work, local
  resource pressure, and compute budget, not only session count.

## Agent Session And Context

Current behavior:

- Responsibilities: holds model config, HF token, `ContextManager`, event
  sequence counter, cancellation flag, pending approval state, sandbox handle,
  running HF job ids, and trajectory save/upload hooks.
- Inputs: event queue, per-session config, tool specs, optional HF token, and
  local-mode flag.
- Outputs: redacted `AgentEvent` envelopes, trajectory JSON, local session logs,
  detached session dataset upload attempts, model/effort state updates, and
  cancellation signals.
- Persistence: conversation messages and cancellation state are memory-only.
  Trajectory save is a JSON backup and optional detached Hub upload, not a live
  session store.
- Failure modes: LiteLLM model metadata can be missing and falls back to 200k
  tokens; detached uploads can fail silently after local save; redaction is
  heuristic; dangling tool calls are patched with stub tool results.
- Tests: `tests/unit/test_agent_events.py`,
  `tests/unit/test_session_uploader_redaction.py`,
  `tests/unit/test_context_compaction_interrupt.py`, and
  `tests/unit/test_redaction.py`.

Target behavior:

- Context, approvals, and running-tool references should be resumable from a
  durable store.
- Public event contracts should expose envelope metadata once replay/cursor
  semantics are stable.

## Agent Loop And Approvals

Current behavior:

- Responsibilities: appends user messages, streams or returns assistant output,
  evaluates tool policy, executes auto-approved tools, batches
  approval-required tools, handles approval responses, compacts context, retries
  transient LLM errors, interrupts running tools, and emits terminal events.
- Inputs: `Submission` operations, LiteLLM messages, tool specs, tool call JSON,
  policy decisions, approval decisions, optional edited scripts, and config
  flags such as `yolo_mode`, `confirm_cpu_jobs`, and `auto_file_upload`.
- Outputs: assistant chunks/messages, tool call/output/state events,
  `approval_required` events with policy metadata, `turn_complete`,
  `interrupted`, and `error` events.
- Persistence: loop state is memory-only. Operation status and redacted events
  are persisted by the backend around the loop.
- Failure modes: malformed tool JSON becomes a tool error; provider auth,
  quota, context-window, network, or unsupported reasoning-effort errors surface
  to the user; pending approvals are abandoned if a new user message arrives;
  approved tools run concurrently and may still fail after approval.
- Tests: `tests/unit/test_agent_loop.py`,
  `tests/unit/test_tool_router_approval.py`,
  `tests/unit/test_headless_approval_safety.py`, and
  `tests/unit/test_context_compaction_interrupt.py`.

Target behavior:

- Approval state should survive backend restart and support richer UI rendering
  from policy metadata.
- LLM/tool retry state should become observable enough for deterministic
  replay and debugging.

## Policy Approval Audit Contracts

Current behavior:

- Responsibilities: provide inert policy, approval, and audit contracts for
  planned trust-sensitive commands before those commands are implemented.
- Inputs: command name and arguments for `/share-traces`, `/ledger verify`, and
  `/proof bundle`.
- Outputs: `PolicyAuditContract` records with risk, approval requirement,
  approval title/body, side effects, rollback, budget impact, credential usage,
  privacy and visibility defaults, audit event type names, required audit
  fields, redaction requirements, preconditions, and notes.
- Event contracts: `policy.audit_intent_recorded` and
  `policy.audit_result_recorded` payloads are closed schemas only; they validate
  the future durable audit records before any writer or command dispatcher
  exists.
- Ledger helpers: `backend.policy_audit_ledger` owns strict intent/result
  records, payload helpers, redacted payload helpers, event-to-record
  validation, pure session projections, duplicate rejection, result-to-intent
  correlation, and pending intent tracking.
- Builder helpers: pure policy audit builders create validated intent/result
  records and redacted event draft payloads from a `PolicyAuditContract` plus
  explicit caller metadata. They apply stage-specific required-field gates,
  public trace acknowledgement/redaction checks, protected-field rejection, and
  result-to-intent correlation.
- Envelope helpers: pure `MLJ-TPS-014d` helpers wrap already-built, validated
  policy audit drafts into validated, redacted `AgentEvent` envelopes. Inputs
  are policy audit drafts, not command args or live contracts; unknown event
  types fail closed.
- Persistence: none. The contracts do not dispatch commands, mutate Hub
  visibility, verify ledgers, create proof bundles, sign/export artifacts, or
  emit, append, or write audit events. The `MLJ-TPS-014d` helpers return
  envelopes only, with no durable writes or runtime side effects.
- Failure modes: unknown commands and unsupported trust-sensitive arguments
  raise `PolicyAuditContractError` instead of guessing a policy.
- Tests: `tests/unit/test_policy_audit_contracts.py`,
  `tests/unit/test_policy_audit_ledger.py`, `tests/unit/test_agent_events.py`,
  `tests/unit/test_policy_engine.py`, and
  `tests/unit/test_tool_router_approval.py`.

Target behavior:

- `/share-traces`, `/ledger verify`, `/proof bundle`, and future export
  commands should route through these contracts plus durable approval/audit
  event persistence before any mutating or trust-signaling behavior lands.

## Tool Router And Policy Engine

Current behavior:

- Responsibilities: registers built-in tools, optional MCP tools, and an
  OpenAPI docs search tool; exposes OpenAI-format tool specs; maps tool calls
  to Python handlers or MCP calls; normalizes legacy tuple, HF-style dict, MCP
  content, and structured results into `ToolResult`.
- Inputs: configured MCP servers, trusted MCP server names, optional HF token,
  tool names, tool arguments, session/config, and `policy_approved`.
- Outputs: LLM tool specs without metadata, `PolicyDecision` objects,
  legacy `(output, success)` tuples, and structured `ToolResult` objects.
- Persistence: router registrations and MCP origins are in memory per session.
- Failure modes: MCP init is non-fatal; unregistered MCP calls are blocked;
  approval-required calls are blocked until called with `policy_approved=True`;
  generic MCP tools require approval; unknown tools return policy errors.
- Tests: `tests/unit/test_tool_metadata.py`,
  `tests/unit/test_policy_engine.py`,
  `tests/unit/test_tool_router_approval.py`,
  `tests/unit/test_tool_results.py`, and
  `tests/unit/test_mcp_gateway_trust_boundary.py`.

Target behavior:

- Tool metadata should become the single source for UI risk display, audit
  logging, and narrower per-tool/server MCP policy.
- Built-in handlers should eventually return structured `ToolResult` directly
  instead of relying on adapters.

## MCP Gateway

Current behavior:

- Responsibilities: loads configured FastMCP servers, normalizes raw MCP tool
  names to `mcp__{server}__{tool}`, records origin metadata, skips known
  replacement/collision-prone names, and calls registered MCP tools by original
  raw client name.
- Inputs: `mcpServers` config, trusted HF MCP server list, optional user HF
  token, MCP tool schemas, and namespaced tool calls.
- Outputs: namespaced tool specs, origin metadata, optional forwarded
  Authorization header, MCP result content converted to tool results.
- Persistence: server credential policy and origin map live in memory.
- Failure modes: ambiguous server origin, blocklisted raw names, duplicate
  namespaced names, MCP connection failure, and unregistered MCP calls are
  blocked or skipped.
- Tests: `tests/unit/test_mcp_gateway_trust_boundary.py`,
  `tests/unit/test_tool_metadata.py`, and
  `tests/unit/test_tool_router_approval.py`.

Target behavior:

- MCP servers should have explicit capability and credential policies, with
  reviewed trust labels rather than generic approval for all tools.
- Retrieved MCP content should be tagged as untrusted before entering model
  context or UI projections.

## Execution Tools

Current behavior:

- Responsibilities: provide `bash`, `read`, `write`, and `edit` either against
  local filesystem in CLI mode or an HF Space sandbox in backend mode; provide
  `sandbox_create` in sandbox mode.
- Inputs: shell commands, work dirs, file paths, file contents, edit strings,
  sandbox hardware, and session/HF token.
- Outputs: stdout/stderr or sandbox output, file contents, edit/write status,
  sandbox URLs, and `tool_log` events for streamable work.
- Persistence: local read-before-write/edit tracking is process memory;
  sandbox persists only for the session and is deleted on session cleanup when
  owned by the session.
- Failure modes: local paths outside allowed roots are denied; destructive
  local shell commands are blocked; sandbox paths outside `/app` and `/tmp` are
  denied; missing sandbox blocks sandbox operations; network/HF failures block
  sandbox creation.
- Tests: `tests/unit/test_local_execution_guardrails.py` and
  `tests/unit/test_sandbox_execution_guardrails.py`.

Target behavior:

- Local and sandbox guardrails should be policy-configurable and auditable.
- Long-running command/process lifecycle should expose stable ids, status, and
  cancellation semantics across reconnects.

## HF Jobs And Hub Repository Tools

Current behavior:

- Responsibilities: run or schedule HF Jobs, stream job logs, cancel jobs,
  inspect/list jobs, and read/mutate Hugging Face repositories through files
  and git-like operations.
- Inputs: HF token, namespace, scripts or Docker commands, dependencies,
  hardware flavor, timeout, environment, job ids, repo ids, repo type, paths,
  file content, patterns, branches, tags, PR ids, and repo settings.
- Outputs: formatted job/repo status, job log events, job URLs, uploaded file
  URLs or PR URLs, and repository mutation status.
- Persistence: HF Jobs and Hub repos are external persistent side effects.
  Running job ids are tracked in session memory for interrupt cleanup. An inert
  append-only SQLite store can persist explicit active-job and artifact refs,
  including schema-only artifact locator/lifecycle/export-policy metadata.
  Artifact `ref_uri` is now documented as the stable MLJ handle; local paths,
  Hub URLs, sandbox refs, remote URLs, and event pointers belong in locator or
  compatibility fields. A pure artifact producer adapter can build
  `ArtifactRefRecord` from explicit caller-supplied producer metadata without
  inspecting files or tool output text. The backend exposes a read-only
  session-scoped artifact index from persisted `artifact_ref.recorded` events.
  Runtime tools do not write to this store yet.
- Policy metadata helpers: `PolicyEngine` uses the pure HF compute risk helper
  to estimate local risk/spend metadata for known `jobs_tool.py` hardware
  flavors, including scheduled and unknown hardware uncertainty. It enriches
  approval metadata only; it does not launch jobs, call HF services, or mutate
  budget state.
- Failure modes: job storage is ephemeral unless scripts push artifacts to the
  Hub; missing HF token/namespace, invalid hardware, paid compute, job failure,
  repo permission errors, or network errors surface as tool failures; approved
  mutations can still overwrite or delete remote content.
- Tests: `tests/unit/test_policy_engine.py`,
  `tests/unit/test_hf_compute_risk.py`,
  `tests/unit/test_artifact_producers.py`,
  `tests/unit/test_tool_router_approval.py`,
  `tests/unit/test_backend_artifact_index.py`,
  `tests/unit/test_job_artifact_refs.py`,
  `tests/unit/test_experiment_ledger.py`, and workflow/progress tests that
  project job refs.

Target behavior:

- Job launch should require explicit spend/hardware confirmation and record a
  durable budget/audit trail.
- Hub publishing should prefer PR-style changes for non-trivial or destructive
  writes, with artifact lineage linked into workflow state.

## Budget, Dataset, And Provenance Helpers

Current behavior:

- Responsibilities: validate and persist explicit budget ledger records; model
  caller-supplied dataset manifests, diffs, lineage DAGs, and content-addressed
  blob paths; keep provenance primitives inert until runtime producers exist.
- Inputs: caller-supplied budget limit/usage records, dataset manifest records,
  lineage graph records, run-level manifest/lineage refs, and sha256 blob
  digests.
- Outputs: redacted append-only budget ledger rows, deterministic manifest
  diffs, validated lineage graphs, explicit run-level dataset refs, and
  conventional `~/.mlj/blobs/sha256/...` paths.
- Persistence: the budget ledger has an append-only SQLite store for explicit
  records. Dataset lineage and blob helpers are pure models/path conventions
  and perform no filesystem or network I/O.
- Failure modes: duplicate budget records are rejected by
  `(session_id, record_id, source_event_sequence)`; invalid lineage graphs
  reject duplicate/unknown parents and cycles; run-level dataset refs reject
  unknown fields and empty ids; malformed or weak digests are rejected before
  path derivation.
- Tests: `tests/unit/test_budget_ledger.py`,
  `tests/unit/test_dataset_lineage.py`, `tests/unit/test_dataset_blobs.py`,
  `tests/unit/test_experiment_ledger.py`, and `tests/unit/test_agent_events.py`.

Target behavior:

- Runtime producers should eventually write budget, dataset, lineage, and blob
  references only after policy, privacy, and local/sandbox guardrails are
  explicit.
- Provenance export should start with a local-first manifest plus NDJSON record
  files before optional PROV-JSONLD, OpenLineage, Parquet/DuckDB, or MLMD
  adapters.

## Local Inference Diagnostics

Current behavior:

- Responsibilities: describe configured local Ollama/llama.cpp endpoints,
  build intended `/v1/models` probe descriptors, classify caller-supplied probe
  results, build doctor report objects, and render the read-only CLI
  `/doctor local-inference` output.
- Inputs: local runtime config/env metadata, expected local model id, and
  caller-supplied classifications or errors.
- Outputs: pure runtime descriptors, probe descriptors/classifications, and
  doctor reports with runtime id, provider kind, model alias, host class,
  intended models URL, status, redacted messages, and remediation hints.
- Persistence: none. The helpers do not mutate config or record budget usage.
- Failure modes: invalid config returns config-error descriptors; missing or
  malformed caller-supplied payloads become report statuses and hints.
- Tests: `tests/unit/test_local_inference.py`,
  `tests/unit/test_local_inference_doctor.py`,
  `tests/unit/test_doctor_commands.py`, and `tests/unit/test_llm_params.py`.

Target behavior:

- Daemon probes, provider calls, model pulls, and UI/routes are not implemented.
  If added later, they must remain explicit and no-network in the default test
  gate by accepting fake-server or caller-supplied responses.

## CLI Index Commands

Current behavior:

- Responsibilities: render read-only `/runs [filter]`, `/run show <id>`,
  `/metrics [run]`, and `/artifacts [filter]` output from the active local CLI
  session's recorded `experiment.run_recorded` and `artifact_ref.recorded`
  events. When explicitly opted in with `MLJ_BACKEND_BASE_URL` and
  `MLJ_BACKEND_SESSION_ID`, the same commands read backend session index routes
  instead of the in-memory session log.
- Inputs: current session id, in-memory logged events, event metadata, optional
  case-insensitive filter string, or explicit backend base URL/session id/env
  auth settings for backend mode.
- Outputs: plain terminal text listing experiment runs, one run detail, metric
  rows, or artifact refs.
- Persistence: none. The helpers do not append events, inspect artifact blobs,
  submit messages, replay sessions, or contact providers. Backend mode reads
  only the existing durable run/artifact JSON routes.
- Failure modes: no active local session returns a no-active-session message;
  incomplete backend env, backend auth failures, 404s, timeouts, invalid JSON,
  or malformed recorded event data report renderer errors instead of mutating
  state.
- Tests: `tests/unit/test_cli_index_commands.py`,
  `tests/unit/test_backend_index_client.py`,
  `tests/unit/test_cli_command_registry.py`, and
  `tests/unit/test_cli_command_completions.py`.

Target behavior:

- Run comparison, metric ingestion, artifact inspection, and TUI panes remain
  separate slices.

## CLI Evidence Summary

Current behavior:

- Responsibilities: render read-only `/evidence [query]` output from the active
  local CLI session's existing `WorkflowState.evidence_summary` projection.
- Inputs: current session id, in-memory logged events, event metadata, and an
  optional case-insensitive filter string. The renderer only reconstructs event
  types that already feed `evidence_summary`: artifact refs, standalone metrics,
  log refs, explicit evidence items, claim links, decision cards, proof bundles,
  and verifier verdicts.
- Outputs: plain terminal text with evidence summary counts and filtered rows.
- Persistence: none. The command does not read durable stores, append events,
  create/link evidence, verify claims, sign/export proof bundles, inspect
  artifact blobs or log bodies, ingest metrics, or contact providers.
- Failure modes: no active session returns a no-active-session message; empty
  projection returns an empty state; malformed recorded evidence events report a
  renderer error instead of mutating state.
- Tests: `tests/unit/test_cli_evidence_commands.py`,
  `tests/unit/test_cli_command_registry.py`, and
  `tests/unit/test_cli_command_completions.py`.

Target behavior:

- Backend-backed evidence search, claim verification, evidence creation,
  decision/proof editing, and TUI panes remain separate slices.

## CLI Decisions Index

Current behavior:

- Responsibilities: render read-only `/decisions [query]` output from the
  active local CLI session's existing `WorkflowState.evidence_summary`
  projection.
- Inputs: current session id, in-memory logged events, event metadata, and an
  optional case-insensitive filter string. The renderer shows only decision-card
  rows that are already present in the projection.
- Outputs: plain terminal text with a decision count and filtered rows including
  decision id, status, source event sequence, linked evidence/claims/artifacts/
  proof bundles, title, decision, and rationale when present.
- Persistence: none. The command does not read durable stores, append events,
  create/edit decisions, infer assumptions, sign/export proof bundles, inspect
  artifact blobs or log bodies, or contact providers.
- Failure modes: no active session returns a no-active-session message; empty
  projection returns an empty state; malformed recorded decision events report a
  renderer error instead of mutating state.
- Tests: `tests/unit/test_cli_evidence_commands.py`,
  `tests/unit/test_cli_command_registry.py`, and
  `tests/unit/test_cli_command_completions.py`.

Target behavior:

- Durable decision editing, proof signing/export, and TUI
  decision panes remain separate slices.

## CLI Assumptions Index

Current behavior:

- Responsibilities: render read-only `/assumptions [query]` output from the
  active local CLI session's existing `WorkflowState.evidence_summary`
  projection.
- Inputs: current session id, in-memory logged events, event metadata, and an
  optional case-insensitive filter string. The renderer shows only assumption
  rows that are already present in the projection.
- Outputs: plain terminal text with an assumption count and filtered rows
  including assumption id, status, confidence, source event sequence,
  phase/run ids, linked decisions/evidence/claims/artifacts/proof bundles,
  title, statement, rationale, and validation notes when present.
- Persistence: none. The command does not read durable stores, append events,
  create/edit assumptions, infer assumptions from chat, sign/export proof
  bundles, inspect artifact blobs or log bodies, or contact providers.
- Failure modes: no active session returns a no-active-session message; empty
  projection returns an empty state; malformed recorded assumption events report
  a renderer error instead of mutating state.
- Tests: `tests/unit/test_cli_evidence_commands.py`,
  `tests/unit/test_cli_command_registry.py`, and
  `tests/unit/test_cli_command_completions.py`.

Target behavior:

- Durable assumption creation/editing, validation workflows, TUI assumption
  panes, and export/signing integration remain separate slices.

## CLI Ledger Event Index

Current behavior:

- Responsibilities: render read-only `/ledger [query]` output from the active
  local CLI session's redacted `AgentEvent` envelopes.
- Inputs: current session id, in-memory logged events, event metadata, and an
  optional case-insensitive filter string over redacted visible metadata.
- Outputs: plain terminal text with an event count and filtered rows including
  sequence, event id, event type, timestamp, schema version, redaction status,
  safe top-level refs, and sorted top-level payload keys.
- Persistence: none. The command does not read durable stores, append events,
  verify ledgers, sign/export proof bundles, display full payload values,
  inspect artifact blobs or log bodies, or contact providers.
- Failure modes: no active session returns a no-active-session message; empty
  session logs return an empty state; malformed known event payloads report a
  renderer error instead of mutating state.
- Tests: `tests/unit/test_cli_ledger_commands.py`,
  `tests/unit/test_cli_command_registry.py`, and
  `tests/unit/test_cli_command_completions.py`.

Target behavior:

- Durable ledger browsing, `/ledger verify [bundle]`, audit export, and TUI
  ledger panes remain separate slices.

## Assumption Ledger

Current behavior:

- Responsibilities: validate and project explicit, caller-supplied
  `assumption.recorded` events.
- Inputs: event-backed `AssumptionRecord` payloads with session id, assumption
  id, title, statement, status, confidence, optional run/phase refs,
  evidence/claim/decision/artifact/proof refs, rationale, validation notes,
  privacy class, and redaction status.
- Outputs: closed-schema event payloads and read-only `WorkflowState`
  `evidence_summary` rows with `assumption_count`.
- Persistence: none beyond the generic event surfaces that may carry these
  events. There are no runtime producers, no automatic chat inference, no
  decision/proof cross-reference validation, and no export behavior in this
  slice.
- Failure modes: malformed payloads fail `AgentEvent` validation; projection
  rejects duplicate `assumption_id` values and session mismatches.
- Tests: `tests/unit/test_assumption_ledger.py`,
  `tests/unit/test_agent_events.py`, `tests/unit/test_workflow_state.py`, and
  `tests/unit/test_cli_evidence_commands.py`.

Target behavior:

- TUI assumption panes, assumption producers, validation workflows, and
  export/signing integration remain separate slices.

## CLI Handoff Preview

Current behavior:

- Responsibilities: render read-only `/handoff preview` output from the active
  local CLI session by combining `WorkflowState` projection with the pure
  handoff summary generator.
- Inputs: current session id, in-memory logged events, and event metadata. Extra
  arguments are rejected with usage text so the preview cannot be mistaken for
  path/export behavior.
- Outputs: plain terminal text with session/status/phase/next-action scalars,
  counts, and compact sections for completed phases, blockers, pending
  approvals, active jobs, decisions, evidence, artifacts, failures, and risks.
- Persistence: none. The command does not append `handoff.summary_created`,
  write files, create checkpoints/forks, read durable stores, call backend
  routes, invoke LLM summarization, inspect artifact blobs or log bodies, start
  workflows, or contact providers.
- Failure modes: no active session returns a no-active-session message; empty
  projection renders stale/empty sections; malformed recorded events report a
  renderer error instead of mutating state.
- Tests: `tests/unit/test_cli_handoff_commands.py`,
  `tests/unit/test_cli_command_registry.py`, and
  `tests/unit/test_cli_command_completions.py`.

Target behavior:

- Mutating `/handoff [path]`, durable handoff creation, file export, backend
  handoff routes, and TUI handoff panes remain separate slices.

## Backend API, SSE, And Events

Current behavior:

- Responsibilities: authenticate routes, create/list/delete sessions, submit
  chat/approval operations, stream SSE, replay events by sequence cursor, expose
  redacted messages, operations, workflow state, artifact refs and artifact
  detail, experiment run refs and run detail, health, model config, quotas, and
  flow previews.
- Inputs: HTTP requests, bearer token or `hf_access_token` cookie, JSON bodies,
  SSE cursor query/header, and current session owner.
- Outputs: REST JSON, SSE `data:` messages in legacy `{event_type, data}` shape,
  optional SSE `id:` sequence fields, keepalive comments, and HTTP errors.
- Persistence: event envelopes are appended to SQLite before broadcast when
  possible; public SSE remains compatibility-shaped.
- Failure modes: auth is bypassed when `OAUTH_CLIENT_ID` is absent; inactive or
  unauthorized sessions return 404/403; bad cursors return 400; `/api/health`
  is process health only; `/api/health/llm` depends on provider credentials and
  network.
- Tests: `tests/unit/test_backend_session_sse.py`,
  `tests/unit/test_backend_artifact_index.py`,
  `tests/unit/test_backend_run_index.py`,
  `tests/unit/test_backend_run_detail.py`,
  `tests/unit/test_backend_operation_routes.py`,
  `tests/unit/test_event_store.py`, and
  `tests/unit/test_user_quotas.py`.

Target behavior:

- Public SSE should converge on a documented envelope contract with replay,
  redaction status, schema versioning, and resumable terminal-state behavior.
- Auth, quota, and provider-gating behavior should be documented per deployment
  mode.

## Durable Workflow Projection

Current behavior:

- Responsibilities: derive read-only workflow/project state from persisted
  events, durable session records, and durable operation records; project phase,
  approval, job, artifact, evidence, verifier, and compatibility information.
- Inputs: stored `AgentEvent` envelopes, `SessionRecord`, `OperationRecord`
  lists, flow templates, phase events, and verifier mappings.
- Outputs: `WorkflowState` API responses, frontend project snapshots, evidence
  summaries, active/pending refs, and compatibility warnings.
- Persistence: projection data is read from SQLite stores and in-repo flow
  templates. The projection itself is recomputed.
- Failure modes: missing durable events or records produce partial/stale
  snapshots; redacted refs limit detail; malformed or unsupported templates are
  rejected by template validation.
- Tests: `tests/unit/test_workflow_state.py`,
  `tests/unit/test_flow_templates.py`, `tests/unit/test_flow_preview_api.py`,
  `tests/unit/test_phase_gates.py`, `tests/unit/test_phase_event_persistence.py`,
  `tests/unit/test_evidence_ledger.py`, and verifier/progress tests.

Target behavior:

- Workflow projection should be the stable handoff surface for resumed,
  forked, and audited ML work.
- Snapshot freshness and compatibility warnings should drive UI recovery
  behavior rather than being best-effort hints.

## Frontend Chat Transport And Stores

Current behavior:

- Responsibilities: bridge backend SSE to Vercel AI SDK `UIMessageChunk`
  streams, keep per-session UI state in Zustand, persist browser message caches,
  reconnect to live event streams, hydrate messages/workflow state, and surface
  approvals, tool panels, research progress, quotas, and dead sessions.
- Inputs: backend REST/SSE responses, `AgentEvent` objects, localStorage caches,
  AI SDK approval responses, edited scripts, and active-session selection.
- Outputs: chat messages, panel state, project snapshots, plan state, tool error
  state, approval requests/responses, event cursors, and localStorage entries.
- Persistence: UI messages, backend-format messages, research state, rejected
  tools, tool errors, and event cursors are browser-local best-effort caches.
- Failure modes: backend restart can make a cached session dead; localStorage
  writes can fail; malformed workflow snapshots fall back to compatibility
  warnings; reconnect streams can end or be stale and require hydration.
- Tests: frontend tests under `frontend/src/lib/*.test.ts` plus backend SSE
  tests for the server contract.

Target behavior:

- Frontend recovery should prefer durable backend event replay and workflow
  snapshots over browser-only caches.
- Approval and policy metadata should be rendered from the same structured
  contract used by backend policy decisions.

## Research Subagent

Current behavior:

- Responsibilities: run an independent LiteLLM research loop with a read-only
  tool subset, summarize findings back to the main agent, emit research progress
  logs, and avoid polluting the main conversation context.
- Inputs: research task/context, main session model/HF token, read-only tool
  specs, policy decisions, and retrieved docs/papers/GitHub/Hub content.
- Outputs: concise research summary, research `tool_log` progress, token/tool
  counters, and tool result messages in the subagent context.
- Persistence: research messages are not durable; frontend keeps short
  localStorage research state for recovery while a session is processing.
- Failure modes: unavailable tools, non-read-only HF repo operations,
  approval-required policy results, high-risk policy results, LLM errors,
  context budget limits, and iteration limits stop or constrain research.
- Tests: `tests/unit/test_research_tool_isolation.py`.

Target behavior:

- Retrieved content should be explicitly marked untrusted and summarized with
  citation/source metadata.
- Research outputs should preserve enough provenance for audit and follow-up
  verification without importing raw untrusted text into privileged prompts.
