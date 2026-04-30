from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any, Literal, Protocol, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints
from pydantic import ValidationInfo, field_validator, model_validator

from agent.core.redaction import redact_value


DECISION_CARD_RECORDED_EVENT = "decision_card.recorded"
PROOF_BUNDLE_RECORDED_EVENT = "proof_bundle.recorded"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class DecisionProofLedgerError(ValueError):
    pass


class AgentEventLike(Protocol):
    id: str
    session_id: str
    sequence: int
    event_type: str
    data: dict[str, Any] | None


class DecisionProofLedgerModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
    )


class ChecksumRef(DecisionProofLedgerModel):
    checksum_id: NonEmptyStr
    algorithm: Literal[
        "sha256",
        "sha384",
        "sha512",
        "sha1",
        "md5",
        "blake2b",
        "blake3",
        "unknown",
    ]
    value: NonEmptyStr = Field(
        validation_alias=AliasChoices("value", "digest", "checksum"),
        serialization_alias="value",
    )
    source: Literal[
        "manual",
        "artifact_ref",
        "manifest_ref",
        "local_path",
        "remote_uri",
        "event_ref",
    ]
    artifact_id: NonEmptyStr | None = None
    manifest_id: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    event_id: NonEmptyStr | None = None
    label: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_source_target(self) -> ChecksumRef:
        _require_source_target(
            source=self.source,
            field_by_source={
                "artifact_ref": "artifact_id",
                "manifest_ref": "manifest_id",
                "local_path": "path",
                "remote_uri": "uri",
                "event_ref": "event_id",
            },
            record=self,
            label="checksum ref",
        )
        return self


