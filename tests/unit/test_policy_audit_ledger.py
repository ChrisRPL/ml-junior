from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.core.events import AgentEvent
from agent.core.policy_audit_contracts import (
    POLICY_AUDIT_INTENT_EVENT,
    POLICY_AUDIT_RESULT_EVENT,
    build_policy_audit_contract,
)
from backend.event_store import SQLiteEventStore
from backend.policy_audit_ledger import (
    PolicyAuditAppendAdapter,
    PolicyAuditEventDraft,
    PolicyAuditEventEnvelopeMetadata,
    PolicyAuditIntentRecord,
    PolicyAuditIntentMetadata,
    PolicyAuditLedgerError,
    PolicyAuditResultMetadata,
    PolicyAuditResultRecord,
    build_policy_audit_agent_event,
    build_policy_audit_intent_agent_event,
    build_policy_audit_intent_event_draft,
    build_policy_audit_intent_record,
    build_policy_audit_result_agent_event,
    build_policy_audit_result_record,
    build_policy_audit_result_event_draft,
    policy_audit_intent_from_event,
    policy_audit_intent_payload,
    policy_audit_result_from_event,
    policy_audit_result_payload,
    project_policy_audit_ledger,
    project_policy_audit_results,
    redacted_policy_audit_intent_payload,
    redacted_policy_audit_result_payload,
)


def _intent(**overrides) -> PolicyAuditIntentRecord:
    values = {
        "session_id": "session-a",
        "audit_id": "audit-share-public",
        "source_event_sequence": 8,
        "actor": "human-review",
        "command": "/share-traces",
        "action": "trace_visibility_public",
        "contract_version": "1",
        "target_ref": "traces/session-a",
        "approval_id": "approval-1",
        "privacy_class": "sensitive",
        "visibility": "public",
        "redaction_status": "redacted",
        "rollback_guidance": "Run /share-traces private.",
        "destination_repo": "user/ml-junior-sessions",
        "owner_namespace": "user",
        "include_legacy_sessions": False,
        "dataset_card_warning_ack": True,
        "revocation_guidance": "Flip the dataset private and rotate leaked tokens.",
        "created_at": "2026-05-02T10:10:00+00:00",
        "metadata": {"source": "synthetic-fixture"},
    }
    values.update(overrides)
    return PolicyAuditIntentRecord.model_validate(values)


def _result(**overrides) -> PolicyAuditResultRecord:
    values = {
        "session_id": "session-a",
        "audit_id": "audit-result-share-public",
        "source_event_sequence": 9,
        "intent_audit_id": "audit-share-public",
        "status": "succeeded",
        "redaction_status": "redacted",
        "result_ref": "hf://datasets/user/ml-junior-sessions",
        "destination_repo": "user/ml-junior-sessions",
        "owner_namespace": "user",
        "checked_at": "2026-05-02T10:11:00+00:00",
        "created_at": "2026-05-02T10:11:01+00:00",
        "metadata": {"source": "synthetic-fixture"},
    }
    values.update(overrides)
    return PolicyAuditResultRecord.model_validate(values)


def _intent_event(
    record: PolicyAuditIntentRecord,
    *,
    sequence: int = 1,
    session_id: str = "session-a",
    event_type: str = POLICY_AUDIT_INTENT_EVENT,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 5, 2, 10, 10, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=policy_audit_intent_payload(record),
    )


def _result_event(
    record: PolicyAuditResultRecord,
    *,
    sequence: int = 1,
    session_id: str = "session-a",
    event_type: str = POLICY_AUDIT_RESULT_EVENT,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 5, 2, 10, 11, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=policy_audit_result_payload(record),
    )


def test_policy_audit_payloads_round_trip_from_events() -> None:
    intent = _intent()
    result = _result()

    assert policy_audit_intent_from_event(_intent_event(intent)) == intent
    assert policy_audit_result_from_event(_result_event(result)) == result
    assert policy_audit_intent_payload(intent)["contract_version"] == "1"
    assert policy_audit_intent_payload(intent)["source_event_sequence"] == 8
    assert policy_audit_result_payload(result)["intent_audit_id"] == (
        "audit-share-public"
    )


