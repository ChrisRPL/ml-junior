import { isRecord } from './project-projection-utils';

const INVALID_OPTIONAL_VALUE = Symbol('invalid_optional_value');

export type FlowPreviewFetch = (path: string, options?: RequestInit) => Promise<Response>;

export interface FlowTemplateMetadata {
  category: string;
  tags: string[];
  runtime_class: string;
}

export type FlowTemplateSourceKind = 'builtin' | 'custom' | 'community';
export type FlowTemplateSourceAvailability = 'available' | 'reserved';
export type FlowTemplateSourceTrustStatus = 'trusted' | 'untrusted';
export type FlowTemplateSourceLoadingStatus = 'enabled' | 'disabled';

export interface FlowTemplateSourceDescriptor {
  kind: FlowTemplateSourceKind;
  label: string;
  availability: FlowTemplateSourceAvailability;
  trust_status: FlowTemplateSourceTrustStatus;
  loading_status: FlowTemplateSourceLoadingStatus;
  template_count: number;
  read_only: boolean;
  supports_upload: boolean;
  supports_remote_fetch: boolean;
  source_path: string | null;
  description: string;
}

export interface FlowTemplateSourceMetadata {
  kind: FlowTemplateSourceKind;
  path: string;
  schema_version: string;
  template_version: string;
}

export interface FlowCatalogItem {
  id: string;
  name: string;
  version: string;
  description: string | null;
  metadata: FlowTemplateMetadata;
  template_source: FlowTemplateSourceMetadata;
  phase_count: number;
  required_inputs: string[];
  approval_point_count: number;
  verifier_count: number;
}

export interface FlowInputPreview {
  id: string;
  type: string;
  required: boolean;
  default: unknown | null;
  description: string | null;
}

export interface FlowBudgetsPreview {
  max_gpu_hours: number | null;
  max_runs: number | null;
  max_wall_clock_hours: number | null;
  max_llm_usd: number | null;
}

export interface FlowPhasePreview {
  id: string;
  name: string;
  objective: string;
  status: string;
  order: number;
  required_outputs: string[];
  approval_points: string[];
  verifiers: string[];
}

export interface FlowApprovalPointPreview {
  id: string;
  risk: string;
  action: string;
  target: string;
  description: string | null;
  phase_ids: string[];
}

export interface FlowRequiredOutputPreview {
  id: string;
  type: string;
  description: string | null;
  required: boolean;
  phase_ids: string[];
}

export interface FlowArtifactPreview {
  id: string;
  type: string;
  description: string | null;
  required: boolean;
}

export interface FlowVerifierCheckPreview {
  id: string;
  type: string;
  description: string;
  required: boolean;
  phase_ids: string[];
  mapping_status?: 'mapped' | 'intentional_unmapped' | 'unknown_unmapped';
  catalog_check_id?: string | null;
  catalog_check_name?: string | null;
  catalog_check_category?: string | null;
  catalog_check_type?: string | null;
  catalog_evidence_ref_types?: string[];
}

export interface FlowRiskyOperationPreview {
  id: string;
  risk: string;
  action: string;
  target: string;
  description: string | null;
  source: 'approval_point';
  phase_ids: string[];
}

export interface FlowVerifierCatalogCoveragePreview {
  verifier_count: number;
  mapped_count: number;
  unmapped_count: number;
  intentional_unmapped_verifier_ids: string[];
  unknown_unmapped_verifier_ids: string[];
}

export interface FlowPreviewResponse {
  id: string;
  name: string;
  version: string;
  description: string | null;
  metadata: FlowTemplateMetadata;
  template_source: FlowTemplateSourceMetadata;
  inputs: FlowInputPreview[];
  required_inputs: FlowInputPreview[];
  budgets: FlowBudgetsPreview;
  phases: FlowPhasePreview[];
  approval_points: FlowApprovalPointPreview[];
  required_outputs: FlowRequiredOutputPreview[];
  artifacts: FlowArtifactPreview[];
  verifier_checks: FlowVerifierCheckPreview[];
  risky_operations: FlowRiskyOperationPreview[];
  verifier_catalog_coverage?: FlowVerifierCatalogCoveragePreview;
}

export type FlowPreviewApiWarning =
  | 'flow_sources_backend_unavailable'
  | 'flow_sources_http_error'
  | 'flow_sources_malformed'
  | 'flow_catalog_backend_unavailable'
  | 'flow_catalog_http_error'
  | 'flow_catalog_malformed'
  | 'flow_preview_backend_unavailable'
  | 'flow_preview_http_error'
  | 'flow_preview_malformed';

