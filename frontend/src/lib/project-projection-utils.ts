import type { AgentEvent, ApprovalToolItem } from '../types/events';
import type {
  ActiveJobRef,
  LiveTrackingRef,
  ProjectBudgetSnapshot,
  ProjectCompatibility,
  ProjectEvidenceSummary,
  ProjectPhaseSnapshot,
  ProjectSnapshot,
  ProjectVerifierCatalogCounts,
  ProjectVerifierCatalogMappingRow,
  ProjectVerifierCatalogSummary,
} from '../types/project';

export const MAX_PROCESSED_EVENT_IDS = 200;
export const WORKFLOW_MISSING_PRODUCERS = [
  'workflow_events',
  'budget_ledger',
  'evidence_ledger',
  'live_tracking',
];

const STREAMABLE_TOOLS = new Set(['hf_jobs', 'sandbox', 'bash']);
const TERMINAL_TOOL_STATUSES = new Set([
  'abandoned',
  'cancelled',
  'canceled',
  'complete',
  'completed',
  'done',
  'error',
  'failed',
  'rejected',
  'succeeded',
  'success',
]);

export function makePhase(
  id: string,
  label: string,
  status: ProjectPhaseSnapshot['status'],
  updatedAt: string | null | undefined,
): ProjectPhaseSnapshot {
  return {
    id,
    label,
    status,
    started_at: null,
    updated_at: updatedAt ?? null,
  };
}

export function makeBudgetPlaceholder(): ProjectBudgetSnapshot {
  return {
    source: 'placeholder',
    status: 'placeholder',
    currency: null,
    limit: null,
    used: null,
    items: [],
  };
}

export function makeEvidencePlaceholder(): ProjectEvidenceSummary {
  return {
    source: 'placeholder',
    status: 'placeholder',
    claim_count: 0,
    artifact_count: 0,
    metric_count: 0,
    items: [],
  };
}

export function makeLiveTrackingPlaceholder(sessionId: string): LiveTrackingRef {
  return {
    provider: 'trackio',
    enabled: false,
    status: 'placeholder',
    space_id: null,
    project: `session:${sessionId}`,
    run_id: null,
    tool_call_id: null,
    url: null,
    source: 'compatibility',
  };
}

export function isStreamableTool(tool: string): boolean {
  return STREAMABLE_TOOLS.has(tool);
}

export function makeJobRef(
  tool: string,
  tool_call_id: string,
  status: string,
  event: AgentEvent,
  args: Record<string, unknown>,
): ActiveJobRef | null {
  if (!isStreamableTool(tool)) {
    return null;
  }
  return {
    source: 'event',
    source_event_sequence: getEventSequence(event),
    tool,
    tool_call_id,
    status,
    arguments: args,
    created_at: event.timestamp ?? null,
    updated_at: event.timestamp ?? null,
    redaction_status: event.redaction_status,
  };
}

export function terminalStatus(status: string, fallback: string): string {
  return isTerminalToolStatus(status) ? status : fallback;
}

export function isTerminalToolStatus(status: string): boolean {
  return TERMINAL_TOOL_STATUSES.has(status.toLowerCase());
}

export function isTerminalFailure(status: string): boolean {
  return ['failed', 'error'].includes(status.toLowerCase());
}

export function mergeBudget(
  current: ProjectBudgetSnapshot,
  value: unknown,
  updatedAt: string | undefined,
): ProjectBudgetSnapshot {
  if (!isRecord(value)) return current;
  return {
    source: readString(value, 'source') ?? 'event',
    status: readString(value, 'status') ?? current.status,
    currency: readString(value, 'currency') ?? current.currency,
    limit: readNumber(value, 'limit') ?? current.limit,
    used: readNumber(value, 'used') ?? current.used,
    items: Array.isArray(value.items) ? value.items : current.items,
    updated_at: updatedAt ?? current.updated_at,
  };
}

export function mergeEvidence(
  current: ProjectEvidenceSummary,
  value: unknown,
  updatedAt: string | undefined,
): ProjectEvidenceSummary {
  if (!isRecord(value)) return current;
  const verifierCatalog = Object.prototype.hasOwnProperty.call(value, 'verifier_catalog')
    ? normalizeVerifierCatalogMetadata(value.verifier_catalog) ?? current.verifier_catalog
    : current.verifier_catalog;
  return {
    source: readString(value, 'source') ?? 'event',
    status: readString(value, 'status') ?? current.status,
    claim_count: readNumber(value, 'claim_count') ?? current.claim_count,
    artifact_count: readNumber(value, 'artifact_count') ?? current.artifact_count,
    metric_count: readNumber(value, 'metric_count') ?? current.metric_count,
    items: Array.isArray(value.items) ? value.items : current.items,
    updated_at: updatedAt ?? current.updated_at,
    ...(verifierCatalog ? { verifier_catalog: verifierCatalog } : {}),
  };
}