def test_policy_audit_events_reject_wrong_type_and_session_mismatch() -> None:
    intent = _intent()
    result = _result()

    with pytest.raises(PolicyAuditLedgerError, match=POLICY_AUDIT_INTENT_EVENT):
        policy_audit_intent_from_event(
            SimpleNamespace(
                event_type=POLICY_AUDIT_RESULT_EVENT,
                session_id="session-a",
                data=policy_audit_intent_payload(intent),
            )
        )

    with pytest.raises(PolicyAuditLedgerError, match=POLICY_AUDIT_RESULT_EVENT):
        policy_audit_result_from_event(
            SimpleNamespace(
                event_type=POLICY_AUDIT_INTENT_EVENT,
                session_id="session-a",
                data=policy_audit_result_payload(result),
            )
        )

    with pytest.raises(PolicyAuditLedgerError, match="session_id"):
        policy_audit_intent_from_event(
            _intent_event(intent, session_id="session-b")
        )

    with pytest.raises(PolicyAuditLedgerError, match="session_id"):
        policy_audit_result_from_event(
            _result_event(result, session_id="session-b")
        )


def test_project_policy_audit_ledger_filters_orders_and_tracks_pending() -> None:
    first = _intent(audit_id="audit-first", action="trace_visibility_private")
    second = _intent(audit_id="audit-second", action="proof_bundle_create")
    result = _result(
        audit_id="audit-result-first",
        intent_audit_id="audit-first",
        status="succeeded",
    )
    other = _intent(session_id="session-b", audit_id="audit-other")

    projection = project_policy_audit_ledger(
        "session-a",
        [
            _intent_event(second, sequence=3),
            _intent_event(other, sequence=1, session_id="session-b"),
            _result_event(result, sequence=4),
            _intent_event(first, sequence=2),
        ],
    )

    assert [record.audit_id for record in projection.intents] == [
        "audit-first",
        "audit-second",
    ]
    assert [record.audit_id for record in projection.results] == [
        "audit-result-first"
    ]
    assert [record.audit_id for record in projection.pending_intents] == [
        "audit-second"
    ]


def test_project_policy_audit_ledger_rejects_duplicates_and_orphan_results() -> None:
    intent = _intent()

    with pytest.raises(PolicyAuditLedgerError, match="duplicate policy audit intent"):
        project_policy_audit_ledger(
            "session-a",
            [
                _intent_event(intent, sequence=1),
                _intent_event(intent, sequence=2),
            ],
        )

    with pytest.raises(PolicyAuditLedgerError, match="duplicate policy audit result"):
        project_policy_audit_results(
            "session-a",
            [
                _result_event(_result(audit_id="result-a"), sequence=1),
                _result_event(_result(audit_id="result-a"), sequence=2),
            ],
        )

    with pytest.raises(PolicyAuditLedgerError, match="duplicate policy audit result"):
        project_policy_audit_results(
            "session-a",
            [
                _result_event(
                    _result(
                        audit_id="result-a",
                        intent_audit_id="audit-share-public",
                    ),
                    sequence=1,
                ),
                _result_event(
                    _result(
                        audit_id="result-b",
                        intent_audit_id="audit-share-public",
                    ),
                    sequence=2,
                ),
            ],
        )

    with pytest.raises(PolicyAuditLedgerError, match="unknown intent_audit_id"):
        project_policy_audit_ledger(
            "session-a",
            [
                _result_event(
                    _result(intent_audit_id="missing-intent"),
                    sequence=1,
                ),
            ],
        )


def test_policy_audit_intent_record_rejects_duplicate_refs() -> None:
    with pytest.raises(ValueError, match="duplicate evidence_ids"):
        _intent(evidence_ids=["evidence-1", "evidence-1"])