export interface FlowPreviewApiFailureResult {
  ok: false;
  warning: FlowPreviewApiWarning;
  status?: number;
  error?: unknown;
}

export type FlowCatalogLoadResult =
  | { ok: true; catalog: FlowCatalogItem[] }
  | FlowPreviewApiFailureResult;

export type FlowSourcesLoadResult =
  | { ok: true; sources: FlowTemplateSourceDescriptor[] }
  | FlowPreviewApiFailureResult;

export type FlowPreviewLoadResult =
  | { ok: true; preview: FlowPreviewResponse }
  | FlowPreviewApiFailureResult;

export async function fetchFlowSources(
  fetcher: FlowPreviewFetch = fetch,
): Promise<FlowSourcesLoadResult> {
  let response: Response;
  try {
    response = await fetcher('/api/flow-sources');
  } catch (error) {
    return { ok: false, warning: 'flow_sources_backend_unavailable', error };
  }

  if (!response.ok) {
    return { ok: false, warning: 'flow_sources_http_error', status: response.status };
  }

  try {
    const payload = await response.json();
    const sources = parseFlowSources(payload);
    return sources ? { ok: true, sources } : { ok: false, warning: 'flow_sources_malformed', status: response.status };
  } catch (error) {
    return { ok: false, warning: 'flow_sources_malformed', status: response.status, error };
  }
}

export async function fetchFlowCatalog(
  fetcher: FlowPreviewFetch = fetch,
): Promise<FlowCatalogLoadResult> {
  let response: Response;
  try {
    response = await fetcher('/api/flows');
  } catch (error) {
    return { ok: false, warning: 'flow_catalog_backend_unavailable', error };
  }

  if (!response.ok) {
    return { ok: false, warning: 'flow_catalog_http_error', status: response.status };
  }

  try {
    const payload = await response.json();
    const catalog = parseFlowCatalog(payload);
    return catalog ? { ok: true, catalog } : { ok: false, warning: 'flow_catalog_malformed', status: response.status };
  } catch (error) {
    return { ok: false, warning: 'flow_catalog_malformed', status: response.status, error };
  }
}

export async function fetchFlowPreview(
  templateId: string,
  fetcher: FlowPreviewFetch = fetch,
): Promise<FlowPreviewLoadResult> {
  let response: Response;
  try {
    response = await fetcher(`/api/flows/${encodeURIComponent(templateId)}/preview`);
  } catch (error) {
    return { ok: false, warning: 'flow_preview_backend_unavailable', error };
  }

  if (!response.ok) {
    return { ok: false, warning: 'flow_preview_http_error', status: response.status };
  }

  try {
    const payload = await response.json();
    const preview = parseFlowPreview(payload);
    return preview ? { ok: true, preview } : { ok: false, warning: 'flow_preview_malformed', status: response.status };
  } catch (error) {
    return { ok: false, warning: 'flow_preview_malformed', status: response.status, error };
  }
}

function parseFlowCatalog(value: unknown): FlowCatalogItem[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(parseCatalogItem);
  if (items.some((item) => item === null)) return null;
  return items as FlowCatalogItem[];
}

function parseFlowSources(value: unknown): FlowTemplateSourceDescriptor[] | null {
  if (!Array.isArray(value)) return null;
  const sources = value.map(parseFlowSourceDescriptor);
  if (sources.some((source) => source === null)) return null;
  return sources as FlowTemplateSourceDescriptor[];
}

function parseFlowPreview(value: unknown): FlowPreviewResponse | null {
  if (!isRecord(value)) return null;
  const description = readNullableString(value.description);
  const metadata = parseMetadata(value.metadata);
  const templateSource = parseTemplateSource(value.template_source);
  const inputs = parseArray(value.inputs, parseInput);
  const requiredInputs = parseArray(value.required_inputs, parseInput);
  const budgets = parseBudgets(value.budgets);
  const phases = parseArray(value.phases, parsePhase);
  const approvalPoints = parseArray(value.approval_points, parseApprovalPoint);
  const requiredOutputs = parseArray(value.required_outputs, parseRequiredOutput);
  const artifacts = parseArray(value.artifacts, parseArtifact);
  const verifierChecks = parseArray(value.verifier_checks, parseVerifierCheck);
  const riskyOperations = parseArray(value.risky_operations, parseRiskyOperation);
  const verifierCatalogCoverage = Object.prototype.hasOwnProperty.call(value, 'verifier_catalog_coverage')
    ? parseVerifierCatalogCoverage(value.verifier_catalog_coverage)
    : undefined;

  if (
    typeof value.id !== 'string'
    || typeof value.name !== 'string'
    || typeof value.version !== 'string'
    || description === undefined
    || metadata === null
    || templateSource === null
    || inputs === null
    || requiredInputs === null
    || budgets === null
    || phases === null
    || approvalPoints === null
    || requiredOutputs === null
    || artifacts === null
    || verifierChecks === null
    || riskyOperations === null
    || verifierCatalogCoverage === null
  ) {
    return null;
  }

  return {
    id: value.id,
    name: value.name,
    version: value.version,
    description,
    metadata,
    template_source: templateSource,
    inputs,
    required_inputs: requiredInputs,
    budgets,
    phases,
    approval_points: approvalPoints,
    required_outputs: requiredOutputs,
    artifacts,
    verifier_checks: verifierChecks,
    risky_operations: riskyOperations,
    ...(verifierCatalogCoverage === undefined ? {} : { verifier_catalog_coverage: verifierCatalogCoverage }),
  };
}

