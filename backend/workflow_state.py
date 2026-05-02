from __future__ import annotations

from datetime import datetime
from typing import Any

from agent.core.events import AgentEvent
from backend.assumption_ledger import project_assumptions
from backend.budget_ledger import (
    BudgetLimitRecord,
    BudgetUsageRecord,
    project_budget_limits,
    project_budget_usage,
)
from backend.decision_proof_ledger import (
    project_decision_cards,
    project_proof_bundles,
)
from backend.evidence_ledger import (
    EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    EVIDENCE_ITEM_RECORDED_EVENT,
    evidence_claim_link_record_from_event,
    evidence_item_record_from_event,
)
from backend.experiment_ledger import project_log_refs, project_metrics
from backend.flow_verifier_mapping import build_flow_verifier_coverage_report
from backend.human_requests import project_human_requests
from backend.job_artifact_refs import project_active_jobs, project_artifact_refs
from backend.operation_store import OperationRecord
from backend.session_store import SessionRecord
from backend.verifier_check_catalog import (
    VerifierCheckCatalogNotFoundError,
    get_builtin_verifier_check,
)
from backend.verifier_ledger import (
    VERIFIER_COMPLETED_EVENT,
    verifier_verdict_record_from_event,
)

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
    recorded_metric_refs = _metric_refs_from_events(session_id, unique_events)
    recorded_log_refs = _log_refs_from_events(session_id, unique_events)
    recorded_evidence_items = _evidence_items_from_events(session_id, unique_events)
    recorded_claim_links = _evidence_claim_links_from_events(session_id, unique_events)
    recorded_decision_cards = _decision_cards_from_events(session_id, unique_events)
    recorded_assumptions = _assumptions_from_events(session_id, unique_events)
    recorded_proof_bundles = _proof_bundles_from_events(session_id, unique_events)
    recorded_budget_limits = _budget_limits_from_events(session_id, unique_events)
    recorded_budget_usage = _budget_usage_from_events(session_id, unique_events)
    missing_producers = _missing_producers(
        budget_available=bool(recorded_budget_limits or recorded_budget_usage)
    )
    recorded_verifier_verdicts = _verifier_verdicts_from_events(
        session_id,
        unique_events,
    )
    recorded_human_requests = _human_requests_from_events(session_id, unique_events)
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
        human_requests=recorded_human_requests,
        budget=_budget_summary(
            budget_limits=recorded_budget_limits,
            budget_usage=recorded_budget_usage,
        ),
        evidence_summary=_evidence_summary(
            artifact_refs=recorded_artifact_refs,
            metric_refs=recorded_metric_refs,
            log_refs=recorded_log_refs,
            evidence_items=recorded_evidence_items,
            claim_links=recorded_claim_links,
            decision_cards=recorded_decision_cards,
            assumptions=recorded_assumptions,
            proof_bundles=recorded_proof_bundles,
            verifier_verdicts=recorded_verifier_verdicts,
        ),
        live_tracking_refs=[_live_tracking_placeholder(session_id)],
        resume=WorkflowResumeState(event_sequence=last_event_sequence),
        compatibility=WorkflowCompatibility(
            stale=stale,
            missing_producers=missing_producers,
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


def _missing_producers(*, budget_available: bool) -> list[str]:
    producers = list(_WORKFLOW_MISSING_PRODUCERS)
    if budget_available:
        producers = [
            producer for producer in producers if producer != "budget_ledger"
        ]
    return producers


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


def _metric_refs_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in project_metrics(session_id, events)
    ]


def _log_refs_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in project_log_refs(session_id, events)
    ]


def _evidence_items_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    latest: dict[str, tuple[tuple[int, str], dict[str, Any]]] = {}
    for event in _ordered_session_events(
        session_id,
        events,
        EVIDENCE_ITEM_RECORDED_EVENT,
    ):
        record = evidence_item_record_from_event(event)
        latest[record.evidence_id] = (
            (event.sequence, str(event.id)),
            record.model_dump(mode="json", exclude_none=True),
        )

    return [
        record for _, record in sorted(latest.values(), key=lambda value: value[0])
    ]


def _evidence_claim_links_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    latest: dict[str, tuple[tuple[int, str], dict[str, Any]]] = {}
    for event in _ordered_session_events(
        session_id,
        events,
        EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    ):
        record = evidence_claim_link_record_from_event(event)
        latest[record.link_id] = (
            (event.sequence, str(event.id)),
            record.model_dump(mode="json", exclude_none=True),
        )

    return [
        record for _, record in sorted(latest.values(), key=lambda value: value[0])
    ]


def _decision_cards_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in project_decision_cards(session_id, events)
    ]


def _assumptions_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in project_assumptions(session_id, events)
    ]


def _proof_bundles_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        record.model_dump(mode="json", exclude_none=True)
        for record in project_proof_bundles(session_id, events)
    ]


