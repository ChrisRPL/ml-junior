# Security Policy

read_when: changing credentials, authentication, MCP, local execution, sandbox
execution, Hub publishing, HF Jobs, compute spend, redaction, retrieved content,
or policy/approval behavior.

Status: security policy skeleton for current code. "Current behavior" marks
implemented controls. "Target behavior" marks required direction and must not
be presented as shipped protection.

## Assets

Current behavior protects or handles these assets:

- User HF OAuth tokens from `Authorization: Bearer`, `hf_access_token` cookies,
  or `HF_TOKEN` fallback.
- Server provider credentials such as `OPENAI_API_KEY`, Anthropic/Bedrock
  credentials, and config values substituted from `.env`.
- Session messages, tool arguments, tool outputs, approvals, event logs, and
  trajectory uploads.
- Local filesystem data in CLI local mode.
- Remote sandbox files/processes and HF Jobs compute.
- Hugging Face Hub models, datasets, Spaces, branches, tags, PRs, and files.
- MCP server credentials and retrieved MCP content.
- Browser localStorage caches for UI and backend-format messages.

Target behavior:

- Every credential-bearing asset should have an owner, scope, lifetime,
  storage location, and redaction classification.
- Durable audit records should link approvals, side effects, credentials used,
  spend class, and rollback notes.

## Trust Boundaries

Current behavior:

- Browser to backend: authenticated in production by HF token/cookie; dev mode
  bypasses auth when `OAUTH_CLIENT_ID` is not set.
- Backend to model providers: LiteLLM calls use server or user-routed
  credentials depending on model/provider path.
- Backend to Hugging Face: tools use the session HF token when available.
- Backend to MCP: only configured servers are used; tools are namespaced and
  registered before invocation.
- Agent to local machine: CLI local mode exposes local `bash/read/write/edit`.
- Agent to local inference daemon: planned local Ollama and llama.cpp endpoints
  are local machine or private-network services selected by explicit
  `local/...` model ids. They are trusted only as user-controlled local
  processes, not as remote providers.
- Agent to sandbox/Jobs: backend mode exposes HF Space sandbox tools and HF
  Jobs through approval policy.
- Retrieved content to model context: docs, papers, GitHub files, datasets, Hub
  repo files, and MCP output are untrusted tool outputs.

Target behavior:

- Untrusted retrieved content should be tagged before it enters prompts,
  durable stores, or UI projections.
- Deployment mode should make auth bypass, provider credential source, and
  token forwarding behavior explicit.

## Credentials

Current behavior:

- Config supports `${VAR}` substitution and loads `.env` from the project root.
- Auth is disabled in dev mode when `OAUTH_CLIENT_ID` is absent; production
  validates bearer/cookie tokens against HF OAuth and caches user info briefly.
- Session creation extracts the HF token from bearer header, cookie, then
  `HF_TOKEN` env fallback. The token is stored in memory on the session for
  tool execution.
- Anthropic model selection is gated to members of `HF_EMPLOYEE_ORG`
  (default `huggingface`) because it uses server-side Anthropic/Bedrock billing.
- Direct OpenAI models require server `OPENAI_API_KEY`.
- Redaction covers common HF, GitHub, bearer, opaque provider, env assignment,
  key/value, URL query secret, CLI flag, and local user path patterns.

Current limits:

- HF tokens in live sessions are memory-resident and not a formal token vault.
- Environment fallback can make local/dev behavior broader than a specific
  authenticated user's token.
- Redaction is pattern-based and can miss new token formats or unusual payloads.

Target behavior:

- Production should avoid broad env-token fallback for user-scoped side effects
  unless explicitly configured.
- Credential use should be recorded as policy metadata on every tool result and
  event that crosses a trust boundary.
- Token scopes, rotation, revocation, and retention rules should be documented
  per deployment.

## MCP

Current behavior:

- MCP servers come from config and are initialized per `ToolRouter`.
- Raw MCP tools are exposed only through normalized names
  `mcp__{server}__{tool}`.
- Raw MCP tools named `hf_jobs`, `hf_doc_search`, `hf_doc_fetch`, and
  `hf_whoami` are skipped to prevent replacement of built-ins.
- Duplicate or colliding namespaced MCP tools are skipped.
- User HF tokens are forwarded only to servers listed in
  `trusted_hf_mcp_servers`, and explicit `Authorization` headers in MCP config
  are preserved.
- Generic MCP tools carry MCP metadata and require approval unless a narrower
  policy is registered.
