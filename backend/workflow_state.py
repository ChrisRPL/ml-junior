from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.core.events import AgentEvent
from backend.job_artifact_refs import project_active_jobs, project_artifact_refs
from backend.operation_store import OperationRecord
from backend.session_store import SessionRecord

try:
    from models import (
        PhaseState,
        WorkflowCompatibility,
        WorkflowObjective,
        WorkflowPlanItem,
        WorkflowResumeState,
        WorkflowState,
    )
except ModuleNotFoundError:
    from backend.models import (
        PhaseState,
        WorkflowCompatibility,
        WorkflowObjective,
        WorkflowPlanItem,
        WorkflowResumeState,
        WorkflowState,
    )

_WORKFLOW_MISSING_PRODUCERS = [
    "workflow_events",
    "budget_ledger",
    "evidence_ledger",
    "live_tracking",
]
_ACTIVE_JOB_TERMINAL_STATES = {
    "cancelled",
    "canceled",
    "complete",
    "completed",
    "done",
    "error",
    "failed",
    "succeeded",
    "success",
}
_PROCESSING_EVENTS = {
    "assistant_chunk",
    "assistant_message",
    "assistant_stream_end",
    "processing",
    "tool_call",
    "tool_output",
    "tool_state_change",
}
_PHASE_EVENT_TYPES = {
    "phase.not_started",
    "phase.pending",
    "phase.started",
    "phase.blocked",
    "phase.completed",
    "phase.failed",
    "phase.verified",
}
_PHASE_EVENT_STATUS = {
    "not_started": "placeholder",
    "pending": "pending",
    "active": "active",
    "started": "active",
    "blocked": "blocked",
    "complete": "complete",
    "completed": "complete",
    "verified": "complete",
    "failed": "failed",
    "verifier_pending": "blocked",
}


def build_workflow_state(
    *,
    session_id: str,
    events: list[AgentEvent],
    session_record: SessionRecord | None = None,
    operations: list[OperationRecord] | None = None,
) -> WorkflowState:
    """Build a read-only workflow projection from durable backend state."""
    unique_events = _dedupe_events(
        [event for event in events if event.session_id == session_id]
    )
    last_event_sequence = max((event.sequence for event in unique_events), default=0)
    last_event = unique_events[-1] if unique_events else None
    last_event_timestamp = _event_timestamp(last_event)
    record_updated_at = (
        session_record.updated_at.isoformat() if session_record is not None else None
    )
    updated_at = last_event_timestamp or record_updated_at
    stale = not unique_events

    plan_items: list[WorkflowPlanItem] = []
    event_pending_approvals: dict[str, dict[str, Any]] = {}
    active_jobs: dict[str, dict[str, Any]] = {}
    recorded_active_jobs = _active_job_refs_from_events(session_id, unique_events)
    recorded_artifact_refs = _artifact_refs_from_events(session_id, unique_events)
    phase_projection: PhaseState | None = None
    phase_started_at: dict[str, str | None] = {}
    phase_blockers: list[dict[str, Any]] = []
    status = "stale" if stale else "idle"

    for event in unique_events:
        event_timestamp = _event_timestamp(event)
        data = event.data or {}

        if event.event_type == "plan_update":
            plan_items = _plan_items_from_event(data, event, event_timestamp)
        elif event.event_type == "approval_required":
            event_pending_approvals = _approval_refs_from_event(
                data,
                event,
                event_timestamp,
            )
        elif event.event_type in {"tool_call", "tool_state_change", "tool_output"}:
            if event_pending_approvals:
                event_pending_approvals = {}
            _apply_tool_event(active_jobs, event, event_timestamp)
        elif event.event_type == "turn_complete":
            event_pending_approvals = {}
        elif event.event_type in _PHASE_EVENT_TYPES:
            projected_phase = _phase_state_from_event(
                event,
                event_timestamp,
                phase_started_at,
            )
            if projected_phase is not None:
                phase_projection = projected_phase
            phase_blockers = _phase_blockers_from_event(event, event_timestamp)

    pending_approvals = _merge_refs(
        event_pending_approvals.values(),
        _durable_refs(
            getattr(session_record, "pending_approval_refs", []),
            source="durable",
        ),
        key_names=("tool_call_id", "approval_id", "id"),
    )
    active_job_refs = _merge_refs(
        active_jobs.values(),
        [
            *recorded_active_jobs,
            *_durable_refs(
                getattr(session_record, "active_job_refs", []),
                source="durable",
            ),
        ],
        key_names=("job_id", "tool_call_id", "id"),
    )

    if pending_approvals:
        status = "waiting_approval"
    elif active_job_refs:
        status = "processing"
    elif last_event is not None:
        status = _status_from_last_event(last_event)
        if (
            status == "processing"
            and not active_job_refs
            and last_event.event_type == "tool_output"
        ):
            status = "completed"

    return WorkflowState(
        snapshot_version=1,
        session_id=session_id,
        project_id=f"session:{session_id}",
        status=status,
        objective=WorkflowObjective(),
        phase=phase_projection or _phase_state(session_record, status, updated_at),
        plan=plan_items,
        blockers=phase_blockers,
        pending_approvals=pending_approvals,
        active_jobs=active_job_refs,
        operation_refs=_operation_refs(operations or []),
        human_requests=[],
        budget=_budget_placeholder(),
        evidence_summary=_evidence_summary(recorded_artifact_refs),
        live_tracking_refs=[_live_tracking_placeholder(session_id)],
        resume=WorkflowResumeState(event_sequence=last_event_sequence),
        compatibility=WorkflowCompatibility(
            stale=stale,
            missing_producers=list(_WORKFLOW_MISSING_PRODUCERS),
        ),
        last_event_sequence=last_event_sequence,
        updated_at=updated_at,
    )