function parseCatalogItem(value: unknown): FlowCatalogItem | null {
  if (!isRecord(value)) return null;
  const description = readNullableString(value.description);
  const metadata = parseMetadata(value.metadata);
  const templateSource = parseTemplateSource(value.template_source);
  const requiredInputs = parseStringArray(value.required_inputs);

  if (
    typeof value.id !== 'string'
    || typeof value.name !== 'string'
    || typeof value.version !== 'string'
    || description === undefined
    || metadata === null
    || templateSource === null
    || !isNonNegativeInteger(value.phase_count)
    || requiredInputs === null
    || !isNonNegativeInteger(value.approval_point_count)
    || !isNonNegativeInteger(value.verifier_count)
  ) {
    return null;
  }

  return {
    id: value.id,
    name: value.name,
    version: value.version,
    description,
    metadata,
    template_source: templateSource,
    phase_count: value.phase_count,
    required_inputs: requiredInputs,
    approval_point_count: value.approval_point_count,
    verifier_count: value.verifier_count,
  };
}

function parseMetadata(value: unknown): FlowTemplateMetadata | null {
  if (!isRecord(value)) return null;
  const tags = parseStringArray(value.tags);
  if (typeof value.category !== 'string' || typeof value.runtime_class !== 'string' || tags === null) {
    return null;
  }
  return { category: value.category, runtime_class: value.runtime_class, tags };
}

function parseFlowSourceDescriptor(value: unknown): FlowTemplateSourceDescriptor | null {
  if (!isRecord(value)) return null;
  const kind = readTemplateSourceKind(value.kind);
  const availability = readTemplateSourceAvailability(value.availability);
  const trustStatus = readTemplateSourceTrustStatus(value.trust_status);
  const loadingStatus = readTemplateSourceLoadingStatus(value.loading_status);
  const sourcePath = readNullableString(value.source_path);

  if (
    kind === null
    || typeof value.label !== 'string'
    || availability === null
    || trustStatus === null
    || loadingStatus === null
    || !isNonNegativeInteger(value.template_count)
    || typeof value.read_only !== 'boolean'
    || typeof value.supports_upload !== 'boolean'
    || typeof value.supports_remote_fetch !== 'boolean'
    || sourcePath === undefined
    || typeof value.description !== 'string'
  ) {
    return null;
  }

  return {
    kind,
    label: value.label,
    availability,
    trust_status: trustStatus,
    loading_status: loadingStatus,
    template_count: value.template_count,
    read_only: value.read_only,
    supports_upload: value.supports_upload,
    supports_remote_fetch: value.supports_remote_fetch,
    source_path: sourcePath,
    description: value.description,
  };
}

function parseTemplateSource(value: unknown): FlowTemplateSourceMetadata | null {
  if (!isRecord(value)) return null;
  const kind = readTemplateSourceKind(value.kind);
  if (
    kind === null
    || typeof value.path !== 'string'
    || typeof value.schema_version !== 'string'
    || typeof value.template_version !== 'string'
  ) {
    return null;
  }
  return {
    kind,
    path: value.path,
    schema_version: value.schema_version,
    template_version: value.template_version,
  };
}

function parseInput(value: unknown): FlowInputPreview | null {
  if (!isRecord(value)) return null;
  const description = readNullableString(value.description);
  if (typeof value.id !== 'string' || typeof value.type !== 'string' || typeof value.required !== 'boolean' || description === undefined) {
    return null;
  }
  return {
    id: value.id,
    type: value.type,
    required: value.required,
    default: Object.prototype.hasOwnProperty.call(value, 'default') ? value.default ?? null : null,
    description,
  };
}

