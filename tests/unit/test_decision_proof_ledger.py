from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from agent.core.events import AgentEvent
from backend.decision_proof_ledger import (
    DECISION_CARD_RECORDED_EVENT,
    PROOF_BUNDLE_RECORDED_EVENT,
    DecisionCardRecord,
    DecisionProofLedgerError,
    ProofBundleRecord,
    decision_card_record_from_event,
    decision_card_recorded_payload,
    proof_bundle_record_from_event,
    proof_bundle_recorded_payload,
    project_decision_cards,
    project_decision_proof_ledger,
    project_proof_bundles,
    redacted_decision_card_payload,
    redacted_proof_bundle_payload,
)


def make_decision(
    *,
    session_id: str = "session-a",
    decision_id: str = "decision-1",
    **overrides: Any,
) -> DecisionCardRecord:
    values = _valid_decision_payload(session_id=session_id, decision_id=decision_id)
    values.update(overrides)
    return DecisionCardRecord.model_validate(values)


def make_proof(
    *,
    session_id: str = "session-a",
    proof_bundle_id: str = "proof-1",
    **overrides: Any,
) -> ProofBundleRecord:
    values = _valid_proof_payload(
        session_id=session_id,
        proof_bundle_id=proof_bundle_id,
    )
    values.update(overrides)
    return ProofBundleRecord.model_validate(values)


def make_decision_event(
    record: DecisionCardRecord,
    *,
    sequence: int = 1,
    event_type: str = DECISION_CARD_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-decision-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=decision_card_recorded_payload(record),
    )


def make_proof_event(
    record: ProofBundleRecord,
    *,
    sequence: int = 1,
    event_type: str = PROOF_BUNDLE_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-proof-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=proof_bundle_recorded_payload(record),
    )


def test_payload_helpers_roundtrip_closed_models_and_aliases():
    decision = make_decision(decision_id="decision-roundtrip")
    proof_payload = _valid_proof_payload(proof_bundle_id="proof-roundtrip")
    proof_payload["proof_id"] = "proof-alias"
    del proof_payload["proof_bundle_id"]
    proof = ProofBundleRecord.model_validate(proof_payload)

    assert DecisionCardRecord.model_validate(
        decision_card_recorded_payload(decision)
    ) == decision
    assert ProofBundleRecord.model_validate(proof_bundle_recorded_payload(proof)) == proof
    assert proof_bundle_recorded_payload(proof)["proof_bundle_id"] == "proof-alias"
    assert "proof_id" not in proof_bundle_recorded_payload(proof)


def test_event_record_validators_reject_wrong_type_and_session_mismatch():
    decision = make_decision(decision_id="decision-validate")
    proof = make_proof(proof_bundle_id="proof-validate")

    assert decision_card_record_from_event(make_decision_event(decision)) == decision
    assert proof_bundle_record_from_event(make_proof_event(proof)) == proof

    with pytest.raises(DecisionProofLedgerError, match=DECISION_CARD_RECORDED_EVENT):
        decision_card_record_from_event(
            make_decision_event(decision, event_type="phase.completed")
        )
    with pytest.raises(DecisionProofLedgerError, match=PROOF_BUNDLE_RECORDED_EVENT):
        proof_bundle_record_from_event(
            make_proof_event(proof, event_type="phase.completed")
        )

    with pytest.raises(DecisionProofLedgerError, match="session_id"):
        decision_card_record_from_event(
            make_decision_event(
                make_decision(session_id="session-b", decision_id="decision-validate"),
                session_id="session-a",
            )
        )
    with pytest.raises(DecisionProofLedgerError, match="session_id"):
        proof_bundle_record_from_event(
            make_proof_event(
                make_proof(session_id="session-b", proof_bundle_id="proof-validate"),
                session_id="session-a",
            )
        )


