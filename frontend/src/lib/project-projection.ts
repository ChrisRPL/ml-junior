import type { AgentEvent } from '../types/events';
import {
  PROJECT_SNAPSHOT_VERSION,
  type OperationRef,
  type PendingApprovalRef,
  type ProjectPlanItem,
  type ProjectSnapshot,
  type ProjectStatus,
} from '../types/project';
import {
  MAX_PROCESSED_EVENT_IDS,
  WORKFLOW_MISSING_PRODUCERS,
  activeJobKey,
  addWarning,
  extractLiveTrackingRefs,
  getEventKey,
  getEventSequence,
  isApprovalToolItem,
  isTerminalFailure,
  isTerminalToolStatus,
  liveTrackingKey,
  makeBudgetPlaceholder,
  makeEvidencePlaceholder,
  makeJobRef,
  makeLiveTrackingPlaceholder,
  makePhase,
  mergeBudget,
  mergeEvidence,
  normalizeLiveTrackingRefs,
  processedEventIds,
  readRecord,
  readString,
  readStringArray,
  terminalStatus,
  upsertMany,
  upsertOne,
} from './project-projection-utils';

export function createEmptyProjectSnapshot(sessionId: string): ProjectSnapshot {
  return {
    snapshot_version: PROJECT_SNAPSHOT_VERSION,
    session_id: sessionId,
    project_id: `session:${sessionId}`,
    status: 'idle',
    objective: {
      text: null,
      source: 'placeholder',
      updated_at: null,
    },
    phase: makePhase('compatibility-session', 'Session', 'placeholder', null),
    plan: [],
    blockers: [],
    pending_approvals: [],
    active_jobs: [],
    operation_refs: [],
    human_requests: [],
    budget: makeBudgetPlaceholder(),
    evidence_summary: makeEvidencePlaceholder(),
    live_tracking_refs: [makeLiveTrackingPlaceholder(sessionId)],
    resume: {
      event_sequence: 0,
      can_resume: false,
      reason: 'executable_resume_not_implemented',
    },
    compatibility: {
      stale: false,
      missing_producers: [...WORKFLOW_MISSING_PRODUCERS],
      warnings: [],
      processed_event_ids: [],
    },
    last_event_sequence: 0,
    updated_at: null,
  };
}

export function projectSnapshotFromEvents(
  sessionId: string,
  events: AgentEvent[],
  durableSnapshot?: ProjectSnapshot | null,
): ProjectSnapshot {
  return events.reduce<ProjectSnapshot>(
    (snapshot, event) => reduceProjectSnapshotEvent(snapshot, event, durableSnapshot),
    seedSnapshot(sessionId, durableSnapshot),
  );
}

export function reduceProjectSnapshotEvent(
  current: ProjectSnapshot | null | undefined,
  event: AgentEvent,
  durableSnapshot?: ProjectSnapshot | null,
): ProjectSnapshot {
  const sessionId = event.session_id ?? readString(event.data, 'session_id');
  const base = chooseBaseSnapshot(current, durableSnapshot, sessionId);
  const eventKey = getEventKey(event);
  const sequence = getEventSequence(event);

  if (isDuplicateOrStale(base, eventKey, sequence)) {
    return base;
  }

  let next = touchSnapshot(base, event, eventKey, sequence);

  switch (event.event_type) {
    case 'processing':
      next = {
        ...setStatus(next, 'processing', readString(event.data, 'objective')),
        phase: makePhase('compatibility-session', 'Session', 'active', event.timestamp ?? next.updated_at),
      };
      break;

    case 'plan_update':
      next = {
        ...setStatus(next, 'processing'),
        phase: makePhase('planning', 'Planning', 'active', event.timestamp ?? next.updated_at),
        plan: normalizePlan(event),
      };
      break;

    case 'approval_required':
      next = applyApprovalRequired(next, event);
      break;

    case 'tool_call':
      next = applyToolCall(next, event);
      break;

    case 'tool_state_change':
      next = applyToolStateChange(next, event);
      break;

    case 'tool_output':
      next = applyToolOutput(next, event);
      break;

    case 'turn_complete':
      next = {
        ...setStatus(next, 'completed'),
        phase: makePhase('delivery', 'Delivery', 'complete', event.timestamp ?? next.updated_at),
        active_jobs: [],
        pending_approvals: [],
      };
      break;

    case 'interrupted':
      next = {
        ...setStatus(next, 'interrupted'),
        phase: makePhase('compatibility-session', 'Session', 'blocked', event.timestamp ?? next.updated_at),
        active_jobs: next.active_jobs.map((job) => ({ ...job, status: terminalStatus(job.status, 'cancelled') })),
      };
      break;

    case 'shutdown':
      next = {
        ...setStatus(next, 'completed'),
        phase: makePhase('delivery', 'Delivery', 'complete', event.timestamp ?? next.updated_at),
      };
      break;

    case 'error':
      next = applyError(next, event);
      break;

    default:
      break;
  }

  return applyCompatibilityPayload(next, event);
}

