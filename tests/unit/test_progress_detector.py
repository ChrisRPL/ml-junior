from __future__ import annotations

from datetime import datetime, timedelta, timezone

from agent.core.events import AgentEvent
from backend.models import (
    PhaseState,
    WorkflowCompatibility,
    WorkflowObjective,
    WorkflowResumeState,
    WorkflowState,
)
from backend.progress_detector import (
    ProgressDetectorThresholds,
    detect_progress_findings,
)


BASE_TIME = datetime(2026, 4, 30, 10, 0, tzinfo=timezone.utc)


def at(minutes: int) -> datetime:
    return BASE_TIME + timedelta(minutes=minutes)


def make_event(
    *,
    sequence: int,
    event_type: str,
    data: dict,
    session_id: str = "session-a",
    minutes: int | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=at(minutes if minutes is not None else sequence),
        event_type=event_type,
        data=data,
    )


def make_workflow_state(
    *,
    status: str = "processing",
    phase_status: str = "active",
    phase_started_at: str | None = None,
    updated_at: str | None = None,
    artifact_count: int = 0,
    session_id: str = "session-a",
) -> WorkflowState:
    return WorkflowState(
        session_id=session_id,
        project_id=f"session:{session_id}",
        status=status,
        objective=WorkflowObjective(),
        phase=PhaseState(
            id="phase-train",
            label="Train model",
            status=phase_status,
            started_at=phase_started_at,
            updated_at=updated_at,
        ),
        plan=[],
        blockers=[],
        pending_approvals=[],
        active_jobs=[],
        operation_refs=[],
        human_requests=[],
        budget={
            "source": "placeholder",
            "status": "placeholder",
            "items": [],
        },
        evidence_summary={
            "source": "event",
            "status": "available",
            "artifact_count": artifact_count,
            "items": [],
        },
        live_tracking_refs=[],
        resume=WorkflowResumeState(event_sequence=0),
        compatibility=WorkflowCompatibility(stale=False, missing_producers=[]),
        last_event_sequence=0,
        updated_at=updated_at,
    )


def finding_kinds(report) -> list[str]:
    return [finding.kind for finding in report.findings]


def test_detects_repeated_identical_errors_with_event_evidence():
    workflow_state = make_workflow_state(
        status="error",
        phase_status="failed",
        updated_at=at(2).isoformat(),
    )
    events = [
        make_event(
            sequence=1,
            event_type="error",
            data={"error": "CUDA out of memory"},
        ),
        make_event(
            sequence=2,
            event_type="error",
            data={"error": " CUDA   out of memory "},
        ),
        make_event(
            sequence=3,
            event_type="error",
            data={"error": "CUDA out of memory"},
            session_id="session-b",
        ),
    ]

    report = detect_progress_findings(
        workflow_state=workflow_state,
        events=events,
        thresholds=ProgressDetectorThresholds(repeated_error_count=2),
    )

    assert finding_kinds(report) == ["repeated_identical_error"]
    finding = report.findings[0]
    assert finding.advisory is True
    assert finding.recommended_next_action
    assert finding.evidence[0].details["count"] == 2
    assert finding.evidence[0].details["normalized_error"] == "cuda out of memory"
    assert [ref.sequence for ref in finding.evidence[0].event_refs] == [1, 2]


def test_detects_stale_active_workflow_with_no_artifacts():
    workflow_state = make_workflow_state(
        phase_started_at=at(0).isoformat(),
        updated_at=at(45).isoformat(),
    )
    events = [
        make_event(
            sequence=1,
            event_type="phase.started",
            minutes=0,
            data={"phase_id": "phase-train", "phase_name": "Train model"},
        ),
        make_event(
            sequence=2,
            event_type="tool_call",
            minutes=20,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "logs", "job_id": "job-1"},
                "tool_call_id": "tc-1",
            },
        ),
        make_event(
            sequence=3,
            event_type="assistant_message",
            minutes=45,
            data={"content": "Still waiting for output."},
        ),
    ]

    report = detect_progress_findings(
        workflow_state=workflow_state,
        events=events,
        now=at(45),
        thresholds=ProgressDetectorThresholds(
            stale_progress_seconds=30 * 60,
            long_active_phase_seconds=3 * 60 * 60,
            polling_signal_count=4,
        ),
    )

    assert finding_kinds(report) == ["stale_no_artifact_progress"]
    details = report.findings[0].evidence[0].details
    assert details["artifact_count"] == 0
    assert details["active_seconds"] == 45 * 60
    assert details["seconds_without_progress"] == 45 * 60
    assert details["threshold_seconds"] == 30 * 60