def _dedupe_events(events: list[AgentEvent]) -> list[AgentEvent]:
    seen_sequences: set[int] = set()
    seen_ids: set[str] = set()
    unique: list[AgentEvent] = []
    for event in sorted(events, key=lambda item: (item.sequence, str(item.id))):
        if event.sequence in seen_sequences or event.id in seen_ids:
            continue
        seen_sequences.add(event.sequence)
        seen_ids.add(event.id)
        unique.append(event)
    return unique


def _event_timestamp(event: AgentEvent | None) -> str | None:
    if event is None:
        return None
    timestamp = event.timestamp
    if isinstance(timestamp, datetime):
        return timestamp.isoformat()
    if timestamp is None:
        return None
    return str(timestamp)


def _phase_state(
    session_record: SessionRecord | None,
    status: str,
    updated_at: str | None,
) -> PhaseState:
    started_at = (
        session_record.created_at.isoformat() if session_record is not None else None
    )
    return PhaseState(
        id="compatibility-session",
        label="Session",
        status=_phase_status(status),
        started_at=started_at,
        updated_at=updated_at,
    )


def _phase_state_from_event(
    event: AgentEvent,
    updated_at: str | None,
    phase_started_at: dict[str, str | None],
) -> PhaseState | None:
    data = event.data or {}
    phase_id = data.get("phase_id")
    if phase_id is None:
        return None
    phase_id = str(phase_id)

    if event.event_type == "phase.started":
        phase_started_at[phase_id] = updated_at

    return PhaseState(
        id=phase_id,
        label=str(data.get("phase_name") or phase_id),
        status=_phase_event_status(event),
        started_at=phase_started_at.get(phase_id),
        updated_at=updated_at,
    )


def _phase_event_status(event: AgentEvent) -> str:
    data = event.data or {}
    raw_status = data.get("to_status") or data.get("status")
    if raw_status is None:
        raw_status = event.event_type.removeprefix("phase.")
    return _PHASE_EVENT_STATUS.get(str(raw_status).strip().lower(), "blocked")


def _phase_blockers_from_event(
    event: AgentEvent,
    updated_at: str | None,
) -> list[dict[str, Any]]:
    if event.event_type != "phase.blocked":
        return []

    data = event.data or {}
    return [
        {
            "source": "event",
            "type": "phase_gate",
            "source_event_sequence": event.sequence,
            "updated_at": updated_at,
            "phase_id": data.get("phase_id"),
            "gate_status": data.get("gate_status"),
            "requested_status": data.get("requested_status"),
            "to_status": data.get("to_status"),
            "missing_outputs": list(data.get("missing_outputs") or []),
            "pending_verifiers": list(data.get("pending_verifiers") or []),
            "failed_verifiers": list(data.get("failed_verifiers") or []),
            "waiver_records": list(data.get("waiver_records") or []),
        }
    ]


def _phase_status(status: str) -> str:
    if status == "processing":
        return "active"
    if status in {"waiting_approval", "blocked", "interrupted"}:
        return "blocked"
    if status == "error":
        return "failed"
    if status == "completed":
        return "complete"
    return "placeholder"


def _plan_items_from_event(
    data: dict[str, Any],
    event: AgentEvent,
    updated_at: str | None,
) -> list[WorkflowPlanItem]:
    items: list[WorkflowPlanItem] = []
    for raw_item in data.get("plan") or []:
        if not isinstance(raw_item, dict):
            continue
        item_id = raw_item.get("id")
        content = raw_item.get("content")
        status = raw_item.get("status")
        if item_id is None or content is None or status is None:
            continue
        items.append(
            WorkflowPlanItem(
                id=str(item_id),
                content=str(content),
                status=str(status),
                source_event_sequence=event.sequence,
                updated_at=updated_at,
            )
        )
    return items


def _approval_refs_from_event(
    data: dict[str, Any],
    event: AgentEvent,
    updated_at: str | None,
) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for index, raw_tool in enumerate(data.get("tools") or []):
        if not isinstance(raw_tool, dict):
            continue
        tool_call_id = (
            raw_tool.get("tool_call_id") or f"approval:{event.sequence}:{index}"
        )
        ref = {
            "source": "event",
            "source_event_sequence": event.sequence,
            "updated_at": updated_at,
            **raw_tool,
            "tool_call_id": str(tool_call_id),
        }
        refs[str(tool_call_id)] = ref
    return refs


