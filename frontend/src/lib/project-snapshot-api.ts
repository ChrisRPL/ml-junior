import { createEmptyProjectSnapshot } from './project-projection';
import { addWarning, isRecord } from './project-projection-utils';
import { PROJECT_SNAPSHOT_VERSION, type ProjectSnapshot } from '../types/project';

export type ProjectSnapshotFetch = (path: string, options?: RequestInit) => Promise<Response>;

export type ProjectSnapshotHydrationFailure =
  | 'workflow_snapshot_fetch_403'
  | 'workflow_snapshot_fetch_404'
  | 'workflow_snapshot_fetch_failed'
  | 'workflow_snapshot_http_error'
  | 'workflow_snapshot_malformed';

export type ProjectSnapshotHydrationResult =
  | { ok: true; snapshot: ProjectSnapshot }
  | { ok: false; warning: ProjectSnapshotHydrationFailure; status?: number; error?: unknown };

export async function fetchProjectSnapshot(
  sessionId: string,
  fetcher: ProjectSnapshotFetch = fetch,
): Promise<ProjectSnapshotHydrationResult> {
  try {
    const response = await fetcher(`/api/session/${encodeURIComponent(sessionId)}/workflow`);
    if (response.status === 403) {
      return { ok: false, warning: 'workflow_snapshot_fetch_403', status: response.status };
    }
    if (response.status === 404) {
      return { ok: false, warning: 'workflow_snapshot_fetch_404', status: response.status };
    }
    if (!response.ok) {
      return { ok: false, warning: 'workflow_snapshot_http_error', status: response.status };
    }

    const payload = await response.json();
    if (!isProjectSnapshot(payload, sessionId)) {
      return { ok: false, warning: 'workflow_snapshot_malformed', status: response.status };
    }

    return { ok: true, snapshot: normalizeHydratedSnapshot(payload) };
  } catch (error) {
    return { ok: false, warning: 'workflow_snapshot_fetch_failed', error };
  }
}

export function snapshotFromHydrationFailure(
  sessionId: string,
  current: ProjectSnapshot | null | undefined,
  warning: ProjectSnapshotHydrationFailure,
): ProjectSnapshot {
  const base = current ?? createEmptyProjectSnapshot(sessionId);
  return {
    ...base,
    status: current ? base.status : 'stale',
    resume: {
      ...base.resume,
      stale_snapshot: true,
    },
    compatibility: addWarning(
      {
        ...base.compatibility,
        stale: true,
      },
      warning,
    ),
  };
}

export function chooseHydratedProjectSnapshot(
  current: ProjectSnapshot | null | undefined,
  incoming: ProjectSnapshot,
): ProjectSnapshot {
  if (current && incoming.last_event_sequence < current.last_event_sequence) {
    return {
      ...current,
      resume: {
        ...current.resume,
        stale_snapshot: true,
      },
      compatibility: addWarning(current.compatibility, 'workflow_snapshot_stale'),
    };
  }

  return normalizeHydratedSnapshot(incoming);
}

function normalizeHydratedSnapshot(snapshot: ProjectSnapshot): ProjectSnapshot {
  return {
    ...snapshot,
    compatibility: {
      warnings: [],
      processed_event_ids: [],
      ...snapshot.compatibility,
      durable_snapshot_version: snapshot.snapshot_version,
    },
  };
}

function isProjectSnapshot(value: unknown, sessionId: string): value is ProjectSnapshot {
  if (!isRecord(value)) return false;
  return value.snapshot_version === PROJECT_SNAPSHOT_VERSION
    && value.session_id === sessionId
    && typeof value.project_id === 'string'
    && typeof value.status === 'string'
    && isRecord(value.objective)
    && isRecord(value.phase)
    && Array.isArray(value.plan)
    && Array.isArray(value.blockers)
    && Array.isArray(value.pending_approvals)
    && Array.isArray(value.active_jobs)
    && Array.isArray(value.operation_refs)
    && Array.isArray(value.human_requests)
    && isRecord(value.budget)
    && isRecord(value.evidence_summary)
    && Array.isArray(value.live_tracking_refs)
    && isRecord(value.resume)
    && isRecord(value.compatibility)
    && typeof value.compatibility.stale === 'boolean'
    && Array.isArray(value.compatibility.missing_producers)
    && isNonNegativeInteger(value.last_event_sequence)
    && (value.updated_at === null || typeof value.updated_at === 'string');
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
