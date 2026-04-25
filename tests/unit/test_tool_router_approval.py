"""Tool router and approval behavior characterization tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.config import Config
from agent.core.agent_loop import _needs_approval
from agent.core.tools import NOT_ALLOWED_TOOL_NAMES, ToolRouter, ToolSpec


def config_for_approval(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "model_name": "test/model",
        "mcpServers": {},
        "save_sessions": False,
        "reasoning_effort": None,
    }
    values.update(overrides)
    return Config(**values)


class FakeMCPClient:
    def __init__(self, tools: list[SimpleNamespace]) -> None:
        self.tools = tools

    async def list_tools(self) -> list[SimpleNamespace]:
        return self.tools


@pytest.mark.parametrize(
    ("tool_args", "expected"),
    [
        ({"operation": "run"}, True),
        ({"operation": "run", "hardware_flavor": "cpu-basic"}, True),
        ({"operation": "uv", "flavor": "cpu-basic"}, True),
        ({"operation": "scheduled run", "hardware": "cpu-basic"}, True),
        ({"operation": "scheduled uv", "hardware": "cpu-basic"}, True),
        ({"operation": "ps"}, False),
        ({"operation": "logs"}, False),
        ({"operation": "scheduled ps"}, False),
    ],
)
def test_needs_approval_hf_jobs_cpu_and_read_only_operations(
    tool_args: dict[str, Any], expected: bool
):
    assert _needs_approval("hf_jobs", tool_args, config_for_approval()) is expected


@pytest.mark.parametrize(
    "tool_args",
    [
        {"operation": "run"},
        {"operation": "run", "hardware_flavor": "cpu-basic"},
        {"operation": "uv", "flavor": "cpu-basic"},
        {"operation": "scheduled uv", "hardware": "cpu-basic"},
    ],
)
def test_needs_approval_hf_jobs_cpu_respects_confirm_cpu_jobs_false(
    tool_args: dict[str, Any],
):
    config = config_for_approval(confirm_cpu_jobs=False)

    assert _needs_approval("hf_jobs", tool_args, config) is False


@pytest.mark.parametrize("hardware_key", ["hardware_flavor", "flavor", "hardware"])
def test_needs_approval_hf_jobs_gpu_ignores_confirm_cpu_jobs_false(
    hardware_key: str,
):
    config = config_for_approval(confirm_cpu_jobs=False)
    tool_args = {"operation": "run", hardware_key: "t4-small"}

    assert _needs_approval("hf_jobs", tool_args, config) is True


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("upload", True),
        ("delete", True),
        ("list", False),
        ("read", False),
    ],
)
def test_needs_approval_hf_repo_files_upload_delete_only(
    operation: str, expected: bool
):
    assert (
        _needs_approval(
            "hf_repo_files",
            {"operation": operation, "repo_id": "org/repo"},
            config_for_approval(),
        )
        is expected
    )


@pytest.mark.parametrize(
    "operation",
    ["delete_branch", "delete_tag", "merge_pr", "create_repo", "update_repo"],
)
def test_needs_approval_hf_repo_git_destructive_operations(operation: str):
    assert (
        _needs_approval(
            "hf_repo_git",
            {"operation": operation, "repo_id": "org/repo"},
            config_for_approval(),
        )
        is True
    )


@pytest.mark.parametrize(
    "operation",
    ["create_branch", "create_tag", "list_refs", "create_pr", "close_pr"],
)
def test_needs_approval_hf_repo_git_non_destructive_operations(operation: str):
    assert (
        _needs_approval(
            "hf_repo_git",
            {"operation": operation, "repo_id": "org/repo"},
            config_for_approval(),
        )
        is False
    )


def test_needs_approval_sandbox_create_always_requires_approval():
    assert _needs_approval("sandbox_create", {}, config_for_approval()) is True


@pytest.mark.parametrize(
    ("tool_name", "tool_args"),
    [
        ("sandbox_create", {}),
        ("hf_jobs", {"operation": "run", "hardware_flavor": "a10g-large"}),
        ("hf_repo_files", {"operation": "delete", "repo_id": "org/repo"}),
        ("hf_repo_git", {"operation": "delete_branch", "repo_id": "org/repo"}),
    ],
)
def test_needs_approval_yolo_mode_bypasses_current_approval_gates(
    tool_name: str, tool_args: dict[str, Any]
):
    config = config_for_approval(yolo_mode=True)

    assert _needs_approval(tool_name, tool_args, config) is False


async def test_call_tool_routes_registered_handler_and_preserves_return_contract():
    calls: list[tuple[dict[str, Any], Any, str | None]] = []
    session = object()

    async def handler(
        arguments: dict[str, Any],
        session: Any = None,
        tool_call_id: str | None = None,
    ) -> tuple[str, bool]:
        calls.append((arguments, session, tool_call_id))
        return "offline ok", True

    router = ToolRouter({})
    router.register_tool(
        ToolSpec(
            name="offline_echo",
            description="Offline test handler",
            parameters={"type": "object", "properties": {}},
            handler=handler,
        )
    )

    output, success = await router.call_tool(
        "offline_echo",
        {"value": 1},
        session=session,
        tool_call_id="tc_1",
    )

    assert (output, success) == ("offline ok", True)
    assert calls == [({"value": 1}, session, "tc_1")]


async def test_call_tool_unknown_without_initialized_mcp_returns_current_error():
    router = ToolRouter({})

    output, success = await router.call_tool("missing_tool", {"value": 1})

    assert (output, success) == ("MCP client not initialized", False)


async def test_register_mcp_tools_skips_not_allowed_tool_names():
    router = ToolRouter({})
    originals = {name: router.tools.get(name) for name in NOT_ALLOWED_TOOL_NAMES}
    fake_tools = [
        SimpleNamespace(
            name=name,
            description=f"blocked MCP replacement for {name}",
            inputSchema={"type": "object", "properties": {}},
        )
        for name in NOT_ALLOWED_TOOL_NAMES
    ]
    fake_tools.append(
        SimpleNamespace(
            name="allowed_mcp_tool",
            description="Allowed MCP tool",
            inputSchema={
                "type": "object",
                "properties": {"value": {"type": "string"}},
            },
        )
    )
    router.mcp_client = FakeMCPClient(fake_tools)

    await router.register_mcp_tools()

    assert router.tools["allowed_mcp_tool"].description == "Allowed MCP tool"
    assert router.tools["allowed_mcp_tool"].handler is None
    for name, original in originals.items():
        if original is None:
            assert name not in router.tools
        else:
            assert router.tools[name] is original
            assert router.tools[name].description != (
                f"blocked MCP replacement for {name}"
            )


async def test_register_mcp_tools_currently_overwrites_allowed_builtin_name():
    router = ToolRouter({})
    collision_name = "sandbox_create"
    original = router.tools[collision_name]
    router.mcp_client = FakeMCPClient(
        [
            SimpleNamespace(
                name=collision_name,
                description="MCP collision replacement",
                inputSchema={"type": "object", "properties": {"replacement": {}}},
            )
        ]
    )

    await router.register_mcp_tools()

    replacement = router.tools[collision_name]
    assert replacement is not original
    assert replacement.description == "MCP collision replacement"
    assert replacement.parameters == {
        "type": "object",
        "properties": {"replacement": {}},
    }
    assert replacement.handler is None