function seedSnapshot(sessionId: string, durableSnapshot?: ProjectSnapshot | null): ProjectSnapshot {
  if (!durableSnapshot || durableSnapshot.session_id !== sessionId) {
    return createEmptyProjectSnapshot(sessionId);
  }
  return markRestored(normalizeDurableSnapshot(durableSnapshot));
}

function chooseBaseSnapshot(
  current: ProjectSnapshot | null | undefined,
  durableSnapshot?: ProjectSnapshot | null,
  sessionId?: string,
): ProjectSnapshot {
  if (!current) {
    return seedSnapshot(sessionId ?? durableSnapshot?.session_id ?? 'unknown-session', durableSnapshot);
  }
  if (!durableSnapshot || durableSnapshot.session_id !== current.session_id) {
    return current;
  }

  const durable = normalizeDurableSnapshot(durableSnapshot);
  if (durable.last_event_sequence > current.last_event_sequence) {
    return markRestored(durable);
  }
  if (durable.last_event_sequence < current.last_event_sequence && !current.resume.stale_snapshot) {
    return {
      ...current,
      resume: { ...current.resume, stale_snapshot: true },
      compatibility: addWarning(current.compatibility, 'durable_snapshot_stale'),
    };
  }
  return current;
}

function normalizeDurableSnapshot(snapshot: ProjectSnapshot): ProjectSnapshot {
  return {
    ...snapshot,
    compatibility: {
      warnings: [],
      processed_event_ids: [],
      ...snapshot.compatibility,
    },
    live_tracking_refs: snapshot.live_tracking_refs.length > 0
      ? snapshot.live_tracking_refs
      : [makeLiveTrackingPlaceholder(snapshot.session_id)],
  };
}

function markRestored(snapshot: ProjectSnapshot): ProjectSnapshot {
  return {
    ...snapshot,
    resume: { ...snapshot.resume, restored_from_snapshot: true },
    compatibility: {
      ...snapshot.compatibility,
      durable_snapshot_version: snapshot.snapshot_version,
    },
  };
}

function isDuplicateOrStale(snapshot: ProjectSnapshot, eventKey: string | null, sequence: number | null): boolean {
  if (sequence !== null && sequence <= snapshot.last_event_sequence) {
    return true;
  }
  return eventKey !== null && processedEventIds(snapshot).includes(eventKey);
}

function touchSnapshot(
  snapshot: ProjectSnapshot,
  event: AgentEvent,
  eventKey: string | null,
  sequence: number | null,
): ProjectSnapshot {
  const processed_event_ids = eventKey
    ? [...processedEventIds(snapshot).filter((id) => id !== eventKey), eventKey].slice(-MAX_PROCESSED_EVENT_IDS)
    : processedEventIds(snapshot);

  return {
    ...snapshot,
    updated_at: event.timestamp ?? snapshot.updated_at,
    last_event_sequence: sequence ?? snapshot.last_event_sequence,
    resume: {
      ...snapshot.resume,
      event_sequence: sequence ?? snapshot.resume.event_sequence,
      last_durable_event_id: event.id ?? snapshot.resume.last_durable_event_id,
    },
    compatibility: {
      ...snapshot.compatibility,
      event_schema_version: event.schema_version ?? snapshot.compatibility.event_schema_version,
      redaction_status: event.redaction_status ?? snapshot.compatibility.redaction_status,
      processed_event_ids,
    },
  };
}

function setStatus(
  snapshot: ProjectSnapshot,
  status: ProjectStatus,
  objectiveText?: string,
): ProjectSnapshot {
  return {
    ...snapshot,
    status,
    objective: objectiveText
      ? { text: objectiveText, source: 'event', updated_at: snapshot.updated_at }
      : snapshot.objective,
  };
}

function normalizePlan(event: AgentEvent): ProjectPlanItem[] {
  const plan = Array.isArray(event.data?.plan) ? event.data.plan : [];
  const sequence = getEventSequence(event);
  return plan
    .filter((item): item is Record<string, unknown> => typeof item === 'object' && item !== null)
    .map((item, index) => ({
      id: readString(item, 'id') ?? `plan-${index + 1}`,
      content: readString(item, 'content') ?? '',
      status: readString(item, 'status') ?? 'pending',
      source_event_sequence: sequence,
      updated_at: event.timestamp ?? null,
    }));
}