def test_redacted_policy_audit_payloads_scrub_secrets() -> None:
    secret = "hf_auditsecret123456789"

    intent_payload, intent_status = redacted_policy_audit_intent_payload(
        _intent(
            destination_repo=f"user/ml-junior-sessions?token={secret}",
            rollback_guidance=f"Authorization: Bearer {secret}",
            metadata={"token": secret},
            redaction_status="none",
        )
    )
    result_payload, result_status = redacted_policy_audit_result_payload(
        _result(
            result_ref=f"hf://datasets/user/ml-junior-sessions?token={secret}",
            error_summary=f"Authorization: Bearer {secret}",
            metadata={"token": secret},
            redaction_status="none",
        )
    )

    assert intent_status == "redacted"
    assert result_status == "redacted"
    assert secret not in repr(intent_payload)
    assert secret not in repr(result_payload)
    assert "[REDACTED]" in intent_payload["rollback_guidance"]
    assert "[REDACTED]" in result_payload["error_summary"]


def test_build_share_traces_public_intent_and_result_records() -> None:
    contract = build_policy_audit_contract("/share-traces", "public")

    intent = build_policy_audit_intent_record(
        contract,
        session_id=" session-a ",
        audit_id=" audit-share-public ",
        actor=" human-review ",
        approval_id=" approval-1 ",
        target_ref=" traces/session-a ",
        source_event_sequence=8,
        created_at=" 2026-05-02T10:10:00+00:00 ",
        fields={
            "destination_repo": " user/ml-junior-sessions ",
            "owner_namespace": " user ",
            "dataset_card_warning_ack": True,
            "revocation_guidance": " Flip the dataset private. ",
        },
        request_metadata={"ui_surface": "approval-center"},
        correlation_id="share-public-1",
    )
    result = build_policy_audit_result_record(
        contract,
        session_id=" session-a ",
        audit_id=" audit-result-share-public ",
        intent_audit_id=intent.audit_id,
        status="succeeded",
        source_event_sequence=9,
        result_ref=" hf://datasets/user/ml-junior-sessions ",
        checked_at=" 2026-05-02T10:11:00+00:00 ",
        fields={
            "destination_repo": " user/ml-junior-sessions ",
            "owner_namespace": " user ",
        },
        request_metadata={"ui_surface": "approval-center"},
        correlation_id="share-public-1",
    )

    assert intent.session_id == "session-a"
    assert intent.audit_id == "audit-share-public"
    assert intent.command == "/share-traces"
    assert intent.action == "trace_visibility_public"
    assert intent.approval_id == "approval-1"
    assert intent.privacy_class == "sensitive"
    assert intent.visibility == "public"
    assert intent.metadata["contract"]["risk"] == "critical"
    assert intent.metadata["contract"]["approval_title"] == (
        "Publish trace dataset publicly"
    )
    assert intent.metadata["request"] == {"ui_surface": "approval-center"}
    assert intent.metadata["correlation_id"] == "share-public-1"
    assert result.intent_audit_id == intent.audit_id
    assert result.visibility == "public"
    assert result.destination_repo == "user/ml-junior-sessions"


def test_build_policy_audit_records_reject_status_contract() -> None:
    contract = build_policy_audit_contract("/share-traces")

    with pytest.raises(PolicyAuditLedgerError, match="does not require audit"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-status",
            actor="human-review",
            correlation_id="status-1",
        )

    with pytest.raises(PolicyAuditLedgerError, match="does not require audit"):
        build_policy_audit_result_record(
            contract,
            session_id="session-a",
            audit_id="audit-result-status",
            intent_audit_id="audit-status",
            status="succeeded",
            correlation_id="status-1",
        )


