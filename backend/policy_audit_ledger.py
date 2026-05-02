from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo
from pydantic import field_validator

from agent.core.policy_audit_contracts import (
    POLICY_AUDIT_INTENT_EVENT,
    POLICY_AUDIT_RESULT_EVENT,
    PolicyAuditContract,
)
from agent.core.redaction import redact_value

if TYPE_CHECKING:
    from agent.core.events import AgentEvent


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
_SUPPORTED_POLICY_AUDIT_COMMANDS = {
    "/share-traces",
    "/ledger verify",
    "/proof bundle",
}
_POLICY_AUDIT_EVENT_TYPES = {
    POLICY_AUDIT_INTENT_EVENT,
    POLICY_AUDIT_RESULT_EVENT,
}
_INTENT_REQUIRED_FIELDS_BY_ACTION = {
    "trace_visibility_public": (
        "approval_id",
        "destination_repo",
        "owner_namespace",
        "visibility",
        "dataset_card_warning_ack",
        "revocation_guidance",
    ),
    "trace_visibility_private": (
        "approval_id",
        "destination_repo",
        "owner_namespace",
        "visibility",
    ),
    "ledger_integrity_verify": (
        "target_ref",
        "verifier_id",
    ),
    "proof_bundle_create": (
        "approval_id",
        "target_ref",
        "bundle_id",
        "manifest_checksum",
    ),
}
_RESULT_REQUIRED_FIELDS_BY_ACTION = {
    "trace_visibility_public": (
        "result_ref",
        "destination_repo",
        "owner_namespace",
    ),
    "trace_visibility_private": (
        "result_ref",
        "destination_repo",
        "owner_namespace",
    ),
    "ledger_integrity_verify": (
        "verdict",
        "checked_at",
    ),
    "proof_bundle_create": (
        "result_ref",
        "manifest_checksum",
    ),
}
_INTENT_PROTECTED_FIELDS = {
    "session_id",
    "audit_id",
    "source_event_sequence",
    "actor",
    "command",
    "action",
    "contract_version",
    "target_ref",
    "approval_id",
    "privacy_class",
    "visibility",
    "redaction_status",
    "rollback_guidance",
    "created_at",
    "metadata",
}
_RESULT_PROTECTED_FIELDS = {
    "session_id",
    "audit_id",
    "source_event_sequence",
    "intent_audit_id",
    "status",
    "privacy_class",
    "visibility",
    "redaction_status",
    "result_ref",
    "checked_at",
    "created_at",
    "metadata",
}


@dataclass(frozen=True)
class PolicyAuditIntentMetadata:
    session_id: str
    audit_id: str
    actor: str
    source_event_sequence: int
    created_at: str
    correlation_id: str
    approval_id: str | None = None
    target_ref: str | None = None
    destination_repo: str | None = None
    owner_namespace: str | None = None
    include_legacy_sessions: bool = False
    dataset_card_warning_ack: bool | None = None
    revocation_guidance: str | None = None
    verifier_id: str | None = None
    input_checksum: str | None = None
    bundle_id: str | None = None
    run_id: str | None = None
    decision_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    manifest_checksum: str | None = None
    signature_ref: str | None = None
    signing_key_ref: str | None = None
    redaction_status: Literal["none", "partial", "redacted"] | None = None
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class PolicyAuditResultMetadata:
    session_id: str
    audit_id: str
    source_event_sequence: int
    status: Literal["succeeded", "failed", "canceled", "superseded"]
    created_at: str
    correlation_id: str
    result_ref: str | None = None
    verdict: Literal["passed", "failed", "inconclusive"] | None = None
    manifest_checksum: str | None = None
    destination_repo: str | None = None
    owner_namespace: str | None = None
    checked_at: str | None = None
    error_summary: str | None = None
    redaction_status: Literal["none", "partial", "redacted"] | None = None
    metadata: Mapping[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class PolicyAuditEventDraft:
    event_type: Literal[
        "policy.audit_intent_recorded",
        "policy.audit_result_recorded",
    ]
    payload: dict[str, Any]
    redaction_status: Literal["none", "partial", "redacted"]


@dataclass(frozen=True)
class PolicyAuditEventEnvelopeMetadata:
    sequence: int
    event_id: str | None = None
    timestamp: datetime | str | None = None
    schema_version: int | None = None


class PolicyAuditLedgerError(ValueError):
    pass


class AgentEventLike(Protocol):
    id: str
    session_id: str
    sequence: int
    event_type: str
    data: dict[str, Any] | None


class PolicyAuditLedgerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
    )


