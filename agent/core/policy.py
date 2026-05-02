"""Tool approval policy decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from agent.core.hf_compute_risk import HfComputeRisk, assess_hf_compute_risk
from agent.tools.local_guardrails import evaluate_local_policy_failure


class RiskLevel(str, Enum):
    """Coarse risk levels for tool execution."""

    READ_ONLY = "read_only"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class ToolMetadata:
    """Optional metadata supplied by tool registries or MCP adapters."""

    source: str | None = None
    read_only: bool | None = None
    local: bool | None = None
    risk: RiskLevel | str | None = None
    side_effects: list[str] = field(default_factory=list)
    rollback: str | None = None
    budget_impact: str | None = None
    credential_usage: list[str] = field(default_factory=list)
    reason: str | None = None
    mcp_origin: str | None = None
    mcp_server: str | None = None
    mcp_tool: str | None = None
    mcp_trusted: bool | None = None
    mcp_forwarded_hf_token: bool | None = None


@dataclass
class PolicyDecision:
    """Approval decision plus user-facing risk metadata."""

    requires_approval: bool
    risk: RiskLevel | str
    allowed: bool = True
    side_effects: list[str] = field(default_factory=list)
    rollback: str = "None needed."
    budget_impact: str = "None."
    credential_usage: list[str] = field(default_factory=list)
    reason: str = ""
    code: str | None = None

    @property
    def needs_approval(self) -> bool:
        """Compatibility alias for older approval terminology."""

        return self.requires_approval

    @property
    def denied(self) -> bool:
        return not self.allowed

    def approval_metadata(self) -> dict[str, Any]:
        return {
            "risk": self.risk.value if isinstance(self.risk, RiskLevel) else str(self.risk),
            "side_effects": list(self.side_effects),
            "rollback": self.rollback,
            "budget_impact": self.budget_impact,
            "credential_usage": list(self.credential_usage),
            "reason": self.reason,
        }


class PolicyEngine:
    """Evaluate tool calls against the current approval policy."""

    JOB_CREATE_OPERATIONS = {"run", "uv", "scheduled run", "scheduled uv"}
    HF_PRIVATE_APPROVAL_OPERATIONS = {"create_repo"}
    HF_REPO_FILE_APPROVAL_OPERATIONS = {"upload", "delete"}
    HF_REPO_GIT_READ_OPERATIONS = {"list_refs", "list_prs", "get_pr"}
    HF_REPO_GIT_APPROVAL_OPERATIONS = {
        "create_branch",
        "delete_branch",
        "create_tag",
        "delete_tag",
        "create_pr",
        "merge_pr",
        "close_pr",
        "comment_pr",
        "change_pr_status",
        "create_repo",
        "update_repo",
    }
    READ_ONLY_TOOLS = {
        "read",
        "research",
        "hf_papers",
        "hf_inspect_dataset",
        "explore_hf_docs",
        "fetch_hf_docs",
        "github_find_examples",
        "github_list_repos",
        "github_read_file",
    }
    FILE_WRITE_TOOLS = {"write", "edit"}

    @classmethod
    def evaluate(
        cls,
        tool_name: str,
        tool_args: dict[str, Any],
        config: Any,
        metadata: ToolMetadata | None = None,
        **extra: Any,
    ) -> PolicyDecision:
        """Return the approval decision for a tool call.

        Approval booleans intentionally match ``agent_loop._needs_approval`` for
        existing tools. Risk fields give the UI more context without changing
        execution gates.
        """

        metadata = metadata or _metadata_from_router(tool_name, extra.get("tool_router"))

        args_valid, args_error = _validate_tool_args(tool_args)
        if not args_valid:
            return cls._with_metadata(
                PolicyDecision(
                    requires_approval=False,
                    risk=RiskLevel.UNKNOWN,
                    reason=args_error or "Malformed tool arguments; validation handles the error.",
                ),
                metadata,
            )

        decision = cls._evaluate_valid_args(tool_name, tool_args, config, metadata)
        decision = cls._with_metadata(decision, metadata)

        if decision.allowed and _auto_approval_enabled(config):
            decision.requires_approval = False
            decision.reason = f"Auto-approved by yolo/autonomy mode. {decision.reason}".strip()

        return decision

    @classmethod
    def _evaluate_valid_args(
        cls,
        tool_name: str,
        tool_args: dict[str, Any],
        config: Any,
        metadata: ToolMetadata,
    ) -> PolicyDecision:
        if tool_name == "sandbox_create":
            return PolicyDecision(
                requires_approval=True,
                risk=RiskLevel.HIGH,
                side_effects=["Creates an isolated execution sandbox."],
                rollback="Stop or delete the sandbox.",
                budget_impact="May consume compute while running.",
                credential_usage=["hf_token"],
                reason="Creating a sandbox starts a new execution environment.",
            )

        if tool_name == "hf_jobs":
            return cls._evaluate_hf_jobs(tool_args, config)

        if tool_name == "hf_private_repos":
            return cls._evaluate_hf_private_repos(tool_args, config)

        if tool_name == "hf_repo_files":
            return cls._evaluate_hf_repo_files(tool_args)

        if tool_name == "hf_repo_git":
            return cls._evaluate_hf_repo_git(tool_args)

        if tool_name == "plan_tool":
            return PolicyDecision(
                requires_approval=False,
                risk=RiskLevel.LOW,
                side_effects=["agent_state"],
                rollback="Replace the plan with a later plan update.",
                budget_impact="None.",
                reason="Agent plan state update.",
            )

        local_policy_failure = evaluate_local_policy_failure(
            tool_name,
            tool_args,
            config=config,
            is_local_tool=metadata.local is True or metadata.source == "local",
        )
        if local_policy_failure is not None:
            return PolicyDecision(
                requires_approval=False,
                risk=RiskLevel(local_policy_failure.risk),
                allowed=False,
                side_effects=list(local_policy_failure.side_effects),
                rollback="None needed; command was not executed.",
                budget_impact="None.",
                credential_usage=list(local_policy_failure.credential_usage),
                reason=local_policy_failure.reason,
                code=local_policy_failure.code,
            )

        if tool_name in cls.READ_ONLY_TOOLS or metadata.read_only is True:
            return PolicyDecision(
                requires_approval=False,
                risk=RiskLevel.READ_ONLY,
                reason="Read-only tool call.",
            )

        if tool_name == "bash":
            return PolicyDecision(
                requires_approval=True,
                risk=RiskLevel.HIGH,
                side_effects=["local_exec"],
                rollback="Command-specific; inspect output and revert affected files if needed.",
                budget_impact="May consume local or sandbox CPU, disk, and network.",
                credential_usage=["local_system"],
                reason="Shell execution requires approval because it can mutate the environment.",
            )

        if tool_name in cls.FILE_WRITE_TOOLS:
            return PolicyDecision(
                requires_approval=True,
                risk=RiskLevel.MEDIUM,
                side_effects=["local_write"],
                rollback="Restore affected files from version control or backups.",
                budget_impact="None.",
                credential_usage=["local_filesystem"],
                reason="Filesystem writes require approval because they mutate project state.",
            )

        if metadata.source == "mcp":
            return PolicyDecision(
                requires_approval=True,
                risk=RiskLevel.UNKNOWN,
                side_effects=["Calls an external MCP server."],
                rollback="Tool-specific; inspect output and undo any side effects manually.",
                budget_impact="Unknown.",
                credential_usage=["mcp_server"],
                reason="MCP tools require approval unless a narrower policy is registered.",
            )

        return PolicyDecision(
            requires_approval=True,
            risk=RiskLevel.UNKNOWN,
            side_effects=["Unknown tool side effects."],
            rollback="Unknown.",
            budget_impact="Unknown.",
            reason="No approval rule matched; defaulting to approval required.",
        )

    @classmethod
    def _evaluate_hf_jobs(cls, tool_args: dict[str, Any], config: Any) -> PolicyDecision:
        compute_risk = assess_hf_compute_risk(tool_args)
        operation = compute_risk.operation
        if operation not in cls.JOB_CREATE_OPERATIONS:
            return PolicyDecision(
                requires_approval=False,
                risk=RiskLevel.READ_ONLY,
                budget_impact=compute_risk.budget_impact,
                credential_usage=["hf_token"],
                reason="Hugging Face job read/status operation.",
            )

        is_cpu_job = compute_risk.hardware_category == "cpu"
        requires_approval = True
        reason = _hf_jobs_reason(compute_risk)

        if is_cpu_job and not compute_risk.is_scheduled:
            requires_approval = _config_bool(config, "confirm_cpu_jobs", True)
            reason = (
                f"CPU job launch requires approval. {reason}"
                if requires_approval
                else f"CPU job approval disabled by confirm_cpu_jobs=false. {reason}"
            )

        return PolicyDecision(
            requires_approval=requires_approval,
            risk=RiskLevel(compute_risk.risk_tier),
            side_effects=["Starts or schedules a Hugging Face compute job."],
            rollback="Cancel the job or delete the scheduled job.",
            budget_impact=compute_risk.budget_impact,
            credential_usage=["hf_token"],
            reason=reason,
        )

    @classmethod
    def _evaluate_hf_private_repos(
        cls, tool_args: dict[str, Any], config: Any
    ) -> PolicyDecision:
        operation = tool_args.get("operation", "")
        if operation == "upload_file":
            requires_approval = not _config_bool(config, "auto_file_upload", False)
            return PolicyDecision(
                requires_approval=requires_approval,
                risk=RiskLevel.HIGH,
                side_effects=["Uploads file content to a Hugging Face repository."],
                rollback="Delete or overwrite the uploaded file.",
                budget_impact="None.",
                credential_usage=["hf_token"],
                reason=(
                    "Private repository file upload requires approval."
                    if requires_approval
                    else "File upload approval disabled by auto_file_upload=true."
                ),
            )

        if operation in cls.HF_PRIVATE_APPROVAL_OPERATIONS:
            return PolicyDecision(
                requires_approval=True,
                risk=RiskLevel.HIGH,
                side_effects=["Creates a Hugging Face repository."],
                rollback="Delete or archive the repository if needed.",
                budget_impact="May create persistent Hub storage.",
                credential_usage=["hf_token"],
                reason="Repository creation requires approval.",
            )

        return PolicyDecision(
            requires_approval=False,
            risk=RiskLevel.READ_ONLY,
            credential_usage=["hf_token"],
            reason="Private repository read/status operation.",
        )

    @classmethod
    def _evaluate_hf_repo_files(cls, tool_args: dict[str, Any]) -> PolicyDecision:
        operation = tool_args.get("operation", "")
        if operation not in cls.HF_REPO_FILE_APPROVAL_OPERATIONS:
            return PolicyDecision(
                requires_approval=False,
                risk=RiskLevel.READ_ONLY,
                credential_usage=["hf_token"],
                reason="Hugging Face repository file read/list operation.",
            )

        is_delete = operation == "delete"
        return PolicyDecision(
            requires_approval=True,
            risk=RiskLevel.HIGH,
            side_effects=[
                (
                    "Deletes files from a Hugging Face repository."
                    if is_delete
                    else "Uploads or overwrites files in a Hugging Face repository."
                )
            ],
            rollback=(
                "Restore deleted files from repository history."
                if is_delete
                else "Revert the commit or overwrite with previous content."
            ),
            budget_impact="May create persistent Hub storage." if not is_delete else "None.",
            credential_usage=["hf_token"],
            reason="Hugging Face repository file mutation requires approval.",
        )

    @classmethod
    def _evaluate_hf_repo_git(cls, tool_args: dict[str, Any]) -> PolicyDecision:
        operation = tool_args.get("operation", "")
        if operation in cls.HF_REPO_GIT_READ_OPERATIONS:
            return PolicyDecision(
                requires_approval=False,
                risk=RiskLevel.LOW,
                credential_usage=["hf_token"],
                reason="Hugging Face repository git operation does not require approval.",
            )

        return PolicyDecision(
            requires_approval=True,
            risk=RiskLevel.HIGH,
            side_effects=["Mutates Hugging Face repository refs, PRs, or settings."],
            rollback="Revert repository settings, recreate refs, or open a corrective PR.",
            budget_impact="May create persistent Hub storage." if operation == "create_repo" else "None.",
            credential_usage=["hf_token"],
            reason="Hugging Face repository git mutation requires approval.",
        )

    @staticmethod
    def _with_metadata(
        decision: PolicyDecision, metadata: ToolMetadata
    ) -> PolicyDecision:
        has_specific_metadata = (
            (
                bool(decision.side_effects)
                and decision.side_effects != ["Unknown tool side effects."]
            )
            or decision.rollback not in {"None needed.", "Unknown."}
            or decision.budget_impact not in {"None.", "Unknown."}
            or bool(decision.credential_usage)
        )
        fill_from_metadata = (
            decision.risk == RiskLevel.UNKNOWN and not has_specific_metadata
        )
        risk = _coerce_risk(metadata.risk)
        if risk is not None and fill_from_metadata:
            decision.risk = risk
        if metadata.side_effects and fill_from_metadata:
            decision.side_effects = list(metadata.side_effects)
        if metadata.rollback is not None and fill_from_metadata:
            decision.rollback = metadata.rollback
        if metadata.budget_impact is not None and fill_from_metadata:
            decision.budget_impact = metadata.budget_impact
        if metadata.credential_usage and not decision.credential_usage:
            decision.credential_usage = list(metadata.credential_usage)
        if metadata.reason is not None and not decision.reason:
            decision.reason = metadata.reason
        return decision


def _validate_tool_args(tool_args: Any) -> tuple[bool, str | None]:
    if not isinstance(tool_args, dict):
        return False, f"Tool call error: tool_args must be a dict, not {type(tool_args).__name__}."

    args = tool_args.get("args", {})
    if isinstance(args, str):
        return (
            False,
            f"Tool call error: 'args' must be a JSON object, not a string. You passed: {args!r}",
        )
    if not isinstance(args, dict) and args is not None:
        return (
            False,
            f"Tool call error: 'args' must be a JSON object. You passed type: {type(args).__name__}",
        )
    return True, None


def _metadata_from_router(tool_name: str, tool_router: Any | None) -> ToolMetadata:
    tools = getattr(tool_router, "tools", None)
    if isinstance(tools, dict):
        spec = tools.get(tool_name)
        if spec is not None and getattr(spec, "handler", None) is None:
            metadata = getattr(spec, "metadata", None)
            if isinstance(metadata, ToolMetadata):
                return metadata
            return ToolMetadata(source="mcp")
    return ToolMetadata()


def _auto_approval_enabled(config: Any) -> bool:
    if _config_bool(config, "yolo_mode", False):
        return True

    autonomy = _config_str(config, "autonomy", "")
    approval_policy = _config_str(config, "approval_policy", "")
    approval_mode = _config_str(config, "approval_mode", "")
    return any(
        value in {"auto", "autonomous", "full", "never", "unattended", "yolo"}
        for value in {autonomy, approval_policy, approval_mode}
    )


def _config_bool(config: Any, attr: str, default: bool) -> bool:
    if config is None:
        return default
    return bool(getattr(config, attr, default))


def _config_str(config: Any, attr: str, default: str) -> str:
    if config is None:
        return default
    value = getattr(config, attr, default)
    if value is None:
        return default
    return str(value).strip().lower()


def _hf_jobs_reason(compute_risk: HfComputeRisk) -> str:
    parts = [
        f"Hugging Face job launch risk: {compute_risk.hardware_category}",
        f"spend={compute_risk.spend_class}",
    ]
    if compute_risk.duration_estimate is not None:
        parts.append(
            f"duration={compute_risk.duration_estimate}"
            f" ({compute_risk.duration_source})"
        )
    if compute_risk.is_scheduled:
        parts.append("scheduled recurrence requires approval")
    if compute_risk.uncertainty_flags:
        parts.append(
            "uncertainty=" + ", ".join(compute_risk.uncertainty_flags)
        )
    return "; ".join(parts) + "."


def _coerce_risk(value: RiskLevel | str | None) -> RiskLevel | None:
    if value is None:
        return None
    if isinstance(value, RiskLevel):
        return value
    try:
        return RiskLevel(value)
    except ValueError:
        return RiskLevel.UNKNOWN
