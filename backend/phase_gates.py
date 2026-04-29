from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

try:
    from backend.flow_templates import FlowTemplate, TemplatePhase
    from backend.models import WorkflowState
except ModuleNotFoundError:
    from flow_templates import FlowTemplate, TemplatePhase
    from models import WorkflowState


PhaseRuntimeStatus = Literal[
    "not_started",
    "pending",
    "active",
    "blocked",
    "complete",
    "failed",
]
PhaseGateStatus = Literal["satisfied", "blocked", "verifier_pending"]

_TERMINAL_VERIFIER_PASS_STATUSES = {
    "complete",
    "completed",
    "pass",
    "passed",
    "success",
    "succeeded",
    "verified",
}
_TERMINAL_VERIFIER_FAIL_STATUSES = {"error", "fail", "failed", "rejected"}
_ALLOWED_TRANSITIONS: dict[PhaseRuntimeStatus, set[PhaseRuntimeStatus]] = {
    "not_started": {"pending", "active", "failed"},
    "pending": {"active", "blocked", "failed"},
    "active": {"blocked", "complete", "failed"},
    "blocked": {"active", "complete", "failed"},
    "complete": set(),
    "failed": set(),
}
_EVENT_TYPES: dict[PhaseRuntimeStatus, str] = {
    "not_started": "phase.not_started",
    "pending": "phase.pending",
    "active": "phase.started",
    "blocked": "phase.blocked",
    "complete": "phase.completed",
    "failed": "phase.failed",
}


class PhaseGateError(ValueError):
    """Raised when a phase gate cannot be evaluated."""


class PhaseTransitionError(PhaseGateError):
    """Raised when a requested phase transition is not valid."""


@dataclass(frozen=True)
class PhaseGateEvaluation:
    phase_id: str
    status: PhaseGateStatus
    required_outputs: tuple[str, ...]
    available_outputs: tuple[str, ...]
    waived_outputs: tuple[str, ...]
    missing_outputs: tuple[str, ...]
    required_verifiers: tuple[str, ...]
    passed_verifiers: tuple[str, ...]
    pending_verifiers: tuple[str, ...]
    failed_verifiers: tuple[str, ...]
    waiver_records: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def can_complete(self) -> bool:
        return self.status == "satisfied"

    def to_event_data(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "gate_status": self.status,
            "can_complete": self.can_complete,
            "required_outputs": list(self.required_outputs),
            "available_outputs": list(self.available_outputs),
            "waived_outputs": list(self.waived_outputs),
            "missing_outputs": list(self.missing_outputs),
            "required_verifiers": list(self.required_verifiers),
            "passed_verifiers": list(self.passed_verifiers),
            "pending_verifiers": list(self.pending_verifiers),
            "failed_verifiers": list(self.failed_verifiers),
            "waiver_records": [dict(record) for record in self.waiver_records],
        }


@dataclass(frozen=True)
class PhaseTransitionResult:
    phase_id: str
    from_status: PhaseRuntimeStatus
    requested_status: PhaseRuntimeStatus
    to_status: PhaseRuntimeStatus
    allowed: bool
    gate: PhaseGateEvaluation
    events: tuple[dict[str, Any], ...]


