# Current Architecture

Read when: changing agent queues, backend sessions, SSE, tools, approvals,
compaction, or local/sandbox execution.

Status: Phase 0 current-state snapshot for MLJ-P0-006. "Current behavior"
below means implemented in this repository now. "ML Junior target behavior"
means product/runtime direction and must not be treated as shipped behavior.

## Runtime Shape

Current behavior:

- The README is branded ML Junior. The installed CLI entrypoints are
  `ml-junior` and the retained compatibility alias `ml-intern`.
- The runtime is a Python async agent package, a FastAPI backend, and a Vite
  frontend built into the production Docker image.
- The agent loop is queue-driven. Inputs become `Submission` objects containing
  an `Operation`; agent output is accepted through the legacy `Event` shape and
  normalized into internal `AgentEvent` envelopes.
- The backend has SQLite-backed durable stores for session metadata, operation
  records, and redacted event envelopes under `session_logs/` by default. Store
  paths can be overridden with `MLJ_SESSION_STORE_PATH`,
  `MLJ_OPERATION_STORE_PATH`, and `MLJ_EVENT_STORE_PATH`.
- The default config is `configs/main_agent_config.json`, with an Anthropic
  model, session saving enabled, CPU job confirmation enabled, automatic file
  upload enabled, and one Hugging Face MCP server configured.

ML Junior target behavior:

- Product naming, UX, executable resume, stronger policy, and broader
  production hardening should eventually be ML Junior-specific.
- Durable metadata stores are current behavior. Restart-safe execution and
  full live-session recovery are target behavior unless this doc says
  "Current behavior".

## Queues And Agent Loop

Current behavior:

- Each session owns a `submission_queue` and an `event_queue`.
- `OpType` supports `user_input`, `exec_approval`, `interrupt`, `undo`,
  `compact`, and `shutdown`.
- `SessionManager.submit()` enqueues work. `_run_session()` drains the queue,
  marks `is_processing`, and calls `process_submission()`.
- `Handlers.run_agent()` appends the user message, emits `processing`, calls
  LiteLLM, executes tool calls, stores tool results, and emits terminal events.
- Non-approval tool calls in a single LLM response are executed concurrently.
- Interrupts set `Session._cancelled` directly instead of waiting behind queued
  work.

Current limitations:

- Queues are in process only. A backend restart loses active work.
- Submitted operations are durably recorded, but a restart does not rebuild
  in-flight queues or resume a partially processed operation.
- Persisted event envelopes support API replay by sequence cursor; they are
  replay of emitted events, not execution replay.
- One session task processes queued operations serially, even though tools
  inside a turn may run concurrently.

## Context Manager

Current behavior:

- `ContextManager` stores LiteLLM `Message` objects in memory, beginning with a
  rendered system prompt from `agent/prompts/system_prompt_v3.yaml`.
- The system prompt includes current time, resolved HF username when a token is
  available, tool count, and local-mode context when enabled.
- `Session` derives model context size from LiteLLM model metadata, falling back
  to 200k tokens.
- `running_context_usage` is updated from LLM usage token counts when messages
  are added with `token_count`.
- Compaction triggers above 90% of `model_max_tokens`. It preserves the system
  message, the first user message, and a recent tail, then summarizes the middle
  with an LLM call.
- Browser restore uses `SessionManager.seed_from_summary()` with a restore
  prompt that turns cached messages into a new user-role memory note.

Current limitations:

- Context lives in memory. Durable session/event/operation records and session
  trajectory saving do not reconstruct live `ContextManager` state.
- Compaction and restore-summary require a working LLM/provider path.
- Token accounting depends on provider usage data until post-compact recount.
- Dangling tool calls are patched with stub tool results so later LLM calls stay
  valid, but this is recovery behavior, not full execution replay.

## ToolRouter

Current behavior:

- `ToolRouter` registers built-in tools, then optional MCP tools, then an
  OpenAPI search tool during async initialization.
- `ToolRouter.call_tool()` still returns the legacy `(output_string,
  success_bool)` tuple to the orchestrator.