def test_build_ledger_verify_records_require_contract_fields() -> None:
    contract = build_policy_audit_contract("/ledger verify", "proof-report")

    with pytest.raises(PolicyAuditLedgerError, match="verifier_id"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-ledger-verify",
            actor="human-review",
            correlation_id="ledger-1",
        )

    intent = build_policy_audit_intent_record(
        contract,
        session_id="session-a",
        audit_id="audit-ledger-verify",
        actor="human-review",
        fields={"verifier_id": "verifier-local"},
        correlation_id="ledger-1",
    )

    with pytest.raises(PolicyAuditLedgerError, match="verdict"):
        build_policy_audit_result_record(
            contract,
            session_id="session-a",
            audit_id="audit-result-ledger-verify",
            intent_audit_id=intent.audit_id,
            status="succeeded",
            checked_at="2026-05-02T10:12:00+00:00",
            fields={"verifier_id": "verifier-local"},
            correlation_id="ledger-1",
        )

    result = build_policy_audit_result_record(
        contract,
        session_id="session-a",
        audit_id="audit-result-ledger-verify",
        intent_audit_id=intent.audit_id,
        status="succeeded",
        checked_at="2026-05-02T10:12:00+00:00",
        fields={
            "verifier_id": "verifier-local",
            "verdict": "passed",
        },
        correlation_id="ledger-1",
    )

    assert intent.target_ref == "proof-report"
    assert intent.verifier_id == "verifier-local"
    assert result.verifier_id == "verifier-local"
    assert result.verdict == "passed"


def test_build_proof_bundle_intent_requires_approval_and_bundle_fields() -> None:
    contract = build_policy_audit_contract("/proof bundle", "run-gpqa")

    with pytest.raises(PolicyAuditLedgerError, match="approval_id"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-proof",
            actor="human-review",
            correlation_id="proof-1",
        )

    with pytest.raises(PolicyAuditLedgerError, match="bundle_id"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-proof",
            actor="human-review",
            approval_id="approval-1",
            correlation_id="proof-1",
        )

    intent = build_policy_audit_intent_record(
        contract,
        session_id="session-a",
        audit_id="audit-proof",
        actor="human-review",
        approval_id="approval-1",
        fields={
            "bundle_id": "proof-run-gpqa",
            "manifest_checksum": "sha256:abc123",
        },
        correlation_id="proof-1",
    )

    assert intent.target_ref == "run-gpqa"
    assert intent.bundle_id == "proof-run-gpqa"
    assert intent.manifest_checksum == "sha256:abc123"
    assert intent.metadata["contract"]["credential_usage"] == ["signing_key"]


def test_build_policy_audit_records_reject_unknown_and_protected_fields() -> None:
    contract = build_policy_audit_contract("/share-traces", "private")

    with pytest.raises(PolicyAuditLedgerError, match="cannot override: command"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-private",
            actor="human-review",
            approval_id="approval-1",
            fields={
                "command": "/memory",
                "destination_repo": "user/ml-junior-sessions",
                "owner_namespace": "user",
            },
            correlation_id="private-1",
        )

    with pytest.raises(ValueError, match="unknown"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-private",
            actor="human-review",
            approval_id="approval-1",
            fields={
                "destination_repo": "user/ml-junior-sessions",
                "owner_namespace": "user",
                "unknown": "nope",
            },
            correlation_id="private-1",
        )


def test_build_policy_audit_records_require_correlation_id() -> None:
    contract = build_policy_audit_contract("/ledger verify", "proof-report")

    with pytest.raises(PolicyAuditLedgerError, match="correlation_id"):
        build_policy_audit_intent_record(
            contract,
            session_id="session-a",
            audit_id="audit-ledger",
            actor="human-review",
            fields={"verifier_id": "verifier-local"},
        )


def test_policy_audit_intent_event_draft_validates_through_agent_event() -> None:
    contract = build_policy_audit_contract("/share-traces", "public")

    draft = build_policy_audit_intent_event_draft(
        contract,
        PolicyAuditIntentMetadata(
            session_id=" session-a ",
            audit_id=" audit-share-public ",
            actor=" human-review ",
            source_event_sequence=8,
            created_at=" 2026-05-02T10:10:00+00:00 ",
            correlation_id="share-public-1",
            approval_id=" approval-1 ",
            target_ref=" traces/session-a ",
            destination_repo=" user/ml-junior-sessions ",
            owner_namespace=" user ",
            dataset_card_warning_ack=True,
            revocation_guidance=" Flip the dataset private. ",
            metadata={"surface": "approval-center"},
        ),
    )
    event = AgentEvent(
        session_id="session-a",
        sequence=20,
        event_type=draft.event_type,
        data=draft.payload,
    )

    assert draft.event_type == POLICY_AUDIT_INTENT_EVENT
    assert draft.redaction_status == "redacted"
    assert event.data["audit_id"] == "audit-share-public"
    assert event.data["metadata"]["contract"]["risk"] == "critical"
    assert event.data["metadata"]["correlation_id"] == "share-public-1"


