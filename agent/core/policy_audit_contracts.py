"""Pure policy, approval, and audit contracts for trust-sensitive commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent.core.policy import RiskLevel


POLICY_AUDIT_INTENT_EVENT = "policy.audit_intent_recorded"
POLICY_AUDIT_RESULT_EVENT = "policy.audit_result_recorded"


class PolicyAuditContractError(ValueError):
    """Raised when no policy/audit contract exists for a requested action."""


@dataclass(frozen=True)
class PolicyAuditContract:
    """Contract required before a planned trust-sensitive command can execute."""

    command: str
    action: str
    risk: RiskLevel
    requires_approval: bool
    audit_required: bool
    approval_title: str
    approval_body: str
    contract_version: str = "1"
    side_effects: tuple[str, ...] = ()
    rollback: str = "None needed."
    budget_impact: str = "None."
    credential_usage: tuple[str, ...] = ()
    privacy_default: str = "private"
    visibility_default: str | None = None
    audit_intent_event_type: str | None = POLICY_AUDIT_INTENT_EVENT
    audit_result_event_type: str | None = POLICY_AUDIT_RESULT_EVENT
    audit_required_fields: tuple[str, ...] = ()
    redaction_requirements: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    audit_defaults: dict[str, Any] = field(default_factory=dict)

    def approval_metadata(self) -> dict[str, Any]:
        """Return user-facing approval metadata without enabling execution."""

        return {
            "risk": self.risk.value,
            "contract_version": self.contract_version,
            "side_effects": list(self.side_effects),
            "rollback": self.rollback,
            "budget_impact": self.budget_impact,
            "credential_usage": list(self.credential_usage),
            "reason": self.approval_body,
            "audit": {
                "required": self.audit_required,
                "intent_event_type": self.audit_intent_event_type,
                "result_event_type": self.audit_result_event_type,
                "required_fields": list(self.audit_required_fields),
                "defaults": dict(self.audit_defaults),
            },
            "privacy_default": self.privacy_default,
            "visibility_default": self.visibility_default,
            "redaction_requirements": list(self.redaction_requirements),
            "preconditions": list(self.preconditions),
        }


def build_policy_audit_contract(
    command: str,
    arguments: str = "",
) -> PolicyAuditContract:
    """Build the inert policy/audit contract for a planned trusted action."""

    command = _normalize_command(command)
    arguments = arguments.strip()
    if command == "/share-traces":
        return _share_traces_contract(arguments)
    if command == "/ledger verify":
        return _ledger_verify_contract(arguments)
    if command == "/proof bundle":
        return _proof_bundle_contract(arguments)
    raise PolicyAuditContractError(f"No policy/audit contract for command: {command}")


def _share_traces_contract(arguments: str) -> PolicyAuditContract:
    risk_level = _risk_level()
    visibility = arguments.strip().lower()
    if visibility in {"", "status"}:
        return PolicyAuditContract(
            command="/share-traces",
            action="trace_visibility_status",
            risk=risk_level.READ_ONLY,
            requires_approval=False,
            audit_required=False,
            approval_title="Show trace sharing status",
            approval_body="Read current trace sharing configuration only.",
            audit_intent_event_type=None,
            audit_result_event_type=None,
            audit_required_fields=(),
            redaction_requirements=(
                "Redact local paths, tokens, private URLs, and dataset row samples.",
            ),
            preconditions=("Trace-sharing config source is available.",),
        )
    if visibility not in {"public", "private"}:
        raise PolicyAuditContractError(
            "Usage: /share-traces [public|private]"
        )

    public = visibility == "public"
    return PolicyAuditContract(
        command="/share-traces",
        action=f"trace_visibility_{visibility}",
        risk=risk_level.CRITICAL if public else risk_level.HIGH,
        requires_approval=True,
        audit_required=True,
        approval_title=(
            "Publish trace dataset publicly"
            if public
            else "Set trace dataset private"
        ),
        approval_body=(
            "This changes Hugging Face Hub trace dataset visibility. Public "
            "traces can expose prompts, tool outputs, file paths, private task "
            "context, or credentials missed by best-effort redaction."
            if public
            else "This changes Hugging Face Hub trace dataset visibility back "
            "to private and should record who requested the remote mutation."
        ),
        side_effects=("remote_hf_dataset_visibility_change",),
        rollback=(
            "Run /share-traces private and verify Hub visibility."
            if public
            else "Run /share-traces public only after a new explicit approval."
        ),
        budget_impact="May create or update persistent Hugging Face Hub metadata.",
        credential_usage=("hf_token",),
        privacy_default="private",
        visibility_default=visibility,
        audit_required_fields=(
            "actor",
            "session_id",
            "command",
            "action",
            "destination_repo",
            "owner_namespace",
            "visibility",
            "privacy_class",
            "redaction_status",
            "approval_id",
            "rollback_guidance",
        ),
        redaction_requirements=(
            "Best-effort secret redaction is mandatory before any public visibility.",
            "Dataset cards must warn that traces may still contain sensitive data.",
            "Do not include private dataset row samples in public trace payloads.",
            "Redact local user paths, private URLs, authorization headers, and tokens.",
        ),
        preconditions=(
            "Trace sharing is opt-in only.",
            "Destination repo namespace is derived from authenticated HF identity.",
            "Do not conflate OAuth subject or internal user_id with HF username.",
            "A private destination exists before any public visibility change.",
        ),
        notes=(
            "Upstream ml-intern is a reference pattern, not a wholesale port.",
            "The direct upstream visibility handler must be wrapped in policy, "
            "approval, and durable audit first.",
        ),
        audit_defaults={
            "privacy_class": "sensitive" if public else "private",
            "redaction_status": "redacted",
            "visibility": visibility,
        },
    )


def _ledger_verify_contract(arguments: str) -> PolicyAuditContract:
    risk_level = _risk_level()
    target = arguments.strip() or "<bundle>"
    return PolicyAuditContract(
        command="/ledger verify",
        action="ledger_integrity_verify",
        risk=risk_level.LOW,
        requires_approval=False,
        audit_required=True,
        approval_title="Verify ledger bundle",
        approval_body=(
            "Verification is read-only when it only checks a local bundle, but "
            "any persisted or shared verdict must be auditable."
        ),
        side_effects=(),
        rollback="Delete or supersede an incorrect verifier verdict record.",
        budget_impact="None.",
        credential_usage=(),
        privacy_default="private",
        visibility_default=None,
        audit_required_fields=(
            "actor",
            "session_id",
            "command",
            "action",
            "target_ref",
            "verifier_id",
            "verdict",
            "checked_at",
            "redaction_status",
        ),
        redaction_requirements=(
            "Do not print artifact blobs, log bodies, or full payload values.",
            "Redact local paths and private URLs in verifier output.",
        ),
        preconditions=(
            "Target bundle or ledger ref is explicit.",
            "Verification result schema exists before persisting verdicts.",
        ),
        audit_defaults={
            "target_ref": target,
            "privacy_class": "private",
            "redaction_status": "redacted",
        },
    )


def _proof_bundle_contract(arguments: str) -> PolicyAuditContract:
    risk_level = _risk_level()
    target = arguments.strip() or "<run>"
    return PolicyAuditContract(
        command="/proof bundle",
        action="proof_bundle_create",
        risk=risk_level.HIGH,
        requires_approval=True,
        audit_required=True,
        approval_title="Create proof bundle",
        approval_body=(
            "Creating a proof bundle can write provenance manifests and may "
            "include signed or exportable evidence references. The bundle must "
            "not imply verification unless the verifier evidence is present."
        ),
        side_effects=("local_write", "provenance_manifest_create"),
        rollback="Delete the bundle and emit a superseding audit record.",
        budget_impact="None unless remote export is separately approved.",
        credential_usage=("signing_key",),
        privacy_default="private",
        visibility_default=None,
        audit_required_fields=(
            "actor",
            "session_id",
            "command",
            "action",
            "target_ref",
            "bundle_id",
            "manifest_checksum",
            "privacy_class",
            "redaction_status",
            "approval_id",
            "rollback_guidance",
        ),
        redaction_requirements=(
            "Bundle manifests include refs and checksums, not secret payload bodies.",
            "Artifact/log blobs require separate redacted export approval.",
            "Private URLs and local paths must be redacted or replaced with stable refs.",
        ),
        preconditions=(
            "Decision/evidence/proof projection exists for the target.",
            "Signing/export policy is explicit before any remote publication.",
        ),
        notes=(
            "Local bundle creation and remote trace sharing are separate approvals.",
        ),
        audit_defaults={
            "target_ref": target,
            "privacy_class": "private",
            "redaction_status": "redacted",
        },
    )


def _normalize_command(command: str) -> str:
    return " ".join(command.strip().lower().split())


def _risk_level():
    from agent.core.policy import RiskLevel

    return RiskLevel
