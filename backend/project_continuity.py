from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from agent.core.events import AgentEvent

try:
    from models import (
        HandoffSummary,
        HandoffSummaryCreatedEvent,
        ProjectCheckpoint,
        ProjectForkPoint,
        WorkflowState,
    )
except ModuleNotFoundError:
    from backend.models import (
        HandoffSummary,
        HandoffSummaryCreatedEvent,
        ProjectCheckpoint,
        ProjectForkPoint,
        WorkflowState,
    )


CHECKPOINT_CREATED_EVENT = "checkpoint.created"
FORK_POINT_CREATED_EVENT = "fork_point.created"
HANDOFF_SUMMARY_CREATED_EVENT = "handoff.summary_created"


class ContinuityEventError(ValueError):
    """Raised when a durable continuity event is not the expected metadata shape."""


def checkpoint_from_event(event: AgentEvent) -> ProjectCheckpoint:
    """Validate a checkpoint.created event as metadata only."""
    if event.event_type != CHECKPOINT_CREATED_EVENT:
        raise ContinuityEventError(f"Expected {CHECKPOINT_CREATED_EVENT}")
    return ProjectCheckpoint.model_validate(event.data or {})


def fork_point_from_event(event: AgentEvent) -> ProjectForkPoint:
    """Validate a fork_point.created event without creating referenced records."""
    if event.event_type != FORK_POINT_CREATED_EVENT:
        raise ContinuityEventError(f"Expected {FORK_POINT_CREATED_EVENT}")
    return ProjectForkPoint.model_validate(event.data or {})