def test_policy_audit_result_event_draft_correlates_and_projects() -> None:
    contract = build_policy_audit_contract("/ledger verify", "proof-report")
    intent_draft = build_policy_audit_intent_event_draft(
        contract,
        PolicyAuditIntentMetadata(
            session_id="session-a",
            audit_id="audit-ledger",
            actor="human-review",
            source_event_sequence=8,
            created_at="2026-05-02T10:10:00+00:00",
            correlation_id="ledger-1",
            verifier_id="verifier-local",
        ),
    )
    result_draft = build_policy_audit_result_event_draft(
        contract,
        intent_payload=intent_draft.payload,
        metadata=PolicyAuditResultMetadata(
            session_id="session-a",
            audit_id="audit-result-ledger",
            source_event_sequence=9,
            status="succeeded",
            created_at="2026-05-02T10:11:01+00:00",
            correlation_id="ledger-1",
            verdict="passed",
            checked_at="2026-05-02T10:11:00+00:00",
        ),
    )
    pending_projection = project_policy_audit_ledger(
        "session-a",
        [
            AgentEvent(
                id="event-1",
                session_id="session-a",
                sequence=1,
                event_type=intent_draft.event_type,
                data=intent_draft.payload,
            )
        ],
    )
    completed_projection = project_policy_audit_ledger(
        "session-a",
        [
            AgentEvent(
                id="event-1",
                session_id="session-a",
                sequence=1,
                event_type=intent_draft.event_type,
                data=intent_draft.payload,
            ),
            AgentEvent(
                id="event-2",
                session_id="session-a",
                sequence=2,
                event_type=result_draft.event_type,
                data=result_draft.payload,
            ),
        ],
    )

    assert result_draft.event_type == POLICY_AUDIT_RESULT_EVENT
    assert result_draft.payload["intent_audit_id"] == "audit-ledger"
    assert result_draft.payload["verdict"] == "passed"
    assert [record.audit_id for record in pending_projection.pending_intents] == [
        "audit-ledger"
    ]
    assert completed_projection.pending_intents == []


def test_policy_audit_result_event_draft_rejects_correlation_mismatch() -> None:
    contract = build_policy_audit_contract("/ledger verify", "proof-report")
    intent_draft = build_policy_audit_intent_event_draft(
        contract,
        PolicyAuditIntentMetadata(
            session_id="session-a",
            audit_id="audit-ledger",
            actor="human-review",
            source_event_sequence=8,
            created_at="2026-05-02T10:10:00+00:00",
            correlation_id="ledger-1",
            verifier_id="verifier-local",
        ),
    )

    with pytest.raises(PolicyAuditLedgerError, match="correlation_id"):
        build_policy_audit_result_event_draft(
            contract,
            intent_payload=intent_draft.payload,
            metadata=PolicyAuditResultMetadata(
                session_id="session-a",
                audit_id="audit-result-ledger",
                source_event_sequence=9,
                status="succeeded",
                created_at="2026-05-02T10:11:01+00:00",
                correlation_id="ledger-2",
                verdict="passed",
                checked_at="2026-05-02T10:11:00+00:00",
            ),
        )