export function normalizeEvidenceSummary(summary: ProjectEvidenceSummary): ProjectEvidenceSummary {
  const verifierCatalog = normalizeVerifierCatalogMetadata(
    (summary as ProjectEvidenceSummary & { verifier_catalog?: unknown }).verifier_catalog,
  );
  const normalized = { ...summary };
  delete (normalized as ProjectEvidenceSummary & { verifier_catalog?: unknown }).verifier_catalog;
  return verifierCatalog ? { ...normalized, verifier_catalog: verifierCatalog } : normalized;
}

export function normalizeVerifierCatalogMetadata(value: unknown): ProjectVerifierCatalogSummary | null | undefined {
  if (value === undefined) return undefined;
  if (!isRecord(value)) return null;

  const catalogCheckIds = parseStringArray(value.catalog_check_ids);
  const directCatalogCheckIds = parseStringArray(value.direct_catalog_check_ids);
  const mappedCatalogCheckIds = parseStringArray(value.mapped_catalog_check_ids);
  const flowLocalVerifierIds = parseStringArray(value.flow_local_verifier_ids);
  const intentionalUnmappedIds = parseStringArray(value.intentional_unmapped_ids);
  const unknownIds = parseStringArray(value.unknown_ids);
  const mappingRows = parseVerifierCatalogMappingRows(value.mapping_rows);
  const counts = parseVerifierCatalogCounts(value.counts);

  if (
    typeof value.source !== 'string'
    || catalogCheckIds === null
    || directCatalogCheckIds === null
    || mappedCatalogCheckIds === null
    || flowLocalVerifierIds === null
    || intentionalUnmappedIds === null
    || unknownIds === null
    || mappingRows === null
    || counts === null
  ) {
    return null;
  }

  return {
    source: value.source,
    catalog_check_ids: catalogCheckIds,
    direct_catalog_check_ids: directCatalogCheckIds,
    mapped_catalog_check_ids: mappedCatalogCheckIds,
    flow_local_verifier_ids: flowLocalVerifierIds,
    intentional_unmapped_ids: intentionalUnmappedIds,
    unknown_ids: unknownIds,
    mapping_rows: mappingRows,
    counts,
  };
}

export function extractLiveTrackingRefs(event: AgentEvent, toolCallId: string): LiveTrackingRef[] {
  const spaceId = readString(event.data, 'trackio_space_id') ?? readString(event.data, 'trackioSpaceId');
  const project = readString(event.data, 'trackio_project') ?? readString(event.data, 'trackioProject');
  const passthrough = normalizeLiveTrackingRefs(event.data?.live_tracking_refs);
  if (!spaceId && !project) return passthrough;

  return [
    ...passthrough,
    {
      provider: 'trackio',
      enabled: true,
      status: readString(event.data, 'state') ?? readString(event.data, 'status') ?? 'active',
      space_id: spaceId ?? null,
      project: project ?? null,
      run_id: readString(event.data, 'run_id') ?? null,
      tool_call_id: toolCallId,
      url: readString(event.data, 'trackio_url') ?? readString(event.data, 'trackioUrl') ?? null,
      source: 'event',
      updated_at: event.timestamp ?? null,
    },
  ];
}

export function normalizeLiveTrackingRefs(value: unknown): LiveTrackingRef[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter(isRecord)
    .map((ref) => ({
      id: readString(ref, 'id'),
      provider: readString(ref, 'provider') ?? 'trackio',
      enabled: readBoolean(ref, 'enabled') ?? (readString(ref, 'status') !== 'placeholder'),
      status: readString(ref, 'status') ?? 'active',
      space_id: readString(ref, 'space_id') ?? null,
      project: readString(ref, 'project') ?? readString(ref, 'project_id') ?? null,
      run_id: readString(ref, 'run_id') ?? null,
      tool_call_id: readString(ref, 'tool_call_id') ?? null,
      url: readString(ref, 'url') ?? null,
      source: readString(ref, 'source') ?? 'event',
      updated_at: readString(ref, 'updated_at') ?? null,
      metadata: readRecord(ref.metadata),
    }));
}

export function getEventKey(event: AgentEvent): string | null {
  const sequence = getEventSequence(event);
  if (sequence !== null) return `seq:${sequence}`;
  const id = event.id ?? event.sse_id ?? event.cursor;
  return id ? `id:${id}` : null;
}