def _apply_tool_event(
    active_jobs: dict[str, dict[str, Any]],
    event: AgentEvent,
    updated_at: str | None,
) -> None:
    data = event.data or {}
    tool_call_id = data.get("tool_call_id")
    if tool_call_id is None:
        return
    key = str(data.get("job_id") or tool_call_id)

    if event.event_type == "tool_state_change":
        status = str(data.get("state") or data.get("status") or "running")
        if status.lower() in _ACTIVE_JOB_TERMINAL_STATES:
            _drop_active_job(active_jobs, key=key, tool_call_id=str(tool_call_id))
            return
        active_jobs[key] = {
            "source": "event",
            "source_event_sequence": event.sequence,
            "updated_at": updated_at,
            "tool_call_id": str(tool_call_id),
            "tool": data.get("tool"),
            "job_id": data.get("job_id"),
            "status": status,
            "url": data.get("jobUrl") or data.get("job_url"),
        }
        return

    if event.event_type == "tool_output":
        _drop_active_job(active_jobs, key=key, tool_call_id=str(tool_call_id))


def _drop_active_job(
    active_jobs: dict[str, dict[str, Any]],
    *,
    key: str,
    tool_call_id: str,
) -> None:
    active_jobs.pop(key, None)
    for active_key, ref in list(active_jobs.items()):
        if ref.get("tool_call_id") == tool_call_id:
            active_jobs.pop(active_key, None)


def _status_from_last_event(event: AgentEvent) -> str:
    if event.event_type in _PHASE_EVENT_TYPES:
        return _workflow_status_from_phase_event(event)
    if event.event_type == "ready":
        return "idle"
    if event.event_type == "approval_required":
        return "waiting_approval"
    if event.event_type == "error":
        return "error"
    if event.event_type == "interrupted":
        return "interrupted"
    if event.event_type in {"shutdown", "turn_complete"}:
        return "completed"
    if event.event_type in _PROCESSING_EVENTS:
        return "processing"
    return "idle"


def _workflow_status_from_phase_event(event: AgentEvent) -> str:
    phase_status = _phase_event_status(event)
    if phase_status == "blocked":
        return "blocked"
    if phase_status == "failed":
        return "error"
    if phase_status == "complete":
        return "completed"
    if phase_status in {"pending", "active"}:
        return "processing"
    return "idle"


def _durable_refs(value: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    refs: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            refs.append({"source": source, **item})
        else:
            refs.append({"source": source, "value": item})
    return refs


def _merge_refs(
    primary: Any,
    secondary: list[dict[str, Any]],
    *,
    key_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in [*list(primary), *secondary]:
        key = _ref_key(ref, key_names)
        if key in seen:
            continue
        seen.add(key)
        merged.append(dict(ref))
    return merged


def _ref_key(ref: dict[str, Any], key_names: tuple[str, ...]) -> str:
    for key_name in key_names:
        value = ref.get(key_name)
        if value is not None:
            return f"{key_name}:{value}"
    return repr(sorted(ref.items()))


def _operation_refs(operations: list[OperationRecord]) -> list[dict[str, Any]]:
    return [
        {
            "id": record.id,
            "type": record.operation_type,
            "status": record.status,
            "idempotency_key": record.idempotency_key,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
        }
        for record in operations
    ]


def _active_job_refs_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        {
            "source": "event",
            **record.model_dump(mode="json", exclude_none=True),
        }
        for record in project_active_jobs(session_id, events)
    ]


def _artifact_refs_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in project_artifact_refs(session_id, events)
    ]


def _budget_placeholder() -> dict[str, Any]:
    return {
        "source": "placeholder",
        "status": "placeholder",
        "currency": None,
        "limit": None,
        "used": None,
        "items": [],
    }


def _evidence_summary(artifact_refs: list[dict[str, Any]]) -> dict[str, Any]:
    if not artifact_refs:
        return _evidence_summary_placeholder()

    return {
        "source": "event",
        "status": "available",
        "claim_count": 0,
        "artifact_count": len(artifact_refs),
        "metric_count": 0,
        "items": artifact_refs,
    }


def _evidence_summary_placeholder() -> dict[str, Any]:
    return {
        "source": "placeholder",
        "status": "placeholder",
        "claim_count": 0,
        "artifact_count": 0,
        "metric_count": 0,
        "items": [],
    }


def _live_tracking_placeholder(session_id: str) -> dict[str, Any]:
    return {
        "provider": "trackio",
        "enabled": False,
        "status": "placeholder",
        "space_id": None,
        "project": f"session:{session_id}",
        "run_id": None,
        "tool_call_id": None,
        "url": None,
        "source": "compatibility",
    }