- `ToolRouter.call_tool_result()` is the structured compatibility path. It
  normalizes legacy tuple handlers, HF-style `formatted` dictionaries, and MCP
  content blocks into `agent.core.tool_results.ToolResult`.
- `ToolResult` carries `display_text`, `success`, optional `ToolError`,
  `ArtifactRef`, `MetricRecord`, `SideEffect`, raw value, and metadata fields.
- `ToolSpec` carries the LLM-facing name, description, parameters, optional
  Python handler, and optional policy metadata.
- Built-ins include research, HF docs, HF papers, dataset inspection, planning,
  HF Jobs, HF repo files/git, GitHub examples/repos/read-file, and either local
  tools or sandbox tools.
- MCP tools are exposed to the LLM as `mcp__{server}__{tool}` using deterministic
  normalization, with an origin map back to the configured server and raw tool
  name. Raw MCP tools named `hf_jobs`, `hf_doc_search`, `hf_doc_fetch`, and
  `hf_whoami` are skipped to avoid conflicts with built-ins.
- User HF tokens are forwarded to MCP servers only when the configured server
  name appears in `trusted_hf_mcp_servers`; explicit `Authorization` headers in
  an MCP server config are preserved and not overwritten.
- Tool calls are evaluated by router policy before execution. Calls go to a
  Python handler when present. Registered namespaced MCP calls go through the
  FastMCP client with their original raw tool name. Unknown raw MCP tool names
  are blocked rather than forwarded.
- MCP connection failure is non-fatal; the agent continues without MCP tools.

Current limitations:

- Tool availability can change at startup depending on network, MCP, and
  OpenAPI initialization.
- Generic MCP tools remain conservatively approval-gated until a narrower policy
  exists for a specific tool/server.
- Existing built-in handlers mostly still return tuples or HF-style dicts; the
  structured model is currently an adapter layer, not a full handler rewrite.

## PolicyEngine And ToolMetadata

Current behavior:

- `agent.core.policy` defines `RiskLevel`, `ToolMetadata`, `PolicyDecision`,
  and `PolicyEngine.evaluate(...)`.
- `ToolSpec` carries optional policy metadata. Built-in sandbox/local, HF,
  GitHub, docs, research, and plan tools are registered with metadata; MCP
  tools receive generic MCP metadata at registration.
- `ToolRouter.evaluate_policy(...)` evaluates a registered tool call before
  execution. `ToolRouter.call_tool_result(...)` denies policy-blocked calls and
  refuses approval-required calls unless the caller passes the approved
  execution flag used by `exec_approval`.
- The research subagent uses a read-only tool surface. It does not expose
  `bash`, blocks fabricated mutating tools before router policy, restricts
  `hf_repo_files` to `list`/`read`, and still consults router policy before
  execution without passing the approved execution flag.
- `agent.core.agent_loop._needs_approval(...)` remains as a compatibility shim
  backed by `PolicyEngine.evaluate(...)`.
- `approval_required` event payloads include tool name, arguments, tool call
  ID, risk, side effects, rollback notes, budget impact, credential usage, and
  reason. Pending approval session info carries the same additive metadata.
- `yolo_mode` and compatible autonomy/approval modes skip approval while
  preserving risk metadata. `confirm_cpu_jobs` and `auto_file_upload` remain
  policy inputs.

Current limitations:

- Generic MCP tools remain approval-gated until a narrower policy exists for a
  specific trusted tool/server.
- Local and sandbox path/command guardrails are still tracked by `MLJ-TPS-006`.

## Approvals

Current behavior:

- `yolo_mode` disables approvals.
- `sandbox_create` requires approval.
- `hf_jobs` run operations require approval. CPU jobs can skip approval only
  when `confirm_cpu_jobs` is false.
- Legacy `hf_private_repos` policy is still modeled for compatibility tests,
  but that built-in is currently disabled in favor of `hf_repo_files` and
  `hf_repo_git`.
- `hf_repo_files.upload/delete`, `hf_repo_git` mutations, local/sandbox
  shell/write/edit operations, and generic MCP tools require approval.
- Approval requests are batched in one `approval_required` event and stored as
  `Session.pending_approval`.
- Approval responses can approve, reject, add feedback, and edit scripts before
  approved `hf_jobs` execution.
