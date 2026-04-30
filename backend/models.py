"""Pydantic models for API requests and responses."""

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class OpType(str, Enum):
    """Operation types matching agent/core/agent_loop.py."""

    USER_INPUT = "user_input"
    EXEC_APPROVAL = "exec_approval"
    INTERRUPT = "interrupt"
    UNDO = "undo"
    COMPACT = "compact"
    SHUTDOWN = "shutdown"


class Operation(BaseModel):
    """Operation to be submitted to the agent."""

    op_type: OpType
    data: dict[str, Any] | None = None


class Submission(BaseModel):
    """Submission wrapper with ID and operation."""

    id: str
    operation: Operation


class ToolApproval(BaseModel):
    """Approval decision for a single tool call."""

    tool_call_id: str
    approved: bool
    feedback: str | None = None
    edited_script: str | None = None


class ApprovalRequest(BaseModel):
    """Request to approve/reject tool calls."""

    session_id: str
    approvals: list[ToolApproval]


class SubmitRequest(BaseModel):
    """Request to submit user input."""

    session_id: str
    text: str


class TruncateRequest(BaseModel):
    """Request to truncate conversation history to before a specific user message."""

    user_message_index: int


class SessionResponse(BaseModel):
    """Response when creating a new session."""

    session_id: str
    ready: bool = True


class OperationResponse(BaseModel):
    """Redacted durable operation record returned by session-scoped APIs."""

    id: str
    session_id: str
    type: str
    status: str
    idempotency_key: str | None = None
    payload: Any
    result: Any | None = None
    error: Any | None = None
    payload_redaction_status: str
    result_redaction_status: str
    error_redaction_status: str
    created_at: str
    updated_at: str


class WorkflowObjective(BaseModel):
    """Projected workflow objective metadata."""

    text: str | None = None
    source: Literal["placeholder", "event", "durable"] = "placeholder"
    updated_at: str | None = None


class PhaseState(BaseModel):
    """Compatibility phase state until explicit workflow phases exist."""

    id: str
    label: str
    status: Literal["placeholder", "pending", "active", "blocked", "complete", "failed"]
    started_at: str | None = None
    updated_at: str | None = None


class WorkflowPlanItem(BaseModel):
    """Projected plan item from plan_update events."""

    id: str
    content: str
    status: str
    source_event_sequence: int | None = None
    updated_at: str | None = None


class WorkflowResumeState(BaseModel):
    """Resume cursor metadata. Executable resume is intentionally absent."""

    event_sequence: int
    can_resume: bool = False
    reason: Literal["executable_resume_not_implemented"] = (
        "executable_resume_not_implemented"
    )


class WorkflowCompatibility(BaseModel):
    """Explicit placeholders for future workflow producers."""

    stale: bool
    missing_producers: list[str]


class WorkflowState(BaseModel):
    """Read-only workflow projection returned by the backend API."""

    snapshot_version: Literal[1] = 1
    session_id: str
    project_id: str
    status: Literal[
        "idle",
        "processing",
        "waiting_approval",
        "blocked",
        "error",
        "interrupted",
        "completed",
        "stale",
    ]
    objective: WorkflowObjective
    phase: PhaseState
    plan: list[WorkflowPlanItem]
    blockers: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]]
    active_jobs: list[dict[str, Any]]
    operation_refs: list[dict[str, Any]]
    human_requests: list[dict[str, Any]]
    budget: dict[str, Any]
    evidence_summary: dict[str, Any]
    live_tracking_refs: list[dict[str, Any]]
    resume: WorkflowResumeState
    compatibility: WorkflowCompatibility
    last_event_sequence: int
    updated_at: str | None = None