def evaluate_phase_gate(
    template: FlowTemplate,
    phase_id: str,
    *,
    available_outputs: Iterable[str | Mapping[str, Any]] = (),
    output_waivers: Iterable[str | Mapping[str, Any]] = (),
    verifier_results: (
        Mapping[str, str | Mapping[str, Any]] | Iterable[Mapping[str, Any]]
    ) = (),
) -> PhaseGateEvaluation:
    """Evaluate completion gates for one template phase without side effects."""
    phase = _get_phase(template, phase_id)
    output_specs = {output.id: output for output in template.required_outputs}
    verifier_specs = {verifier.id: verifier for verifier in template.verifiers}
    available_output_ids = _stable_ids(
        available_outputs,
        keys=("output_id", "required_output_id", "id"),
    )
    waiver_records = _waiver_records(output_waivers)
    waived_output_ids = tuple(record["output_id"] for record in waiver_records)
    verifier_statuses = _verifier_statuses(verifier_results)

    required_outputs = tuple(
        output_id
        for output_id in phase.required_outputs
        if output_specs.get(output_id) is None or output_specs[output_id].required
    )
    missing_outputs = tuple(
        output_id
        for output_id in required_outputs
        if output_id not in available_output_ids and output_id not in waived_output_ids
    )
    required_verifiers = tuple(
        verifier_id
        for verifier_id in phase.verifiers
        if verifier_specs.get(verifier_id) is None
        or verifier_specs[verifier_id].required
    )
    passed_verifiers = tuple(
        verifier_id
        for verifier_id in required_verifiers
        if verifier_statuses.get(verifier_id) in _TERMINAL_VERIFIER_PASS_STATUSES
    )
    failed_verifiers = tuple(
        verifier_id
        for verifier_id in required_verifiers
        if verifier_statuses.get(verifier_id) in _TERMINAL_VERIFIER_FAIL_STATUSES
    )
    pending_verifiers = tuple(
        verifier_id
        for verifier_id in required_verifiers
        if verifier_id not in passed_verifiers and verifier_id not in failed_verifiers
    )

    if missing_outputs or failed_verifiers:
        status: PhaseGateStatus = "blocked"
    elif pending_verifiers:
        status = "verifier_pending"
    else:
        status = "satisfied"

    return PhaseGateEvaluation(
        phase_id=phase.id,
        status=status,
        required_outputs=required_outputs,
        available_outputs=available_output_ids,
        waived_outputs=waived_output_ids,
        missing_outputs=missing_outputs,
        required_verifiers=required_verifiers,
        passed_verifiers=passed_verifiers,
        pending_verifiers=pending_verifiers,
        failed_verifiers=failed_verifiers,
        waiver_records=waiver_records,
    )


def plan_phase_transition(
    template: FlowTemplate,
    workflow_state: WorkflowState,
    phase_id: str,
    target_status: PhaseRuntimeStatus,
    *,
    current_status: PhaseRuntimeStatus | None = None,
    available_outputs: Iterable[str | Mapping[str, Any]] = (),
    output_waivers: Iterable[str | Mapping[str, Any]] = (),
    verifier_results: (
        Mapping[str, str | Mapping[str, Any]] | Iterable[Mapping[str, Any]]
    ) = (),
) -> PhaseTransitionResult:
    """Build deterministic phase transition events without persisting them."""
    phase = _get_phase(template, phase_id)
    from_status = current_status or _status_from_state(workflow_state, phase)
    _validate_transition(from_status, target_status)

    gate = evaluate_phase_gate(
        template,
        phase_id,
        available_outputs=available_outputs,
        output_waivers=output_waivers,
        verifier_results=verifier_results,
    )
    allowed = target_status != "complete" or gate.can_complete
    to_status = target_status if allowed else "blocked"
    events = _transition_events(
        template=template,
        workflow_state=workflow_state,
        phase=phase,
        from_status=from_status,
        requested_status=target_status,
        to_status=to_status,
        allowed=allowed,
        gate=gate,
    )

    return PhaseTransitionResult(
        phase_id=phase.id,
        from_status=from_status,
        requested_status=target_status,
        to_status=to_status,
        allowed=allowed,
        gate=gate,
        events=events,
    )


def _get_phase(template: FlowTemplate, phase_id: str) -> TemplatePhase:
    for phase in template.phases:
        if phase.id == phase_id:
            return phase
    raise PhaseGateError(f"Unknown phase id: {phase_id}")


def _status_from_state(
    workflow_state: WorkflowState,
    phase: TemplatePhase,
) -> PhaseRuntimeStatus:
    if (
        workflow_state.phase.id == phase.id
        and workflow_state.phase.status != "placeholder"
    ):
        return _normalize_status(workflow_state.phase.status)
    return _normalize_status(phase.status)