- If the user sends a new message while approval is pending, pending tools are
  abandoned and rejection tool messages are inserted into context.

Current limitations:

- Pending approval execution state is memory-only. Durable session records keep
  redacted pending approval refs for visibility and workflow projection, but
  they cannot resume an approval after restart.
- The approval center is still UI-first around existing approval flows; richer
  rendering of policy metadata belongs to `MLJ-UX-004`.

## SSE And Backend API

Current behavior:

- `/api/health` is unauthenticated and returns `status`, `active_sessions`, and
  `max_sessions`.
- `/api/health/llm` makes a provider call and is network/API-key dependent.
- `/api/chat/{session_id}` submits either text or approvals, then streams SSE
  until `turn_complete`, `approval_required`, `error`, `interrupted`, or
  `shutdown`.
- `/api/events/{session_id}` subscribes to events for an existing active
  session. When `after_sequence`, `after`, or `Last-Event-ID` is supplied, it
  replays persisted events after that sequence before live events.
- SSE payloads are JSON under `data:`. Events with a sequence also include
  `id: <sequence>`. Keepalive comments are sent every 15s.
- Internal agent events are Pydantic `AgentEvent` envelopes with `id`,
  `session_id`, per-session `sequence`, `timestamp`, `event_type`,
  `schema_version`, `redaction_status`, and typed payload validation for the
  current event list.
- `EventBroadcaster` reads from the session event queue, persists redacted
  `AgentEvent` envelopes through `SQLiteEventStore`, then fans out the stored
  event to current subscribers.
- Event payloads are passed through targeted redaction before queueing and
  trajectory logging. Redaction covers obvious token/key patterns, bearer auth
  headers, private token URL query params, local user paths, and private dataset
  row previews.
- `Session.get_trajectory()` redacts serialized message copies without mutating
  the live LLM context in `ContextManager`.
- Session auto-save and detached upload use `Session.get_trajectory()`, and the
  detached uploader redacts loaded legacy JSON again before JSONL upload.
- `GET /api/session/{session_id}/messages` returns redacted serialized copies
  for browser/cache recovery without mutating live `ContextManager` messages.
- The public SSE payload remains the compatibility shape
  `{ "event_type": "...", "data": { ... } }`; envelope metadata is not emitted
  inside `data:`. Replay currently exposes the sequence through the SSE `id:`
  field rather than a public envelope contract.
- The backend subscribes to the broadcaster before submitting work so it does
  not miss same-turn events.

Current limitations:

- Live fan-out only reaches current subscribers; clients recover missed events
  by reconnecting to `/api/events/{session_id}` with a stored sequence cursor.
- Replay is session-scoped and sequence-based. It does not rebuild backend
  queues, pending LLM calls, sandbox handles, or live `ContextManager` state.
- `/api/chat/{session_id}` is a live same-turn stream and does not accept replay
  cursors; cursor replay is on `/api/events/{session_id}`.
- If the process is down, no new events are produced. Already stored events
  remain queryable after restart through the event store.
- `redaction_status` and other envelope metadata are internal-only today; public
  SSE remains legacy-shaped for compatibility.
- Redaction is targeted and heuristic; new provider token formats or unusual
  private data previews may need additional patterns.
- `/api/events/{session_id}` currently does not enforce `is_processing` despite
  the docstring saying it is for in-progress sessions.

## Workflow Projection And Flow Templates

Current behavior:

- `GET /api/session/{session_id}/workflow` returns a read-only `WorkflowState`
  projection for any accessible durable session.
- The projection is recomputed from persisted `AgentEvent` envelopes, the
  durable `SessionRecord`, and durable `OperationRecord` rows. It exposes
  status, phase, plan items, blockers, pending approvals, active jobs,
  operation refs, human requests, budget summaries, evidence summary, live
  tracking placeholders, last event sequence, and resume cursor metadata.
- `WorkflowResumeState.can_resume` is `false` with reason
  `executable_resume_not_implemented`; the cursor is informational for replay
  and UI hydration.
- Phase events, plan updates, approval events, tool state/output events, active
  job refs, artifact/metric/log refs, evidence items, evidence claim links,
  decision/proof records, budget records, human requests, and verifier verdicts
  project into workflow state when those events exist.
