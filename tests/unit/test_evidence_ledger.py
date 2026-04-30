from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from agent.core.events import AgentEvent
from backend.evidence_ledger import (
    EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    EVIDENCE_ITEM_RECORDED_EVENT,
    EvidenceLedgerError,
    SQLiteEvidenceLedgerStore,
    evidence_claim_link_record_from_event,
    evidence_claim_link_recorded_payload,
    evidence_item_record_from_event,
    evidence_item_recorded_payload,
    generate_evidence_claim_link_id,
    generate_evidence_id,
    project_evidence_claim_links,
    project_evidence_items,
)
from backend.models import EvidenceClaimLinkRecord, EvidenceItemRecord


def test_generate_evidence_ids_return_unique_stable_prefixes():
    first_evidence = generate_evidence_id()
    second_evidence = generate_evidence_id()
    first_link = generate_evidence_claim_link_id()
    second_link = generate_evidence_claim_link_id()

    assert first_evidence.startswith("evidence-")
    assert second_evidence.startswith("evidence-")
    assert first_evidence != second_evidence
    assert first_link.startswith("evidence-link-")
    assert second_link.startswith("evidence-link-")
    assert first_link != second_link


def make_item_event(
    record: EvidenceItemRecord,
    *,
    sequence: int = 1,
    event_type: str = EVIDENCE_ITEM_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-evidence-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=evidence_item_recorded_payload(record),
    )


def make_link_event(
    record: EvidenceClaimLinkRecord,
    *,
    sequence: int = 1,
    event_type: str = EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-link-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=evidence_claim_link_recorded_payload(record),
    )


def make_item(
    *,
    session_id: str = "session-a",
    evidence_id: str = "evidence-1",
    **overrides: Any,
) -> EvidenceItemRecord:
    values = _valid_item_payload(session_id=session_id, evidence_id=evidence_id)
    values.update(overrides)
    return EvidenceItemRecord.model_validate(values)


def make_link(
    *,
    session_id: str = "session-a",
    link_id: str = "evidence-link-1",
    evidence_id: str = "evidence-1",
    **overrides: Any,
) -> EvidenceClaimLinkRecord:
    values = _valid_link_payload(
        session_id=session_id,
        link_id=link_id,
        evidence_id=evidence_id,
    )
    values.update(overrides)
    return EvidenceClaimLinkRecord.model_validate(values)


def test_payload_helpers_roundtrip_closed_models():
    item = make_item(evidence_id="evidence-roundtrip")
    link = make_link(link_id="link-roundtrip", evidence_id=item.evidence_id)

    assert EvidenceItemRecord.model_validate(
        evidence_item_recorded_payload(item)
    ) == item
    assert EvidenceClaimLinkRecord.model_validate(
        evidence_claim_link_recorded_payload(link)
    ) == link


def test_event_record_validators_reject_wrong_type_and_session_mismatch():
    item = make_item(evidence_id="evidence-validate")
    link = make_link(link_id="link-validate", evidence_id=item.evidence_id)

    assert evidence_item_record_from_event(make_item_event(item)) == item
    assert evidence_claim_link_record_from_event(make_link_event(link)) == link

    with pytest.raises(EvidenceLedgerError, match=EVIDENCE_ITEM_RECORDED_EVENT):
        evidence_item_record_from_event(
            make_item_event(item, event_type="phase.completed")
        )
    with pytest.raises(EvidenceLedgerError, match=EVIDENCE_CLAIM_LINK_RECORDED_EVENT):
        evidence_claim_link_record_from_event(
            make_link_event(link, event_type="phase.completed")
        )

    with pytest.raises(EvidenceLedgerError, match="session_id"):
        evidence_item_record_from_event(
            make_item_event(
                make_item(session_id="session-b", evidence_id="evidence-validate"),
                session_id="session-a",
            )
        )
    with pytest.raises(EvidenceLedgerError, match="session_id"):
        evidence_claim_link_record_from_event(
            make_link_event(
                make_link(session_id="session-b", link_id="link-validate"),
                session_id="session-a",
            )
        )


def test_projections_filter_by_session_and_type_order_by_event_sequence():
    first_item = make_item(evidence_id="evidence-1")
    second_item = make_item(evidence_id="evidence-2")
    other_item = make_item(session_id="session-b", evidence_id="evidence-b")
    wrong_item = make_item(evidence_id="evidence-wrong")
    first_link = make_link(link_id="link-1", evidence_id="evidence-1")
    second_link = make_link(link_id="link-2", evidence_id="evidence-2")
    other_link = make_link(session_id="session-b", link_id="link-b")
    events = [
        make_item_event(wrong_item, sequence=1, event_type="phase.completed"),
        make_item_event(second_item, sequence=4),
        make_item_event(other_item, sequence=2),
        make_item_event(first_item, sequence=3),
        make_link_event(second_link, sequence=7),
        make_link_event(other_link, sequence=5),
        make_link_event(first_link, sequence=6),
    ]

    assert [
        record.evidence_id for record in project_evidence_items("session-a", events)
    ] == ["evidence-1", "evidence-2"]
    assert [
        record.link_id for record in project_evidence_claim_links("session-a", events)
    ] == ["link-1", "link-2"]