def test_projections_filter_by_session_and_type_order_by_event_sequence():
    first_decision = make_decision(decision_id="decision-1")
    second_decision = make_decision(decision_id="decision-2")
    other_decision = make_decision(session_id="session-b", decision_id="decision-b")
    wrong_decision = make_decision(decision_id="decision-wrong")
    first_proof = make_proof(proof_bundle_id="proof-1")
    second_proof = make_proof(proof_bundle_id="proof-2")
    other_proof = make_proof(session_id="session-b", proof_bundle_id="proof-b")
    events = [
        make_decision_event(wrong_decision, sequence=1, event_type="phase.completed"),
        make_decision_event(second_decision, sequence=4),
        make_decision_event(other_decision, sequence=2),
        make_decision_event(first_decision, sequence=3),
        make_proof_event(second_proof, sequence=7),
        make_proof_event(other_proof, sequence=5),
        make_proof_event(first_proof, sequence=6),
    ]

    assert [
        record.decision_id for record in project_decision_cards("session-a", events)
    ] == ["decision-1", "decision-2"]
    assert [
        record.proof_bundle_id for record in project_proof_bundles("session-a", events)
    ] == ["proof-1", "proof-2"]


def test_projections_reject_duplicate_record_ids():
    first_decision = make_decision(decision_id="decision-duplicate", title="First")
    second_decision = make_decision(decision_id="decision-duplicate", title="Second")
    first_proof = make_proof(proof_bundle_id="proof-duplicate", title="First")
    second_proof = make_proof(proof_bundle_id="proof-duplicate", title="Second")

    with pytest.raises(DecisionProofLedgerError, match="duplicate"):
        project_decision_cards(
            "session-a",
            [
                make_decision_event(first_decision, sequence=1),
                make_decision_event(second_decision, sequence=2),
            ],
        )
    with pytest.raises(DecisionProofLedgerError, match="duplicate"):
        project_proof_bundles(
            "session-a",
            [
                make_proof_event(first_proof, sequence=1),
                make_proof_event(second_proof, sequence=2),
            ],
        )


def test_combined_projection_validates_local_decision_proof_cross_refs():
    decision = make_decision(
        decision_id="decision-linked",
        proof_bundle_ids=["proof-linked"],
    )
    proof = make_proof(
        proof_bundle_id="proof-linked",
        decision_ids=["decision-linked"],
    )

    projection = project_decision_proof_ledger(
        "session-a",
        [make_proof_event(proof, sequence=2), make_decision_event(decision, sequence=1)],
    )

    assert projection.session_id == "session-a"
    assert projection.decision_cards == [decision]
    assert projection.proof_bundles == [proof]

    missing_proof = make_decision(
        decision_id="decision-missing-proof",
        proof_bundle_ids=["proof-missing"],
    )
    with pytest.raises(DecisionProofLedgerError, match="unknown proof_bundle_id"):
        project_decision_proof_ledger(
            "session-a",
            [make_decision_event(missing_proof)],
        )

    missing_decision = make_proof(
        proof_bundle_id="proof-missing-decision",
        decision_ids=["decision-missing"],
    )
    with pytest.raises(DecisionProofLedgerError, match="unknown decision_id"):
        project_decision_proof_ledger(
            "session-a",
            [make_proof_event(missing_decision)],
        )


@pytest.mark.parametrize(
    ("payload_factory", "mutation"),
    [
        (
            lambda: _valid_decision_payload(),
            lambda payload: payload.update(
                {"evidence_ids": ["evidence-1", "evidence-1"]}
            ),
        ),
        (
            lambda: _valid_decision_payload(),
            lambda payload: payload["manifest_refs"].append(
                {
                    "manifest_id": "manifest-1",
                    "source": "manual",
                    "checksum_ids": ["checksum-1"],
                }
            ),
        ),
        (
            lambda: _valid_decision_payload(),
            lambda payload: payload["manifest_refs"][0].update(
                {"checksum_ids": ["checksum-missing"]}
            ),
        ),
        (
            lambda: _valid_decision_payload(),
            lambda payload: payload["checksum_refs"][0].update(
                {"source": "local_path", "path": None}
            ),
        ),
        (
            lambda: _valid_proof_payload(),
            lambda payload: payload.update(
                {"decision_ids": ["decision-1", "decision-1"]}
            ),
        ),
        (
            lambda: _valid_proof_payload(),
            lambda payload: payload["checksum_refs"].append(
                {
                    "checksum_id": "checksum-2",
                    "algorithm": "sha256",
                    "value": "abc123",
                    "source": "manual",
                }
            ),
        ),
    ],
)
def test_schemas_reject_duplicate_or_invalid_refs(payload_factory, mutation):
    payload = payload_factory()
    mutation(payload)

    with pytest.raises((DecisionProofLedgerError, ValidationError)):
        if "decision_id" in payload:
            DecisionCardRecord.model_validate(payload)
        else:
            ProofBundleRecord.model_validate(payload)