function parseBudgets(value: unknown): FlowBudgetsPreview | null {
  if (!isRecord(value)) return null;
  const maxGpuHours = readNullableNumber(value.max_gpu_hours);
  const maxRuns = readNullableInteger(value.max_runs);
  const maxWallClockHours = readNullableNumber(value.max_wall_clock_hours);
  const maxLlmUsd = readNullableNumber(value.max_llm_usd);
  if (
    maxGpuHours === undefined
    || maxRuns === undefined
    || maxWallClockHours === undefined
    || maxLlmUsd === undefined
  ) {
    return null;
  }
  return {
    max_gpu_hours: maxGpuHours,
    max_runs: maxRuns,
    max_wall_clock_hours: maxWallClockHours,
    max_llm_usd: maxLlmUsd,
  };
}

function parsePhase(value: unknown): FlowPhasePreview | null {
  if (!isRecord(value)) return null;
  const requiredOutputs = parseStringArray(value.required_outputs);
  const approvalPoints = parseStringArray(value.approval_points);
  const verifiers = parseStringArray(value.verifiers);
  if (
    typeof value.id !== 'string'
    || typeof value.name !== 'string'
    || typeof value.objective !== 'string'
    || typeof value.status !== 'string'
    || !isNonNegativeInteger(value.order)
    || requiredOutputs === null
    || approvalPoints === null
    || verifiers === null
  ) {
    return null;
  }
  return {
    id: value.id,
    name: value.name,
    objective: value.objective,
    status: value.status,
    order: value.order,
    required_outputs: requiredOutputs,
    approval_points: approvalPoints,
    verifiers,
  };
}

function parseApprovalPoint(value: unknown): FlowApprovalPointPreview | null {
  if (!isRecord(value)) return null;
  const description = readNullableString(value.description);
  const phaseIds = parseStringArray(value.phase_ids);
  if (
    typeof value.id !== 'string'
    || typeof value.risk !== 'string'
    || typeof value.action !== 'string'
    || typeof value.target !== 'string'
    || description === undefined
    || phaseIds === null
  ) {
    return null;
  }
  return {
    id: value.id,
    risk: value.risk,
    action: value.action,
    target: value.target,
    description,
    phase_ids: phaseIds,
  };
}

function parseRequiredOutput(value: unknown): FlowRequiredOutputPreview | null {
  if (!isRecord(value)) return null;
  const description = readNullableString(value.description);
  const required = readOptionalRequiredFlag(value.required);
  const phaseIds = parseStringArray(value.phase_ids);
  if (
    typeof value.id !== 'string'
    || typeof value.type !== 'string'
    || description === undefined
    || required === null
    || phaseIds === null
  ) {
    return null;
  }
  return { id: value.id, type: value.type, description, required, phase_ids: phaseIds };
}

function parseArtifact(value: unknown): FlowArtifactPreview | null {
  if (!isRecord(value)) return null;
  const description = readNullableString(value.description);
  const required = readOptionalRequiredFlag(value.required);
  if (
    typeof value.id !== 'string'
    || typeof value.type !== 'string'
    || description === undefined
    || required === null
  ) {
    return null;
  }
  return { id: value.id, type: value.type, description, required };
}

function parseVerifierCheck(value: unknown): FlowVerifierCheckPreview | null {
  if (!isRecord(value)) return null;
  const phaseIds = parseStringArray(value.phase_ids);
  const required = readOptionalRequiredFlag(value.required);
  const mappingStatus = readOptionalMappingStatus(value.mapping_status);
  const catalogCheckId = readOptionalNullableString(value, 'catalog_check_id');
  const catalogCheckName = readOptionalNullableString(value, 'catalog_check_name');
  const catalogCheckCategory = readOptionalNullableString(value, 'catalog_check_category');
  const catalogCheckType = readOptionalNullableString(value, 'catalog_check_type');
  const catalogEvidenceRefTypes = Object.prototype.hasOwnProperty.call(value, 'catalog_evidence_ref_types')
    ? parseStringArray(value.catalog_evidence_ref_types)
    : undefined;
  if (
    typeof value.id !== 'string'
    || typeof value.type !== 'string'
    || typeof value.description !== 'string'
    || required === null
    || phaseIds === null
    || mappingStatus === null
    || catalogCheckId === INVALID_OPTIONAL_VALUE
    || catalogCheckName === INVALID_OPTIONAL_VALUE
    || catalogCheckCategory === INVALID_OPTIONAL_VALUE
    || catalogCheckType === INVALID_OPTIONAL_VALUE
    || catalogEvidenceRefTypes === null
  ) {
    return null;
  }
  return {
    id: value.id,
    type: value.type,
    description: value.description,
    required,
    phase_ids: phaseIds,
    ...(mappingStatus === undefined ? {} : { mapping_status: mappingStatus }),
    ...(catalogCheckId === null ? { catalog_check_id: null } : catalogCheckId === undefined ? {} : { catalog_check_id: catalogCheckId }),
    ...(catalogCheckName === null ? { catalog_check_name: null } : catalogCheckName === undefined ? {} : { catalog_check_name: catalogCheckName }),
    ...(catalogCheckCategory === null ? { catalog_check_category: null } : catalogCheckCategory === undefined ? {} : { catalog_check_category: catalogCheckCategory }),
    ...(catalogCheckType === null ? { catalog_check_type: null } : catalogCheckType === undefined ? {} : { catalog_check_type: catalogCheckType }),
    ...(catalogEvidenceRefTypes === undefined ? {} : { catalog_evidence_ref_types: catalogEvidenceRefTypes }),
  };
}