- Budget projection is read-only. It aggregates recorded budget limit/usage
  events into totals and ledger rows. An append-only redacted SQLite budget
  ledger store can persist explicit caller-supplied limit/usage records, but
  no runtime producer writes to it and it does not reserve, spend, or enforce
  quota.
- Active job and artifact records also have an inert append-only SQLite store
  for caller-supplied refs. Nothing wires that store to job launch, polling,
  artifact discovery, routes, or workflow producers yet.
- Dataset lineage currently exists as closed, caller-supplied manifest/diff
  models, an inert transform/filter/augment/merge lineage DAG schema, and pure
  sha256 blob digest/path conventions. Experiment run records can reference
  dataset manifests and lineage ids directly as explicit schema-only refs,
  alongside existing dataset snapshot refs. This does not create snapshots,
  infer lineage, walk files, read/write blob caches, call datasets/HF services,
  or emit runtime events.
- Built-in flow templates live under `backend/builtin_flow_templates/`.
  `GET /api/flows` returns the read-only catalog. `GET
  /api/flows/{template_id}/preview` returns inputs, required inputs, budgets,
  phases, approvals, expected outputs/artifacts, verifier checks, verifier
  catalog coverage, risky operations, and source metadata.
- `GET /api/flow-sources` returns read-only source descriptors. `builtin` is
  available and trusted; `custom` and `community` are reserved disabled sources
  with no upload, local directory loading, or remote fetch behavior.
- CLI `/flows` and `/flow preview <id>` use the same backend flow-template
  helpers and are read-only.

Current limitations:

- Workflow state is a projection, not an executable workflow engine. Flow
  start, pause, resume, and fork are not implemented.
- Projection quality depends on which events have been emitted. Compatibility
  warnings can include placeholder producer names such as workflow events,
  budget ledger, evidence ledger, or live tracking.
- Stored operation refs are useful for inspection and projection, but they do
  not make queued work restartable.

ML Junior target behavior:

- Workflow projection should become the stable handoff and recovery surface for
  resumed, forked, and audited ML work.
- Flow start/pause/resume/fork should become real operations only after the
  backend has executable workflow state and policy coverage.

## Current Event List

Current agent/backend event types validated or projected in code:

- `ready`: session loop initialized.
- `processing`: a user input turn started.
- `assistant_chunk`: streamed assistant content delta.
- `assistant_message`: non-streaming assistant content.
- `assistant_stream_end`: streaming assistant output ended.
- `tool_call`: tool execution was requested.
- `tool_output`: tool execution produced an output and success flag.
- `tool_log`: tool/system log line.
- `tool_state_change`: approval/runtime state change for an existing tool call.
- `approval_required`: one or more tool calls require user approval.
- `plan_update`: plan tool emitted a full todo list.
- `phase.not_started`, `phase.pending`, `phase.started`, `phase.blocked`,
  `phase.completed`, `phase.failed`, and `phase.verified`: phase state
  projection events.
- `checkpoint.created`, `fork_point.created`, and `handoff.summary_created`:
  project continuity metadata.
- `dataset_snapshot.recorded`, `code_snapshot.recorded`,
  `experiment.run_recorded`, `metric.recorded`, `log_ref.recorded`,
  `active_job.recorded`, and `artifact_ref.recorded`: experiment and artifact
  ledger metadata.
- `evidence_item.recorded`, `evidence_claim_link.recorded`, and
  `verifier.completed`: evidence/verifier metadata for workflow projection.
- `decision_card.recorded` and `proof_bundle.recorded`: inert decision/proof
  metadata for future audit bundles. They validate explicit caller-supplied
  records and project into `evidence_summary`, but do not sign, export, or
  block final answers.
- `budget.limit_recorded` and `budget.usage_recorded`: inert budget limit and
  usage ledger metadata. They validate explicit caller-supplied records and
  project into `WorkflowState.budget`, but do not enforce spend caps, consume
  quota, or launch/poll jobs.
- `human_request.requested` and `human_request.resolved`: human-in-the-loop
  workflow metadata.
