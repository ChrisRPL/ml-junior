from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo
from pydantic import field_validator

from agent.core.redaction import redact_value


ASSUMPTION_RECORDED_EVENT = "assumption.recorded"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class AssumptionLedgerError(ValueError):
    pass


class AgentEventLike(Protocol):
    id: str
    session_id: str
    sequence: int
    event_type: str
    data: dict[str, Any] | None


class AssumptionLedgerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
    )


class AssumptionRecord(AssumptionLedgerModel):
    session_id: NonEmptyStr
    assumption_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    title: NonEmptyStr
    statement: NonEmptyStr
    status: Literal["open", "validated", "invalidated", "superseded"]
    confidence: Literal["low", "medium", "high", "unknown"] = "unknown"
    rationale: NonEmptyStr | None = None
    validation_notes: NonEmptyStr | None = None
    phase_id: NonEmptyStr | None = None
    run_id: NonEmptyStr | None = None
    decision_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    claim_ids: list[NonEmptyStr] = Field(default_factory=list)
    artifact_ids: list[NonEmptyStr] = Field(default_factory=list)
    proof_bundle_ids: list[NonEmptyStr] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None
    updated_at: NonEmptyStr | None = None

    @field_validator(
        "decision_ids",
        "evidence_ids",
        "claim_ids",
        "artifact_ids",
        "proof_bundle_ids",
    )
    @classmethod
    def validate_unique_text_refs(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        _reject_duplicate_values(value, info.field_name or "refs")
        return value


def assumption_recorded_payload(record: AssumptionRecord) -> dict[str, Any]:
    return _record_payload(record)


def redacted_assumption_payload(record: AssumptionRecord) -> tuple[dict[str, Any], str]:
    result = redact_value(_record_payload(record))
    if not isinstance(result.value, dict):
        raise AssumptionLedgerError("redacted assumption payload must be a mapping")

    redaction_status = _stronger_redaction_status(
        record.redaction_status,
        result.status,
    )
    result.value["redaction_status"] = redaction_status
    return result.value, redaction_status


def assumption_record_from_event(event: AgentEventLike) -> AssumptionRecord:
    if event.event_type != ASSUMPTION_RECORDED_EVENT:
        raise AssumptionLedgerError(f"Expected {ASSUMPTION_RECORDED_EVENT}")

    record = AssumptionRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise AssumptionLedgerError(
            "assumption event session_id does not match record session_id"
        )
    return record


def project_assumptions(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> list[AssumptionRecord]:
    records = [
        assumption_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            ASSUMPTION_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_record_ids(records, "assumption_id", "assumption")
    return records


def _ordered_session_events(
    session_id: str,
    events: Sequence[AgentEventLike],
    event_type: str,
) -> list[AgentEventLike]:
    return sorted(
        [
            event
            for event in events
            if event.session_id == session_id and event.event_type == event_type
        ],
        key=lambda event: (event.sequence, str(event.id)),
    )


def _record_payload(record: AssumptionRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _reject_duplicate_record_ids(
    records: Sequence[Any],
    id_field: str,
    label: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = getattr(record, id_field)
        if record_id in seen:
            raise AssumptionLedgerError(f"duplicate {label} id: {record_id}")
        seen.add(record_id)


def _reject_duplicate_values(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {label}: {value}")
        seen.add(value)


def _stronger_redaction_status(left: str, right: str) -> str:
    order = {"none": 0, "partial": 1, "redacted": 2}
    left_value = str(left)
    right_value = str(right)
    if order.get(left_value, 0) >= order.get(right_value, 0):
        return left_value
    return right_value
