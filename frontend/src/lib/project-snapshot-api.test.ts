import type { ProjectSnapshot } from '../types/project';
import { createEmptyProjectSnapshot } from './project-projection';
import {
  chooseHydratedProjectSnapshot,
  fetchProjectSnapshot,
  snapshotFromHydrationFailure,
  type ProjectSnapshotFetch,
} from './project-snapshot-api';

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function snapshot(sequence: number, overrides: Partial<ProjectSnapshot> = {}): ProjectSnapshot {
  return {
    ...createEmptyProjectSnapshot('session-1'),
    status: 'processing',
    last_event_sequence: sequence,
    resume: {
      event_sequence: sequence,
      can_resume: false,
      reason: 'executable_resume_not_implemented',
    },
    ...overrides,
  };
}

async function testSuccessfulHydration(): Promise<void> {
  let path = '';
  const durable = snapshot(7);
  const fetcher: ProjectSnapshotFetch = async (nextPath) => {
    path = nextPath;
    return response(200, durable);
  };

  const result = await fetchProjectSnapshot('session-1', fetcher);
  assert(path === '/api/session/session-1/workflow', 'should fetch session workflow path');
  assert(result.ok, 'successful response should hydrate');
  assert(result.ok && result.snapshot.last_event_sequence === 7, 'hydrated snapshot should preserve sequence');
  assert(
    result.ok && result.snapshot.compatibility.durable_snapshot_version === 1,
    'hydrated snapshot should mark durable version',
  );
}

async function testFailedResponseFallback(): Promise<void> {
  const notFoundFetcher: ProjectSnapshotFetch = async () => response(404, { detail: 'not found' });
  const result = await fetchProjectSnapshot('session-1', notFoundFetcher);

  assert(!result.ok, '404 should return fallback result');
  assert(!result.ok && result.warning === 'workflow_snapshot_fetch_404', '404 warning should be explicit');

  const forbiddenFetcher: ProjectSnapshotFetch = async () => response(403, { detail: 'forbidden' });
  const forbidden = await fetchProjectSnapshot('session-1', forbiddenFetcher);
  assert(!forbidden.ok && forbidden.warning === 'workflow_snapshot_fetch_403', '403 warning should be explicit');

  const current = snapshot(3, { objective: { text: 'Keep live projection', source: 'event', updated_at: null } });
  const fallback = snapshotFromHydrationFailure('session-1', current, result.ok ? 'workflow_snapshot_fetch_failed' : result.warning);
  assert(fallback.last_event_sequence === 3, 'fallback should keep current event projection sequence');
  assert(fallback.objective.text === 'Keep live projection', 'fallback should keep current event projection data');
  assert(fallback.compatibility.warnings?.includes('workflow_snapshot_fetch_404') === true, 'fallback should expose warning');
}

async function testMalformedPayloadFallback(): Promise<void> {
  const fetcher: ProjectSnapshotFetch = async () => response(200, { snapshot_version: 1, session_id: 'session-1' });
  const result = await fetchProjectSnapshot('session-1', fetcher);

  assert(!result.ok, 'malformed payload should return fallback result');
  assert(!result.ok && result.warning === 'workflow_snapshot_malformed', 'malformed warning should be explicit');

  const fallback = snapshotFromHydrationFailure(
    'session-1',
    null,
    result.ok ? 'workflow_snapshot_fetch_failed' : result.warning,
  );
  assert(fallback.status === 'stale', 'empty fallback should mark snapshot stale');
  assert(fallback.compatibility.stale === true, 'empty fallback should mark compatibility stale');
  assert(fallback.compatibility.warnings?.includes('workflow_snapshot_malformed') === true, 'empty fallback should expose warning');
}

function testOlderHydrationDoesNotOverwriteNewerEvents(): void {
  const current = snapshot(10, {
    plan: [{ id: 'live', content: 'Live event projection', status: 'in_progress' }],
  });
  const older = snapshot(5, {
    plan: [{ id: 'old', content: 'Old durable projection', status: 'completed' }],
  });

  const chosen = chooseHydratedProjectSnapshot(current, older);
  assert(chosen.last_event_sequence === 10, 'newer event projection sequence should win');
  assert(chosen.plan[0]?.id === 'live', 'older durable snapshot should not overwrite live projection');
  assert(chosen.resume.stale_snapshot === true, 'stale hydration should be marked');
  assert(chosen.compatibility.warnings?.includes('workflow_snapshot_stale') === true, 'stale hydration warning should be exposed');
}

async function run(): Promise<void> {
  await testSuccessfulHydration();
  await testFailedResponseFallback();
  await testMalformedPayloadFallback();
  testOlderHydrationDoesNotOverwriteNewerEvents();
}

run().then(() => {
  console.log('project-snapshot-api: 4 tests passed');
});
