# Long-Running Projects

read_when: changing durable events, operation/session stores, workflow
projection, checkpoints, handoff summaries, progress detection, stuck detection,
job monitoring, or resume semantics.

Status: current-vs-target continuity contract. "Current behavior" means
shipped in this repository now. "Target behavior" is direction only.

## Current Behavior

- SQLite stores persist session metadata, operation records, and redacted event
  envelopes under `session_logs/` by default.
- `/api/events/{session_id}` can replay persisted events after a sequence cursor
  before streaming live events.
- `/api/session/{session_id}/workflow` recomputes read-only workflow state from
  persisted events, durable session records, durable operation records, and flow
  template metadata.
- Workflow state can expose phase, plan, blocker, pending approval, active job,
  operation, human request, evidence, artifact, metric, log, verifier, and
  resume-cursor fields when corresponding events or records exist.
- `WorkflowResumeState.can_resume` is currently `false` with reason
  `executable_resume_not_implemented`.
- Project continuity, progress detector, phase gate, evidence ledger, and
  verifier projection helpers exist as backend support for read-only state.

Current limitations:

- Backend restart does not recreate live queues, model context, pending approval
  execution state, sandbox handles, HF tokens, quota flags, or running tool
  state.
- Event replay is observability replay, not execution replay.
- Stored operation records do not make queued work restartable.
- Flow start/runtime, experiment board execution, and executable resume are not
  shipped.

## Failure Modes To Design Against

- The user cannot tell what the agent is doing or why.
- Tool output, experiment configs, artifacts, and metrics are buried in chat.
- Approval requests lack enough risk, side-effect, rollback, or budget context.
- Final answers overclaim unsupported results.
- Jobs keep running without visible progress.
- Costs grow invisibly.
- Repeated failures continue without a changed strategy.
- Refresh or crash loses live execution state.

## Target Mechanisms

Durable events should represent meaningful project progress:

- project or session created;
- flow selected;
- phase started, blocked, completed, skipped, failed, or verified;
- plan changed;
- tool or job started, progressed, completed, failed, or cancelled;
- approval requested, edited, approved, denied, or expired;
- artifact, metric, log, or evidence item recorded;
- verifier passed, failed, or waived;
- final report produced.

Checkpoints should be available at high-risk or high-value points:

- flow start;
- before destructive tool calls;
- before job launch;
- after code snapshots;
- after successful baselines;
- after best experiment runs;
- before publish.

Forking should eventually work from phases, experiment runs, code snapshots,
dataset snapshots, and model checkpoints.

## Handoff Summaries

Target handoff summaries should be generated at phase boundaries and when the
user asks for continuity. Keep them short and structured:

- current status;
- goal and success criteria;
- completed phases;
- current phase and blocker;
- key decisions;
- evidence collected;
- current artifacts;
- running jobs;
- failed attempts;
- open risks;
- next recommended action.

## Progress And Stuck Detection

Target heartbeat events should report active phase, active tool or job, last
meaningful progress, time since progress, budget consumed, and next expected
milestone.

Stuck detection should use semantic signals:

- repeated failed commands;
- no new artifacts;
- no metric improvement after repeated runs;
- excessive time in one phase;
- repeated searches without a decision;
- job polling without status change;
- repeated edits without passing tests.

## Contributor Rules

- Use durable state for observability, but do not claim execution resume until
  live work can actually be recreated after restart.
- Finalization should depend on verifier completion or explicit user stop, not
  the model simply ending tool calls.
- Keep current-state docs honest about memory-only runtime pieces.
