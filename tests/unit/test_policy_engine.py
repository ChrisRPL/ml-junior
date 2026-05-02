"""Policy engine approval behavior tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.config import Config
from agent.core.events import AgentEvent
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


def test_hf_job_approval_metadata_preserves_enriched_compute_risk() -> None:
    scheduled_unknown = PolicyEngine.evaluate(
        "hf_jobs",
        {
            "operation": "scheduled run",
            "hardware_flavor": "future-h200x8",
            "timeout": "bogus",
        },
        config_for_policy(confirm_cpu_jobs=False),
    )

    metadata = scheduled_unknown.approval_metadata()

    assert scheduled_unknown.requires_approval is True
    assert metadata["risk"] == "unknown"
    assert metadata["side_effects"] == [
        "Starts or schedules a Hugging Face compute job."
    ]
    assert metadata["rollback"] == "Cancel the job or delete the scheduled job."
    assert metadata["budget_impact"] == (
        "Unknown HF compute spend; hardware is missing or not recognized in "
        "the local flavor list."
    )
    assert metadata["credential_usage"] == ["hf_token"]
    assert "scheduled recurrence requires approval" in metadata["reason"]
    assert "uncertainty=unparsed_timeout, unknown_hardware" in metadata["reason"]
    assert "recurrence_multiplier_unknown" in metadata["reason"]


def test_confirm_cpu_jobs_false_only_skips_explicit_cpu_approval_gate() -> None:
    tool_args = {
        "operation": "run",
        "hardware_flavor": "cpu-basic",
        "timeout": "45m",
    }

    gated = PolicyEngine.evaluate(
        "hf_jobs",
        tool_args,
        config_for_policy(confirm_cpu_jobs=True),
    )
    ungated = PolicyEngine.evaluate(
        "hf_jobs",
        tool_args,
        config_for_policy(confirm_cpu_jobs=False),
    )

    gated_metadata = gated.approval_metadata()
    ungated_metadata = ungated.approval_metadata()

    assert gated.requires_approval is True
    assert ungated.requires_approval is False
    assert {
        key: gated_metadata[key]
        for key in (
            "risk",
            "side_effects",
            "rollback",
            "budget_impact",
            "credential_usage",
        )
    } == {
        key: ungated_metadata[key]
        for key in (
            "risk",
            "side_effects",
            "rollback",
            "budget_impact",
            "credential_usage",
        )
    }
    assert ungated_metadata["risk"] == "medium"
    assert "Estimated cpu-basic cpu spend: about $0.01 for 45m." == (
        ungated_metadata["budget_impact"]
    )
    assert "confirm_cpu_jobs=false" in ungated_metadata["reason"]
    assert "Hugging Face job launch risk: cpu" in ungated_metadata["reason"]


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


def _hf_jobs_approval_event(tool_args: dict[str, Any], sequence: int = 1) -> AgentEvent:
    decision = PolicyEngine.evaluate(
        "hf_jobs",
        tool_args,
        config_for_policy(confirm_cpu_jobs=True),
    )
    metadata = decision.approval_metadata()
    return AgentEvent(
        session_id="session-a",
        sequence=sequence,
        event_type="approval_required",
        data={
            "tools": [
                {
                    "tool": "hf_jobs",
                    "arguments": tool_args,
                    "tool_call_id": "tc-1",
                    **metadata,
                }
            ],
            "count": 1,
        },
    )


def test_hf_compute_risk_preserved_in_approval_required_event() -> None:
    event = _hf_jobs_approval_event(
        {"operation": "run", "hardware_flavor": "a100x8", "timeout": "2h"},
        sequence=5,
    )

    assert event.event_type == "approval_required"
    assert event.sequence == 5
    tools = event.data["tools"]
    assert len(tools) == 1
    tool_data = tools[0]
    assert tool_data["risk"] == "critical"
    assert tool_data["budget_impact"] == (
        "Estimated a100x8 multi_gpu spend: about $40.00 for 2h."
    )
    assert "multi_gpu" in tool_data["reason"]
    assert "spend=high" in tool_data["reason"]
    assert tool_data["side_effects"] == [
        "Starts or schedules a Hugging Face compute job."
    ]
    assert tool_data["rollback"] == "Cancel the job or delete the scheduled job."
    assert tool_data["credential_usage"] == ["hf_token"]


def test_hf_compute_risk_preserved_in_scheduled_cpu_approval_event() -> None:
    event = _hf_jobs_approval_event(
        {"operation": "scheduled run", "hardware_flavor": "cpu-upgrade"},
        sequence=3,
    )

    tools = event.data["tools"]
    assert tools[0]["risk"] == "high"
    assert "cpu-upgrade cpu spend" in tools[0]["budget_impact"]
    assert "recurrence_multiplier_unknown" in tools[0]["reason"]
    assert "Recurring schedule" in tools[0]["budget_impact"]


def test_hf_compute_risk_redaction_preserves_approval_structure() -> None:
    secret = "hf_supersecret_token_xyz"
    event = _hf_jobs_approval_event(
        {
            "operation": "run",
            "hardware_flavor": "a100x8",
            "timeout": "2h",
            "env": {"HF_TOKEN": secret},
        },
        sequence=1,
    )

    redacted = event.redacted_copy()
    tools = redacted.data["tools"]
    assert len(tools) == 1
    assert tools[0]["risk"] == "critical"
    assert "about $40.00 for 2h" in tools[0]["budget_impact"]
    assert tools[0]["side_effects"] == [
        "Starts or schedules a Hugging Face compute job."
    ]
    assert tools[0]["credential_usage"] == ["hf_token"]
    assert secret not in repr(redacted.data)


def test_hf_compute_risk_approval_event_is_frontend_compatible() -> None:
    event = _hf_jobs_approval_event(
        {"operation": "run", "hardware_flavor": "t4-small", "timeout": "45m"},
        sequence=2,
    )

    sse_payload = event.to_legacy_sse()
    assert sse_payload["event_type"] == "approval_required"
    tools = sse_payload["data"]["tools"]
    assert tools[0]["risk"] == "high"
    assert "t4-small" in tools[0]["budget_impact"]
    assert "about $0.30 for 45m" in tools[0]["budget_impact"]
    assert "tool_call_id" in tools[0]
    assert "arguments" in tools[0]


def test_hf_compute_risk_pending_approval_session_info_shape() -> None:
    decision = PolicyEngine.evaluate(
        "hf_jobs",
        {"operation": "run", "hardware_flavor": "l4x1", "timeout": "1h"},
        config_for_policy(confirm_cpu_jobs=True),
    )
    metadata = decision.approval_metadata()

    pending_approval = {
        "tool_calls": [{"id": "tc-1"}],
        "policy": {"tc-1": metadata},
    }

    assert pending_approval["policy"]["tc-1"]["risk"] == "high"
    assert "l4x1" in pending_approval["policy"]["tc-1"]["budget_impact"]
    assert "about $0.80 for 1h" in pending_approval["policy"]["tc-1"]["budget_impact"]
    assert pending_approval["policy"]["tc-1"]["credential_usage"] == ["hf_token"]
