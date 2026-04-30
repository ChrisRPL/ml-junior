# UX Architecture

read_when: changing the web UI, project dashboard, workflow projection display,
tool/job visibility, evidence surfaces, approvals UI, artifact navigation, or
handoff views.

Status: current-vs-target product contract. "Current behavior" means shipped in
this repository now. "Target behavior" is direction only.

## Product Thesis

ML Junior should be project-centric, not chat-only. Contributors should make ML
work inspectable through structured state: goals, plans, phases, tools, jobs,
artifacts, evidence, approvals, failures, and next actions.

Do not expose raw chain-of-thought. Expose operational reasoning that can be
audited: plan items, phase summaries, decisions, evidence links, tool calls,
verifier status, confidence, and blockers.

## Current Behavior

- The browser app has chat-centered session UX backed by REST and SSE routes.
- The frontend can hydrate messages, workflow snapshots, approval requests,
  tool panels, research progress, quotas, and event cursors from backend data
  and browser-local caches.
- `GET /api/session/{session_id}/workflow` returns a read-only workflow
  projection from persisted event, session, and operation records.
- `GET /api/flows` and `GET /api/flows/{template_id}/preview` expose read-only
  built-in flow metadata for UI preview.
- The project dashboard includes read-only panels for flow definitions,
  workflow timeline, handoff notes, evidence, artifact/job refs, and budget
  ledger details from `ProjectSnapshot` only. Budget rows are display-only and
  do not provide spend controls or approvals.
- Approvals use the existing approval flow and include structured risk,
  side-effect, rollback, budget, and credential metadata from backend policy.
- Durable event replay exists for `/api/events/{session_id}` by sequence cursor.

Current limitations:

- The workflow projection is not an executable workflow engine.
- Flow start, pause, resume, and fork are not shipped.
- A standalone experiment board, evidence ledger, approval center, artifact
  browser, and human handoff view are target surfaces, not current guarantees.
- Browser caches are best-effort. Backend restart does not recreate live queues,
  pending approvals, sandbox handles, tokens, or in-memory model context.

## Target Behavior

The web UI should organize long ML work around these surfaces:

- Project dashboard: objective, deliverable, status, active template, current
  phase, blockers, approvals, changed artifacts, budgets, and resume/fork/export
  controls.
- Flow timeline: phases with status, objective, substep, timestamps, linked
  tools, artifacts, verifier result, and user intervention points.
- Experiment board: runs grouped by lifecycle state with hypothesis, dataset,
  code/config snapshot, seed, runtime, metrics, logs, artifacts, verdict, and
  compare/fork actions.
- Evidence ledger: trace final claims to papers, docs, dataset inspections,
  code diffs, command output, logs, metrics, artifacts, approvals, and verifier
  results.
- Tool and job monitor: active/completed tool calls, redacted args, risk,
  approval state, timeout/retry policy, logs, side effects, artifacts, and cost.
- Approval center: diff-like approval cards with action, target, risk, proposed
  command or change, expected side effects, rollback plan, budget impact, and
  approve/deny/edit controls.
- Research notebook: objective, assumptions, literature and dataset notes,
  experiment log, failures, decisions, results, next steps, and reproducibility
  instructions.
- Artifact browser: typed datasets, code snapshots, configs, checkpoints, logs,
  plots, reports, cards, Hub uploads, and PRs or patches.
- Handoff view: concise status, completed work, running jobs, failures,
  evidence, pending decisions, risks, and next recommended action.

## Contributor Rules

- Keep current UI claims grounded in `docs/CURRENT_ARCHITECTURE.md` and
  `docs/COMPONENT_SPECS.md`.
- Prefer durable backend projections over browser-only state for new project
  surfaces.
- Treat workflow, approval, evidence, artifact, and experiment displays as
  structured state views, not chat transcript decorations.
- Do not add demo data to imply shipped project state.