def test_policy_audit_agent_event_builder_wraps_validated_redacted_envelope() -> None:
    secret = "hf_auditsecret123456789"
    raw_payload = policy_audit_intent_payload(
        _intent(
            rollback_guidance=f"Authorization: Bearer {secret}",
            metadata={"token": secret},
            redaction_status="none",
        )
    )

    event = build_policy_audit_agent_event(
        PolicyAuditEventDraft(
            event_type=POLICY_AUDIT_INTENT_EVENT,
            payload=raw_payload,
            redaction_status="none",
        ),
        PolicyAuditEventEnvelopeMetadata(
            sequence=7,
            event_id="policy-event-7",
            timestamp=datetime(2026, 5, 2, 10, 12, 0, tzinfo=timezone.utc),
            schema_version=2,
        ),
    )

    assert isinstance(event, AgentEvent)
    assert event.id == "policy-event-7"
    assert event.session_id == "session-a"
    assert event.sequence == 7
    assert event.schema_version == 2
    assert event.event_type == POLICY_AUDIT_INTENT_EVENT
    assert event.redaction_status == "redacted"
    assert event.data["redaction_status"] == "redacted"
    assert secret not in repr(event.data)


def test_policy_audit_agent_event_builder_fails_closed_on_bad_envelope() -> None:
    draft = PolicyAuditEventDraft(
        event_type=POLICY_AUDIT_INTENT_EVENT,
        payload=policy_audit_intent_payload(_intent()),
        redaction_status="redacted",
    )

    with pytest.raises(ValueError, match="greater than or equal to 1"):
        build_policy_audit_agent_event(
            draft,
            PolicyAuditEventEnvelopeMetadata(sequence=0),
        )

    with pytest.raises(PolicyAuditLedgerError, match="session_id"):
        build_policy_audit_agent_event(
            PolicyAuditEventDraft(
                event_type=POLICY_AUDIT_INTENT_EVENT,
                payload={"audit_id": "audit-missing-session"},
                redaction_status="redacted",
            ),
            PolicyAuditEventEnvelopeMetadata(sequence=1),
        )

    with pytest.raises(PolicyAuditLedgerError, match="unsupported policy audit"):
        build_policy_audit_agent_event(
            PolicyAuditEventDraft(
                event_type="tool.call",  # type: ignore[arg-type]
                payload=policy_audit_intent_payload(_intent()),
                redaction_status="redacted",
            ),
            PolicyAuditEventEnvelopeMetadata(sequence=1),
        )


def test_policy_audit_intent_and_result_agent_event_builders_project() -> None:
    contract = build_policy_audit_contract("/share-traces", "public")
    intent_draft = build_policy_audit_intent_event_draft(
        contract,
        PolicyAuditIntentMetadata(
            session_id="session-a",
            audit_id="audit-share-public",
            actor="human-review",
            source_event_sequence=8,
            created_at="2026-05-02T10:10:00+00:00",
            correlation_id="share-public-1",
            approval_id="approval-1",
            target_ref="traces/session-a",
            destination_repo="user/ml-junior-sessions",
            owner_namespace="user",
            dataset_card_warning_ack=True,
            revocation_guidance="Flip the dataset private.",
        ),
    )
    result_draft = build_policy_audit_result_event_draft(
        contract,
        intent_payload=intent_draft.payload,
        metadata=PolicyAuditResultMetadata(
            session_id="session-a",
            audit_id="audit-result-share-public",
            source_event_sequence=12,
            status="succeeded",
            created_at="2026-05-02T10:11:01+00:00",
            correlation_id="share-public-1",
            result_ref="hf://datasets/user/ml-junior-sessions",
            destination_repo="user/ml-junior-sessions",
            owner_namespace="user",
            checked_at="2026-05-02T10:11:00+00:00",
        ),
    )
    intent_event = build_policy_audit_intent_agent_event(
        intent_draft,
        PolicyAuditEventEnvelopeMetadata(sequence=11, event_id="policy-intent-11"),
    )
    result_event = build_policy_audit_result_agent_event(
        result_draft,
        PolicyAuditEventEnvelopeMetadata(
            sequence=12,
            event_id="policy-result-12",
        ),
    )

    projection = project_policy_audit_ledger(
        "session-a",
        [result_event, intent_event],
    )

    assert intent_event.redaction_status == "redacted"
    assert result_event.redaction_status == "redacted"
    assert intent_event.event_type == POLICY_AUDIT_INTENT_EVENT
    assert result_event.event_type == POLICY_AUDIT_RESULT_EVENT
    assert [record.audit_id for record in projection.intents] == [
        "audit-share-public"
    ]
    assert [record.audit_id for record in projection.results] == [
        "audit-result-share-public"
    ]
    assert projection.pending_intents == []


