from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from agent.core.redaction import REDACTION_NONE, redact_value


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


@dataclass
class Event:
    """Legacy event shape used by existing agent call sites."""

    event_type: str
    data: dict[str, Any] | None = None


class RedactionStatus(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    REDACTED = "redacted"


class EventPayload(BaseModel):
    """Base class for typed event payloads.

    Current UI payloads are still compatibility-first, so known payloads are
    validated for required fields while extra fields remain allowed.
    """

    model_config = ConfigDict(extra="allow")


class EmptyPayload(EventPayload):
    pass


class MessagePayload(EventPayload):
    message: str


class AssistantContentPayload(EventPayload):
    content: str


class ToolCallPayload(EventPayload):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str


class ToolOutputPayload(EventPayload):
    tool: str
    tool_call_id: str
    output: str
    success: bool


class ToolLogPayload(EventPayload):
    tool: str
    log: str
    agent_id: str | None = None
    label: str | None = None


class ApprovalToolPayload(EventPayload):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str


class ApprovalRequiredPayload(EventPayload):
    tools: list[ApprovalToolPayload]
    count: int


class ToolStateChangePayload(EventPayload):
    tool_call_id: str
    tool: str
    state: str
    jobUrl: str | None = None


class TurnCompletePayload(EventPayload):
    history_size: int


class CompactedPayload(EventPayload):
    old_tokens: int
    new_tokens: int


class ErrorPayload(EventPayload):
    error: str


class PlanItemPayload(EventPayload):
    id: str
    content: str
    status: str


class PlanUpdatePayload(EventPayload):
    plan: list[PlanItemPayload]


class StrictEventPayload(EventPayload):
    """Payload base for durable metadata events with a closed schema."""

    model_config = ConfigDict(extra="forbid")


class PhaseContinuityRefPayload(StrictEventPayload):
    type: Literal["phase"]
    phase_id: str = Field(min_length=1)


class RunContinuityRefPayload(StrictEventPayload):
    type: Literal["run"]
    run_id: str = Field(min_length=1)


class CodeSnapshotContinuityRefPayload(StrictEventPayload):
    type: Literal["code_snapshot"]
    snapshot_id: str = Field(min_length=1)


class DatasetSnapshotContinuityRefPayload(StrictEventPayload):
    type: Literal["dataset_snapshot"]
    snapshot_id: str = Field(min_length=1)


class ModelCheckpointContinuityRefPayload(StrictEventPayload):
    type: Literal["model_checkpoint"]
    checkpoint_id: str = Field(min_length=1)


class EventSequenceContinuityRefPayload(StrictEventPayload):
    type: Literal["event_sequence"]
    sequence: int = Field(ge=1)


ContinuityRefPayload = Annotated[
    PhaseContinuityRefPayload
    | RunContinuityRefPayload
    | CodeSnapshotContinuityRefPayload
    | DatasetSnapshotContinuityRefPayload
    | ModelCheckpointContinuityRefPayload
    | EventSequenceContinuityRefPayload,
    Field(discriminator="type"),
]


class CheckpointCreatedPayload(StrictEventPayload):
    session_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    phase_id: str | None = Field(default=None, min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    refs: list[ContinuityRefPayload] | None = None


class ForkPointCreatedPayload(StrictEventPayload):
    session_id: str = Field(min_length=1)
    fork_point_id: str = Field(min_length=1)
    reason: str | None = Field(default=None, min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    refs: list[ContinuityRefPayload] = Field(default_factory=list)


class HandoffSummarySnapshotPayload(StrictEventPayload):
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


class HandoffSummaryCreatedPayload(StrictEventPayload):
    session_id: str = Field(min_length=1)
    handoff_id: str = Field(min_length=1)
    source_event_sequence: int | None = Field(default=None, ge=1)
    summary: HandoffSummarySnapshotPayload

    @model_validator(mode="after")
    def validate_summary_session(self) -> HandoffSummaryCreatedPayload:
        if self.summary.session_id != self.session_id:
            raise ValueError("summary.session_id must match session_id")
        return self


class ExperimentLedgerPayload(StrictEventPayload):
    """Closed-schema base for inert experiment ledger event payloads."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ExperimentDatasetSnapshotRefPayload(ExperimentLedgerPayload):
    snapshot_id: NonEmptyStr
    source: Literal["dataset_registry", "local_path", "remote_uri", "event_ref"]
    uri: NonEmptyStr | None = None
    name: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None


class ExperimentCodeSnapshotRefPayload(ExperimentLedgerPayload):
    snapshot_id: NonEmptyStr
    source: Literal["git", "archive", "local_path", "event_ref"]
    uri: NonEmptyStr | None = None
    git_commit: NonEmptyStr | None = None
    git_ref: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None


class DatasetSnapshotRecordedPayload(ExperimentLedgerPayload):
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


class CodeSnapshotRecordedPayload(ExperimentLedgerPayload):
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


class ExperimentMetricRecordPayload(ExperimentLedgerPayload):
    name: NonEmptyStr
    value: int | float | str | bool
    source: Literal["manual", "tool", "verifier", "external_tracking"]
    step: int | None = Field(default=None, ge=0)
    unit: NonEmptyStr | None = None
    recorded_at: NonEmptyStr | None = None


class ExperimentLogRefPayload(ExperimentLedgerPayload):
    log_id: NonEmptyStr
    source: Literal["stdout", "stderr", "local_path", "remote_uri", "event_ref"]
    uri: NonEmptyStr | None = None
    label: NonEmptyStr | None = None


class MetricRecordedPayload(ExperimentMetricRecordPayload):
    session_id: NonEmptyStr
    metric_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)


class LogRefRecordedPayload(ExperimentLogRefPayload):
    session_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)


class ExperimentArtifactRefPayload(ExperimentLedgerPayload):
    artifact_id: NonEmptyStr
    type: NonEmptyStr
    source: Literal["local_path", "remote_uri", "hf_hub", "event_ref"]
    uri: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None


class ExperimentVerifierRefPayload(ExperimentLedgerPayload):
    verifier_id: NonEmptyStr
    type: Literal["manual", "metric", "artifact", "command", "llm"]
    status: Literal["pending", "passed", "failed", "inconclusive"]
    source: Literal["flow_template", "runtime", "external"]
    result_ref: NonEmptyStr | None = None


class ExperimentExternalTrackingRefPayload(ExperimentLedgerPayload):
    tracking_id: NonEmptyStr
    source: Literal["external_tracking", "event_ref"]
    provider: NonEmptyStr
    uri: NonEmptyStr | None = None
    run_name: NonEmptyStr | None = None


class ExperimentRunRuntimePayload(ExperimentLedgerPayload):
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


class ExperimentRunRecordedPayload(ExperimentLedgerPayload):
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
    dataset_snapshot_refs: list[ExperimentDatasetSnapshotRefPayload] = Field(
        default_factory=list
    )
    code_snapshot_refs: list[ExperimentCodeSnapshotRefPayload] = Field(
        default_factory=list
    )
    config: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None
    runtime: ExperimentRunRuntimePayload | None = None
    metrics: list[ExperimentMetricRecordPayload] = Field(default_factory=list)
    log_refs: list[ExperimentLogRefPayload] = Field(default_factory=list)
    artifact_refs: list[ExperimentArtifactRefPayload] = Field(default_factory=list)
    verifier_refs: list[ExperimentVerifierRefPayload] = Field(default_factory=list)
    external_tracking_refs: list[ExperimentExternalTrackingRefPayload] = Field(
        default_factory=list
    )
    created_at: NonEmptyStr | None = None


class ActiveJobRecordedPayload(ExperimentLedgerPayload):
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


class ArtifactRefRecordedPayload(ExperimentLedgerPayload):
    session_id: NonEmptyStr
    artifact_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    type: NonEmptyStr
    source: Literal[
        "tool",
        "job",
        "local_path",
        "remote_uri",
        "hf_hub",
        "event_ref",
        "manual",
    ]
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


EVENT_PAYLOAD_MODELS: dict[str, type[EventPayload]] = {
    "ready": MessagePayload,
    "processing": MessagePayload,
    "assistant_message": AssistantContentPayload,
    "assistant_chunk": AssistantContentPayload,
    "assistant_stream_end": EmptyPayload,
    "tool_call": ToolCallPayload,
    "tool_output": ToolOutputPayload,
    "tool_log": ToolLogPayload,
    "approval_required": ApprovalRequiredPayload,
    "tool_state_change": ToolStateChangePayload,
    "turn_complete": TurnCompletePayload,
    "compacted": CompactedPayload,
    "error": ErrorPayload,
    "shutdown": EmptyPayload,
    "interrupted": EmptyPayload,
    "undo_complete": EmptyPayload,
    "plan_update": PlanUpdatePayload,
    "checkpoint.created": CheckpointCreatedPayload,
    "fork_point.created": ForkPointCreatedPayload,
    "handoff.summary_created": HandoffSummaryCreatedPayload,
    "dataset_snapshot.recorded": DatasetSnapshotRecordedPayload,
    "code_snapshot.recorded": CodeSnapshotRecordedPayload,
    "metric.recorded": MetricRecordedPayload,
    "log_ref.recorded": LogRefRecordedPayload,
    "experiment.run_recorded": ExperimentRunRecordedPayload,
    "active_job.recorded": ActiveJobRecordedPayload,
    "artifact_ref.recorded": ArtifactRefRecordedPayload,
}


class AgentEvent(BaseModel):
    """Internal event envelope for queueing and future persistence."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    redaction_status: RedactionStatus = RedactionStatus.NONE
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_known_payload(self) -> AgentEvent:
        payload_model = EVENT_PAYLOAD_MODELS.get(self.event_type)
        if payload_model is None:
            return self
        payload = payload_model.model_validate(self.data or {})
        self.data = payload.model_dump(exclude_none=True)
        return self

    @classmethod
    def from_legacy(
        cls,
        event: Event,
        *,
        session_id: str,
        sequence: int,
    ) -> AgentEvent:
        return cls(
            session_id=session_id,
            sequence=sequence,
            event_type=event.event_type,
            data=event.data or {},
        )

    def to_legacy_sse(self) -> dict[str, Any]:
        """Serialize to the current SSE payload shape."""
        return {"event_type": self.event_type, "data": self.data}

    def to_legacy_dict(self) -> dict[str, Any]:
        """Alias for callers that do not need to know SSE naming."""
        return self.to_legacy_sse()

    def redacted_copy(self) -> AgentEvent:
        """Return an event copy with serialized data redacted."""
        result = redact_value(self.data)
        if result.status == REDACTION_NONE:
            return self
        status = _stronger_redaction_status(self.redaction_status, result.status)
        return self.model_copy(
            update={
                "data": result.value,
                "redaction_status": status,
            }
        )


def _stronger_redaction_status(left: str, right: str) -> str:
    order = {
        RedactionStatus.NONE.value: 0,
        RedactionStatus.PARTIAL.value: 1,
        RedactionStatus.REDACTED.value: 2,
    }
    left_value = str(left)
    right_value = str(right)
    if order.get(left_value, 0) >= order.get(right_value, 0):
        return left_value
    return right_value