- Unknown/unregistered MCP calls are blocked even with approval.

Current limits:

- Trust is server-name based, not a reviewed per-tool capability manifest.
- MCP output is converted into ordinary tool output and is not yet separately
  tagged as untrusted content.

Target behavior:

- Each MCP server should have an allowlist of tools, credential scope, data
  handling class, and approval policy.
- MCP outputs should be labeled as external untrusted content in prompts,
  storage, and UI.

## Local Execution

Current behavior:

- CLI interactive/headless paths use local mode and expose
  `bash/read/write/edit` on the user's filesystem.
- Local paths must resolve inside allowed roots from
  `MLJ_LOCAL_ALLOWED_ROOTS`, `MLJ_LOCAL_WORKSPACE_ROOT`, config roots, or the
  current working directory.
- Local `write` and `edit` require the file to have been read earlier in the
  process.
- Local shell policy blocks known destructive commands such as remove/delete
  commands, `git reset --hard`, `git clean`, `git restore`, `git rm`,
  `find -delete`, `dd of=`, and disk erase/format operations.
- Policy requires approval for local shell and filesystem writes unless
  `yolo_mode` or compatible autonomy settings auto-approve.

Local inference:

- Local model ids resolve only to OpenAI-compatible Ollama or llama.cpp `/v1`
  endpoints on localhost, container-host aliases, or private IP addresses.
- Endpoint resolution and local inference probe helpers are validation and
  classification helpers; they do not perform network I/O, start daemons, pull
  models, or write config.
- Local inference doctor reports are also pure. They combine already supplied
  descriptors/classifications into redacted status and remediation text.
- `/doctor local-inference` is a read-only CLI renderer for local metadata and
  config-error reports. It does not probe daemons, perform provider calls, pull
  models, or write config.
- Any future `/doctor local-inference` daemon-response classification must
  treat daemon responses as untrusted local process output and redact secrets,
  auth headers, token query parameters, local user paths, prompts, and response
  bodies.
- Local inference must not reuse remote provider API keys. Dummy local API keys
  are acceptable only for OpenAI-compatible client wiring.
- CLI backend index mode is opt-in through `MLJ_BACKEND_BASE_URL` and
  `MLJ_BACKEND_SESSION_ID`. It may attach only `MLJ_BACKEND_BEARER_TOKEN` as a
  bearer token, reads only run/artifact index JSON, applies terminal redaction,
  and must not submit messages, replay sessions, inspect artifact blobs, call
  providers/Trackio, or emit events.
- `/evidence` is a read-only current-session renderer over existing workflow
  evidence summary event rows. It applies terminal redaction and must not read
  durable stores, create/link evidence, verify claims, sign/export proof
  bundles, inspect artifact blobs or log bodies, ingest metrics, contact
  providers/Trackio, or emit events.
- `/decisions` is a read-only current-session renderer over existing decision
  cards in the workflow evidence summary. It applies terminal redaction and
  must not read durable stores, create/edit decisions, infer assumptions,
  sign/export proof bundles, inspect artifact blobs or log bodies, contact
  providers/Trackio, or emit events.
- `assumption.recorded` is an inert explicit-event contract. It must not be
  produced from implicit chat summarization, must preserve privacy/redaction
  metadata, and currently has no mutating CLI command, runtime producer, export
  path, or public sharing path. `/assumptions` may render only current-session
  projected assumption rows and must not create, update, infer, export, or share
  assumptions.
- `/ledger` is a read-only current-session renderer over redacted event
  envelope metadata only. It may show sequence, event id/type, timestamp,
  schema version, redaction status, safe top-level refs, and top-level payload
  keys. It must not read durable stores, display full payload/body/blob/log
  values, verify ledgers, sign/export/share, contact providers, or emit events.
- Policy approval audit contracts exist for trust-sensitive planned commands:
  `/share-traces public|private`, `/ledger verify [bundle]`, and `/proof bundle
  [run]`. The contracts are inert and define approval text, risk, side effects,
  rollback, credential usage, privacy defaults, audit event names, required
  audit fields, redaction requirements, and preconditions. Closed
  `policy.audit_intent_recorded` and `policy.audit_result_recorded` payload
  schemas and inert projection helpers exist so future audit writers fail
  closed on unknown fields, session mismatch, duplicate ids, and missing
  intent/result correlation. Pure builders now create validated, redacted
  intent/result payload drafts from contracts plus explicit caller metadata and
  fail closed on missing stage-specific audit fields, unknown commands or
  arguments, unknown payload fields, protected-field overrides, missing
  correlation ids, public trace sharing without acknowledgement/redaction, and
  mismatched result correlation. They must be used before implementing those
  commands, but they do not by themselves permit execution, remote visibility
  changes, verification, signing, export, or audit emission.
