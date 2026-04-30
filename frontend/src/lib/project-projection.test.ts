import type { AgentEvent } from '../types/events';
import type { ProjectSnapshot } from '../types/project';
import { createEmptyProjectSnapshot, projectSnapshotFromEvents, reduceProjectSnapshotEvent } from './project-projection';

function event(sequence: number, event_type: AgentEvent['event_type'], data: Record<string, unknown> = {}): AgentEvent {
  return {
    id: `event-${sequence}`,
    session_id: 'session-1',
    sequence,
    timestamp: `2026-04-28T10:00:${String(sequence).padStart(2, '0')}Z`,
    event_type,
    data,
  };
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function verifierCatalog(): NonNullable<ProjectSnapshot['evidence_summary']['verifier_catalog']> {
  return {
    source: 'flow_verifier_mapping',
    catalog_check_ids: ['dataset.card.present', 'eval.metric.valid'],
    direct_catalog_check_ids: ['dataset.card.present'],
    mapped_catalog_check_ids: ['eval.metric.valid'],
    flow_local_verifier_ids: ['metric-is-reported'],
    intentional_unmapped_ids: ['paper-specific-sanity-check'],
    unknown_ids: ['new-local-check'],
    mapping_rows: [{
      flow_verifier_id: 'metric-is-reported',
      catalog_check_id: 'eval.metric.valid',
    }],
    counts: {
      verdict_count: 3,
      observed_id_count: 3,
      catalog_check_id_count: 2,
      direct_catalog_check_id_count: 1,
      mapped_catalog_check_id_count: 1,
      flow_local_verifier_id_count: 2,
      intentional_unmapped_id_count: 1,
      unknown_id_count: 1,
    },
  };
}

function testReplayAndDuplicateEvents(): void {
  const planUpdate = event(2, 'plan_update', {
    plan: [{ id: 'p1', content: 'Build adapter', status: 'in_progress' }],
  });
  const snapshot = projectSnapshotFromEvents('session-1', [
    event(1, 'processing', { objective: 'Train a classifier' }),
    planUpdate,
    planUpdate,
  ]);

  assert(snapshot.objective.text === 'Train a classifier', 'processing should set objective placeholder');
  assert(snapshot.plan.length === 1, 'duplicate plan_update should not duplicate plan rows');
  assert(snapshot.last_event_sequence === 2, 'last sequence should stop at newest unique event');
  assert(snapshot.compatibility.processed_event_ids?.length === 2, 'duplicate should not add another processed id');
}

function testApprovalRestorationFromDurableSnapshot(): void {
  const durable: ProjectSnapshot = {
    ...createEmptyProjectSnapshot('session-1'),
    status: 'waiting_approval',
    pending_approvals: [{
      tool: 'hf_jobs',
      tool_call_id: 'tc-approval',
      arguments: { script: 'print(1)' },
      status: 'pending',
    }],
    last_event_sequence: 10,
  };

  const snapshot = projectSnapshotFromEvents('session-1', [], durable);
  assert(snapshot.resume.restored_from_snapshot === true, 'durable snapshot should mark restored state');
  assert(snapshot.pending_approvals[0]?.tool_call_id === 'tc-approval', 'pending approval should restore from durable snapshot');
}

function testDeferredToolRestoreAndJobStatusUpdate(): void {
  const durable: ProjectSnapshot = {
    ...createEmptyProjectSnapshot('session-1'),
    status: 'processing',
    active_jobs: [{
      tool: 'hf_jobs',
      tool_call_id: 'tc-job',
      status: 'deferred',
      job_id: 'job-1',
    }],
    last_event_sequence: 4,
  };
  const snapshot = reduceProjectSnapshotEvent(undefined, event(5, 'tool_state_change', {
    tool: 'hf_jobs',
    tool_call_id: 'tc-job',
    state: 'running',
    job_url: 'https://huggingface.co/jobs/job-1',
  }), durable);

  assert(snapshot.active_jobs[0]?.status === 'running', 'deferred job should update to running');
  assert(snapshot.active_jobs[0]?.url === 'https://huggingface.co/jobs/job-1', 'job URL should update from state event');
  assert(snapshot.operation_refs.some((ref) => ref.id === 'tool:tc-job' && ref.status === 'running'), 'operation ref should mirror job status');
}

function testStaleSnapshotFallback(): void {
  const current = projectSnapshotFromEvents('session-1', [
    event(1, 'processing'),
    event(2, 'tool_call', { tool: 'hf_jobs', tool_call_id: 'tc-job', arguments: {} }),
  ]);
  const staleDurable: ProjectSnapshot = {
    ...createEmptyProjectSnapshot('session-1'),
    status: 'waiting_approval',
    pending_approvals: [{
      tool: 'bash',
      tool_call_id: 'old-approval',
      arguments: {},
      status: 'pending',
    }],
    last_event_sequence: 1,
  };

  const snapshot = reduceProjectSnapshotEvent(current, event(3, 'turn_complete'), staleDurable);
  assert(snapshot.status === 'completed', 'newer replay event should win over stale durable snapshot');
  assert(snapshot.pending_approvals.length === 0, 'stale pending approvals should not leak into current projection');
  assert(snapshot.resume.stale_snapshot === true, 'stale durable snapshot should be marked');
  assert(snapshot.compatibility.warnings?.includes('durable_snapshot_stale') === true, 'stale snapshot warning should be retained');
}

function testLiveTrackingRefsPassthroughAndPlaceholder(): void {
  const snapshot = projectSnapshotFromEvents('session-1', [
    event(1, 'tool_state_change', {
      tool: 'hf_jobs',
      tool_call_id: 'tc-track',
      state: 'running',
      trackioSpaceId: 'space-1',
      trackioProject: 'project-1',
      live_tracking_refs: [{
        id: 'custom-ref',
        provider: 'trackio',
        enabled: true,
        tool_call_id: 'tc-track',
        status: 'seeded',
        space_id: null,
        project: null,
        run_id: null,
        url: null,
        source: 'event',
      }],
    }),
  ]);

  assert(snapshot.live_tracking_refs.some((ref) => ref.id === 'custom-ref' && ref.status === 'seeded'), 'live_tracking_refs should pass through');
  assert(snapshot.live_tracking_refs.some((ref) => ref.tool_call_id === 'tc-track' && ref.space_id === 'space-1'), 'Trackio event fields should become inert refs');
}

function testEvidenceSummaryAbsentVerifierCatalogCompatibility(): void {
  const snapshot = projectSnapshotFromEvents('session-1', [
    event(1, 'processing', {
      evidence_summary: {
        source: 'event',
        status: 'available',
        claim_count: 1,
        artifact_count: 2,
        metric_count: 3,
        items: [],
      },
    }),
  ]);

  assert(snapshot.evidence_summary.claim_count === 1, 'evidence summary should still merge without verifier catalog metadata');
  assert(snapshot.evidence_summary.verifier_catalog === undefined, 'absent verifier catalog metadata should remain optional');
}

function testEvidenceSummaryVerifierCatalogPreservation(): void {
  const catalog = verifierCatalog();
  const snapshot = projectSnapshotFromEvents('session-1', [
    event(1, 'processing', {
      evidence_summary: {
        source: 'event',
        status: 'available',
        claim_count: 1,
        artifact_count: 1,
        metric_count: 1,
        items: [],
        verifier_catalog: catalog,
      },
    }),
    event(2, 'processing', {
      evidence_summary: {
        source: 'event',
        status: 'available',
        claim_count: 2,
        artifact_count: 1,
        metric_count: 1,
        items: [],
      },
    }),
  ]);

  assert(snapshot.evidence_summary.claim_count === 2, 'later evidence summary fields should merge');
  assert(
    snapshot.evidence_summary.verifier_catalog?.mapped_catalog_check_ids[0] === 'eval.metric.valid',
    'valid verifier catalog metadata should be preserved during event projection merge',
  );
  assert(
    snapshot.evidence_summary.verifier_catalog?.counts.unknown_id_count === 1,
    'verifier catalog counts should be preserved during event projection merge',
  );
}

function testEvidenceSummaryMalformedVerifierCatalogDoesNotCrash(): void {
  const snapshot = projectSnapshotFromEvents('session-1', [
    event(1, 'processing', {
      evidence_summary: {
        source: 'event',
        status: 'available',
        claim_count: 1,
        artifact_count: 1,
        metric_count: 1,
        items: [],
        verifier_catalog: {
          source: 'flow_verifier_mapping',
          catalog_check_ids: ['dataset.card.present', 42],
        },
      },
    }),
  ]);

  assert(snapshot.evidence_summary.claim_count === 1, 'malformed optional verifier catalog metadata should not block summary merge');
  assert(snapshot.evidence_summary.verifier_catalog === undefined, 'malformed optional verifier catalog metadata should be ignored');
}

const tests = [
  testReplayAndDuplicateEvents,
  testApprovalRestorationFromDurableSnapshot,
  testDeferredToolRestoreAndJobStatusUpdate,
  testStaleSnapshotFallback,
  testLiveTrackingRefsPassthroughAndPlaceholder,
  testEvidenceSummaryAbsentVerifierCatalogCompatibility,
  testEvidenceSummaryVerifierCatalogPreservation,
  testEvidenceSummaryMalformedVerifierCatalogDoesNotCrash,
];

for (const test of tests) {
  test();
}

console.log(`project-projection: ${tests.length} tests passed`);