class HumanRequestModel(BaseModel):
    """Closed-schema base for inert human request records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class HumanRequestBase(HumanRequestModel):
    session_id: NonEmptyStr
    request_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    channel: NonEmptyStr | None = None
    summary: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"] = "unknown"
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None
    updated_at: NonEmptyStr | None = None


class HumanRequestRecord(HumanRequestBase):
    """Inert human request lifecycle projection from durable events."""

    status: Literal["requested", "answered", "expired", "canceled"]
    resolved_at: NonEmptyStr | None = None
    resolution_summary: NonEmptyStr | None = None


class HumanRequestRequestedPayload(HumanRequestBase):
    status: Literal["requested"] = "requested"
    summary: NonEmptyStr


class HumanRequestResolvedPayload(HumanRequestBase):
    status: Literal["answered", "expired", "canceled"]
    resolved_at: NonEmptyStr | None = None
    resolution_summary: NonEmptyStr | None = None


class ContinuityModel(BaseModel):
    """Closed-schema base for metadata-only continuity records."""

    model_config = ConfigDict(extra="forbid")


class PhaseContinuityRef(ContinuityModel):
    type: Literal["phase"]
    phase_id: str = Field(min_length=1)


class RunContinuityRef(ContinuityModel):
    type: Literal["run"]
    run_id: str = Field(min_length=1)


class CodeSnapshotContinuityRef(ContinuityModel):
    type: Literal["code_snapshot"]
    snapshot_id: str = Field(min_length=1)


class DatasetSnapshotContinuityRef(ContinuityModel):
    type: Literal["dataset_snapshot"]
    snapshot_id: str = Field(min_length=1)


class ModelCheckpointContinuityRef(ContinuityModel):
    type: Literal["model_checkpoint"]
    checkpoint_id: str = Field(min_length=1)


class EventSequenceContinuityRef(ContinuityModel):
    type: Literal["event_sequence"]
    sequence: int = Field(ge=1)


ContinuityRef = Annotated[
    PhaseContinuityRef
    | RunContinuityRef
    | CodeSnapshotContinuityRef
    | DatasetSnapshotContinuityRef
    | ModelCheckpointContinuityRef
    | EventSequenceContinuityRef,
    Field(discriminator="type"),
]


class ProjectCheckpoint(ContinuityModel):
    """Metadata-only checkpoint record; referenced records are not created here."""

    session_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    phase_id: str | None = Field(default=None, min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    refs: list[ContinuityRef] | None = None


class ProjectForkPoint(ContinuityModel):
    """Metadata-only fork point with typed references to existing records."""

    session_id: str = Field(min_length=1)
    fork_point_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    refs: list[ContinuityRef] = Field(default_factory=list)


class HandoffSummary(ContinuityModel):
    """Pure handoff projection; empty values mean no durable source recorded them."""

    session_id: str = Field(min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=0)
    goal: str | None = None
    completed_phases: list[dict[str, Any]] = Field(default_factory=list)
    current_phase: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    jobs: list[dict[str, Any]] = Field(default_factory=list)
    failures: list[dict[str, Any]] = Field(default_factory=list)
    risks: list[dict[str, Any]] = Field(default_factory=list)
    next_action: str = "not_recorded"


class HandoffSummaryCreatedEvent(ContinuityModel):
    """Durable metadata payload for a generated handoff summary."""

    session_id: str = Field(min_length=1)
    handoff_id: str = Field(min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    summary: HandoffSummary


class ExperimentLedgerModel(BaseModel):
    """Closed-schema base for inert experiment ledger records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ExperimentDatasetSnapshotRef(ExperimentLedgerModel):
    snapshot_id: NonEmptyStr
    source: Literal["dataset_registry", "local_path", "remote_uri", "event_ref"]
    uri: NonEmptyStr | None = None
    name: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None


class ExperimentDatasetManifestRef(ExperimentLedgerModel):
    manifest_id: NonEmptyStr


class ExperimentDatasetLineageRef(ExperimentLedgerModel):
    lineage_id: NonEmptyStr
    node_id: NonEmptyStr | None = None


class ExperimentCodeSnapshotRef(ExperimentLedgerModel):
    snapshot_id: NonEmptyStr
    source: Literal["git", "archive", "local_path", "event_ref"]
    uri: NonEmptyStr | None = None
    git_commit: NonEmptyStr | None = None
    git_ref: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None


