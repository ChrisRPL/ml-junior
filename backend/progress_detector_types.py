from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


FindingKind = Literal[
    "repeated_identical_error",
    "stale_no_artifact_progress",
    "long_active_phase",
    "polling_loop_signal",
]
FindingSeverity = Literal["info", "warning"]

ARTIFACT_EVENT_TYPES = {
    "artifact.created",
    "artifact.recorded",
    "artifact_ref.recorded",
}
MATERIAL_PROGRESS_EVENT_TYPES = {
    *ARTIFACT_EVENT_TYPES,
    "checkpoint.created",
    "code_snapshot.recorded",
    "dataset_snapshot.recorded",
    "evidence_item.recorded",
    "experiment.run_recorded",
    "log_ref.recorded",
    "metric.recorded",
    "phase.completed",
    "phase.verified",
    "verifier.completed",
}
ACTIVE_WORKFLOW_STATUSES = {"processing", "waiting_approval", "blocked"}
ACTIVE_PHASE_STATUSES = {"active", "blocked"}
POLLING_STATES = {"pending", "polling", "queued", "running", "waiting"}
POLLING_WORDS = {
    "check",
    "describe",
    "get",
    "list",
    "poll",
    "status",
    "wait",
    "watch",
}
FAILED_STATES = {"error", "fail", "failed", "failure"}


class ProgressDetectorThresholds(BaseModel):
    """Tunable thresholds for advisory-only stuck/progress detection."""

    model_config = ConfigDict(extra="forbid", strict=True)

    repeated_error_count: int = Field(default=2, ge=2)
    stale_progress_seconds: int = Field(default=30 * 60, ge=1)
    long_active_phase_seconds: int = Field(default=2 * 60 * 60, ge=1)
    polling_signal_count: int = Field(default=4, ge=2)


class ProgressEventRef(BaseModel):
    """Small event reference safe to return in detector findings."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    sequence: int
    event_type: str
    timestamp: str | None = None


class ProgressFindingEvidence(BaseModel):
    """Structured evidence supporting one advisory finding."""

    model_config = ConfigDict(extra="forbid")

    source: Literal["event", "workflow", "derived"]
    summary: str
    event_refs: list[ProgressEventRef] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)


class ProgressFinding(BaseModel):
    """Advisory finding. It must not be treated as a runtime decision."""

    model_config = ConfigDict(extra="forbid")

    kind: FindingKind
    severity: FindingSeverity = "warning"
    advisory: Literal[True] = True
    title: str
    summary: str
    evidence: list[ProgressFindingEvidence]
    recommended_next_action: str


class ProgressDetectorReport(BaseModel):
    """Pure progress/stuck detector output over caller-supplied state."""

    model_config = ConfigDict(extra="forbid")

    snapshot_version: Literal[1] = 1
    session_id: str
    observed_at: str | None = None
    finding_count: int
    findings: list[ProgressFinding]
