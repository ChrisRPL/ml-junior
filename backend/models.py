"""Pydantic models for API requests and responses."""

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel


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


class FlowTemplateMetadata(BaseModel):
    """Derived catalog metadata for a built-in flow template."""

    category: str
    tags: list[str]
    runtime_class: str


class FlowTemplateSourceMetadata(BaseModel):
    """Source metadata for a built-in flow template."""

    kind: Literal["builtin"]
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


class FlowVerifierCheckPreview(BaseModel):
    """Verifier check preview with phase references."""

    id: str
    type: str
    description: str
    required: bool = True
    phase_ids: list[str]


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