- Pure `MLJ-TPS-014d` `AgentEvent` envelope builders wrap already-built policy
  audit drafts into validated, redacted envelopes and fail closed on unknown
  event types. They do not append events, write durable audit rows, dispatch
  commands, call providers/HF/network, add backend routes, add UI/TUI surfaces,
  or enable audit emission.
- `/handoff preview` is a read-only current-session renderer over redacted
  logged events, workflow projection, and the pure handoff summary generator. It
  must not emit `handoff.summary_created`, write/export files, read durable
  stores, call backend routes, create checkpoints/forks, invoke LLM
  summarization, inspect artifact blobs or log bodies, start/resume/fork
  workflows, contact providers, or mutate state. `/handoff [path]` remains
  planned and mutating until its durable write/export policy is explicit.

Current limits:

- Read-before-write/edit state is process-local memory.
- Shell blocking is pattern/classification based and cannot prove arbitrary
  shell commands are safe.
- Headless CLI stops on approval-gated calls unless the user explicitly passes
  `--yolo` or `--auto-approve`.
- A local daemon can read prompts sent to it and may have its own plugins,
  logging, model cache, or network behavior outside ML Junior's control.

Target behavior:

- Local execution should have a reviewed workspace manifest, command allow/deny
  policy, durable audit trail, and explicit user confirmation for high-risk
  classes even in automated modes.
- Destructive commands should require an explicit out-of-band override, not only
  general tool approval.
- `/doctor local-inference` should remain read-only and no-network in tests by
  accepting fake-server or caller-supplied response/error payloads for
  classification.

## Sandbox Execution

Current behavior:

- Backend-created sessions use sandbox mode by default.
- `sandbox_create` is approval-gated and creates an HF Space sandbox using the
  session HF token.
- Sandbox operation tools require an active sandbox.
- Sandbox paths are normalized and limited to `/app` and `/tmp`.
- Sandbox output/log text is redacted against known session secrets and general
  redaction rules.
- Owned sandbox Spaces are deleted during session cleanup when possible.

Current limits:

- Sandbox creation and operation depend on HF network/API availability.
- Cleanup failure is non-fatal and can leave remote resources behind.
- Sandbox resource spend is represented as policy metadata but not enforced by
  a hard budget in code.

Target behavior:

- Sandbox lifecycle should include durable resource ids, owner, hardware,
  timeout, spend class, and cleanup status.
- Sandbox logs should keep structured redaction status and source labels.

## HF Jobs And Compute Spend

Current behavior:

- `hf_jobs` read/status operations do not require approval.
- `hf_jobs` `run`, `uv`, `scheduled run`, and `scheduled uv` require approval.
- Explicit non-scheduled CPU job approval can be disabled by
  `confirm_cpu_jobs=false`; scheduled CPU jobs, GPU jobs, and missing/unknown
  hardware still require approval.
- Approval metadata includes risk, side effects, rollback, budget impact,
  credential usage, and reason.
- HF Jobs approval metadata uses a pure local compute risk helper for known
  hardware flavors and user-supplied duration, including uncertainty for
  scheduled or unknown hardware. It does not call HF services or mutate budget
  state.
- Running job ids are tracked in session memory and cancel attempts are made on
  interrupt.
- Claude quota is charged at first Anthropic message submit per session.

Current limits:

- Inert budget limit and usage ledger records can now be validated as
  `AgentEvent` payloads, projected into workflow state, and persisted in an
  append-only redacted SQLite store when supplied explicitly. No runtime
  producer emits them yet.
- There is still no hard spend cap for HF Jobs, and the budget ledger does not
  enforce, reserve, or consume quota.
- Running job refs are still produced by runtime memory, while an inert
  append-only job/artifact store exists only for explicit caller-supplied refs.
  It is not wired to job launch, polling, cancellation, or artifact discovery.
- Job storage is ephemeral unless scripts publish artifacts to the Hub.

Target behavior:

- Job launch approval should show estimated hardware cost, timeout, token/secret
  use, artifact persistence plan, and cancellation path.
- Org/user spend caps should be enforced before remote compute starts.

## Hub Publishing

Current behavior:

- `hf_repo_files` list/read operations are read-only.
- `hf_repo_files` upload/delete require approval.
- `hf_repo_git` read operations are allowed; branch/tag/PR/repo mutations
  require approval.
- Uploads can use `create_pr=true` when the tool arguments request it.
- Session trajectory auto-save and detached upload are enabled by config and
  use redacted trajectory data.

Current limits:

- Direct uploads/deletes can mutate persistent Hub state after approval.
- `auto_file_upload` exists for legacy private repo behavior; current
  `hf_repo_files` mutations remain approval-gated.
- Publishing policy does not yet classify model cards, dataset cards, private
  data, licenses, or generated artifacts.

Target behavior:

- Default publishing should prefer PRs or draft changes for non-trivial writes.
- Any Hub publication should record license/privacy class, artifact lineage,
  source data sensitivity, and rollback instructions.

## Redaction And Logging

Current behavior:

- `AgentEvent.redacted_copy()` redacts event payloads before queueing/logging.
- SQLite event, operation, and session stores persist redacted payloads/refs and
  retain redaction status fields.
- `Session.get_trajectory()` redacts serialized messages without mutating the
  live context.
- `/api/session/{session_id}/messages` returns redacted serialized copies.
- Detached session upload redacts loaded legacy JSON again before JSONL upload.

Current limits:

- Public SSE still sends legacy `{event_type, data}` payloads, so envelope
  redaction metadata is not fully exposed to the frontend.
- Browser localStorage caches redacted backend messages when hydrated from the
  backend, but user-entered UI messages and local UI state are browser-local
  best effort.
- Redaction status does not prove that content is safe to disclose.

Target behavior:

- Redaction status should be visible in public event contracts and workflow
  snapshots where useful.
- New event payloads and stores should include tests for secrets, local paths,
  private dataset rows, and provider-specific token formats.

## Untrusted Retrieved Content

Current behavior:

- Research, docs, papers, GitHub, dataset, Hub repo, and MCP tools retrieve
  external content that may contain prompt injection, malicious code, or false
  instructions.
- The research subagent exposes only a read-only tool subset, restricts
  `hf_repo_files` to list/read, and blocks approval-required or higher-risk
  policy results.
- Main-agent retrieved content is stored as ordinary tool output in model
  context after policy allows the tool call.

Current limits:

- Retrieved content is not yet wrapped in a formal untrusted-content schema.
- The model may still see hostile text from external docs or repos as part of
  tool results.

Target behavior:

- Retrieved content should be quoted, source-labeled, and treated as data, not
  instructions.
- Tool outputs should separate source metadata, extracted facts, and raw text.
- Any code from external sources should be reviewed, adapted, and tested before
  local, sandbox, Jobs, or Hub side effects.

## Change Checklist

Use this checklist for changes touching security-sensitive paths:

- Identify assets and trust boundaries crossed by the change.
- Mark whether behavior is current implementation or target-only.
- Keep approvals in front of local writes/exec, sandbox creation, HF Jobs run,
  Hub mutation, and generic MCP tools.
- Add or update redaction tests for new payload shapes.
- Add regression tests when changing policy, event persistence, local/sandbox
  execution, MCP trust, Hub publishing, or spend behavior.
- Add fake-server/no-network tests when changing local inference endpoint
  resolution, probe classification, or `/doctor local-inference` contracts.
- Run the offline gate from `docs/TESTING.md` when code changes accompany the
  policy update.

## Verification Map

Current focused tests:

- Credentials/auth/quota: `tests/unit/test_user_quotas.py`,
  `tests/unit/test_backend_session_sse.py`.
- MCP trust boundary: `tests/unit/test_mcp_gateway_trust_boundary.py`,
  `tests/unit/test_tool_metadata.py`.
- Policy/approvals/spend class: `tests/unit/test_policy_engine.py`,
  `tests/unit/test_tool_router_approval.py`,
  `tests/unit/test_headless_approval_safety.py`.
- Local and sandbox execution: `tests/unit/test_local_execution_guardrails.py`,
  `tests/unit/test_sandbox_execution_guardrails.py`.
- Redaction/stores: `tests/unit/test_redaction.py`,
  `tests/unit/test_agent_events.py`, `tests/unit/test_event_store.py`,
  `tests/unit/test_operation_store.py`, `tests/unit/test_session_store.py`,
  `tests/unit/test_session_uploader_redaction.py`.
- Retrieved-content isolation: `tests/unit/test_research_tool_isolation.py`.