@pytest.mark.parametrize(
    ("payload_factory", "field", "value"),
    [
        (lambda: _valid_decision_payload(), "source_event_sequence", 0),
        (lambda: _valid_decision_payload(), "status", "signed"),
        (lambda: _valid_decision_payload(), "redaction_status", "complete"),
        (lambda: _valid_decision_payload(), "signature", "later"),
        (lambda: _valid_proof_payload(), "status", "verified"),
        (lambda: _valid_proof_payload(), "privacy_class", "internal"),
        (lambda: _valid_proof_payload(), "signature", "later"),
    ],
)
def test_schemas_reject_invalid_values_and_signing_fields(
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        if "decision_id" in payload:
            DecisionCardRecord.model_validate(payload)
        else:
            ProofBundleRecord.model_validate(payload)


def test_redacted_payload_helpers_cover_sensitive_metadata_without_storage():
    secret = "hf_decisionsecret123456789"
    decision = make_decision(
        decision_id="decision-secret",
        rationale=f"Authorization: Bearer {secret}",
        metadata={"api_key": secret},
    )
    proof = make_proof(
        proof_bundle_id="proof-secret",
        metadata={"token": secret, "note": f"HF_TOKEN={secret}"},
    )

    redacted_decision, decision_status = redacted_decision_card_payload(decision)
    redacted_proof, proof_status = redacted_proof_bundle_payload(proof)

    assert secret not in str(redacted_decision)
    assert secret not in str(redacted_proof)
    assert redacted_decision["redaction_status"] == decision_status
    assert redacted_proof["redaction_status"] == proof_status
    assert decision_status in {"partial", "redacted"}
    assert proof_status in {"partial", "redacted"}


def _valid_decision_payload(
    *,
    session_id: str = "session-a",
    decision_id: str = "decision-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "decision_id": decision_id,
        "source_event_sequence": 20,
        "title": "Choose evaluation metric",
        "decision": "Use macro F1 as the primary metric.",
        "status": "accepted",
        "rationale": "Macro F1 reflects minority-class performance.",
        "phase_id": "phase-eval",
        "run_id": "run-1",
        "actor": "human-review",
        "alternatives": [
            {
                "alternative_id": "alternative-accuracy",
                "title": "Accuracy",
                "summary": "Rejected because classes are imbalanced.",
                "outcome": "rejected",
            }
        ],
        "evidence_ids": ["evidence-1"],
        "claim_ids": ["claim-1"],
        "artifact_ids": ["artifact-1"],
        "proof_bundle_ids": [],
        "manifest_refs": [
            {
                "manifest_id": "manifest-1",
                "source": "remote_uri",
                "uri": "https://example.test/manifest.json",
                "checksum_ids": ["checksum-1"],
                "label": "Evaluation manifest",
            }
        ],
        "checksum_refs": [
            {
                "checksum_id": "checksum-1",
                "algorithm": "sha256",
                "value": "abc123",
                "source": "manual",
                "label": "Manifest digest",
            }
        ],
        "metadata": {"reviewed_by": "synthetic-fixture"},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:10:00Z",
    }


def _valid_proof_payload(
    *,
    session_id: str = "session-a",
    proof_bundle_id: str = "proof-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "proof_bundle_id": proof_bundle_id,
        "source_event_sequence": 21,
        "title": "Metric decision proof",
        "summary": "Evidence and verifier refs supporting the metric decision.",
        "status": "complete",
        "scope": "metric-selection",
        "phase_id": "phase-eval",
        "run_id": "run-1",
        "decision_ids": [],
        "evidence_ids": ["evidence-1"],
        "claim_ids": ["claim-1"],
        "artifact_ids": ["artifact-1"],
        "verifier_verdict_ids": ["verdict-1"],
        "manifest_refs": [
            {
                "manifest_id": "manifest-1",
                "source": "remote_uri",
                "uri": "https://example.test/proof-manifest.json",
                "checksum_ids": ["checksum-1"],
                "label": "Proof manifest",
            }
        ],
        "checksum_refs": [
            {
                "checksum_id": "checksum-1",
                "algorithm": "sha256",
                "value": "abc123",
                "source": "manual",
                "label": "Proof manifest digest",
            }
        ],
        "metadata": {"reviewed_by": "synthetic-fixture"},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:11:00Z",
    }