def test_detects_long_active_phase_from_workflow_state_only():
    workflow_state = make_workflow_state(
        phase_started_at=at(0).isoformat(),
        updated_at=at(130).isoformat(),
        artifact_count=1,
    )

    report = detect_progress_findings(
        workflow_state=workflow_state,
        events=[],
        now=at(130),
        thresholds=ProgressDetectorThresholds(
            stale_progress_seconds=4 * 60 * 60,
            long_active_phase_seconds=2 * 60 * 60,
        ),
    )

    assert finding_kinds(report) == ["long_active_phase"]
    details = report.findings[0].evidence[0].details
    assert details["phase_id"] == "phase-train"
    assert details["active_seconds"] == 130 * 60
    assert details["threshold_seconds"] == 2 * 60 * 60


def test_detects_polling_loop_signals_without_material_progress():
    workflow_state = make_workflow_state(
        phase_started_at=at(0).isoformat(),
        updated_at=at(3).isoformat(),
        artifact_count=1,
    )
    events = [
        make_event(
            sequence=1,
            event_type="tool_call",
            minutes=1,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "status", "job_id": "job-1"},
                "tool_call_id": "tc-1",
            },
        ),
        make_event(
            sequence=2,
            event_type="tool_call",
            minutes=2,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "status", "job_id": "job-1"},
                "tool_call_id": "tc-2",
            },
        ),
        make_event(
            sequence=3,
            event_type="tool_call",
            minutes=3,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "status", "job_id": "job-1"},
                "tool_call_id": "tc-3",
            },
        ),
    ]

    report = detect_progress_findings(
        workflow_state=workflow_state,
        events=events,
        now=at(3),
        thresholds=ProgressDetectorThresholds(
            stale_progress_seconds=4 * 60 * 60,
            long_active_phase_seconds=4 * 60 * 60,
            polling_signal_count=3,
        ),
    )

    assert finding_kinds(report) == ["polling_loop_signal"]
    evidence = report.findings[0].evidence[0]
    assert evidence.details["count"] == 3
    assert evidence.details["first_sequence"] == 1
    assert evidence.details["last_sequence"] == 3
    assert [ref.sequence for ref in evidence.event_refs] == [1, 2, 3]


def test_material_progress_between_polls_suppresses_polling_finding():
    workflow_state = make_workflow_state(
        phase_started_at=at(0).isoformat(),
        updated_at=at(4).isoformat(),
        artifact_count=1,
    )
    events = [
        make_event(
            sequence=1,
            event_type="tool_call",
            minutes=1,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "status", "job_id": "job-1"},
                "tool_call_id": "tc-1",
            },
        ),
        make_event(
            sequence=2,
            event_type="metric.recorded",
            minutes=2,
            data={
                "session_id": "session-a",
                "metric_id": "metric-1",
                "source_event_sequence": 2,
                "name": "accuracy",
                "value": 0.9,
                "source": "tool",
                "step": 1,
                "recorded_at": at(2).isoformat(),
            },
        ),
        make_event(
            sequence=3,
            event_type="tool_call",
            minutes=3,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "status", "job_id": "job-1"},
                "tool_call_id": "tc-3",
            },
        ),
        make_event(
            sequence=4,
            event_type="tool_call",
            minutes=4,
            data={
                "tool": "hf_jobs",
                "arguments": {"operation": "status", "job_id": "job-1"},
                "tool_call_id": "tc-4",
            },
        ),
    ]

    report = detect_progress_findings(
        workflow_state=workflow_state,
        events=events,
        now=at(4),
        thresholds=ProgressDetectorThresholds(
            stale_progress_seconds=4 * 60 * 60,
            long_active_phase_seconds=4 * 60 * 60,
            polling_signal_count=3,
        ),
    )

    assert report.findings == []