def _make_memory_store() -> SQLiteEventStore:
    return SQLiteEventStore(":memory:")


def test_append_adapter_persists_intent_event() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    intent = _intent()
    event = _intent_event(intent, sequence=1)

    stored = adapter.append(event)

    assert stored.session_id == event.session_id
    assert stored.sequence == event.sequence
    assert stored.event_type == POLICY_AUDIT_INTENT_EVENT
    # clean payload without secrets stays none; adapter preserves redacted_copy behavior
    assert stored.redaction_status == "none"

    replayed = store.replay("session-a")
    assert len(replayed) == 1
    assert replayed[0].sequence == 1
    assert replayed[0].event_type == POLICY_AUDIT_INTENT_EVENT


def test_append_adapter_persists_result_event() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    result = _result()
    event = _result_event(result, sequence=2)

    stored = adapter.append(event)

    assert stored.session_id == event.session_id
    assert stored.sequence == event.sequence
    assert stored.event_type == POLICY_AUDIT_RESULT_EVENT

    replayed = store.replay("session-a")
    assert len(replayed) == 1
    assert replayed[0].sequence == 2


def test_append_adapter_redacts_before_persist() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)
    secret = "hf_supersecret_token_xyz"

    intent = _intent(
        rollback_guidance=f"Authorization: Bearer {secret}",
        redaction_status="none",
    )
    event = _intent_event(intent, sequence=1)
    assert event.redaction_status == "none"

    stored = adapter.append(event)

    # bearer-token rule triggers partial redaction for this payload shape
    assert stored.redaction_status in ("partial", "redacted")
    assert secret not in repr(stored.data)
    replayed = store.replay("session-a")
    assert secret not in repr(replayed[0].data)


def test_append_adapter_preserves_ordering_evidence() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    intent = _intent(audit_id="audit-first")
    result = _result(audit_id="audit-result-first", intent_audit_id="audit-first")

    adapter.append(_intent_event(intent, sequence=1))
    adapter.append(_result_event(result, sequence=2))

    replayed = store.replay("session-a")
    assert [e.sequence for e in replayed] == [1, 2]


def test_append_adapter_fails_closed_on_unsupported_event_type() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    bad_event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type="tool.call",
        data={},
    )

    with pytest.raises(PolicyAuditLedgerError, match="unsupported policy audit"):
        adapter.append(bad_event)

    assert store.replay("session-a") == []


def test_append_adapter_fails_closed_on_bad_sequence() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    # Bypass AgentEvent pydantic validation to test adapter-level sequence gate
    event = AgentEvent.model_construct(
        session_id="session-a",
        sequence=0,
        event_type=POLICY_AUDIT_INTENT_EVENT,
        data=policy_audit_intent_payload(_intent()),
    )

    with pytest.raises(ValueError, match="sequence must be greater than or equal to 1"):
        adapter.append(event)

    assert store.replay("session-a") == []


def test_append_adapter_fails_closed_on_missing_session_id() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    event = AgentEvent(
        session_id="",
        sequence=1,
        event_type=POLICY_AUDIT_INTENT_EVENT,
        data=policy_audit_intent_payload(_intent()),
    )

    with pytest.raises(PolicyAuditLedgerError, match="missing session_id"):
        adapter.append(event)

    assert store.replay("session-a") == []


def test_append_adapter_is_inert_without_explicit_call() -> None:
    store = _make_memory_store()
    adapter = PolicyAuditAppendAdapter(store.append)

    assert store.replay("session-a") == []
    # adapter exists but was never called
    assert store.replay("session-a") == []
