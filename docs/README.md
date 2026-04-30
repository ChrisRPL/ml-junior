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