export function getEventSequence(event: AgentEvent): number | null {
  return readPositiveInteger(event.sequence) ?? readPositiveInteger(event.cursor) ?? readPositiveInteger(event.sse_id);
}

export function readPositiveInteger(value: unknown): number | null {
  if (typeof value === 'number' && Number.isSafeInteger(value) && value >= 1) return value;
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= 1 ? parsed : null;
}

export function isApprovalToolItem(value: unknown): value is ApprovalToolItem {
  return isRecord(value)
    && typeof value.tool === 'string'
    && typeof value.tool_call_id === 'string'
    && isRecord(value.arguments);
}

export function upsertOne<T>(items: T[], item: T, keyOf: (item: T) => string): T[] {
  return upsertMany(items, [item], keyOf);
}

export function upsertMany<T>(items: T[], updates: T[], keyOf: (item: T) => string): T[] {
  if (updates.length === 0) return items;
  const byKey = new Map(items.map((item) => [keyOf(item), item]));
  for (const update of updates) {
    const key = keyOf(update);
    byKey.set(key, { ...byKey.get(key), ...update });
  }
  return Array.from(byKey.values());
}

export function activeJobKey(job: Pick<ActiveJobRef, 'tool_call_id' | 'job_id' | 'status'>): string {
  return job.tool_call_id ?? job.job_id ?? job.status;
}

export function liveTrackingKey(ref: LiveTrackingRef): string {
  return ref.id ?? `${ref.provider}:${ref.tool_call_id ?? ref.run_id ?? ref.project ?? ref.space_id ?? ref.source}`;
}

export function processedEventIds(snapshot: ProjectSnapshot): string[] {
  return snapshot.compatibility.processed_event_ids ?? [];
}

export function addWarning(
  compatibility: ProjectCompatibility,
  warning: string,
): ProjectCompatibility {
  const warnings = compatibility.warnings ?? [];
  if (warnings.includes(warning)) return compatibility;
  return {
    ...compatibility,
    warnings: [...warnings, warning],
  };
}

export function readString(source: unknown, key: string): string | undefined {
  if (!isRecord(source)) return undefined;
  const value = source[key];
  return typeof value === 'string' && value.length > 0 ? value : undefined;
}

export function readNumber(source: unknown, key: string): number | undefined {
  if (!isRecord(source)) return undefined;
  const value = source[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

export function readBoolean(source: unknown, key: string): boolean | undefined {
  if (!isRecord(source)) return undefined;
  const value = source[key];
  return typeof value === 'boolean' ? value : undefined;
}

export function readStringArray(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const strings = value.filter((item): item is string => typeof item === 'string');
  return strings.length > 0 ? strings : undefined;
}

function parseStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) return null;
  return value;
}

function parseVerifierCatalogMappingRows(value: unknown): ProjectVerifierCatalogMappingRow[] | null {
  if (!Array.isArray(value)) return null;
  const rows = value.map((item) => {
    if (!isRecord(item) || typeof item.flow_verifier_id !== 'string' || typeof item.catalog_check_id !== 'string') {
      return null;
    }
    return {
      flow_verifier_id: item.flow_verifier_id,
      catalog_check_id: item.catalog_check_id,
    };
  });
  if (rows.some((item) => item === null)) return null;
  return rows as ProjectVerifierCatalogMappingRow[];
}

function parseVerifierCatalogCounts(value: unknown): ProjectVerifierCatalogCounts | null {
  if (!isRecord(value)) return null;
  if (
    !isNonNegativeInteger(value.verdict_count)
    || !isNonNegativeInteger(value.observed_id_count)
    || !isNonNegativeInteger(value.catalog_check_id_count)
    || !isNonNegativeInteger(value.direct_catalog_check_id_count)
    || !isNonNegativeInteger(value.mapped_catalog_check_id_count)
    || !isNonNegativeInteger(value.flow_local_verifier_id_count)
    || !isNonNegativeInteger(value.intentional_unmapped_id_count)
    || !isNonNegativeInteger(value.unknown_id_count)
  ) {
    return null;
  }

  return {
    verdict_count: value.verdict_count,
    observed_id_count: value.observed_id_count,
    catalog_check_id_count: value.catalog_check_id_count,
    direct_catalog_check_id_count: value.direct_catalog_check_id_count,
    mapped_catalog_check_id_count: value.mapped_catalog_check_id_count,
    flow_local_verifier_id_count: value.flow_local_verifier_id_count,
    intentional_unmapped_id_count: value.intentional_unmapped_id_count,
    unknown_id_count: value.unknown_id_count,
  };
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

export function readRecord(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