class DatasetSnapshotRecord(ExperimentLedgerModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    session_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    source: Literal[
        "dataset_registry",
        "local_path",
        "remote_uri",
        "event_ref",
        "manual",
    ]
    dataset_id: NonEmptyStr | None = None
    name: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    split: NonEmptyStr | None = None
    revision: NonEmptyStr | None = None
    dataset_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    sample_count: int | None = Field(default=None, ge=0)
    library_fingerprint: NonEmptyStr | None = None
    manifest_hash: NonEmptyStr | None = None
    license: NonEmptyStr | None = None
    lineage_refs: list[dict[str, Any]] = Field(default_factory=list)
    diff_refs: list[dict[str, Any]] = Field(default_factory=list)
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None

    @property
    def schema(self) -> dict[str, Any] | None:
        return self.dataset_schema


class CodeSnapshotRecord(ExperimentLedgerModel):
    session_id: NonEmptyStr
    snapshot_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    source: Literal["git", "archive", "local_path", "remote_uri", "event_ref", "manual"]
    repo: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    git_commit: NonEmptyStr | None = None
    git_ref: NonEmptyStr | None = None
    diff_hash: NonEmptyStr | None = None
    changed_files: list[NonEmptyStr] = Field(default_factory=list)
    generated_artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    manifest_hash: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None


class ExperimentMetricRecord(ExperimentLedgerModel):
    name: NonEmptyStr
    value: int | float | str | bool
    source: Literal["manual", "tool", "verifier", "external_tracking"]
    step: int | None = Field(default=None, ge=0)
    unit: NonEmptyStr | None = None
    recorded_at: NonEmptyStr | None = None


class ExperimentLogRef(ExperimentLedgerModel):
    log_id: NonEmptyStr
    source: Literal["stdout", "stderr", "local_path", "remote_uri", "event_ref"]
    uri: NonEmptyStr | None = None
    label: NonEmptyStr | None = None


class ArtifactLocalPathLocator(ExperimentLedgerModel):
    type: Literal["local_path"]
    path: NonEmptyStr
    uri: NonEmptyStr | None = None


class ArtifactSandboxLocator(ExperimentLedgerModel):
    type: Literal["sandbox"]
    sandbox_id: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None


class ArtifactHFHubLocator(ExperimentLedgerModel):
    type: Literal["hf_hub"]
    repo_id: NonEmptyStr
    repo_type: Literal["model", "dataset", "space", "unknown"] | None = None
    revision: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None


class ArtifactRemoteUriLocator(ExperimentLedgerModel):
    type: Literal["remote_uri"]
    uri: NonEmptyStr


class ArtifactEventRefLocator(ExperimentLedgerModel):
    type: Literal["event_ref"]
    event_id: NonEmptyStr
    sequence: int | None = Field(default=None, ge=1)


ArtifactLocator = Annotated[
    ArtifactLocalPathLocator
    | ArtifactSandboxLocator
    | ArtifactHFHubLocator
    | ArtifactRemoteUriLocator
    | ArtifactEventRefLocator,
    Field(discriminator="type"),
]


class MetricRecord(ExperimentMetricRecord):
    """Standalone inert metric record for append-only experiment ledger storage."""

    session_id: NonEmptyStr
    metric_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)


class LogRefRecord(ExperimentLogRef):
    """Standalone inert log reference for append-only experiment ledger storage."""

    session_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)


class ExperimentArtifactRef(ExperimentLedgerModel):
    artifact_id: NonEmptyStr
    type: NonEmptyStr
    source: Literal["local_path", "sandbox", "remote_uri", "hf_hub", "event_ref"]
    uri: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None


class ExperimentVerifierRef(ExperimentLedgerModel):
    verifier_id: NonEmptyStr
    type: Literal["manual", "metric", "artifact", "command", "llm"]
    status: Literal["pending", "passed", "failed", "inconclusive"]
    source: Literal["flow_template", "runtime", "external"]
    result_ref: NonEmptyStr | None = None