def _normalize_status(status: str) -> PhaseRuntimeStatus:
    if status in _ALLOWED_TRANSITIONS:
        return status  # type: ignore[return-value]
    raise PhaseTransitionError(f"Unsupported phase status: {status}")


def _validate_transition(
    from_status: PhaseRuntimeStatus,
    target_status: PhaseRuntimeStatus,
) -> None:
    if target_status not in _ALLOWED_TRANSITIONS:
        raise PhaseTransitionError(
            f"Unsupported target phase status: {target_status}"
        )
    if target_status == from_status:
        return
    if target_status not in _ALLOWED_TRANSITIONS[from_status]:
        raise PhaseTransitionError(
            f"Invalid phase transition: {from_status} -> {target_status}"
        )


def _transition_events(
    *,
    template: FlowTemplate,
    workflow_state: WorkflowState,
    phase: TemplatePhase,
    from_status: PhaseRuntimeStatus,
    requested_status: PhaseRuntimeStatus,
    to_status: PhaseRuntimeStatus,
    allowed: bool,
    gate: PhaseGateEvaluation,
) -> tuple[dict[str, Any], ...]:
    base = {
        "session_id": workflow_state.session_id,
        "project_id": workflow_state.project_id,
        "template_id": template.id,
        "template_version": template.version,
        "phase_id": phase.id,
        "phase_order": phase.order,
        "from_status": from_status,
        "requested_status": requested_status,
        "to_status": to_status,
        "allowed": allowed,
        **gate.to_event_data(),
    }
    events: list[dict[str, Any]] = []
    if allowed and to_status == "complete" and gate.required_verifiers:
        events.append({"event_type": "phase.verified", "data": dict(base)})
    events.append({"event_type": _EVENT_TYPES[to_status], "data": base})
    return tuple(events)


def _stable_ids(
    values: Iterable[str | Mapping[str, Any]],
    *,
    keys: tuple[str, ...],
) -> tuple[str, ...]:
    ids: list[str] = []
    seen: set[str] = set()
    for value in values:
        item_id = value if isinstance(value, str) else _first_string_value(value, keys)
        if item_id is None or item_id in seen:
            continue
        ids.append(item_id)
        seen.add(item_id)
    return tuple(ids)


def _waiver_records(
    waivers: Iterable[str | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for waiver in waivers:
        if isinstance(waiver, str):
            record = {"output_id": waiver}
        else:
            output_id = _first_string_value(
                waiver,
                ("output_id", "required_output_id", "id"),
            )
            if output_id is None:
                continue
            record = {**dict(waiver), "output_id": output_id}
        if record["output_id"] in seen:
            continue
        records.append(record)
        seen.add(record["output_id"])
    return tuple(records)


def _verifier_statuses(
    verifier_results: (
        Mapping[str, str | Mapping[str, Any]] | Iterable[Mapping[str, Any]]
    ),
) -> dict[str, str]:
    if isinstance(verifier_results, Mapping):
        statuses: dict[str, str] = {}
        for verifier_id, result in verifier_results.items():
            status = _normalize_verifier_status(result)
            if status is not None:
                statuses[str(verifier_id)] = status
        return statuses

    statuses: dict[str, str] = {}
    for result in verifier_results:
        verifier_id = _first_string_value(result, ("verifier_id", "id"))
        status = _normalize_verifier_status(result)
        if verifier_id is not None and status is not None:
            statuses[verifier_id] = status
    return statuses


def _normalize_verifier_status(value: str | Mapping[str, Any]) -> str | None:
    if isinstance(value, str):
        return value.strip().lower()
    status = value.get("status") or value.get("verdict")
    if status is None:
        return None
    return str(status).strip().lower()


def _first_string_value(
    mapping: Mapping[str, Any],
    keys: tuple[str, ...],
) -> str | None:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return str(value)
    return None
