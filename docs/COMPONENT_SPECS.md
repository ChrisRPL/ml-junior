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
  but runtime tools do not write to it yet.
- Failure modes: job storage is ephemeral unless scripts push artifacts to the
  Hub; missing HF token/namespace, invalid hardware, paid compute, job failure,
  repo permission errors, or network errors surface as tool failures; approved
  mutations can still overwrite or delete remote content.
- Tests: `tests/unit/test_policy_engine.py`,
  `tests/unit/test_tool_router_approval.py`,
  `tests/unit/test_job_artifact_refs.py`, and
  workflow/progress tests that project job refs.

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
  lineage graph records, and sha256 blob digests.
- Outputs: redacted append-only budget ledger rows, deterministic manifest
  diffs, validated lineage graphs, and conventional `~/.mlj/blobs/sha256/...`
  paths.
- Persistence: the budget ledger has an append-only SQLite store for explicit
  records. Dataset lineage and blob helpers are pure models/path conventions
  and perform no filesystem or network I/O.
- Failure modes: duplicate budget records are rejected by
  `(session_id, record_id, source_event_sequence)`; invalid lineage graphs
  reject duplicate/unknown parents and cycles; malformed or weak digests are
  rejected before path derivation.
- Tests: `tests/unit/test_budget_ledger.py`,
  `tests/unit/test_dataset_lineage.py`, and `tests/unit/test_dataset_blobs.py`.

Target behavior:

- Runtime producers should eventually write budget, dataset, lineage, and blob
  references only after policy, privacy, and local/sandbox guardrails are
  explicit.
- Provenance export should start with a local-first manifest plus NDJSON record
  files before optional PROV-JSONLD, OpenLineage, Parquet/DuckDB, or MLMD
  adapters.

## Backend API, SSE, And Events

Current behavior:

- Responsibilities: authenticate routes, create/list/delete sessions, submit
  chat/approval operations, stream SSE, replay events by sequence cursor, expose
  redacted messages, operations, workflow state, health, model config, quotas,
  and flow previews.
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
