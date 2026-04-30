from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from agent.core.events import AgentEvent
from backend.models import VerifierVerdictRecord
from backend.verifier_ledger import (
    VERIFIER_COMPLETED_EVENT,
    SQLiteVerifierLedgerStore,
    VerifierLedgerError,
    generate_verdict_id,
    generate_verifier_id,
    project_verifier_verdicts,
    verifier_completed_payload,
    verifier_verdict_record_from_event,
)


def test_generate_verifier_ids_return_unique_stable_prefixes():
    first_verdict = generate_verdict_id()
    second_verdict = generate_verdict_id()
    first_verifier = generate_verifier_id()
    second_verifier = generate_verifier_id()

    assert first_verdict.startswith("verdict-")
    assert second_verdict.startswith("verdict-")
    assert first_verdict != second_verdict
    assert first_verifier.startswith("verifier-")
    assert second_verifier.startswith("verifier-")
    assert first_verifier != second_verifier


def make_verdict(
    *,
    session_id: str = "session-a",
    verdict_id: str = "verdict-1",
    **overrides: Any,
) -> VerifierVerdictRecord:
    values = _valid_verdict_payload(session_id=session_id, verdict_id=verdict_id)
    values.update(overrides)
    return VerifierVerdictRecord.model_validate(values)


def make_verdict_event(
    record: VerifierVerdictRecord,
    *,
    sequence: int = 1,
    event_type: str = VERIFIER_COMPLETED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-verdict-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=verifier_completed_payload(record),
    )


def test_payload_helper_roundtrips_closed_model():
    verdict = make_verdict(verdict_id="verdict-roundtrip")

    assert VerifierVerdictRecord.model_validate(
        verifier_completed_payload(verdict)
    ) == verdict


def test_event_record_validator_rejects_wrong_type_and_session_mismatch():
    verdict = make_verdict(verdict_id="verdict-validate")

    assert verifier_verdict_record_from_event(make_verdict_event(verdict)) == verdict

    with pytest.raises(VerifierLedgerError, match=VERIFIER_COMPLETED_EVENT):
        verifier_verdict_record_from_event(
            make_verdict_event(verdict, event_type="phase.completed")
        )

    with pytest.raises(VerifierLedgerError, match="session_id"):
        verifier_verdict_record_from_event(
            make_verdict_event(
                make_verdict(session_id="session-b", verdict_id="verdict-validate"),
                session_id="session-a",
            )
        )


def test_projection_filters_by_session_and_type_ordered_by_event_sequence():
    first = make_verdict(verdict_id="verdict-1")
    second = make_verdict(verdict_id="verdict-2")
    other = make_verdict(session_id="session-b", verdict_id="verdict-b")
    wrong = make_verdict(verdict_id="verdict-wrong")
    events = [
        make_verdict_event(wrong, sequence=1, event_type="phase.completed"),
        make_verdict_event(second, sequence=4),
        make_verdict_event(other, sequence=2),
        make_verdict_event(first, sequence=3),
    ]

    assert [
        record.verdict_id for record in project_verifier_verdicts("session-a", events)
    ] == ["verdict-1", "verdict-2"]


def test_projection_rejects_duplicate_verdict_ids():
    first = make_verdict(verdict_id="verdict-duplicate", summary="first")
    second = make_verdict(verdict_id="verdict-duplicate", summary="second")

    with pytest.raises(VerifierLedgerError, match="duplicate"):
        project_verifier_verdicts(
            "session-a",
            [
                make_verdict_event(first, sequence=1),
                make_verdict_event(second, sequence=2),
            ],
        )


def test_sqlite_create_get_list_and_duplicate_rejection(tmp_path):
    store = SQLiteVerifierLedgerStore(tmp_path / "verifier.sqlite")
    first = make_verdict(verdict_id="verdict-1")
    second = make_verdict(verdict_id="verdict-2", verdict="inconclusive")

    created = store.create(first)
    store.create(second)

    assert store.get("session-a", "verdict-1") == created
    assert store.get("session-a", "missing") is None
    assert [record.verdict_id for record in store.list("session-a")] == [
        "verdict-1",
        "verdict-2",
    ]
    assert store.list("session-a", limit=1) == [created]

    with pytest.raises(VerifierLedgerError, match="already exists"):
        store.create(first)
    with pytest.raises(VerifierLedgerError, match="limit"):
        store.list("session-a", limit=-1)


def test_persisted_json_is_redacted(tmp_path):
    database_path = tmp_path / "verifier.sqlite"
    store = SQLiteVerifierLedgerStore(database_path)
    secret = "hf_verifiersecret123456789"
    verdict = make_verdict(
        verdict_id="verdict-secret",
        rationale=f"Authorization: Bearer {secret}",
        metadata={"api_key": secret},
        checks=[
            {
                "name": "Secret-bearing check",
                "status": "inconclusive",
                "summary": f"Token {secret}",
            }
        ],
    )

    created = store.create(verdict)

    assert secret not in str(created.model_dump())
    assert created.redaction_status in {"partial", "redacted"}

    connection = sqlite3.connect(database_path)
    try:
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert secret not in database_dump
    assert "[REDACTED]" in database_dump


def test_sqlite_store_owns_only_verifier_ledger_table(tmp_path):
    database_path = tmp_path / "verifier.sqlite"
    SQLiteVerifierLedgerStore(database_path).close()

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert tables == {"verifier_verdicts"}


def _valid_verdict_payload(
    *,
    session_id: str = "session-a",
    verdict_id: str = "verdict-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "verdict_id": verdict_id,
        "verifier_id": "final-claims-have-evidence",
        "source_event_sequence": 14,
        "verdict": "passed",
        "scope": "final_answer",
        "final_answer_ref": "final-answer-1",
        "phase_id": "phase-report",
        "run_id": "run-1",
        "evidence_ids": ["evidence-1"],
        "claim_ids": ["claim-1"],
        "summary": "Claims have support.",
        "rationale": "Evidence supports the final claim.",
        "checks": [
            {
                "check_id": "check-1",
                "name": "Claim coverage",
                "status": "passed",
                "summary": "Claim is linked to evidence.",
                "evidence_ids": ["evidence-1"],
                "metadata": {"claim_id": "claim-1"},
            }
        ],
        "metadata": {"source": "synthetic-fixture"},
        "redaction_status": "none",
        "created_at": "2026-04-29T10:09:00Z",
    }
