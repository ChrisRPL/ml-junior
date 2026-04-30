# Flow Templates

read_when: changing built-in flow template files, flow preview APIs, CLI flow
commands, workflow projection, verifier mappings, phase gates, or flow-related
docs.

Status: current-vs-target flow contract. "Current behavior" means shipped in
this repository now. "Target behavior" is direction only.

## Current Behavior

- Built-in flow templates are tracked JSON files in
  `backend/builtin_flow_templates/`.
- `GET /api/flows` returns a read-only catalog of available built-in templates.
- `GET /api/flows/{template_id}/preview` returns a read-only preview with
  inputs, required inputs, budgets, phases, approval points, expected outputs,
  artifacts, verifier checks, verifier catalog coverage, risky operations, and
  source metadata.
- CLI `/flows` and `/flow preview <id>` use the same backend flow-template
  helpers and are read-only.
- Template validation is covered by unit tests for flow templates, preview API,
  CLI flow commands, verifier mapping, phase gates, and workflow projection.

Current limitations:

- Templates are metadata and preview inputs only. They do not start, pause,
  resume, fork, or execute workflow runs.
- Workflow state is recomputed from durable event/session/operation stores and
  template metadata; it is not an execution engine.
- Projection quality depends on emitted events. Missing producers can lead to
  compatibility warnings or partial state.

## Built-In Template Catalog

The current tracked catalog includes templates for:

- `build-evaluation-harness`
- `compare-models`
- `create-model-card`
- `dataset-audit`
- `dataset-card-review`
- `debug-failed-training-run`
- `distill-model`
- `fine-tune-model`
- `hyperparameter-sweep`
- `implement-architecture`
- `literature-overview`
- `metric-selection-review`
- `model-card-refresh`
- `paper-to-implementation-plan`
- `publish-to-hub`
- `rag-evaluation`
- `reproduce-paper`

## Template Shape

Each template should provide enough structure for preview and future execution:

- stable `id`, `name`, `version`, description, metadata, and source path;
- declared inputs with required/optional status and defaults;
- budget hints such as runs, GPU hours, wall-clock hours, or LLM spend;
- ordered phases with objectives and required outputs;
- approval points for risky, mutating, spend, publish, or credential-sensitive
  actions;
- expected artifacts and outputs;
- verifier checks and mapping to verifier catalog entries;
- risky operation metadata for UI and CLI previews.

## Target Behavior

Flow templates should become reusable workflows for common ML work:

- preview before execution;
- user customization through copied or project-local templates;
- phase-level progress and gates;
- budget constraints;
- explicit approval points;
- artifact and evidence requirements;
- verifier checks before phase completion;
- resume, fork, rollback, and final report generation.

Target lifecycle:

- flow runs record the exact template id and version;
- phase completion requires required outputs and verifier checks, or an explicit
  user waiver;
- checkpoints are created at flow start, before destructive actions, before job
  launch, after code snapshots, after successful baselines, after best runs, and
  before publish;
- run state can be resumed or forked only after executable resume exists.

## Contributor Rules

- Keep template ids stable once referenced by users or tests.
- Update preview, verifier, and projection tests when adding schema fields.
- Keep templates concise and real; do not add demo phases or filler outputs.
- Do not document flow execution as shipped until backend start/resume/fork
  capability exists.
