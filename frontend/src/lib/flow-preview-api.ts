import { isRecord } from './project-projection-utils';

export type FlowPreviewFetch = (path: string, options?: RequestInit) => Promise<Response>;

export interface FlowTemplateMetadata {
  category: string;
  tags: string[];
  runtime_class: string;
}

export interface FlowTemplateSourceMetadata {
  kind: 'builtin';
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
}

export type FlowPreviewApiWarning =
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

export type FlowPreviewLoadResult =
  | { ok: true; preview: FlowPreviewResponse }
  | FlowPreviewApiFailureResult;

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

function parseTemplateSource(value: unknown): FlowTemplateSourceMetadata | null {
  if (
    !isRecord(value)
    || value.kind !== 'builtin'
    || typeof value.path !== 'string'
    || typeof value.schema_version !== 'string'
    || typeof value.template_version !== 'string'
  ) {
    return null;
  }
  return {
    kind: value.kind,
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
  if (
    typeof value.id !== 'string'
    || typeof value.type !== 'string'
    || typeof value.description !== 'string'
    || required === null
    || phaseIds === null
  ) {
    return null;
  }
  return { id: value.id, type: value.type, description: value.description, required, phase_ids: phaseIds };
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