def test_projections_reject_duplicate_ids():
    first_item = make_item(evidence_id="evidence-duplicate", title="first")
    second_item = make_item(evidence_id="evidence-duplicate", title="second")
    first_link = make_link(link_id="link-duplicate", rationale="first")
    second_link = make_link(link_id="link-duplicate", rationale="second")

    with pytest.raises(EvidenceLedgerError, match="duplicate"):
        project_evidence_items(
            "session-a",
            [
                make_item_event(first_item, sequence=1),
                make_item_event(second_item, sequence=2),
            ],
        )
    with pytest.raises(EvidenceLedgerError, match="duplicate"):
        project_evidence_claim_links(
            "session-a",
            [
                make_link_event(first_link, sequence=1),
                make_link_event(second_link, sequence=2),
            ],
        )


def test_sqlite_create_get_list_and_duplicate_rejection(tmp_path):
    store = SQLiteEvidenceLedgerStore(tmp_path / "evidence.sqlite")
    first_item = make_item(evidence_id="evidence-1")
    second_item = make_item(evidence_id="evidence-2")
    first_link = make_link(link_id="link-1", evidence_id="evidence-1")
    second_link = make_link(link_id="link-2", evidence_id="evidence-2")

    created_item = store.create_evidence_item(first_item)
    store.create_evidence_item(second_item)
    created_link = store.create_claim_link(first_link)
    store.create_claim_link(second_link)

    assert store.get_evidence_item("session-a", "evidence-1") == created_item
    assert store.get_evidence_item("session-a", "missing") is None
    assert [record.evidence_id for record in store.list_evidence_items("session-a")] == [
        "evidence-1",
        "evidence-2",
    ]
    assert store.list_evidence_items("session-a", limit=1) == [created_item]
    assert store.get_claim_link("session-a", "link-1") == created_link
    assert store.get_claim_link("session-a", "missing") is None
    assert [record.link_id for record in store.list_claim_links("session-a")] == [
        "link-1",
        "link-2",
    ]
    assert store.list_claim_links("session-a", limit=1) == [created_link]

    with pytest.raises(EvidenceLedgerError, match="already exists"):
        store.create_evidence_item(first_item)
    with pytest.raises(EvidenceLedgerError, match="already exists"):
        store.create_claim_link(first_link)


def test_persisted_json_is_redacted(tmp_path):
    database_path = tmp_path / "evidence.sqlite"
    store = SQLiteEvidenceLedgerStore(database_path)
    secret = "hf_evidencesecret123456789"
    item = make_item(
        evidence_id="evidence-secret",
        metadata={"api_key": secret, "note": f"Authorization: Bearer {secret}"},
    )
    link = make_link(
        link_id="link-secret",
        evidence_id=item.evidence_id,
        metadata={"token": secret},
    )

    created_item = store.create_evidence_item(item)
    created_link = store.create_claim_link(link)

    assert secret not in str(created_item.model_dump())
    assert secret not in str(created_link.model_dump())

    connection = sqlite3.connect(database_path)
    try:
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert secret not in database_dump
    assert "[REDACTED]" in database_dump


def test_claim_link_creation_does_not_create_evidence_item_row(tmp_path):
    store = SQLiteEvidenceLedgerStore(tmp_path / "evidence.sqlite")
    link = make_link(link_id="link-ref-only", evidence_id="evidence-ref-only")

    store.create_claim_link(link)

    assert store.get_evidence_item("session-a", "evidence-ref-only") is None
    assert store.list_evidence_items("session-a") == []


def test_sqlite_store_owns_only_evidence_ledger_tables(tmp_path):
    database_path = tmp_path / "evidence.sqlite"
    SQLiteEvidenceLedgerStore(database_path).close()

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

    assert tables == {"evidence_claim_links", "evidence_items"}


def _valid_item_payload(
    *,
    session_id: str = "session-a",
    evidence_id: str = "evidence-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "evidence_id": evidence_id,
        "source_event_sequence": 12,
        "kind": "metric",
        "source": "metric",
        "title": "Validation accuracy",
        "summary": "Accuracy improved over baseline",
        "metric_id": "metric-1",
        "metadata": {"split": "validation"},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:07:00Z",
    }


def _valid_link_payload(
    *,
    session_id: str = "session-a",
    link_id: str = "evidence-link-1",
    evidence_id: str = "evidence-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "link_id": link_id,
        "claim_id": "claim-1",
        "evidence_id": evidence_id,
        "source_event_sequence": 13,
        "relation": "supports",
        "strength": "strong",
        "rationale": "Metric exceeds baseline.",
        "metadata": {"reviewed_by": "synthetic-fixture"},
        "created_at": "2026-04-29T10:08:00Z",
    }