class ManifestRef(DecisionProofLedgerModel):
    manifest_id: NonEmptyStr
    source: Literal["manual", "artifact_ref", "local_path", "remote_uri", "event_ref"]
    artifact_id: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    event_id: NonEmptyStr | None = None
    checksum_ids: list[NonEmptyStr] = Field(default_factory=list)
    label: NonEmptyStr | None = None

    @field_validator("checksum_ids")
    @classmethod
    def validate_unique_checksum_ids(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        _reject_duplicate_values(value, info.field_name or "checksum_ids")
        return value

    @model_validator(mode="after")
    def validate_source_target(self) -> ManifestRef:
        _require_source_target(
            source=self.source,
            field_by_source={
                "artifact_ref": "artifact_id",
                "local_path": "path",
                "remote_uri": "uri",
                "event_ref": "event_id",
            },
            record=self,
            label="manifest ref",
        )
        return self


class DecisionAlternative(DecisionProofLedgerModel):
    alternative_id: NonEmptyStr | None = None
    title: NonEmptyStr
    summary: NonEmptyStr | None = None
    outcome: Literal["chosen", "rejected", "deferred"] | None = None


class DecisionCardRecord(DecisionProofLedgerModel):
    session_id: NonEmptyStr
    decision_id: NonEmptyStr = Field(
        validation_alias=AliasChoices("decision_id", "decision_card_id"),
        serialization_alias="decision_id",
    )
    source_event_sequence: int | None = Field(default=None, ge=1)
    title: NonEmptyStr
    decision: NonEmptyStr
    status: Literal["proposed", "accepted", "rejected", "deferred", "superseded"]
    rationale: NonEmptyStr | None = None
    phase_id: NonEmptyStr | None = None
    run_id: NonEmptyStr | None = None
    actor: NonEmptyStr | None = None
    alternatives: list[DecisionAlternative] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    claim_ids: list[NonEmptyStr] = Field(default_factory=list)
    artifact_ids: list[NonEmptyStr] = Field(default_factory=list)
    proof_bundle_ids: list[NonEmptyStr] = Field(default_factory=list)
    manifest_refs: list[ManifestRef] = Field(default_factory=list)
    checksum_refs: list[ChecksumRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None

    @property
    def decision_card_id(self) -> str:
        return self.decision_id

    @field_validator("evidence_ids", "claim_ids", "artifact_ids", "proof_bundle_ids")
    @classmethod
    def validate_unique_text_refs(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        _reject_duplicate_values(value, info.field_name or "refs")
        return value

    @field_validator("alternatives")
    @classmethod
    def validate_unique_alternative_ids(
        cls,
        value: list[DecisionAlternative],
    ) -> list[DecisionAlternative]:
        _reject_duplicate_optional_record_ids(
            value,
            "alternative_id",
            "decision alternative",
        )
        return value

    @model_validator(mode="after")
    def validate_embedded_refs(self) -> DecisionCardRecord:
        _validate_embedded_manifest_checksum_refs(
            self.manifest_refs,
            self.checksum_refs,
            "decision card",
        )
        return self


class ProofBundleRecord(DecisionProofLedgerModel):
    session_id: NonEmptyStr
    proof_bundle_id: NonEmptyStr = Field(
        validation_alias=AliasChoices("proof_bundle_id", "proof_id"),
        serialization_alias="proof_bundle_id",
    )
    source_event_sequence: int | None = Field(default=None, ge=1)
    title: NonEmptyStr
    summary: NonEmptyStr
    status: Literal["draft", "complete", "inconclusive", "superseded"]
    scope: NonEmptyStr | None = None
    phase_id: NonEmptyStr | None = None
    run_id: NonEmptyStr | None = None
    decision_ids: list[NonEmptyStr] = Field(default_factory=list)
    evidence_ids: list[NonEmptyStr] = Field(default_factory=list)
    claim_ids: list[NonEmptyStr] = Field(default_factory=list)
    artifact_ids: list[NonEmptyStr] = Field(default_factory=list)
    verifier_verdict_ids: list[NonEmptyStr] = Field(default_factory=list)
    manifest_refs: list[ManifestRef] = Field(default_factory=list)
    checksum_refs: list[ChecksumRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"]
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None

    @property
    def proof_id(self) -> str:
        return self.proof_bundle_id

    @field_validator(
        "decision_ids",
        "evidence_ids",
        "claim_ids",
        "artifact_ids",
        "verifier_verdict_ids",
    )
    @classmethod
    def validate_unique_text_refs(
        cls,
        value: list[str],
        info: ValidationInfo,
    ) -> list[str]:
        _reject_duplicate_values(value, info.field_name or "refs")
        return value

    @model_validator(mode="after")
    def validate_embedded_refs(self) -> ProofBundleRecord:
        _validate_embedded_manifest_checksum_refs(
            self.manifest_refs,
            self.checksum_refs,
            "proof bundle",
        )
        return self


DecisionProofRecord: TypeAlias = DecisionCardRecord | ProofBundleRecord


class DecisionProofLedgerProjection(DecisionProofLedgerModel):
    session_id: NonEmptyStr
    decision_cards: list[DecisionCardRecord]
    proof_bundles: list[ProofBundleRecord]


def decision_card_recorded_payload(record: DecisionCardRecord) -> dict[str, Any]:
    return _record_payload(record)


def proof_bundle_recorded_payload(record: ProofBundleRecord) -> dict[str, Any]:
    return _record_payload(record)


def redacted_decision_card_payload(
    record: DecisionCardRecord,
) -> tuple[dict[str, Any], str]:
    return _redacted_record_payload(record)


def redacted_proof_bundle_payload(
    record: ProofBundleRecord,
) -> tuple[dict[str, Any], str]:
    return _redacted_record_payload(record)


def decision_card_record_from_event(event: AgentEventLike) -> DecisionCardRecord:
    if event.event_type != DECISION_CARD_RECORDED_EVENT:
        raise DecisionProofLedgerError(f"Expected {DECISION_CARD_RECORDED_EVENT}")

    record = DecisionCardRecord.model_validate(event.data or {})
    _validate_event_session(record.session_id, event.session_id, "decision card")
    return record


def proof_bundle_record_from_event(event: AgentEventLike) -> ProofBundleRecord:
    if event.event_type != PROOF_BUNDLE_RECORDED_EVENT:
        raise DecisionProofLedgerError(f"Expected {PROOF_BUNDLE_RECORDED_EVENT}")

    record = ProofBundleRecord.model_validate(event.data or {})
    _validate_event_session(record.session_id, event.session_id, "proof bundle")
    return record


def project_decision_cards(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> list[DecisionCardRecord]:
    records = [
        decision_card_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            DECISION_CARD_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_record_ids(records, "decision_id", "decision card")
    return records


def project_proof_bundles(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> list[ProofBundleRecord]:
    records = [
        proof_bundle_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            PROOF_BUNDLE_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_record_ids(records, "proof_bundle_id", "proof bundle")
    return records


def project_decision_proof_ledger(
    session_id: str,
    events: Sequence[AgentEventLike],
) -> DecisionProofLedgerProjection:
    decision_cards = project_decision_cards(session_id, events)
    proof_bundles = project_proof_bundles(session_id, events)
    validate_decision_proof_refs(decision_cards, proof_bundles)
    return DecisionProofLedgerProjection(
        session_id=session_id,
        decision_cards=decision_cards,
        proof_bundles=proof_bundles,
    )


def validate_decision_proof_refs(
    decision_cards: Sequence[DecisionCardRecord],
    proof_bundles: Sequence[ProofBundleRecord],
) -> None:
    decision_ids = {record.decision_id for record in decision_cards}
    proof_bundle_ids = {record.proof_bundle_id for record in proof_bundles}

    for decision in decision_cards:
        for proof_bundle_id in decision.proof_bundle_ids:
            if proof_bundle_id not in proof_bundle_ids:
                raise DecisionProofLedgerError(
                    f"decision card {decision.decision_id} references unknown "
                    f"proof_bundle_id: {proof_bundle_id}"
                )

    for proof_bundle in proof_bundles:
        for decision_id in proof_bundle.decision_ids:
            if decision_id not in decision_ids:
                raise DecisionProofLedgerError(
                    f"proof bundle {proof_bundle.proof_bundle_id} references "
                    f"unknown decision_id: {decision_id}"
                )


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


def _record_payload(record: DecisionProofRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_payload(record: DecisionProofRecord) -> tuple[dict[str, Any], str]:
    result = redact_value(_record_payload(record))
    if not isinstance(result.value, dict):
        raise DecisionProofLedgerError("redacted record payload must be a mapping")

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
        raise DecisionProofLedgerError(
            f"{label} event session_id does not match record session_id"
        )


def _require_source_target(
    *,
    source: str,
    field_by_source: dict[str, str],
    record: DecisionProofLedgerModel,
    label: str,
) -> None:
    field_name = field_by_source.get(source)
    if field_name is not None and not getattr(record, field_name):
        raise ValueError(f"{label} source={source} requires {field_name}")


def _validate_embedded_manifest_checksum_refs(
    manifest_refs: Sequence[ManifestRef],
    checksum_refs: Sequence[ChecksumRef],
    owner_label: str,
) -> None:
    _reject_duplicate_record_ids(manifest_refs, "manifest_id", f"{owner_label} manifest")
    _reject_duplicate_record_ids(checksum_refs, "checksum_id", f"{owner_label} checksum")
    _reject_duplicate_checksum_values(checksum_refs, f"{owner_label} checksum")

    checksum_ids = {record.checksum_id for record in checksum_refs}
    for manifest_ref in manifest_refs:
        for checksum_id in manifest_ref.checksum_ids:
            if checksum_id not in checksum_ids:
                raise ValueError(
                    f"{owner_label} manifest {manifest_ref.manifest_id} references "
                    f"unknown checksum_id: {checksum_id}"
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
            raise DecisionProofLedgerError(f"duplicate {label} id: {record_id}")
        seen.add(record_id)


def _reject_duplicate_optional_record_ids(
    records: Sequence[Any],
    id_field: str,
    label: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = getattr(record, id_field)
        if record_id is None:
            continue
        if record_id in seen:
            raise ValueError(f"duplicate {label} id: {record_id}")
        seen.add(record_id)


def _reject_duplicate_checksum_values(
    checksum_refs: Sequence[ChecksumRef],
    label: str,
) -> None:
    seen: set[tuple[str, str]] = set()
    for checksum_ref in checksum_refs:
        key = (checksum_ref.algorithm, checksum_ref.value)
        if key in seen:
            raise DecisionProofLedgerError(
                f"duplicate {label} value: {checksum_ref.algorithm}:{checksum_ref.value}"
            )
        seen.add(key)


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