function applyApprovalRequired(snapshot: ProjectSnapshot, event: AgentEvent): ProjectSnapshot {
  const rawTools = Array.isArray(event.data?.tools) ? event.data.tools : [];
  const tools = rawTools.filter(isApprovalToolItem);
  const sequence = getEventSequence(event);
  const approvals = tools.map<PendingApprovalRef>((tool) => ({
    source: 'event',
    source_event_sequence: sequence,
    updated_at: event.timestamp ?? null,
    tool: tool.tool,
    tool_call_id: tool.tool_call_id,
    arguments: tool.arguments,
    status: 'pending',
    risk: readString(tool, 'risk'),
    side_effects: readStringArray(readRecord(tool).side_effects),
    rollback: readString(tool, 'rollback'),
    budget_impact: readString(tool, 'budget_impact'),
    credential_usage: readStringArray(readRecord(tool).credential_usage),
    reason: readString(tool, 'reason'),
    redaction_status: event.redaction_status,
    requested_at: event.timestamp ?? null,
  }));

  return {
    ...setStatus(snapshot, 'waiting_approval'),
    phase: makePhase('human-approval', 'Human Approval', 'blocked', event.timestamp ?? snapshot.updated_at),
    pending_approvals: upsertMany(snapshot.pending_approvals, approvals, (approval) => approval.tool_call_id),
    operation_refs: upsertMany(
      snapshot.operation_refs,
      approvals.map((approval) => approvalToOperationRef(approval, event)),
      (operation) => operation.id,
    ),
    blockers: upsertMany(
      snapshot.blockers,
      approvals.map((approval) => ({
        id: `approval:${approval.tool_call_id}`,
        kind: 'approval',
        message: `Approval required for ${approval.tool ?? 'tool'}`,
        source_ref: approval.tool_call_id,
        source_event_sequence: sequence,
        created_at: event.timestamp ?? null,
        updated_at: event.timestamp ?? null,
      })),
      (blocker) => blocker.id,
    ),
  };
}

function applyToolCall(snapshot: ProjectSnapshot, event: AgentEvent): ProjectSnapshot {
  const tool = readString(event.data, 'tool') ?? 'unknown';
  const tool_call_id = readString(event.data, 'tool_call_id') ?? event.id ?? `${tool}:unknown`;
  const args = readRecord(event.data?.arguments);
  const operation = toolOperationRef(tool, tool_call_id, 'running', event, args);
  const job = makeJobRef(tool, tool_call_id, 'running', event, args);
  const liveTrackingRefs = extractLiveTrackingRefs(event, tool_call_id);

  return {
    ...setStatus(snapshot, 'processing'),
    phase: makePhase('execution', 'Execution', 'active', event.timestamp ?? snapshot.updated_at),
    operation_refs: upsertOne(snapshot.operation_refs, operation, (ref) => ref.id),
    pending_approvals: snapshot.pending_approvals.filter((approval) => approval.tool_call_id !== tool_call_id),
    active_jobs: job ? upsertOne(snapshot.active_jobs, job, activeJobKey) : snapshot.active_jobs,
    live_tracking_refs: upsertMany(snapshot.live_tracking_refs, liveTrackingRefs, liveTrackingKey),
  };
}

function applyToolStateChange(snapshot: ProjectSnapshot, event: AgentEvent): ProjectSnapshot {
  const tool = readString(event.data, 'tool') ?? 'unknown';
  const tool_call_id = readString(event.data, 'tool_call_id') ?? event.id ?? `${tool}:unknown`;
  const status = readString(event.data, 'state') ?? readString(event.data, 'status') ?? 'running';
  const jobUrl = readString(event.data, 'job_url') ?? readString(event.data, 'jobUrl');
  const jobId = readString(event.data, 'job_id') ?? readString(event.data, 'jobId');
  const liveTrackingRefs = extractLiveTrackingRefs(event, tool_call_id);
  const operation = toolOperationRef(tool, tool_call_id, status, event, readRecord(event.data?.arguments));
  const isTerminal = isTerminalToolStatus(status);
  const nextStatus: ProjectStatus = isTerminalFailure(status) ? 'error' : 'processing';

  return {
    ...setStatus(snapshot, nextStatus),
    phase: makePhase('execution', 'Execution', isTerminalFailure(status) ? 'failed' : 'active', event.timestamp ?? snapshot.updated_at),
    operation_refs: upsertOne(snapshot.operation_refs, operation, (ref) => ref.id),
    active_jobs: isTerminal
      ? snapshot.active_jobs.filter((job) => activeJobKey(job) !== activeJobKey({ tool_call_id, job_id: jobId, status }))
      : upsertOne(
          snapshot.active_jobs,
          {
            source: 'event',
            source_event_sequence: getEventSequence(event),
            tool,
            tool_call_id,
            status,
            ...(jobId && { job_id: jobId }),
            ...(jobUrl && { url: jobUrl }),
            updated_at: event.timestamp ?? null,
            redaction_status: event.redaction_status,
          },
          activeJobKey,
        ),
    live_tracking_refs: upsertMany(snapshot.live_tracking_refs, liveTrackingRefs, liveTrackingKey),
  };
}

