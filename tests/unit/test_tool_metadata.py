"""Tool metadata and router policy tests."""

from __future__ import annotations

from enum import Enum
from types import SimpleNamespace
from typing import Any

import pytest

from agent.core.tools import (
    MCP_DEFAULT_METADATA,
    ToolRouter,
    ToolSpec,
    create_builtin_tools,
    policy_decision,
    tool_metadata,
)
from agent.tools.local_tools import get_local_tools


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


_METADATA_ALIASES = {
    "side_effect": ("side_effect", "side_effects"),
    "budget": ("budget", "budget_impact"),
    "credentials": ("credentials", "credential_usage"),
}


def _metadata_value(metadata: Any, field: str) -> Any:
    for name in _METADATA_ALIASES.get(field, (field,)):
        if hasattr(metadata, name):
            value = _plain(getattr(metadata, name))
            if field == "credentials" and isinstance(value, str):
                return [part.strip() for part in value.split(",") if part.strip()]
            if field == "credentials" and value is None:
                return []
            if field == "side_effect" and isinstance(value, list):
                return value[0] if value else "none"
            return value
    raise AttributeError(field)


def _decision_value(decision: Any, field: str) -> Any:
    if field == "allowed" and not hasattr(decision, "allowed"):
        return not bool(getattr(decision, "denied", False))
    return _plain(getattr(decision, field))


class FakeMCPClient:
    def __init__(self, tools: list[SimpleNamespace]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[SimpleNamespace]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return SimpleNamespace(content=[], is_error=False)


@pytest.mark.parametrize("local_mode", [False, True])
def test_all_builtin_tools_have_metadata(local_mode: bool):
    tools = create_builtin_tools(local_mode=local_mode)

    missing = [tool.name for tool in tools if tool.metadata is None]

    assert missing == []
    for tool in tools:
        assert _metadata_value(tool.metadata, "risk") is not None
        assert _metadata_value(tool.metadata, "side_effect") is not None
        assert _metadata_value(tool.metadata, "rollback") is not None
        assert _metadata_value(tool.metadata, "budget") is not None
        assert _metadata_value(tool.metadata, "credentials") is not None


def test_local_tools_have_local_metadata():
    tools = {tool.name: tool for tool in get_local_tools()}

    assert set(tools) == {"bash", "read", "write", "edit"}
    assert _metadata_value(tools["bash"].metadata, "risk") == "high"
    assert _metadata_value(tools["bash"].metadata, "side_effect") == "local_exec"
    assert _metadata_value(tools["read"].metadata, "risk") == "read_only"
    assert _metadata_value(tools["read"].metadata, "credentials") == [
        "local_filesystem"
    ]
    assert _metadata_value(tools["write"].metadata, "side_effect") == "local_write"
    assert _metadata_value(tools["edit"].metadata, "rollback") == "manual"


async def test_mcp_tools_get_default_metadata_and_are_evaluable():
    router = ToolRouter({})
    router.mcp_client = FakeMCPClient(
        [
            SimpleNamespace(
                name="mcp_lookup",
                description="Lookup through MCP",
                inputSchema={"type": "object", "properties": {}},
            )
        ]
    )

    await router.register_mcp_tools()

    tool = router.tools["mcp_lookup"]
    decision = router.evaluate_tool_call("mcp_lookup", {})

    assert tool.metadata is MCP_DEFAULT_METADATA
    assert _metadata_value(tool.metadata, "credentials") == ["mcp_server"]
    assert _decision_value(decision, "allowed") is True
    assert _decision_value(decision, "requires_approval") is True


def test_metadata_does_not_leak_into_llm_tool_specs():
    router = ToolRouter({})

    specs = router.get_tool_specs_for_llm()

    assert specs
    for spec in specs:
        assert set(spec) == {"type", "function"}
        assert set(spec["function"]) == {"name", "description", "parameters"}
        assert "metadata" not in spec["function"]


def test_policy_evaluation_exposes_requires_approval_without_denial():
    router = ToolRouter({})

    decision = router.evaluate_tool_call("hf_jobs", {"operation": "run"})
    readonly_decision = router.evaluate_tool_call("hf_jobs", {"operation": "logs"})

    assert _decision_value(decision, "allowed") is True
    assert _decision_value(decision, "requires_approval") is True
    assert _decision_value(readonly_decision, "allowed") is True
    assert _decision_value(readonly_decision, "requires_approval") is False


async def test_call_tool_result_returns_structured_error_when_policy_denies():
    called = False

    class DenyEngine:
        def evaluate(
            self,
            *,
            tool: ToolSpec,
            arguments: dict[str, Any],
            session: Any = None,
        ) -> Any:
            return policy_decision(
                allowed=False,
                reason="blocked by test policy",
                code="test_policy_denied",
            )

    async def handler(arguments: dict[str, Any]) -> tuple[str, bool]:
        nonlocal called
        called = True
        return "should not run", True

    router = ToolRouter({}, policy_engine=DenyEngine())
    router.register_tool(
        ToolSpec(
            name="blocked_tool",
            description="Blocked test tool",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            metadata=tool_metadata(
                risk="high",
                side_effect="external_service",
                rollback="unknown",
                budget="unknown",
            ),
        )
    )

    result = await router.call_tool_result("blocked_tool", {})

    assert called is False
    assert result.success is False
    assert result.error is not None
    assert result.error.kind == "policy"
    assert result.error.code == "test_policy_denied"
    assert result.display_text == "blocked by test policy"
    assert result.metadata["tool_name"] == "blocked_tool"


async def test_direct_approval_required_tool_call_is_blocked_until_approved():
    called = False

    async def handler(arguments: dict[str, Any]) -> tuple[str, bool]:
        nonlocal called
        called = True
        return "ran", True

    router = ToolRouter({})
    router.register_tool(
        ToolSpec(
            name="approval_required_tool",
            description="Approval required test tool",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            metadata=tool_metadata(
                risk="high",
                side_effect="external_service",
                rollback="manual",
                budget="unknown",
            ),
        )
    )

    blocked = await router.call_tool_result("approval_required_tool", {})
    allowed = await router.call_tool_result(
        "approval_required_tool",
        {},
        policy_approved=True,
    )

    assert blocked.success is False
    assert blocked.error is not None
    assert blocked.error.kind == "policy"
    assert blocked.error.code == "tool_policy_approval_required"
    assert allowed.success is True
    assert allowed.display_text == "ran"
    assert called is True


async def test_unregistered_mcp_tool_is_policy_checked_before_fallthrough():
    router = ToolRouter({})
    fake_mcp = FakeMCPClient([])
    router.mcp_client = fake_mcp
    router._mcp_initialized = True

    blocked = await router.call_tool_result("unregistered_mcp_tool", {"value": 1})
    allowed = await router.call_tool_result(
        "unregistered_mcp_tool",
        {"value": 1},
        policy_approved=True,
    )

    assert blocked.success is False
    assert blocked.error is not None
    assert blocked.error.kind == "policy"
    assert blocked.error.code == "tool_policy_approval_required"
    assert fake_mcp.calls == [("unregistered_mcp_tool", {"value": 1})]
    assert allowed.success is True
