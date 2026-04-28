import type { EventRedactionStatus } from './events';

export const PROJECT_SNAPSHOT_VERSION = 1;

export type ProjectStatus =
  | 'idle'
  | 'processing'
  | 'waiting_approval'
  | 'blocked'
  | 'error'
  | 'interrupted'
  | 'completed'
  | 'stale';

export type PhaseStatus =
  | 'placeholder'
  | 'pending'
  | 'active'
  | 'blocked'
  | 'complete'
  | 'failed';

export type ProjectPlanStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | (string & {});

export interface WorkflowObjective {
  text: string | null;
  source: 'placeholder' | 'event' | 'durable' | (string & {});
  updated_at: string | null;
}

export interface ProjectPlanItem {
  id: string;
  content: string;
  status: ProjectPlanStatus;
  source_event_sequence?: number | null;
  updated_at?: string | null;
}

export interface ProjectPhaseSnapshot {
  id: string;
  label: string;
  status: PhaseStatus;
  started_at?: string | null;
  updated_at?: string | null;
}

export interface ProjectBlocker {
  id: string;
  kind: 'error' | 'approval' | 'human_request' | 'tool' | (string & {});
  message: string;
  source_ref?: string;
  source_event_sequence?: number | null;
  created_at?: string | null;
  resolved_at?: string | null;
  updated_at?: string | null;
}

export interface PendingApprovalRef {
  source?: 'event' | 'durable' | (string & {});
  source_event_sequence?: number | null;
  updated_at?: string | null;
  tool?: string;
  tool_call_id: string;
  arguments?: Record<string, unknown>;
  status?: 'pending' | 'approved' | 'rejected' | (string & {});
  risk?: string | null;
  side_effects?: string[];
  rollback?: string | null;
  budget_impact?: string | null;
  credential_usage?: string[];
  reason?: string | null;
  redaction_status?: EventRedactionStatus;
  requested_at?: string | null;
}

export interface ActiveJobRef {
  source?: 'event' | 'durable' | (string & {});
  source_event_sequence?: number | null;
  updated_at?: string | null;
  tool_call_id: string;
  tool?: string | null;
  job_id?: string | null;
  status: string;
  url?: string | null;
  arguments?: Record<string, unknown>;
  output?: string;
  success?: boolean;
  live_tracking_ref_id?: string;
  created_at?: string | null;
  completed_at?: string | null;
  redaction_status?: EventRedactionStatus;
}

export interface OperationRef {
  id: string;
  type: string;
  status: string;
  idempotency_key?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  tool?: string;
  tool_call_id?: string;
  job_id?: string;
  source_event_sequence?: number | null;
  data?: Record<string, unknown>;
}

export interface HumanRequestRef {
  request_id: string;
  status: 'requested' | 'answered' | 'expired' | 'canceled' | (string & {});
  channel?: string;
  summary?: string;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ProjectBudgetSnapshot {
  source: 'placeholder' | 'event' | 'durable' | (string & {});
  status: 'placeholder' | 'active' | 'exhausted' | 'unknown' | (string & {});
  currency: string | null;
  limit: number | null;
  used: number | null;
  items: unknown[];
  updated_at?: string | null;
}

export interface ProjectEvidenceSummary {
  source: 'placeholder' | 'event' | 'durable' | (string & {});
  status: 'placeholder' | 'active' | 'verified' | 'failed' | (string & {});
  claim_count: number;
  artifact_count: number;
  metric_count: number;
  items: unknown[];
  updated_at?: string | null;
}

export interface LiveTrackingRef {
  id?: string;
  provider: 'trackio' | (string & {});
  enabled: boolean;
  status: 'placeholder' | 'active' | 'failed' | 'complete' | (string & {});
  space_id: string | null;
  project: string | null;
  run_id: string | null;
  tool_call_id: string | null;
  url: string | null;
  source: 'compatibility' | 'event' | 'durable' | (string & {});
  updated_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ProjectResumeState {
  event_sequence: number;
  can_resume: boolean;
  reason: 'executable_resume_not_implemented' | (string & {});
  restored_from_snapshot?: boolean;
  stale_snapshot?: boolean;
  last_durable_event_id?: string | null;
}

export interface ProjectCompatibility {
  stale: boolean;
  missing_producers: string[];
  warnings?: string[];
  processed_event_ids?: string[];
  durable_snapshot_version?: number;
  event_schema_version?: string | number;
  redaction_status?: EventRedactionStatus;
}

export interface ProjectSnapshot {
  snapshot_version: number;
  session_id: string;
  project_id: string;
  status: ProjectStatus;
  objective: WorkflowObjective;
  phase: ProjectPhaseSnapshot;
  plan: ProjectPlanItem[];
  blockers: ProjectBlocker[];
  pending_approvals: PendingApprovalRef[];
  active_jobs: ActiveJobRef[];
  operation_refs: OperationRef[];
  human_requests: HumanRequestRef[];
  budget: ProjectBudgetSnapshot;
  evidence_summary: ProjectEvidenceSummary;
  live_tracking_refs: LiveTrackingRef[];
  resume: ProjectResumeState;
  compatibility: ProjectCompatibility;
  last_event_sequence: number;
  updated_at: string | null;
}