function applyToolOutput(snapshot: ProjectSnapshot, event: AgentEvent): ProjectSnapshot {
  const tool = readString(event.data, 'tool') ?? 'unknown';
  const tool_call_id = readString(event.data, 'tool_call_id') ?? event.id ?? `${tool}:unknown`;
  const output = readString(event.data, 'output');
  const success = typeof event.data?.success === 'boolean' ? event.data.success : undefined;
  const status = success === false ? 'failed' : 'succeeded';
  const operation = toolOperationRef(tool, tool_call_id, status, event, { output, success });
  const blocker = success === false
    ? [{
        id: event.id ?? `tool-error:${tool_call_id}`,
        kind: 'tool' as const,
        message: output ?? `${tool} failed`,
        source_ref: tool_call_id,
        source_event_sequence: getEventSequence(event),
        created_at: event.timestamp ?? null,
        updated_at: event.timestamp ?? null,
      }]
    : [];

  return {
    ...setStatus(snapshot, success === false ? 'error' : 'processing'),
    phase: makePhase('execution', 'Execution', success === false ? 'failed' : 'active', event.timestamp ?? snapshot.updated_at),
    operation_refs: upsertOne(snapshot.operation_refs, operation, (ref) => ref.id),
    active_jobs: snapshot.active_jobs.filter((job) => job.tool_call_id !== tool_call_id),
    blockers: upsertMany(snapshot.blockers, blocker, (item) => item.id),
  };
}

function applyError(snapshot: ProjectSnapshot, event: AgentEvent): ProjectSnapshot {
  const message = readString(event.data, 'error') ?? 'Unknown error';
  return {
    ...setStatus(snapshot, 'error'),
    phase: makePhase('compatibility-session', 'Session', 'failed', event.timestamp ?? snapshot.updated_at),
    blockers: upsertOne(
      snapshot.blockers,
      {
        id: event.id ?? `error:${snapshot.blockers.length + 1}`,
        kind: 'error',
        message,
        source_ref: event.id,
        source_event_sequence: getEventSequence(event),
        created_at: event.timestamp ?? null,
        updated_at: event.timestamp ?? null,
      },
      (blocker) => blocker.id,
    ),
  };
}

function applyCompatibilityPayload(snapshot: ProjectSnapshot, event: AgentEvent): ProjectSnapshot {
  const payloadTrackingRefs = normalizeLiveTrackingRefs(event.data?.live_tracking_refs);
  return {
    ...snapshot,
    budget: mergeBudget(snapshot.budget, event.data?.budget, event.timestamp),
    evidence_summary: mergeEvidence(snapshot.evidence_summary, event.data?.evidence_summary, event.timestamp),
    live_tracking_refs: payloadTrackingRefs.length > 0
      ? upsertMany(payloadTrackingRefs, snapshot.live_tracking_refs, liveTrackingKey)
      : snapshot.live_tracking_refs,
  };
}

function approvalToOperationRef(approval: PendingApprovalRef, event: AgentEvent): OperationRef {
  return {
    id: `approval:${approval.tool_call_id}`,
    type: 'approval',
    status: approval.status ?? 'pending',
    tool: approval.tool,
    tool_call_id: approval.tool_call_id,
    source_event_sequence: getEventSequence(event),
    created_at: event.timestamp ?? null,
    updated_at: event.timestamp ?? null,
    data: { arguments: approval.arguments ?? {} },
  };
}

function toolOperationRef(
  tool: string,
  tool_call_id: string,
  status: string,
  event: AgentEvent,
  data?: Record<string, unknown>,
): OperationRef {
  return {
    id: `tool:${tool_call_id}`,
    type: tool === 'hf_jobs' ? 'job' : 'tool',
    status,
    tool,
    tool_call_id,
    source_event_sequence: getEventSequence(event),
    created_at: event.timestamp ?? null,
    updated_at: event.timestamp ?? null,
    ...(data && { data }),
  };
}