- `compacted`: context compaction changed token usage.
- `undo_complete`: undo operation completed.
- `interrupted`: running turn/tool was interrupted.
- `turn_complete`: turn reached a normal terminal state.
- `error`: route/session/loop surfaced an error.
- `shutdown`: session shutdown completed.

Terminal SSE events:

- `turn_complete`
- `approval_required`
- `error`
- `interrupted`
- `shutdown`

## Current API And Command List

Backend routes:

- `GET /api`: API root.
- `GET /api/health`: process health check.
- `GET /api/health/llm`: network/API-key-dependent LLM health probe.
- `GET /api/config/model`: current and available models.
- `GET /api/flows`: read-only built-in flow catalog.
- `GET /api/flow-sources`: read-only source descriptors for builtin, custom,
  and community template sources.
- `GET /api/flows/{template_id}/preview`: read-only flow template preview.
- `POST /api/title`: short title generation through an LLM call.
- `POST /api/session`: create session.
- `POST /api/session/restore-summary`: create session from browser-cached
  message summary.
- `GET /api/session/{session_id}`: session metadata.
- `GET /api/session/{session_id}/workflow`: read-only workflow projection.
- `GET /api/session/{session_id}/operations`: redacted durable operation list.
- `GET /api/session/{session_id}/operations/{operation_id}`: one redacted
  durable operation scoped to the session.
- `POST /api/session/{session_id}/model`: switch session model.
- `GET /api/user/quota`: Claude quota state.
- `GET /api/sessions`: list accessible sessions.
- `DELETE /api/session/{session_id}`: delete session.
- `POST /api/submit`: enqueue user input.
- `POST /api/approve`: enqueue approval decisions.
- `POST /api/chat/{session_id}`: submit text or approvals and stream same-turn
  SSE.
- `GET /api/events/{session_id}`: subscribe to live events, optionally replaying
  persisted events after a sequence cursor.
- `POST /api/interrupt/{session_id}`: signal cancellation.
- `GET /api/session/{session_id}/messages`: in-memory message history.
- `POST /api/undo/{session_id}`: enqueue undo.
- `POST /api/truncate/{session_id}`: truncate before a user message.
- `POST /api/compact/{session_id}`: enqueue compaction.
- `POST /api/shutdown/{session_id}`: enqueue shutdown.

Current CLI slash commands:

- `/help`
- `/undo`
- `/compact`
- `/model [id]`
- `/effort [minimal|low|medium|high|xhigh|max|off]`
- `/yolo`
- `/status`
- `/quit` and `/exit`
- `/flows`
- `/flow preview <id>`

Current slash command registry/completion additions:

- The parser and prompt completer know implemented and planned command
  metadata: group, risk level, mutating/read-only status, aliases, and required
  backend capability.
- Implemented command aliases include `/exit`, `quit`, and `exit` for `/quit`.
- Planned project commands are registered for help/completion only: `/new`,
  `/open`, `/handoff`, `/export`, and `/doctor`.
- Planned flow/workflow commands are registered for help/completion only:
  `/flow start`, `/flow pause`, `/flow resume`, `/flow fork`, `/phase`, and
  `/plan`.
- Planned experiment/tool/evidence/code commands are registered for
  help/completion only, including `/runs`, `/run show`, `/tools`, `/jobs`,
  `/approve`, `/deny`, `/ledger verify`, `/diff`, `/test`, `/commit`, and
  `/pr`. They print a capability-required message instead of executing.

Headless CLI:

- `ml-junior "prompt text"` runs one local-mode turn and exits. The
  compatibility alias `ml-intern "prompt text"` uses the same entrypoint.
- Approval-gated tool calls stop headless execution and print the pending
  approvals unless the user passes `--yolo` / `--auto-approve`.

## Session Manager

Current behavior:

- `SessionManager` holds live `AgentSession` objects in a process-local
  dictionary and lazily initializes SQLite session, operation, and event stores.
- Session creation deep-copies config per session, creates fresh queues, creates
  `ToolRouter` and `Session` in a worker thread, starts `_run_session()`, and
  returns a UUID.
- Session creation also writes a durable session record with owner, model,
  status, and empty pending approval/active job refs.