function parseVerifierCatalogCoverage(value: unknown): FlowVerifierCatalogCoveragePreview | null {
  if (!isRecord(value)) return null;
  const intentionalUnmappedVerifierIds = parseStringArray(value.intentional_unmapped_verifier_ids);
  const unknownUnmappedVerifierIds = parseStringArray(value.unknown_unmapped_verifier_ids);
  if (
    !isNonNegativeInteger(value.verifier_count)
    || !isNonNegativeInteger(value.mapped_count)
    || !isNonNegativeInteger(value.unmapped_count)
    || intentionalUnmappedVerifierIds === null
    || unknownUnmappedVerifierIds === null
  ) {
    return null;
  }
  return {
    verifier_count: value.verifier_count,
    mapped_count: value.mapped_count,
    unmapped_count: value.unmapped_count,
    intentional_unmapped_verifier_ids: intentionalUnmappedVerifierIds,
    unknown_unmapped_verifier_ids: unknownUnmappedVerifierIds,
  };
}

function parseRiskyOperation(value: unknown): FlowRiskyOperationPreview | null {
  const approvalPoint = parseApprovalPoint(value);
  if (approvalPoint === null || !isRecord(value) || value.source !== 'approval_point') return null;
  return { ...approvalPoint, source: value.source };
}

function parseArray<T>(value: unknown, parser: (item: unknown) => T | null): T[] | null {
  if (!Array.isArray(value)) return null;
  const items = value.map(parser);
  if (items.some((item) => item === null)) return null;
  return items as T[];
}

function parseStringArray(value: unknown): string[] | null {
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) return null;
  return value;
}

function readNullableString(value: unknown): string | null | undefined {
  if (value === undefined || value === null) return null;
  return typeof value === 'string' ? value : undefined;
}

function readOptionalNullableString(
  record: Record<string, unknown>,
  key: string,
): string | null | undefined | typeof INVALID_OPTIONAL_VALUE {
  if (!Object.prototype.hasOwnProperty.call(record, key)) return undefined;
  const value = record[key];
  if (value === null) return null;
  return typeof value === 'string' ? value : INVALID_OPTIONAL_VALUE;
}

function readOptionalMappingStatus(value: unknown): FlowVerifierCheckPreview['mapping_status'] | null | undefined {
  if (value === undefined) return undefined;
  if (value === 'mapped' || value === 'intentional_unmapped' || value === 'unknown_unmapped') return value;
  return null;
}

function readTemplateSourceKind(value: unknown): FlowTemplateSourceKind | null {
  if (value === 'builtin' || value === 'custom' || value === 'community') return value;
  return null;
}

function readTemplateSourceAvailability(value: unknown): FlowTemplateSourceAvailability | null {
  if (value === 'available' || value === 'reserved') return value;
  return null;
}

function readTemplateSourceTrustStatus(value: unknown): FlowTemplateSourceTrustStatus | null {
  if (value === 'trusted' || value === 'untrusted') return value;
  return null;
}

function readTemplateSourceLoadingStatus(value: unknown): FlowTemplateSourceLoadingStatus | null {
  if (value === 'enabled' || value === 'disabled') return value;
  return null;
}

function readNullableNumber(value: unknown): number | null | undefined {
  if (value === undefined || value === null) return null;
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function readNullableInteger(value: unknown): number | null | undefined {
  if (value === undefined || value === null) return null;
  return isNonNegativeInteger(value) ? value : undefined;
}

function readOptionalRequiredFlag(value: unknown): boolean | null {
  if (value === undefined) return true;
  return typeof value === 'boolean' ? value : null;
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}
