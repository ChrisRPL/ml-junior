"""Local execution guardrail coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.core.policy import PolicyEngine, RiskLevel, ToolMetadata
from agent.core.tools import ToolRouter
from agent.tools import local_tools


@pytest.fixture
def local_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(workspace)
    monkeypatch.delenv("MLJ_LOCAL_ALLOWED_ROOTS", raising=False)
    monkeypatch.delenv("MLJ_LOCAL_WORKSPACE_ROOT", raising=False)
    local_tools._files_read.clear()
    return workspace


async def test_local_read_blocks_outside_workspace(
    local_workspace: Path,
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    router = ToolRouter({}, local_mode=True)

    result = await router.call_tool_result("read", {"path": str(outside)})

    assert result.success is False
    assert result.error is not None
    assert result.error.kind == "policy"
    assert result.error.code == "local_path_outside_workspace"
    assert "outside allowed roots" in result.display_text


@pytest.mark.parametrize("tool_name", ["write", "edit"])
async def test_local_write_tools_block_outside_workspace(
    local_workspace: Path,
    tmp_path: Path,
    tool_name: str,
) -> None:
    outside = tmp_path / f"outside-{tool_name}.txt"
    outside.write_text("old\n")
    router = ToolRouter({}, local_mode=True)
    args = (
        {"path": str(outside), "content": "new\n"}
        if tool_name == "write"
        else {"path": str(outside), "old_str": "old", "new_str": "new"}
    )

    result = await router.call_tool_result(tool_name, args, policy_approved=True)

    assert result.success is False
    assert result.error is not None
    assert result.error.kind == "policy"
    assert result.error.code == "local_path_outside_workspace"
    assert outside.read_text() == "old\n"


async def test_local_bash_blocks_unsafe_work_dir(
    local_workspace: Path,
    tmp_path: Path,
) -> None:
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    router = ToolRouter({}, local_mode=True)

    result = await router.call_tool_result(
        "bash",
        {"command": "pwd", "work_dir": str(outside_dir)},
        policy_approved=True,
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.kind == "policy"
    assert result.error.code == "local_work_dir_outside_workspace"


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf build",
        "git reset --hard",
        "find . -name '*.tmp' -delete",
    ],
)
async def test_local_bash_blocks_destructive_commands(
    local_workspace: Path,
    command: str,
) -> None:
    router = ToolRouter({}, local_mode=True)

    result = await router.call_tool_result(
        "bash",
        {"command": command, "work_dir": str(local_workspace)},
        policy_approved=True,
    )

    assert result.success is False
    assert result.error is not None
    assert result.error.kind == "policy"
    assert result.error.code == "local_destructive_command"
    assert "Destructive local shell command blocked" in result.display_text


async def test_local_in_workspace_read_write_edit_and_bash_are_allowed(
    local_workspace: Path,
) -> None:
    router = ToolRouter({}, local_mode=True)
    target = local_workspace / "notes.txt"

    write_result = await router.call_tool_result(
        "write",
        {"path": str(target), "content": "alpha\n"},
        policy_approved=True,
    )
    read_result = await router.call_tool_result("read", {"path": str(target)})
    edit_result = await router.call_tool_result(
        "edit",
        {"path": str(target), "old_str": "alpha", "new_str": "beta"},
        policy_approved=True,
    )
    bash_result = await router.call_tool_result(
        "bash",
        {"command": "pwd", "work_dir": str(local_workspace)},
        policy_approved=True,
    )

    assert write_result.success is True
    assert read_result.success is True
    assert "alpha" in read_result.display_text
    assert edit_result.success is True
    assert target.read_text() == "beta\n"
    assert bash_result.success is True
    assert str(local_workspace) in bash_result.display_text


def test_policy_classifies_destructive_bash_as_denied_in_yolo_mode(
    local_workspace: Path,
) -> None:
    decision = PolicyEngine.evaluate(
        "bash",
        {"command": "rm -rf build", "work_dir": str(local_workspace)},
        config=type("Config", (), {"yolo_mode": True})(),
        metadata=ToolMetadata(source="local", local=True),
    )

    assert decision.allowed is False
    assert decision.requires_approval is False
    assert decision.risk is RiskLevel.CRITICAL
    assert decision.code == "local_destructive_command"
    assert "Auto-approved" not in decision.reason


def test_policy_leaves_nonlocal_bash_destructive_commands_to_existing_approval_gate(
    local_workspace: Path,
) -> None:
    decision = PolicyEngine.evaluate(
        "bash",
        {"command": "rm -rf build", "work_dir": str(local_workspace)},
        config=type("Config", (), {"yolo_mode": False})(),
        metadata=ToolMetadata(),
    )

    assert decision.allowed is True
    assert decision.requires_approval is True
    assert decision.risk is RiskLevel.HIGH
    assert decision.code is None