class ExperimentExternalTrackingRef(ExperimentLedgerModel):
    tracking_id: NonEmptyStr
    source: Literal["external_tracking", "event_ref"]
    provider: NonEmptyStr
    uri: NonEmptyStr | None = None
    run_name: NonEmptyStr | None = None


class ExperimentRunRuntime(ExperimentLedgerModel):
    provider: Literal[
        "local",
        "huggingface_jobs",
        "github_actions",
        "external",
        "unknown",
    ]
    started_at: NonEmptyStr | None = None
    ended_at: NonEmptyStr | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    hardware: dict[str, Any] = Field(default_factory=dict)


class ExperimentRunRecord(ExperimentLedgerModel):
    session_id: NonEmptyStr
    run_id: NonEmptyStr
    hypothesis: NonEmptyStr
    status: Literal[
        "planned",
        "running",
        "completed",
        "failed",
        "verified",
        "rejected",
        "cancelled",
    ]
    source_event_sequence: int | None = Field(default=None, ge=1)
    phase_id: NonEmptyStr | None = None
    dataset_snapshot_refs: list[ExperimentDatasetSnapshotRef] = Field(
        default_factory=list
    )
    dataset_manifest_refs: list[ExperimentDatasetManifestRef] = Field(
        default_factory=list
    )
    dataset_lineage_refs: list[ExperimentDatasetLineageRef] = Field(
        default_factory=list
    )
    code_snapshot_refs: list[ExperimentCodeSnapshotRef] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    runtime: ExperimentRunRuntime | None = None
    metrics: list[ExperimentMetricRecord] = Field(default_factory=list)
    log_refs: list[ExperimentLogRef] = Field(default_factory=list)
    artifact_refs: list[ExperimentArtifactRef] = Field(default_factory=list)
    verifier_refs: list[ExperimentVerifierRef] = Field(default_factory=list)
    external_tracking_refs: list[ExperimentExternalTrackingRef] = Field(
        default_factory=list
    )
    created_at: NonEmptyStr | None = None


class ActiveJobRecord(ExperimentLedgerModel):
    """Inert active job reference projected from durable events."""

    session_id: NonEmptyStr
    job_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    tool_call_id: NonEmptyStr | None = None
    tool: NonEmptyStr | None = None
    provider: Literal["huggingface_jobs", "local", "sandbox", "external", "unknown"]
    status: Literal["queued", "running", "completed", "failed", "cancelled", "unknown"]
    url: NonEmptyStr | None = None
    label: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    redaction_status: Literal["none", "partial", "redacted"]
    started_at: NonEmptyStr | None = None
    updated_at: NonEmptyStr | None = None
    completed_at: NonEmptyStr | None = None


class ArtifactRefRecord(ExperimentLedgerModel):
    """Inert artifact reference projected from durable events."""

    session_id: NonEmptyStr
    artifact_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    type: NonEmptyStr
    source: Literal[
        "tool",
        "job",
        "local_path",
        "sandbox",
        "remote_uri",
        "hf_hub",
        "event_ref",
        "manual",
    ]
    ref_uri: NonEmptyStr | None = None
    locator: ArtifactLocator | None = None
    lifecycle: Literal[
        "planned",
        "recorded",
        "available",
        "consumed",
        "archived",
        "deleted",
        "unknown",
    ] | None = None
    mime_type: NonEmptyStr | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    producer: dict[str, Any] | None = None
    export_policy: dict[str, Any] | None = None
    source_tool_call_id: NonEmptyStr | None = None
    source_job_id: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None
    label: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None