- Submitted user input, approval, undo, compact, and shutdown operations are
  written to the durable operation store before being enqueued. `_run_session()`
  transitions them through running and terminal states with redacted
  result/error payloads.
- Interrupt and truncate operations are recorded too, but they act directly on
  the live session instead of waiting behind queued work.
- `EventBroadcaster` persists redacted event envelopes to the event store before
  live fan-out.
- Session refs for pending approvals and active jobs are snapshotted into the
  durable session record as redacted metadata. Ending, deleting, or shutting
  down a session marks the durable session record closed.
- `replay_events()`, `list_operations()`, `get_operation()`, and
  `get_workflow_state()` read from the durable stores.
- Capacity limits are static: 200 global active sessions and 10 per non-dev
  user.
- Session access is owner-based, with `dev` bypass behavior.
- Deleting or ending a session attempts to delete an owned sandbox Space.
- Session info exposes active/processing state, message count, model, owner, and
  pending approvals. For durable-only sessions, it returns stored owner/model
  metadata with inactive/zero-message live state.
- Listing sessions merges durable session rows and live sessions.

Current limitations:

- Live `AgentSession` objects, queues, `ContextManager` messages, sandbox
  handles, HF tokens, quota flags, and approval execution state are
  process-local.
- Durable session records persist metadata and redacted refs, but backend
  restart does not recreate active session tasks.
- Capacity checks count live in-process sessions, not active durable rows from a
  prior process.
- Capacity is count-based only; it does not account for live CPU, memory, or
  provider rate limits.

## Local And Sandbox Modes

Current behavior:

- CLI interactive and headless paths create `ToolRouter(..., local_mode=True)`.
  Local mode provides `bash`, `read`, `write`, and `edit` that operate directly
  on the local filesystem.
- Local mode adds system-prompt context saying there is no sandbox and `/app`
  paths do not apply.
- Headless mode sets `yolo_mode=True` only when `--yolo` /
  `--auto-approve` is passed. Without that flag, approval-gated calls are
  reported and the headless run exits without executing them.
- Local model ids `local/ollama/<model>` and `local/llamacpp/<alias>` resolve
  to OpenAI-compatible local `/v1` endpoints with a dummy local API key. Base
  URLs come from local inference env vars, optional config fields, then
  defaults. Endpoint resolution is pure validation: it allows localhost,
  container-host aliases, and private IP addresses, and it does not probe the
  daemon or make a provider call.
- Local inference probe helpers are also pure metadata/classification helpers.
  They build intended `/v1/models` probe descriptors and classify
  caller-supplied payloads or errors; they do not perform network I/O or start
  local daemons. Endpoint resolution and probe logic live in separate helper
  modules behind the compatibility `agent.core.local_inference` facade.
- Backend-created sessions use sandbox mode by default. Sandbox mode exposes
  `sandbox_create`, `bash`, `read`, `write`, and `edit` backed by a Hugging Face
  Space sandbox.
- Current sandbox operation handlers attempt to auto-create a CPU sandbox when
  no active sandbox exists, but this still requires session context, an HF
  token, and network/HF API access. `sandbox_create` remains the explicit,
  approval-gated sandbox creation tool.

Current limitations:

- Sandbox creation and operation require HF token/network access.
- Local tool read-before-write/edit protection is process-local memory only.

## Current Limitation Summary

- Durable stores cover session metadata, operation records, and event envelopes,
  but live queues, context, sandbox handles, tokens, quota flags, and executable
  resume remain process-local.
- SSE replay exists for `/api/events/{session_id}` with sequence cursors, but
  `/api/chat/{session_id}` remains a live same-turn stream and public payloads
  stay legacy-shaped.
- Workflow state is a read-only projection. Flow catalog/preview are shipped;
  flow start/pause/resume/fork are planned only.
- Provider, HF, MCP, Docker build, and sandbox paths can be network-dependent.
- Some internal docs, package names, and compatibility paths still say
  ML Intern rather than ML Junior.
- `/api/health` is a process health check, not an end-to-end LLM/tool smoke.
- `backend/start.sh` exits 0 after any uvicorn non-zero exit, so Docker start
  must be paired with an HTTP health check.