def checkpoint_created_payload(
    *,
    session_id: str,
    checkpoint_id: str,
    reason: str,
    phase_id: str | None = None,
    source_event_sequence: int | None = None,
    refs: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a checkpoint.created payload from caller-supplied metadata."""
    checkpoint = ProjectCheckpoint(
        session_id=session_id,
        checkpoint_id=checkpoint_id,
        reason=reason,
        phase_id=phase_id,
        source_event_sequence=source_event_sequence,
        refs=list(refs) if refs is not None else None,
    )
    return checkpoint.model_dump(mode="json", exclude_none=True)


def fork_point_created_payload(
    *,
    session_id: str,
    fork_point_id: str,
    reason: str | None = None,
    source_event_sequence: int | None = None,
    refs: Sequence[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a fork_point.created payload from caller-supplied metadata."""
    fork_point = ProjectForkPoint(
        session_id=session_id,
        fork_point_id=fork_point_id,
        reason=reason,
        source_event_sequence=source_event_sequence,
        refs=list(refs) if refs is not None else [],
    )
    return fork_point.model_dump(mode="json", exclude_none=True)


def handoff_summary_created_payload(
    *,
    handoff_id: str,
    summary: HandoffSummary,
) -> dict[str, Any]:
    """Build a durable handoff.summary_created payload from a pure summary."""
    payload = HandoffSummaryCreatedEvent(
        session_id=summary.session_id,
        handoff_id=handoff_id,
        source_event_sequence=summary.source_event_sequence or None,
        summary=summary,
    )
    return payload.model_dump(exclude_none=True)


def generate_handoff_summary(
    *,
    workflow_state: WorkflowState,
    events: Sequence[AgentEvent],
) -> HandoffSummary:
    """Generate a handoff summary from supplied projections and durable events."""
    ordered_events = _ordered_session_events(workflow_state.session_id, events)
    last_sequence = max(
        [
            workflow_state.last_event_sequence,
            *(event.sequence for event in ordered_events),
        ],
        default=workflow_state.last_event_sequence,
    )

    completed_phases = _completed_phases(workflow_state, ordered_events)
    current_phase = _current_phase(workflow_state)
    decisions: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    jobs = _jobs_from_state(workflow_state)
    failures: list[dict[str, Any]] = []
    risks = _risks_from_state(workflow_state)
    next_action = "not_recorded"

    for event in ordered_events:
        item = _event_item(event)
        if event.event_type in {"decision.created", "decision.recorded"}:
            decisions.append(item)
        elif event.event_type in {"evidence.created", "evidence.recorded"}:
            evidence.append(item)
        elif event.event_type in {"artifact.created", "artifact.recorded"}:
            artifacts.append(item)
        elif event.event_type in {"job.created", "job.started", "job.recorded"}:
            jobs.append(item)
        elif event.event_type in {"failure.created", "failure.recorded"}:
            failures.append(item)
        elif event.event_type in {"risk.created", "risk.recorded"}:
            risks.append(item)
        elif event.event_type == "phase.failed":
            failures.append(_phase_failure_item(event))
        elif event.event_type == "error":
            failures.append(_error_item(event))
        elif event.event_type in {"next_action.recorded", "next_action.created"}:
            next_action = _next_action_from_event(event) or next_action

    return HandoffSummary(
        session_id=workflow_state.session_id,
        source_event_sequence=last_sequence,
        goal=_goal_from_state(workflow_state),
        completed_phases=completed_phases,
        current_phase=current_phase,
        decisions=decisions,
        evidence=_evidence_from_state(workflow_state) + evidence,
        artifacts=artifacts,
        jobs=jobs,
        failures=failures,
        risks=risks,
        next_action=next_action,
    )


def _ordered_session_events(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[AgentEvent]:
    return sorted(
        [event for event in events if event.session_id == session_id],
        key=lambda event: (event.sequence, str(event.id)),
    )


def _goal_from_state(workflow_state: WorkflowState) -> str | None:
    objective = workflow_state.objective
    if objective.source == "placeholder":
        return None
    return objective.text


def _completed_phases(
    workflow_state: WorkflowState,
    events: Sequence[AgentEvent],
) -> list[dict[str, Any]]:
    completed: list[dict[str, Any]] = []
    seen: set[str] = set()

    for event in events:
        if event.event_type not in {"phase.completed", "phase.verified"}:
            continue
        phase_id = event.data.get("phase_id")
        if phase_id is None or str(phase_id) in seen:
            continue
        seen.add(str(phase_id))
        completed.append(
            {
                "phase_id": str(phase_id),
                "phase_name": event.data.get("phase_name"),
                "source_event_sequence": event.sequence,
                "updated_at": _event_timestamp(event),
            }
        )

    phase = workflow_state.phase
    if (
        phase.id != "compatibility-session"
        and phase.status == "complete"
        and phase.id not in seen
    ):
        completed.append(
            {
                "phase_id": phase.id,
                "phase_name": phase.label,
                "source_event_sequence": None,
                "updated_at": phase.updated_at,
            }
        )

    return completed


def _current_phase(workflow_state: WorkflowState) -> dict[str, Any] | None:
    phase = workflow_state.phase
    if phase.id == "compatibility-session" or phase.status == "placeholder":
        return None
    return {
        "phase_id": phase.id,
        "phase_name": phase.label,
        "status": phase.status,
        "started_at": phase.started_at,
        "updated_at": phase.updated_at,
    }


def _jobs_from_state(workflow_state: WorkflowState) -> list[dict[str, Any]]:
    return [dict(item) for item in workflow_state.active_jobs]


def _risks_from_state(workflow_state: WorkflowState) -> list[dict[str, Any]]:
    return [dict(item) for item in workflow_state.blockers]


def _evidence_from_state(workflow_state: WorkflowState) -> list[dict[str, Any]]:
    summary = workflow_state.evidence_summary
    if not isinstance(summary, dict) or summary.get("source") == "placeholder":
        return []
    items = summary.get("items")
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]


def _event_item(event: AgentEvent) -> dict[str, Any]:
    item = {
        key: value
        for key, value in (event.data or {}).items()
        if key not in {"session_id"}
    }
    item.setdefault("source", "event")
    item["source_event_sequence"] = event.sequence
    item["updated_at"] = _event_timestamp(event)
    return item


def _phase_failure_item(event: AgentEvent) -> dict[str, Any]:
    return {
        "source": "event",
        "type": "phase",
        "phase_id": event.data.get("phase_id"),
        "phase_name": event.data.get("phase_name"),
        "source_event_sequence": event.sequence,
        "updated_at": _event_timestamp(event),
    }


def _error_item(event: AgentEvent) -> dict[str, Any]:
    return {
        "source": "event",
        "type": "error",
        "error": event.data.get("error"),
        "source_event_sequence": event.sequence,
        "updated_at": _event_timestamp(event),
    }


def _next_action_from_event(event: AgentEvent) -> str | None:
    value = (event.data or {}).get("next_action") or (event.data or {}).get("action")
    if value is None:
        return None
    return str(value)


def _event_timestamp(event: AgentEvent) -> str | None:
    timestamp = event.timestamp
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    if timestamp is None:
        return None
    return str(timestamp)