def _verifier_verdicts_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    latest: dict[str, tuple[tuple[int, str], dict[str, Any]]] = {}
    for event in _ordered_session_events(
        session_id,
        events,
        VERIFIER_COMPLETED_EVENT,
    ):
        record = verifier_verdict_record_from_event(event)
        latest[record.verdict_id] = (
            (event.sequence, str(event.id)),
            record.model_dump(mode="json", exclude_none=True),
        )

    return [
        record for _, record in sorted(latest.values(), key=lambda value: value[0])
    ]


def _human_requests_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[dict[str, Any]]:
    return [
        {"source": "event", **record.model_dump(mode="json", exclude_none=True)}
        for record in project_human_requests(session_id, events)
    ]


def _budget_limits_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[BudgetLimitRecord]:
    return project_budget_limits(session_id, events)


def _budget_usage_from_events(
    session_id: str,
    events: list[AgentEvent],
) -> list[BudgetUsageRecord]:
    return project_budget_usage(session_id, events)


def _ordered_session_events(
    session_id: str,
    events: list[AgentEvent],
    event_type: str,
) -> list[AgentEvent]:
    return sorted(
        [
            event
            for event in events
            if event.session_id == session_id and event.event_type == event_type
        ],
        key=lambda event: (event.sequence, str(event.id)),
    )


def _budget_placeholder() -> dict[str, Any]:
    return {
        "source": "placeholder",
        "status": "placeholder",
        "currency": None,
        "limit": None,
        "used": None,
        "items": [],
    }


def _budget_summary(
    *,
    budget_limits: list[BudgetLimitRecord],
    budget_usage: list[BudgetUsageRecord],
) -> dict[str, Any]:
    if not budget_limits and not budget_usage:
        return _budget_placeholder()

    items = sorted(
        [
            *[
                {
                    "type": "limit",
                    **record.model_dump(mode="json", exclude_none=True),
                }
                for record in budget_limits
            ],
            *[
                {
                    "type": "usage",
                    **record.model_dump(mode="json", exclude_none=True),
                }
                for record in budget_usage
            ],
        ],
        key=_budget_item_sort_key,
    )
    totals = _budget_totals(budget_limits=budget_limits, budget_usage=budget_usage)
    exhausted = any(total["status"] == "exhausted" for total in totals)
    single_total = totals[0] if len(totals) == 1 else None

    return {
        "source": "event",
        "status": "exhausted" if exhausted else "active",
        "currency": single_total["unit"] if single_total is not None else None,
        "limit": single_total["limit"] if single_total is not None else None,
        "used": single_total["used"] if single_total is not None else None,
        "limit_count": len(budget_limits),
        "usage_count": len(budget_usage),
        "totals": totals,
        "items": items,
    }


def _budget_totals(
    *,
    budget_limits: list[BudgetLimitRecord],
    budget_usage: list[BudgetUsageRecord],
) -> list[dict[str, Any]]:
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for record in budget_limits:
        row = _budget_total_row(rows, resource=record.resource, unit=record.unit)
        row["limit"] = (row["limit"] or 0) + record.limit
        row["limit_count"] += 1

    for record in budget_usage:
        row = _budget_total_row(rows, resource=record.resource, unit=record.unit)
        row["used"] += record.amount
        row["usage_count"] += 1

    totals = []
    for row in rows.values():
        limit = row["limit"]
        used = row["used"]
        exhausted = limit is not None and used >= limit
        totals.append(
            {
                **row,
                "remaining": None if limit is None else limit - used,
                "status": "exhausted" if exhausted else "active",
            }
        )
    return sorted(totals, key=lambda row: (row["resource"], row["unit"]))


def _budget_total_row(
    rows: dict[tuple[str, str], dict[str, Any]],
    *,
    resource: str,
    unit: str,
) -> dict[str, Any]:
    key = (resource, unit)
    if key not in rows:
        rows[key] = {
            "resource": resource,
            "unit": unit,
            "limit": None,
            "used": 0,
            "limit_count": 0,
            "usage_count": 0,
        }
    return rows[key]


def _budget_item_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    sequence = item.get("source_event_sequence")
    if isinstance(sequence, int):
        sort_sequence = sequence
    else:
        sort_sequence = 0
    return (sort_sequence, repr(sorted(item.items())))