class PolicyAuditIntentRecord(PolicyAuditLedgerModel):
    session_id: NonEmptyStr
    audit_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    actor: NonEmptyStr
    command: NonEmptyStr
    action: NonEmptyStr
    contract_version: NonEmptyStr = "1"
    target_ref: NonEmptyStr | None = None
    approval_id: NonEmptyStr | None = None
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    visibility: Literal["public", "private", "unknown"] | None = None
    redaction_status: Literal["none", "partial", "redacted"]
    rollback_guidance: NonEmptyStr
    destination_repo: NonEmptyStr | None = None
    owner_namespace: NonEmptyStr | None = None
    include_legacy_sessions: bool = False
    dataset_card_warning_ack: bool | None = None
    revocation_guidance: NonEmptyStr | None = None
    verifier_id: NonEmptyStr | None = None
    input_checksum: NonEmptyStr | None = None
    bundle_id: NonEmptyStr | None = None
    run_id: NonEmptyStr | None = None
    decision_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    artifact_ids: list[NonEmptyStr] = Field(default_factory=list)
    manifest_checksum: NonEmptyStr | None = None
    signature_ref: NonEmptyStr | None = None
    signing_key_ref: NonEmptyStr | None = None
    created_at: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("decision_ids", "evidence_ids", "artifact_ids")
    @classmethod
    def validate_unique_text_refs(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        _reject_duplicate_values(value, info.field_name or "refs")
        return value


class PolicyAuditResultRecord(PolicyAuditLedgerModel):
    session_id: NonEmptyStr
    audit_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    intent_audit_id: NonEmptyStr
    status: Literal["succeeded", "failed", "canceled", "superseded"]
    privacy_class: Literal["public", "private", "sensitive", "unknown"] | None = None
    visibility: Literal["public", "private", "unknown"] | None = None
    redaction_status: Literal["none", "partial", "redacted"]
    result_ref: NonEmptyStr | None = None
    verdict: Literal["passed", "failed", "inconclusive"] | None = None
    verifier_id: NonEmptyStr | None = None
    manifest_checksum: NonEmptyStr | None = None
    destination_repo: NonEmptyStr | None = None
    owner_namespace: NonEmptyStr | None = None
    checked_at: NonEmptyStr | None = None
    error_summary: NonEmptyStr | None = None
    created_at: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicyAuditLedgerProjection(PolicyAuditLedgerModel):
    session_id: NonEmptyStr
    intents: list[PolicyAuditIntentRecord]
    results: list[PolicyAuditResultRecord]
    pending_intents: list[PolicyAuditIntentRecord]


def build_policy_audit_intent_record(
    contract: PolicyAuditContract,
    *,
    session_id: str,
    audit_id: str,
    actor: str,
    approval_id: str | None = None,
    source_event_sequence: int | None = None,
    target_ref: str | None = None,
    created_at: str | None = None,
    redaction_status: str | None = None,
    fields: Mapping[str, Any] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
) -> PolicyAuditIntentRecord:
    _validate_buildable_contract(contract, POLICY_AUDIT_INTENT_EVENT)
    _reject_protected_fields(fields, _INTENT_PROTECTED_FIELDS)
    _require_correlation_id(correlation_id)

    defaults = dict(contract.audit_defaults)
    values: dict[str, Any] = {
        "session_id": session_id,
        "audit_id": audit_id,
        "source_event_sequence": source_event_sequence,
        "actor": actor,
        "command": contract.command,
        "action": contract.action,
        "contract_version": contract.contract_version,
        "target_ref": target_ref or defaults.get("target_ref"),
        "approval_id": approval_id,
        "privacy_class": defaults.get("privacy_class", contract.privacy_default),
        "visibility": defaults.get("visibility", contract.visibility_default),
        "redaction_status": redaction_status
        or defaults.get("redaction_status", "redacted"),
        "rollback_guidance": contract.rollback,
        "created_at": created_at,
        "metadata": _builder_metadata(
            contract,
            request_metadata=request_metadata,
            correlation_id=correlation_id,
        ),
    }
    if fields:
        values.update(dict(fields))

    record = PolicyAuditIntentRecord.model_validate(values)
    _require_stage_fields(contract, record, _INTENT_REQUIRED_FIELDS_BY_ACTION)
    _validate_intent_stage_rules(contract, record)
    return record


def build_policy_audit_result_record(
    contract: PolicyAuditContract,
    *,
    session_id: str,
    audit_id: str,
    intent_audit_id: str,
    status: str,
    source_event_sequence: int | None = None,
    result_ref: str | None = None,
    checked_at: str | None = None,
    created_at: str | None = None,
    redaction_status: str | None = None,
    fields: Mapping[str, Any] | None = None,
    request_metadata: Mapping[str, Any] | None = None,
    correlation_id: str | None = None,
) -> PolicyAuditResultRecord:
    _validate_buildable_contract(contract, POLICY_AUDIT_RESULT_EVENT)
    _reject_protected_fields(fields, _RESULT_PROTECTED_FIELDS)
    _require_correlation_id(correlation_id)

    defaults = dict(contract.audit_defaults)
    values: dict[str, Any] = {
        "session_id": session_id,
        "audit_id": audit_id,
        "source_event_sequence": source_event_sequence,
        "intent_audit_id": intent_audit_id,
        "status": status,
        "privacy_class": defaults.get("privacy_class", contract.privacy_default),
        "visibility": defaults.get("visibility", contract.visibility_default),
        "redaction_status": redaction_status
        or defaults.get("redaction_status", "redacted"),
        "result_ref": result_ref,
        "checked_at": checked_at,
        "created_at": created_at,
        "metadata": _builder_metadata(
            contract,
            request_metadata=request_metadata,
            correlation_id=correlation_id,
        ),
    }
    if fields:
        values.update(dict(fields))

    record = PolicyAuditResultRecord.model_validate(values)
    _require_result_stage_fields(contract, record)
    _validate_result_stage_rules(contract, record)
    return record


def build_policy_audit_intent_event_draft(
    contract: PolicyAuditContract,
    metadata: PolicyAuditIntentMetadata,
) -> PolicyAuditEventDraft:
    fields = _intent_metadata_fields(metadata)
    record = build_policy_audit_intent_record(
        contract,
        session_id=metadata.session_id,
        audit_id=metadata.audit_id,
        actor=metadata.actor,
        approval_id=metadata.approval_id,
        source_event_sequence=metadata.source_event_sequence,
        target_ref=metadata.target_ref,
        created_at=metadata.created_at,
        redaction_status=metadata.redaction_status,
        fields=fields,
        request_metadata=metadata.metadata,
        correlation_id=metadata.correlation_id,
    )
    payload, redaction_status = redacted_policy_audit_intent_payload(record)
    return PolicyAuditEventDraft(
        event_type=POLICY_AUDIT_INTENT_EVENT,
        payload=payload,
        redaction_status=redaction_status,  # type: ignore[arg-type]
    )


def build_policy_audit_result_event_draft(
    contract: PolicyAuditContract,
    intent_payload: Mapping[str, Any],
    metadata: PolicyAuditResultMetadata,
) -> PolicyAuditEventDraft:
    intent = PolicyAuditIntentRecord.model_validate(intent_payload)
    _validate_result_intent_correlation(contract, intent, metadata)
    fields = _result_metadata_fields(metadata)
    record = build_policy_audit_result_record(
        contract,
        session_id=metadata.session_id,
        audit_id=metadata.audit_id,
        intent_audit_id=intent.audit_id,
        status=metadata.status,
        source_event_sequence=metadata.source_event_sequence,
        result_ref=metadata.result_ref,
        checked_at=metadata.checked_at,
        created_at=metadata.created_at,
        redaction_status=metadata.redaction_status,
        fields=fields,
        request_metadata=metadata.metadata,
        correlation_id=metadata.correlation_id,
    )
    payload, redaction_status = redacted_policy_audit_result_payload(record)
    return PolicyAuditEventDraft(
        event_type=POLICY_AUDIT_RESULT_EVENT,
        payload=payload,
        redaction_status=redaction_status,  # type: ignore[arg-type]
    )


def build_policy_audit_agent_event(
    draft: PolicyAuditEventDraft,
    metadata: PolicyAuditEventEnvelopeMetadata,
) -> AgentEvent:
    if draft.event_type not in _POLICY_AUDIT_EVENT_TYPES:
        raise PolicyAuditLedgerError(
            f"unsupported policy audit event type: {draft.event_type}"
        )
    AgentEvent = _agent_event_model()
    values: dict[str, Any] = {
        "session_id": _draft_payload_session_id(draft),
        "sequence": metadata.sequence,
        "event_type": draft.event_type,
        "redaction_status": draft.redaction_status,
        "data": draft.payload,
    }
    if metadata.event_id is not None:
        values["id"] = metadata.event_id
    if metadata.timestamp is not None:
        values["timestamp"] = metadata.timestamp
    if metadata.schema_version is not None:
        values["schema_version"] = metadata.schema_version
    return AgentEvent(**values).redacted_copy()


def build_policy_audit_intent_agent_event(
    draft: PolicyAuditEventDraft,
    envelope: PolicyAuditEventEnvelopeMetadata,
) -> AgentEvent:
    if draft.event_type != POLICY_AUDIT_INTENT_EVENT:
        raise PolicyAuditLedgerError(f"Expected {POLICY_AUDIT_INTENT_EVENT}")
    return build_policy_audit_agent_event(draft, envelope)


def build_policy_audit_result_agent_event(
    draft: PolicyAuditEventDraft,
    envelope: PolicyAuditEventEnvelopeMetadata,
) -> AgentEvent:
    if draft.event_type != POLICY_AUDIT_RESULT_EVENT:
        raise PolicyAuditLedgerError(f"Expected {POLICY_AUDIT_RESULT_EVENT}")
    return build_policy_audit_agent_event(draft, envelope)


def policy_audit_intent_payload(record: PolicyAuditIntentRecord) -> dict[str, Any]:
    return _record_payload(record)


def policy_audit_result_payload(record: PolicyAuditResultRecord) -> dict[str, Any]:
    return _record_payload(record)


def redacted_policy_audit_intent_payload(
    record: PolicyAuditIntentRecord,
) -> tuple[dict[str, Any], str]:
    return _redacted_record_payload(record)


def redacted_policy_audit_result_payload(
    record: PolicyAuditResultRecord,
) -> tuple[dict[str, Any], str]:
    return _redacted_record_payload(record)


def policy_audit_intent_from_event(
    event: AgentEventLike,
) -> PolicyAuditIntentRecord:
    if event.event_type != POLICY_AUDIT_INTENT_EVENT:
        raise PolicyAuditLedgerError(f"Expected {POLICY_AUDIT_INTENT_EVENT}")

    record = PolicyAuditIntentRecord.model_validate(event.data or {})
    _validate_event_session(record.session_id, event.session_id, "policy audit intent")
    return record


def policy_audit_result_from_event(
    event: AgentEventLike,
) -> PolicyAuditResultRecord:
    if event.event_type != POLICY_AUDIT_RESULT_EVENT:
        raise PolicyAuditLedgerError(f"Expected {POLICY_AUDIT_RESULT_EVENT}")

    record = PolicyAuditResultRecord.model_validate(event.data or {})
    _validate_event_session(record.session_id, event.session_id, "policy audit result")
    return record


def project_policy_audit_intents(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> list[PolicyAuditIntentRecord]:
    records = [
        policy_audit_intent_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            POLICY_AUDIT_INTENT_EVENT,
        )
    ]
    _reject_duplicate_record_ids(records, "audit_id", "policy audit intent")
    return records


def project_policy_audit_results(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> list[PolicyAuditResultRecord]:
    records = [
        policy_audit_result_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            POLICY_AUDIT_RESULT_EVENT,
        )
    ]
    _reject_duplicate_record_ids(records, "audit_id", "policy audit result")
    _reject_duplicate_record_ids(records, "intent_audit_id", "policy audit result")
    return records


def project_policy_audit_ledger(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> PolicyAuditLedgerProjection:
    intents = project_policy_audit_intents(session_id, events)
    results = project_policy_audit_results(session_id, events)
    _validate_policy_audit_refs(intents, results)

    completed_intent_ids = {record.intent_audit_id for record in results}
    pending_intents = [
        record for record in intents if record.audit_id not in completed_intent_ids
    ]

    return PolicyAuditLedgerProjection(
        session_id=session_id,
        intents=intents,
        results=results,
        pending_intents=pending_intents,
    )


def _validate_policy_audit_refs(
    intents: Sequence[PolicyAuditIntentRecord],
    results: Sequence[PolicyAuditResultRecord],
) -> None:
    intent_ids = {record.audit_id for record in intents}
    for result in results:
        if result.intent_audit_id not in intent_ids:
            raise PolicyAuditLedgerError(
                f"policy audit result {result.audit_id} references unknown "
                f"intent_audit_id: {result.intent_audit_id}"
            )


def _agent_event_model() -> type[AgentEvent]:
    from agent.core.events import AgentEvent

    return AgentEvent


def _draft_payload_session_id(draft: PolicyAuditEventDraft) -> str:
    session_id = draft.payload.get("session_id")
    if not isinstance(session_id, str) or _is_missing_required_value(session_id):
        raise PolicyAuditLedgerError(
            "policy audit event draft payload missing session_id"
        )
    return session_id


def _validate_buildable_contract(
    contract: PolicyAuditContract,
    event_type: str,
) -> None:
    if contract.command not in _SUPPORTED_POLICY_AUDIT_COMMANDS:
        raise PolicyAuditLedgerError(
            f"unsupported policy audit command: {contract.command}"
        )
    if not contract.audit_required:
        raise PolicyAuditLedgerError(
            f"{contract.command} {contract.action} does not require audit"
        )
    if event_type == POLICY_AUDIT_INTENT_EVENT:
        expected_event_type = contract.audit_intent_event_type
    else:
        expected_event_type = contract.audit_result_event_type
    if expected_event_type != event_type:
        raise PolicyAuditLedgerError(
            f"{contract.command} {contract.action} cannot build {event_type}"
        )


def _reject_protected_fields(
    fields: Mapping[str, Any] | None,
    protected: set[str],
) -> None:
    if not fields:
        return
    blocked = sorted(set(fields).intersection(protected))
    if blocked:
        raise PolicyAuditLedgerError(
            "policy audit builder fields cannot override: " + ", ".join(blocked)
        )


def _require_stage_fields(
    contract: PolicyAuditContract,
    record: PolicyAuditIntentRecord | PolicyAuditResultRecord,
    required_fields_by_action: Mapping[str, Sequence[str]],
) -> None:
    payload = record.model_dump(mode="json")
    required_fields = required_fields_by_action.get(contract.action)
    if required_fields is None:
        raise PolicyAuditLedgerError(
            f"unsupported policy audit action: {contract.action}"
        )
    missing = [
        field_name
        for field_name in required_fields
        if _is_missing_required_value(payload.get(field_name))
    ]
    if missing:
        raise PolicyAuditLedgerError(
            f"{contract.command} {contract.action} missing audit field(s): "
            + ", ".join(missing)
        )


def _require_result_stage_fields(
    contract: PolicyAuditContract,
    record: PolicyAuditResultRecord,
) -> None:
    if contract.action == "proof_bundle_create" and record.status != "succeeded":
        required_fields = ("error_summary",) if record.status == "failed" else ()
        _require_fields(contract, record, required_fields)
        return
    _require_stage_fields(contract, record, _RESULT_REQUIRED_FIELDS_BY_ACTION)


def _require_fields(
    contract: PolicyAuditContract,
    record: PolicyAuditIntentRecord | PolicyAuditResultRecord,
    required_fields: Sequence[str],
) -> None:
    payload = record.model_dump(mode="json")
    missing = [
        field_name
        for field_name in required_fields
        if _is_missing_required_value(payload.get(field_name))
    ]
    if missing:
        raise PolicyAuditLedgerError(
            f"{contract.command} {contract.action} missing audit field(s): "
            + ", ".join(missing)
        )


def _validate_intent_stage_rules(
    contract: PolicyAuditContract,
    record: PolicyAuditIntentRecord,
) -> None:
    if contract.action == "trace_visibility_public":
        if record.dataset_card_warning_ack is not True:
            raise PolicyAuditLedgerError(
                "/share-traces public requires dataset_card_warning_ack"
            )
        if record.redaction_status != "redacted":
            raise PolicyAuditLedgerError(
                "/share-traces public requires redaction_status=redacted"
            )
    if contract.action == "trace_visibility_private" and record.visibility != "private":
        raise PolicyAuditLedgerError("/share-traces private requires visibility=private")
    if contract.action == "trace_visibility_public" and record.visibility != "public":
        raise PolicyAuditLedgerError("/share-traces public requires visibility=public")


def _validate_result_stage_rules(
    contract: PolicyAuditContract,
    record: PolicyAuditResultRecord,
) -> None:
    if contract.action == "trace_visibility_public":
        if record.visibility != "public":
            raise PolicyAuditLedgerError("/share-traces public requires visibility=public")
    if contract.action == "trace_visibility_private":
        if record.visibility != "private":
            raise PolicyAuditLedgerError(
                "/share-traces private requires visibility=private"
            )
    if contract.action == "proof_bundle_create":
        if record.status == "failed" and _is_missing_required_value(record.error_summary):
            raise PolicyAuditLedgerError(
                "/proof bundle failed result requires error_summary"
            )
        if record.status == "succeeded":
            _require_stage_fields(
                contract,
                record,
                _RESULT_REQUIRED_FIELDS_BY_ACTION,
            )


def _validate_result_intent_correlation(
    contract: PolicyAuditContract,
    intent: PolicyAuditIntentRecord,
    metadata: PolicyAuditResultMetadata,
) -> None:
    if intent.session_id != _clean_text(metadata.session_id):
        raise PolicyAuditLedgerError(
            "policy audit result session_id does not match intent session_id"
        )
    if intent.command != contract.command or intent.action != contract.action:
        raise PolicyAuditLedgerError(
            "policy audit result contract does not match intent payload"
        )
    intent_correlation_id = intent.metadata.get("correlation_id")
    if intent_correlation_id and intent_correlation_id != metadata.correlation_id:
        raise PolicyAuditLedgerError(
            "policy audit result correlation_id does not match intent payload"
        )


def _intent_metadata_fields(metadata: PolicyAuditIntentMetadata) -> dict[str, Any]:
    return _drop_none(
        {
            "destination_repo": metadata.destination_repo,
            "owner_namespace": metadata.owner_namespace,
            "include_legacy_sessions": metadata.include_legacy_sessions,
            "dataset_card_warning_ack": metadata.dataset_card_warning_ack,
            "revocation_guidance": metadata.revocation_guidance,
            "verifier_id": metadata.verifier_id,
            "input_checksum": metadata.input_checksum,
            "bundle_id": metadata.bundle_id,
            "run_id": metadata.run_id,
            "decision_ids": list(metadata.decision_ids),
            "evidence_ids": list(metadata.evidence_ids),
            "artifact_ids": list(metadata.artifact_ids),
            "manifest_checksum": metadata.manifest_checksum,
            "signature_ref": metadata.signature_ref,
            "signing_key_ref": metadata.signing_key_ref,
        }
    )


def _result_metadata_fields(metadata: PolicyAuditResultMetadata) -> dict[str, Any]:
    return _drop_none(
        {
            "verdict": metadata.verdict,
            "manifest_checksum": metadata.manifest_checksum,
            "destination_repo": metadata.destination_repo,
            "owner_namespace": metadata.owner_namespace,
            "error_summary": metadata.error_summary,
        }
    )


def _drop_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _require_correlation_id(correlation_id: str | None) -> None:
    if _is_missing_required_value(correlation_id):
        raise PolicyAuditLedgerError("policy audit builder requires correlation_id")


def _builder_metadata(
    contract: PolicyAuditContract,
    *,
    request_metadata: Mapping[str, Any] | None,
    correlation_id: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "contract": {
            "command": contract.command,
            "action": contract.action,
            "contract_version": contract.contract_version,
            "risk": contract.risk.value,
            "requires_approval": contract.requires_approval,
            "audit_required": contract.audit_required,
            "approval_title": _clean_text(contract.approval_title),
            "approval_body": _clean_text(contract.approval_body),
            "side_effects": list(contract.side_effects),
            "rollback": _clean_text(contract.rollback),
            "budget_impact": _clean_text(contract.budget_impact),
            "credential_usage": list(contract.credential_usage),
            "privacy_default": contract.privacy_default,
            "visibility_default": contract.visibility_default,
            "audit_intent_event_type": contract.audit_intent_event_type,
            "audit_result_event_type": contract.audit_result_event_type,
            "audit_required_fields": list(contract.audit_required_fields),
            "redaction_requirements": [
                _clean_text(item) for item in contract.redaction_requirements
            ],
            "preconditions": [_clean_text(item) for item in contract.preconditions],
            "notes": [_clean_text(item) for item in contract.notes],
        }
    }
    if request_metadata:
        metadata["request"] = dict(request_metadata)
    if correlation_id:
        metadata["correlation_id"] = correlation_id
    return metadata


def _is_missing_required_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, Sequence) and not isinstance(value, str):
        return len(value) == 0
    return False


def _clean_text(value: str) -> str:
    return " ".join(value.strip().split())


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


def _record_payload(
    record: PolicyAuditIntentRecord | PolicyAuditResultRecord,
) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_payload(
    record: PolicyAuditIntentRecord | PolicyAuditResultRecord,
) -> tuple[dict[str, Any], str]:
    result = redact_value(_record_payload(record))
    if not isinstance(result.value, dict):
        raise PolicyAuditLedgerError("redacted policy audit payload must be a mapping")

    redaction_status = _stronger_redaction_status(
        record.redaction_status,
        result.status,
    )
    result.value["redaction_status"] = redaction_status
    return result.value, redaction_status


def _validate_event_session(
    record_session_id: str,
    event_session_id: str,
    label: str,
) -> None:
    if record_session_id != event_session_id:
        raise PolicyAuditLedgerError(
            f"{label} event session_id does not match record session_id"
        )


def _reject_duplicate_record_ids(
    records: Sequence[Any],
    id_field: str,
    label: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = getattr(record, id_field)
        if record_id in seen:
            raise PolicyAuditLedgerError(f"duplicate {label} id: {record_id}")
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


class PolicyAuditAppendAdapter:
    """Narrow append adapter that persists policy audit AgentEvent envelopes.

    The adapter is inert: it must be instantiated with an explicit store
    callable and invoked by a caller. It does not wire itself into runtime
    flows, routes, or command dispatch.
    """

    def __init__(
        self,
        append_callable: Callable[[AgentEvent], AgentEvent],
    ) -> None:
        self._append = append_callable

    def append(self, event: AgentEvent) -> AgentEvent:
        """Validate, redact, and append a policy audit event envelope.

        Raises:
            PolicyAuditLedgerError: if the event type is unsupported,
                the session id is missing, or payload validation fails.
            ValueError: if the sequence is less than 1.
        """
        if event.event_type not in _POLICY_AUDIT_EVENT_TYPES:
            raise PolicyAuditLedgerError(
                f"unsupported policy audit event type: {event.event_type}"
            )
        if event.sequence < 1:
            raise ValueError("sequence must be greater than or equal to 1")
        if not isinstance(event.session_id, str) or _is_missing_required_value(
            event.session_id
        ):
            raise PolicyAuditLedgerError(
                "policy audit event envelope missing session_id"
            )

        redacted_event = event.redacted_copy()
        stored_event = self._append(redacted_event)

        if stored_event.sequence != redacted_event.sequence:
            raise PolicyAuditLedgerError(
                "policy audit append adapter sequence mismatch: "
                f"expected {redacted_event.sequence}, got {stored_event.sequence}"
            )
        if stored_event.session_id != redacted_event.session_id:
            raise PolicyAuditLedgerError(
                "policy audit append adapter session_id mismatch"
            )

        return stored_event
