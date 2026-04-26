# Current Architecture

Read when: changing agent queues, backend sessions, SSE, tools, approvals,
compaction, or local/sandbox execution.

Status: Phase 0 current-state snapshot for MLJ-P0-006. "Current behavior"
below means implemented in this repository now. "ML Junior target behavior"
means product/runtime direction and must not be treated as shipped behavior.

## Runtime Shape

Current behavior:

- The repo is still branded `ML Intern` in `README.md` and the CLI entrypoint is
  `ml-intern`.
- The runtime is a Python async agent package, a FastAPI backend, and a Vite
  frontend built into the production Docker image.
- The agent loop is queue-driven. Inputs become `Submission` objects containing
  an `Operation`; agent output is accepted through the legacy `Event` shape and
  normalized into internal `AgentEvent` envelopes.
- The default config is `configs/main_agent_config.json`, with an Anthropic
  model, session saving enabled, CPU job confirmation enabled, automatic file
  upload enabled, and one Hugging Face MCP server configured.

ML Junior target behavior:

- Product naming, UX, and persistence should eventually be ML Junior-specific.
- Any target claims about durable sessions, stronger policy, or broader
  production hardening are not current guarantees unless this doc says
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
- There is no durable replay of submissions or events.
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

- Context lives in memory. Session trajectory saving is separate from restoring
  live backend state.
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
- Built-ins include research, HF docs, HF papers, dataset inspection, planning,
  HF Jobs, HF repo files/git, GitHub examples/repos/read-file, and either local
  tools or sandbox tools.
- MCP tools named `hf_jobs`, `hf_doc_search`, `hf_doc_fetch`, and `hf_whoami`
  are skipped to avoid conflicts with built-ins.
- Tool calls go to a Python handler when present. Otherwise they go through the
  FastMCP client if initialized.
- MCP connection failure is non-fatal; the agent continues without MCP tools.

Current limitations:

- Tool availability can change at startup depending on network, MCP, and
  OpenAPI initialization.
- Approval policy is implemented separately from the router.
- MCP tools can currently overwrite built-in tools whose names are not in
  `NOT_ALLOWED_TOOL_NAMES`; for example, an MCP tool named `sandbox_create`
  replaces the built-in registration. This is current behavior, not a target
  security property.
- Existing built-in handlers mostly still return tuples or HF-style dicts; the
  structured model is currently an adapter layer, not a full handler rewrite.

## Approvals

Current behavior:

- `yolo_mode` disables approvals.
- `sandbox_create` requires approval.
- `hf_jobs` run operations require approval. CPU jobs can skip approval only
  when `confirm_cpu_jobs` is false.
- `hf_private_repos.upload_file` requires approval unless `auto_file_upload` is
  true; repo creation requires approval.
- `hf_repo_files.upload/delete` and destructive `hf_repo_git` operations require
  approval.
- Approval requests are batched in one `approval_required` event and stored as
  `Session.pending_approval`.
- Approval responses can approve, reject, add feedback, and edit scripts before
  approved `hf_jobs` execution.
- If the user sends a new message while approval is pending, pending tools are
  abandoned and rejection tool messages are inserted into context.

Current limitations:

- Pending approvals are memory-only.
- Local mode file and shell tools are not approval-gated by this policy.
- The policy only covers the tool names and operations above.

## SSE And Backend API

Current behavior:

- `/api/health` is unauthenticated and returns `status`, `active_sessions`, and
  `max_sessions`.
- `/api/health/llm` makes a provider call and is network/API-key dependent.
- `/api/chat/{session_id}` submits either text or approvals, then streams SSE
  until `turn_complete`, `approval_required`, `error`, `interrupted`, or
  `shutdown`.
- `/api/events/{session_id}` subscribes to events for an existing session.
- SSE payloads are JSON under `data:`. Keepalive comments are sent every 15s.
- Internal agent events are Pydantic `AgentEvent` envelopes with `id`,
  `session_id`, per-session `sequence`, `timestamp`, `event_type`,
  `schema_version`, `redaction_status`, and typed payload validation for the
  current event list.
- Event payloads are passed through targeted redaction before queueing and
  trajectory logging. Redaction covers obvious token/key patterns, bearer auth
  headers, private token URL query params, local user paths, and private dataset
  row previews.
- `Session.get_trajectory()` redacts serialized message copies without mutating
  the live LLM context in `ContextManager`.
- The public SSE payload remains the compatibility shape
  `{ "event_type": "...", "data": { ... } }`; envelope metadata is not emitted
  to the frontend yet.
- The backend subscribes to the broadcaster before submitting work so it does
  not miss same-turn events.

Current limitations:

- `EventBroadcaster` discards events when no subscribers are listening.
- SSE has no replay buffer; reconnects only receive future events.
- Event envelopes are not persisted yet.
- Redaction is targeted and heuristic; new provider token formats or unusual
  private data previews may need additional patterns.
- `/api/events/{session_id}` currently does not enforce `is_processing` despite
  the docstring saying it is for in-progress sessions.

## Current Event List

Current agent/backend events observed in code:

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
- `POST /api/title`: short title generation through an LLM call.
- `POST /api/session`: create session.
- `POST /api/session/restore-summary`: create session from browser-cached
  message summary.
- `GET /api/session/{session_id}`: session metadata.
- `POST /api/session/{session_id}/model`: switch session model.
- `GET /api/user/quota`: Claude quota state.
- `GET /api/sessions`: list accessible sessions.
- `DELETE /api/session/{session_id}`: delete session.
- `POST /api/submit`: enqueue user input.
- `POST /api/approve`: enqueue approval decisions.
- `POST /api/chat/{session_id}`: submit text or approvals and stream same-turn
  SSE.
- `GET /api/events/{session_id}`: subscribe to future events for a session.
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

Headless CLI:

- `ml-intern "prompt text"` runs one yolo-mode turn and exits.

## Session Manager

Current behavior:

- `SessionManager` is a process-local singleton holding `AgentSession` objects
  in a dictionary.
- Session creation deep-copies config per session, creates fresh queues, creates
  `ToolRouter` and `Session` in a worker thread, starts `_run_session()`, and
  returns a UUID.
- Capacity limits are static: 200 global active sessions and 10 per non-dev
  user.
- Session access is owner-based, with `dev` bypass behavior.
- Deleting or ending a session attempts to delete an owned sandbox Space.
- Session info exposes active/processing state, message count, model, owner, and
  pending approvals.

Current limitations:

- Sessions, ownership state, quota flags, and pending approvals are not durable.
- Capacity is count-based only; it does not account for live CPU, memory, or
  provider rate limits.

## Local And Sandbox Modes

Current behavior:

- CLI interactive and headless paths create `ToolRouter(..., local_mode=True)`.
  Local mode provides `bash`, `read`, `write`, and `edit` that operate directly
  on the local filesystem.
- Local mode adds system-prompt context saying there is no sandbox and `/app`
  paths do not apply.
- Headless mode sets `yolo_mode=True`, auto-approving approval-gated calls.
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

- No durable backend session store.
- No SSE replay.
- Provider, HF, MCP, Docker build, and sandbox paths can be network-dependent.
- Some docs and package names still say ML Intern rather than ML Junior.
- `/api/health` is a process health check, not an end-to-end LLM/tool smoke.
- `backend/start.sh` exits 0 after any uvicorn non-zero exit, so Docker start
  must be paired with an HTTP health check.