def _evidence_summary(
    *,
    artifact_refs: list[dict[str, Any]],
    metric_refs: list[dict[str, Any]],
    log_refs: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    claim_links: list[dict[str, Any]],
    decision_cards: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    proof_bundles: list[dict[str, Any]],
    verifier_verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    if (
        not artifact_refs
        and not metric_refs
        and not log_refs
        and not evidence_items
        and not decision_cards
        and not assumptions
        and not proof_bundles
    ):
        if not claim_links and not verifier_verdicts:
            return _evidence_summary_placeholder()

    items = sorted(
        [
            *artifact_refs,
            *metric_refs,
            *log_refs,
            *evidence_items,
            *claim_links,
            *decision_cards,
            *assumptions,
            *proof_bundles,
            *verifier_verdicts,
        ],
        key=_evidence_item_sort_key,
    )
    if not items:
        return _evidence_summary_placeholder()

    summary = {
        "source": "event",
        "status": "available",
        "claim_count": len(claim_links),
        "claim_link_count": len(claim_links),
        "evidence_count": len(evidence_items),
        "artifact_count": len(artifact_refs),
        "metric_count": len(metric_refs),
        "log_count": len(log_refs),
        "decision_card_count": len(decision_cards),
        "assumption_count": len(assumptions),
        "proof_bundle_count": len(proof_bundles),
        "items": items,
    }
    if verifier_verdicts:
        summary["verifier_count"] = len(verifier_verdicts)
        summary["verifier_counts"] = _verifier_verdict_counts(verifier_verdicts)
        summary["verifier_status"] = _verifier_summary_status(verifier_verdicts)
        summary["verifier_catalog"] = _verifier_catalog_metadata(verifier_verdicts)
    return summary


def _verifier_verdict_counts(
    verifier_verdicts: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {"passed": 0, "failed": 0, "inconclusive": 0}
    for verdict in verifier_verdicts:
        verdict_status = str(verdict.get("verdict") or "")
        if verdict_status in counts:
            counts[verdict_status] += 1
    return counts


def _verifier_summary_status(verifier_verdicts: list[dict[str, Any]]) -> str:
    statuses = {str(verdict.get("verdict") or "") for verdict in verifier_verdicts}
    if "failed" in statuses:
        return "failed"
    if "inconclusive" in statuses:
        return "inconclusive"
    if "passed" in statuses:
        return "passed"
    return "unknown"


def _verifier_catalog_metadata(
    verifier_verdicts: list[dict[str, Any]],
) -> dict[str, Any]:
    observed_ids = _verifier_observed_check_ids(verifier_verdicts)
    direct_catalog_check_ids = tuple(
        verifier_id
        for verifier_id in observed_ids
        if _is_builtin_catalog_check_id(verifier_id)
    )
    direct_catalog_check_id_set = set(direct_catalog_check_ids)
    flow_local_verifier_ids = tuple(
        verifier_id
        for verifier_id in observed_ids
        if verifier_id not in direct_catalog_check_id_set
    )
    coverage = build_flow_verifier_coverage_report(flow_local_verifier_ids)
    mapping_rows = [
        {
            "flow_verifier_id": mapping.flow_verifier_id,
            "catalog_check_id": mapping.catalog_check_id,
        }
        for mapping in coverage.mapped
    ]
    mapped_catalog_check_ids = tuple(
        sorted({row["catalog_check_id"] for row in mapping_rows})
    )
    catalog_check_ids = tuple(
        sorted({*direct_catalog_check_ids, *mapped_catalog_check_ids})
    )
    intentional_unmapped_ids = coverage.intentional_unmapped_verifier_ids
    unknown_ids = coverage.unknown_unmapped_verifier_ids

    return {
        "source": "flow_verifier_mapping",
        "catalog_check_ids": list(catalog_check_ids),
        "direct_catalog_check_ids": list(direct_catalog_check_ids),
        "mapped_catalog_check_ids": list(mapped_catalog_check_ids),
        "flow_local_verifier_ids": list(flow_local_verifier_ids),
        "intentional_unmapped_ids": list(intentional_unmapped_ids),
        "unknown_ids": list(unknown_ids),
        "mapping_rows": mapping_rows,
        "counts": {
            "verdict_count": len(verifier_verdicts),
            "observed_id_count": len(observed_ids),
            "catalog_check_id_count": len(catalog_check_ids),
            "direct_catalog_check_id_count": len(direct_catalog_check_ids),
            "mapped_catalog_check_id_count": len(mapped_catalog_check_ids),
            "flow_local_verifier_id_count": len(flow_local_verifier_ids),
            "intentional_unmapped_id_count": len(intentional_unmapped_ids),
            "unknown_id_count": len(unknown_ids),
        },
    }


def _verifier_observed_check_ids(
    verifier_verdicts: list[dict[str, Any]],
) -> tuple[str, ...]:
    observed: set[str] = set()
    for verdict in verifier_verdicts:
        verifier_id = verdict.get("verifier_id")
        if isinstance(verifier_id, str) and verifier_id:
            observed.add(verifier_id)
        for check in verdict.get("checks") or []:
            if not isinstance(check, dict):
                continue
            check_id = check.get("check_id")
            if isinstance(check_id, str) and check_id:
                observed.add(check_id)
    return tuple(sorted(observed))


def _is_builtin_catalog_check_id(check_id: str) -> bool:
    try:
        get_builtin_verifier_check(check_id)
    except VerifierCheckCatalogNotFoundError:
        return False
    return True


def _evidence_item_sort_key(item: dict[str, Any]) -> tuple[int, str]:
    sequence = item.get("source_event_sequence")
    if isinstance(sequence, int):
        sort_sequence = sequence
    else:
        sort_sequence = 0
    return (sort_sequence, repr(sorted(item.items())))


def _evidence_summary_placeholder() -> dict[str, Any]:
    return {
        "source": "placeholder",
        "status": "placeholder",
        "claim_count": 0,
        "claim_link_count": 0,
        "evidence_count": 0,
        "artifact_count": 0,
        "metric_count": 0,
        "log_count": 0,
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