class EvidenceLedgerModel(BaseModel):
    """Closed-schema base for inert evidence ledger records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class EvidenceItemRecord(EvidenceLedgerModel):
    """Inert evidence item referencing existing experiment or artifact records."""

    session_id: NonEmptyStr
    evidence_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    kind: Literal[
        "metric",
        "artifact",
        "log",
        "dataset_snapshot",
        "code_snapshot",
        "experiment_run",
        "manual",
        "external_ref",
    ]
    source: Literal[
        "metric",
        "artifact_ref",
        "log_ref",
        "dataset_snapshot",
        "code_snapshot",
        "experiment_run",
        "manual",
        "event_ref",
        "external_ref",
    ]
    title: NonEmptyStr | None = None
    summary: NonEmptyStr | None = None
    metric_id: NonEmptyStr | None = None
    artifact_id: NonEmptyStr | None = None
    log_id: NonEmptyStr | None = None
    dataset_snapshot_id: NonEmptyStr | None = None
    code_snapshot_id: NonEmptyStr | None = None
    run_id: NonEmptyStr | None = None
    event_id: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None


class EvidenceClaimLinkRecord(EvidenceLedgerModel):
    """Inert link between a claim string ref and an evidence item string ref."""

    session_id: NonEmptyStr
    link_id: NonEmptyStr
    claim_id: NonEmptyStr
    evidence_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    relation: Literal["supports", "contradicts", "qualifies", "context"]
    strength: Literal["weak", "moderate", "strong", "decisive"] | None = None
    rationale: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: NonEmptyStr | None = None


class VerifierLedgerModel(BaseModel):
    """Closed-schema base for inert verifier verdict ledger records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class VerifierVerdictCheck(VerifierLedgerModel):
    """One inert check result inside a verifier verdict."""

    check_id: NonEmptyStr | None = None
    name: NonEmptyStr
    status: Literal["passed", "failed", "inconclusive"]
    summary: NonEmptyStr | None = None
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerifierVerdictRecord(VerifierLedgerModel):
    """Inert verifier verdict referencing existing workflow and evidence records."""

    session_id: NonEmptyStr
    verdict_id: NonEmptyStr
    verifier_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    verdict: Literal["passed", "failed", "inconclusive"]
    scope: NonEmptyStr | None = None
    final_answer_ref: NonEmptyStr | None = None
    phase_id: NonEmptyStr | None = None
    run_id: NonEmptyStr | None = None
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    claim_ids: list[NonEmptyStr] = Field(default_factory=list)
    summary: NonEmptyStr | None = None
    rationale: NonEmptyStr | None = None
    checks: list[VerifierVerdictCheck] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None


class FlowTemplateMetadata(BaseModel):
    """Derived catalog metadata for a flow template."""

    category: str
    tags: list[str]
    runtime_class: str


FlowTemplateSourceKind = Literal["builtin", "custom", "community"]
FlowTemplateSourceAvailability = Literal["available", "reserved"]
FlowTemplateSourceTrustStatus = Literal["trusted", "untrusted"]
FlowTemplateSourceLoadingStatus = Literal["enabled", "disabled"]


class FlowTemplateSourceDescriptor(BaseModel):
    """Read-only descriptor for one flow template source."""

    kind: FlowTemplateSourceKind
    label: str
    availability: FlowTemplateSourceAvailability
    trust_status: FlowTemplateSourceTrustStatus
    loading_status: FlowTemplateSourceLoadingStatus
    template_count: int = Field(ge=0)
    read_only: bool
    supports_upload: bool
    supports_remote_fetch: bool
    source_path: str | None = None
    description: str


class FlowTemplateSourceMetadata(BaseModel):
    """Source metadata for a flow template."""

    kind: FlowTemplateSourceKind
    path: str
    schema_version: str
    template_version: str


class FlowCatalogItem(BaseModel):
    """Read-only flow catalog entry."""

    id: str
    name: str
    version: str
    description: str | None = None
    metadata: FlowTemplateMetadata
    template_source: FlowTemplateSourceMetadata
    phase_count: int
    required_inputs: list[str]
    approval_point_count: int
    verifier_count: int


