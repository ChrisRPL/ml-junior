from __future__ import annotations

import pytest

from agent.core.policy import RiskLevel
from agent.core.policy_audit_contracts import (
    POLICY_AUDIT_INTENT_EVENT,
    POLICY_AUDIT_RESULT_EVENT,
    PolicyAuditContractError,
    build_policy_audit_contract,
)


def test_share_traces_public_contract_requires_approval_and_audit() -> None:
    contract = build_policy_audit_contract("/share-traces", "public")

    assert contract.command == "/share-traces"
    assert contract.action == "trace_visibility_public"
    assert contract.risk is RiskLevel.CRITICAL
    assert contract.requires_approval is True
    assert contract.audit_required is True
    assert contract.visibility_default == "public"
    assert "hf_token" in contract.credential_usage
    assert "destination_repo" in contract.audit_required_fields
    assert "owner_namespace" in contract.audit_required_fields
    assert any("best-effort" in item.lower() for item in contract.redaction_requirements)
    assert any("authenticated HF identity" in item for item in contract.preconditions)

    metadata = contract.approval_metadata()

    assert metadata["risk"] == "critical"
    assert metadata["audit"]["required"] is True
    assert metadata["audit"]["intent_event_type"] == POLICY_AUDIT_INTENT_EVENT
    assert metadata["audit"]["result_event_type"] == POLICY_AUDIT_RESULT_EVENT
    assert metadata["audit"]["defaults"]["visibility"] == "public"
    assert metadata["privacy_default"] == "private"


def test_share_traces_private_contract_still_records_remote_mutation() -> None:
    contract = build_policy_audit_contract("/share-traces", "private")

    assert contract.risk is RiskLevel.HIGH
    assert contract.requires_approval is True
    assert contract.audit_required is True
    assert contract.visibility_default == "private"
    assert contract.side_effects == ("remote_hf_dataset_visibility_change",)
    assert contract.audit_defaults["privacy_class"] == "private"
    assert "approval_id" in contract.audit_required_fields


def test_share_traces_status_contract_is_read_only() -> None:
    contract = build_policy_audit_contract("/share-traces")

    assert contract.action == "trace_visibility_status"
    assert contract.risk is RiskLevel.READ_ONLY
    assert contract.requires_approval is False
    assert contract.audit_required is False
    assert contract.audit_intent_event_type is None
    assert contract.side_effects == ()


def test_ledger_verify_contract_is_read_only_but_auditable() -> None:
    contract = build_policy_audit_contract("/ledger verify", "proof-report")

    assert contract.action == "ledger_integrity_verify"
    assert contract.risk is RiskLevel.LOW
    assert contract.requires_approval is False
    assert contract.audit_required is True
    assert contract.audit_defaults["target_ref"] == "proof-report"
    assert "verdict" in contract.audit_required_fields
    assert "verifier_id" in contract.audit_required_fields
    assert any("artifact blobs" in item for item in contract.redaction_requirements)


def test_proof_bundle_contract_requires_approval_without_remote_export() -> None:
    contract = build_policy_audit_contract("/proof bundle", "run-gpqa")

    assert contract.action == "proof_bundle_create"
    assert contract.risk is RiskLevel.HIGH
    assert contract.requires_approval is True
    assert contract.audit_required is True
    assert "local_write" in contract.side_effects
    assert "signing_key" in contract.credential_usage
    assert contract.audit_defaults["target_ref"] == "run-gpqa"
    assert "manifest_checksum" in contract.audit_required_fields
    assert any("separate approval" in item for item in contract.notes)


def test_policy_audit_contract_rejects_unknown_commands_and_args() -> None:
    with pytest.raises(PolicyAuditContractError, match="No policy/audit contract"):
        build_policy_audit_contract("/memory")

    with pytest.raises(PolicyAuditContractError, match="Usage"):
        build_policy_audit_contract("/share-traces", "friends")
