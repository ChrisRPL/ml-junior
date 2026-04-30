# Docs

read_when: starting work, looking for the tracked project description, choosing
the right guardrail doc, or updating contributor-facing documentation.

ML Junior docs should stay short, current, and source-controlled. Ignored
planning notes can inform work, but tracked docs are the contributor-facing
source of truth.

## Index

- [PROJECT_DESCRIPTION.md](PROJECT_DESCRIPTION.md):
  read_when: onboarding, explaining ML Junior scope, naming, current behavior,
  or target direction.
- [CURRENT_ARCHITECTURE.md](CURRENT_ARCHITECTURE.md):
  read_when: changing agent queues, backend sessions, SSE, tools, approvals,
  compaction, local execution, or sandbox execution.
- [COMPONENT_SPECS.md](COMPONENT_SPECS.md):
  read_when: changing component contracts, backend session behavior, agent loop
  contracts, tool policy, event streaming, durable stores, workflow projection,
  or frontend chat transport.
- [UX_ARCHITECTURE.md](UX_ARCHITECTURE.md):
  read_when: changing the web UI, project dashboard, workflow projection
  display, tool/job visibility, evidence surfaces, approvals UI, artifact
  navigation, or handoff views.
- [CLI_TUI_SPEC.md](CLI_TUI_SPEC.md):
  read_when: changing CLI commands, slash-command metadata, command completion,
  headless mode, local-mode execution, flow preview commands, or future TUI
  layout.
- [FLOW_TEMPLATES.md](FLOW_TEMPLATES.md):
  read_when: changing built-in flow template files, flow preview APIs, CLI flow
  commands, workflow projection, verifier mappings, phase gates, or flow-related
  docs.
- [LONG_RUNNING_PROJECTS.md](LONG_RUNNING_PROJECTS.md):
  read_when: changing durable events, operation/session stores, workflow
  projection, checkpoints, handoff summaries, progress detection, stuck
  detection, job monitoring, or resume semantics.
- [SECURITY_POLICY.md](SECURITY_POLICY.md):
  read_when: changing credentials, authentication, MCP, local or sandbox
  execution, Hub publishing, HF Jobs, compute spend, redaction, retrieved
  content, or approval policy.
- [TESTING.md](TESTING.md):
  read_when: adding tests, running the offline Python gate, or deciding whether
  a test may touch the network.
- [SMOKE_GATES.md](SMOKE_GATES.md):
  read_when: defining local handoff checks, CI gates, release checks, Docker
  smoke checks, or network-dependent verification.
- [subagent.md](subagent.md):
  read_when: splitting work across overseer, worker, or verifier agents;
  assigning strict write sets; coordinating parallel slices; or verifying another
  agent's handoff.
- [templates/ExecPlan.md](templates/ExecPlan.md):
  read_when: drafting a task plan that needs scope, checkpoints, validation,
  risks, and handoff notes.
- [../CODE_REVIEW.md](../CODE_REVIEW.md):
  read_when: reviewing changes, responding to PR feedback, or deciding what
  evidence a change needs before handoff.

## Doc Rules

- Keep current behavior separate from ML Junior target behavior.
- Update docs when runtime behavior, public APIs, gates, or contributor workflow
  changes.
- Prefer links to tracked docs over references to ignored planning files.
- Keep examples real and minimal; do not add demo data as documentation filler.