class FlowInputPreview(BaseModel):
    """Flow template input preview."""

    id: str
    type: str
    required: bool = False
    default: Any | None = None
    description: str | None = None


class FlowBudgetsPreview(BaseModel):
    """Flow template budget preview."""

    max_gpu_hours: float | None = None
    max_runs: int | None = None
    max_wall_clock_hours: float | None = None
    max_llm_usd: float | None = None


class FlowPhasePreview(BaseModel):
    """Flow template phase preview."""

    id: str
    name: str
    objective: str
    status: str
    order: int
    required_outputs: list[str]
    approval_points: list[str]
    verifiers: list[str]


class FlowApprovalPointPreview(BaseModel):
    """Approval point preview with phase references."""

    id: str
    risk: str
    action: str
    target: str
    description: str | None = None
    phase_ids: list[str]


class FlowRequiredOutputPreview(BaseModel):
    """Required output preview with phase references."""

    id: str
    type: str
    description: str | None = None
    required: bool = True
    phase_ids: list[str]


class FlowArtifactPreview(BaseModel):
    """Expected artifact preview."""

    id: str
    type: str
    description: str | None = None
    required: bool = True


FlowVerifierMappingStatus = Literal[
    "mapped",
    "intentional_unmapped",
    "unknown_unmapped",
]


class FlowVerifierCheckPreview(BaseModel):
    """Verifier check preview with phase and catalog mapping metadata."""

    id: str
    type: str
    description: str
    required: bool = True
    phase_ids: list[str]
    mapping_status: FlowVerifierMappingStatus
    catalog_check_id: str | None = None
    catalog_check_name: str | None = None
    catalog_check_category: str | None = None
    catalog_check_type: str | None = None
    catalog_evidence_ref_types: list[str]


class FlowVerifierCatalogCoveragePreview(BaseModel):
    """Flow-local verifier to catalog coverage summary."""

    verifier_count: int
    mapped_count: int
    unmapped_count: int
    intentional_unmapped_verifier_ids: list[str]
    unknown_unmapped_verifier_ids: list[str]


class FlowRiskyOperationPreview(BaseModel):
    """Risk-labeled operation surfaced before a flow can start."""

    id: str
    risk: str
    action: str
    target: str
    description: str | None = None
    source: Literal["approval_point"]
    phase_ids: list[str]


class FlowPreviewResponse(BaseModel):
    """Read-only flow preview response."""

    id: str
    name: str
    version: str
    description: str | None = None
    metadata: FlowTemplateMetadata
    template_source: FlowTemplateSourceMetadata
    inputs: list[FlowInputPreview]
    required_inputs: list[FlowInputPreview]
    budgets: FlowBudgetsPreview
    phases: list[FlowPhasePreview]
    approval_points: list[FlowApprovalPointPreview]
    required_outputs: list[FlowRequiredOutputPreview]
    artifacts: list[FlowArtifactPreview]
    verifier_checks: list[FlowVerifierCheckPreview]
    verifier_catalog_coverage: FlowVerifierCatalogCoveragePreview
    risky_operations: list[FlowRiskyOperationPreview]


class PendingApprovalTool(BaseModel):
    """A tool waiting for user approval."""

    tool: str
    tool_call_id: str
    arguments: dict[str, Any] = {}
    risk: str | None = None
    side_effects: list[str] = []
    rollback: str | None = None
    budget_impact: str | None = None
    credential_usage: list[str] = []
    reason: str | None = None


class SessionInfo(BaseModel):
    """Session metadata."""

    session_id: str
    created_at: str
    is_active: bool
    is_processing: bool = False
    message_count: int
    user_id: str = "dev"
    pending_approval: list[PendingApprovalTool] | None = None
    model: str | None = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    active_sessions: int = 0
    max_sessions: int = 0


class LLMHealthResponse(BaseModel):
    """LLM provider health check response."""

    status: str  # "ok" | "error"
    model: str
    error: str | None = None
    error_type: str | None = None  # "auth" | "credits" | "rate_limit" | "network" | "unknown"
