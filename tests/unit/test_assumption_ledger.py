from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.core.events import AgentEvent
from backend.assumption_ledger import (
    ASSUMPTION_RECORDED_EVENT,
    AssumptionLedgerError,
    AssumptionRecord,
    assumption_record_from_event,
    assumption_recorded_payload,
    project_assumptions,
    redacted_assumption_payload,
)


def _assumption(**overrides) -> AssumptionRecord:
    values = {
        "session_id": "session-a",
        "assumption_id": "assumption-dataset",
        "source_event_sequence": 3,
        "title": "Dataset label stability",
        "statement": "Validation labels are stable for the current split.",
        "status": "open",
        "confidence": "medium",
        "phase_id": "phase-data",
        "run_id": "run-1",
        "decision_ids": ["decision-metric"],
        "evidence_ids": ["evidence-labels"],
        "claim_ids": ["claim-labels"],
        "artifact_ids": ["artifact-profile"],
        "proof_bundle_ids": ["proof-readiness"],
        "rationale": "Dataset card documents the label policy.",
        "validation_notes": "Needs another check after data refresh.",
        "metadata": {"source": "synthetic-fixture"},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-01-02T03:04:05+00:00",
        "updated_at": "2026-01-02T03:05:05+00:00",
    }
    values.update(overrides)
    return AssumptionRecord.model_validate(values)


def _event(
    record: AssumptionRecord,
    *,
    sequence: int = 1,
    session_id: str = "session-a",
    event_type: str = ASSUMPTION_RECORDED_EVENT,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=assumption_recorded_payload(record),
    )


def test_assumption_record_payload_round_trips() -> None:
    record = _assumption()
    payload = assumption_recorded_payload(record)
    event = _event(record)

    assert AssumptionRecord.model_validate(payload) == record
    assert assumption_record_from_event(event) == record
    assert payload["assumption_id"] == "assumption-dataset"
    assert payload["confidence"] == "medium"


def test_assumption_record_from_event_rejects_wrong_type_and_session_mismatch() -> None:
    record = _assumption()

    with pytest.raises(AssumptionLedgerError, match=ASSUMPTION_RECORDED_EVENT):
        assumption_record_from_event(
            SimpleNamespace(
                event_type="decision_card.recorded",
                session_id="session-a",
                data=assumption_recorded_payload(record),
            )
        )

    with pytest.raises(AssumptionLedgerError, match="session_id"):
        assumption_record_from_event(_event(record, session_id="session-b"))


def test_project_assumptions_filters_orders_and_rejects_duplicates() -> None:
    first = _assumption(assumption_id="assumption-first")
    second = _assumption(assumption_id="assumption-second")
    other = _assumption(session_id="session-b", assumption_id="assumption-other")

    projected = project_assumptions(
        "session-a",
        [
            _event(second, sequence=3),
            _event(other, sequence=1, session_id="session-b"),
            _event(first, sequence=2),
        ],
    )

    assert [record.assumption_id for record in projected] == [
        "assumption-first",
        "assumption-second",
    ]

    with pytest.raises(AssumptionLedgerError, match="duplicate assumption id"):
        project_assumptions(
            "session-a",
            [
                _event(first, sequence=1),
                _event(first, sequence=2),
            ],
        )


def test_assumption_record_rejects_duplicate_refs() -> None:
    with pytest.raises(ValueError, match="duplicate evidence_ids"):
        _assumption(evidence_ids=["evidence-1", "evidence-1"])


def test_redacted_assumption_payload_scrubs_secret_fields() -> None:
    secret = "hf_assumptionsecret123456789"
    payload, status = redacted_assumption_payload(
        _assumption(
            title=f"Dataset label stability {secret}",
            statement=f"Token {secret} appears in source notes.",
            rationale=f"Authorization: Bearer {secret}",
            metadata={"token": secret},
        )
    )

    assert status == "redacted"
    assert secret not in repr(payload)
    assert "[REDACTED]" in payload["statement"]
    assert payload["redaction_status"] == "redacted"
