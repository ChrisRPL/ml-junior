"""Policy engine approval behavior tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.config import Config
from agent.core.policy import PolicyEngine, RiskLevel, ToolMetadata


def config_for_policy(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "model_name": "test/model",
        "mcpServers": {},
        "save_sessions": False,
        "reasoning_effort": None,
    }
    values.update(overrides)
    return Config(**values)


@pytest.mark.parametrize(
    ("tool_name", "tool_args"),
    [
        ("read", {"path": "/tmp/file.py"}),
        ("hf_repo_files", {"operation": "list", "repo_id": "org/repo"}),
        ("hf_repo_files", {"operation": "read", "repo_id": "org/repo", "path": "README.md"}),
        ("hf_jobs", {"operation": "logs", "job_id": "abc"}),
    ],
)
def test_read_only_tools_do_not_require_approval(
    tool_name: str, tool_args: dict[str, Any]
) -> None:
    decision = PolicyEngine.evaluate(tool_name, tool_args, config_for_policy())

    assert decision.requires_approval is False
    assert decision.needs_approval is False
    assert decision.risk is RiskLevel.READ_ONLY
    assert decision.reason


@pytest.mark.parametrize("tool_name", ["bash", "write", "edit"])
def test_local_shell_and_write_tools_require_approval_with_metadata(
    tool_name: str,
) -> None:
    tool_args = {"command": "python --version"} if tool_name == "bash" else {
        "path": "/tmp/file.py",
        "content": "print('ok')",
    }

    decision = PolicyEngine.evaluate(tool_name, tool_args, config_for_policy())

    assert decision.requires_approval is True
    assert decision.risk in {RiskLevel.MEDIUM, RiskLevel.HIGH}
    assert decision.side_effects
    assert decision.rollback
    assert decision.budget_impact
    assert decision.credential_usage
    assert decision.reason


@pytest.mark.parametrize(
    ("operation", "side_effect"),
    [
        ("upload", "Uploads"),
        ("delete", "Deletes"),
    ],
)
def test_hf_repo_file_writes_require_approval(
    operation: str, side_effect: str
) -> None:
    decision = PolicyEngine.evaluate(
        "hf_repo_files",
        {"operation": operation, "repo_id": "org/repo", "path": "README.md"},
        config_for_policy(),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.HIGH
    assert decision.side_effects[0].startswith(side_effect)
    assert decision.rollback
    assert decision.budget_impact
    assert decision.credential_usage
    assert decision.reason


@pytest.mark.parametrize(
    "operation",
    ["delete_branch", "delete_tag", "merge_pr", "create_repo", "update_repo"],
)
def test_hf_repo_git_destructive_operations_require_approval(operation: str) -> None:
    decision = PolicyEngine.evaluate(
        "hf_repo_git",
        {"operation": operation, "repo_id": "org/repo"},
        config_for_policy(),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.HIGH
    assert decision.side_effects
    assert decision.rollback
    assert decision.credential_usage


def test_hf_job_cpu_obeys_confirm_cpu_jobs() -> None:
    approved = PolicyEngine.evaluate(
        "hf_jobs",
        {"operation": "run", "hardware_flavor": "cpu-basic", "timeout": "30m"},
        config_for_policy(),
    )
    auto_cpu = PolicyEngine.evaluate(
        "hf_jobs",
        {"operation": "uv", "flavor": "cpu-upgrade", "timeout": "1h"},
        config_for_policy(confirm_cpu_jobs=False),
    )

    assert approved.requires_approval is True
    assert approved.risk is RiskLevel.MEDIUM
    assert "Estimated cpu-basic cpu spend" in approved.budget_impact
    assert "about $0.01 for 30m" in approved.budget_impact
    assert "spend=nominal" in approved.reason
    assert auto_cpu.requires_approval is False
    assert auto_cpu.risk is RiskLevel.MEDIUM
    assert "about $0.03 for 1h" in auto_cpu.budget_impact
    assert "confirm_cpu_jobs=false" in auto_cpu.reason


@pytest.mark.parametrize("hardware_key", ["hardware_flavor", "flavor", "hardware"])
def test_hf_job_gpu_always_requires_approval(hardware_key: str) -> None:
    decision = PolicyEngine.evaluate(
        "hf_jobs",
        {"operation": "scheduled run", hardware_key: "a10g-large"},
        config_for_policy(confirm_cpu_jobs=False),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.HIGH
    assert "Estimated a10g-large single_gpu spend" in decision.budget_impact
    assert "Recurring schedule" in decision.budget_impact
    assert "scheduled recurrence requires approval" in decision.reason
    assert decision.credential_usage


def test_hf_job_scheduled_cpu_stays_gated_when_cpu_confirmation_disabled() -> None:
    decision = PolicyEngine.evaluate(
        "hf_jobs",
        {"operation": "scheduled run", "hardware_flavor": "cpu-upgrade"},
        config_for_policy(confirm_cpu_jobs=False),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.HIGH
    assert "cpu-upgrade cpu spend" in decision.budget_impact
    assert "recurrence_multiplier_unknown" in decision.reason


def test_hf_job_multi_gpu_exposes_critical_budget_copy() -> None:
    decision = PolicyEngine.evaluate(
        "hf_jobs",
        {"operation": "run", "hardware": "a100x8", "timeout": "2h"},
        config_for_policy(confirm_cpu_jobs=False),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.CRITICAL
    assert "about $40.00 for 2h" in decision.budget_impact
    assert "multi_gpu" in decision.reason
    assert "spend=high" in decision.reason


@pytest.mark.parametrize(
    "tool_args",
    [
        {"operation": "run", "hardware_flavor": "future-h200x8", "timeout": "1h"},
        {"operation": "run"},
    ],
)
def test_hf_job_unknown_or_missing_hardware_does_not_inherit_cpu_skip(
    tool_args: dict[str, Any]
) -> None:
    decision = PolicyEngine.evaluate(
        "hf_jobs",
        tool_args,
        config_for_policy(confirm_cpu_jobs=False),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.UNKNOWN
    assert "Unknown HF compute spend" in decision.budget_impact
    assert "unknown_hardware" in decision.reason
    assert "confirm_cpu_jobs=false" not in decision.reason


def test_hub_publish_and_private_upload_policy() -> None:
    upload = PolicyEngine.evaluate(
        "hf_private_repos",
        {"operation": "upload_file", "repo_id": "org/private", "path": "README.md"},
        config_for_policy(),
    )
    auto_upload = PolicyEngine.evaluate(
        "hf_private_repos",
        {"operation": "upload_file", "repo_id": "org/private", "path": "README.md"},
        config_for_policy(auto_file_upload=True),
    )
    create_repo = PolicyEngine.evaluate(
        "hf_private_repos",
        {"operation": "create_repo", "repo_id": "org/private"},
        config_for_policy(auto_file_upload=True),
    )

    assert upload.requires_approval is True
    assert upload.risk is RiskLevel.HIGH
    assert auto_upload.requires_approval is False
    assert "auto_file_upload=true" in auto_upload.reason
    assert create_repo.requires_approval is True
    assert create_repo.side_effects


def test_malformed_args_do_not_require_approval() -> None:
    decision = PolicyEngine.evaluate(
        "sandbox_create",
        {"args": "not-json-object"},
        config_for_policy(),
    )

    assert decision.requires_approval is False
    assert decision.risk is RiskLevel.UNKNOWN
    assert "must be a JSON object" in decision.reason


def test_mcp_default_requires_approval() -> None:
    decision = PolicyEngine.evaluate(
        "custom_mcp_tool",
        {"value": 1},
        config_for_policy(),
        metadata=ToolMetadata(source="mcp"),
    )

    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.UNKNOWN
    assert "MCP" in decision.reason


@pytest.mark.parametrize(
    "config",
    [
        config_for_policy(yolo_mode=True),
        SimpleNamespace(autonomy="full", confirm_cpu_jobs=True, auto_file_upload=False),
        SimpleNamespace(approval_policy="never", confirm_cpu_jobs=True, auto_file_upload=False),
    ],
)
def test_yolo_and_autonomy_skip_approvals_but_keep_risk_metadata(config: Any) -> None:
    decision = PolicyEngine.evaluate(
        "hf_repo_files",
        {"operation": "delete", "repo_id": "org/repo", "patterns": ["*.tmp"]},
        config,
    )

    assert decision.requires_approval is False
    assert decision.risk is RiskLevel.HIGH
    assert decision.side_effects
    assert decision.rollback
    assert decision.credential_usage
    assert "Auto-approved" in decision.reason
