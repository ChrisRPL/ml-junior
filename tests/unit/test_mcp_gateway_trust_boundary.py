"""MCP gateway trust-boundary tests."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agent.config import Config
from agent.core.tools import NOT_ALLOWED_TOOL_NAMES, ToolRouter


class FakeServerConfig:
    def __init__(self, **data: Any) -> None:
        self.data = data

    def model_dump(self) -> dict[str, Any]:
        dumped = dict(self.data)
        if isinstance(dumped.get("headers"), dict):
            dumped["headers"] = dict(dumped["headers"])
        return dumped


class FakeMCPClient:
    def __init__(self, tools: list[SimpleNamespace]) -> None:
        self.tools = tools
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[SimpleNamespace]:
        return self.tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append((name, arguments))
        return SimpleNamespace(content=[], is_error=False)


def server_config(**overrides: Any) -> FakeServerConfig:
    values = {"transport": "http", "url": "https://example.invalid/mcp"}
    values.update(overrides)
    return FakeServerConfig(**values)


def mcp_tool(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"{name} description",
        inputSchema={"type": "object", "properties": {}},
    )


def test_config_defaults_to_no_trusted_hf_mcp_servers() -> None:
    config = Config(model_name="test/model")

    assert config.trusted_hf_mcp_servers == []


def test_hf_token_forwarded_only_to_trusted_servers_and_preserves_explicit_auth() -> None:
    router = ToolRouter(
        {
            "trusted": server_config(),
            "untrusted": server_config(),
            "explicit": server_config(headers={"Authorization": "Bearer explicit"}),
        },
        hf_token="hf_user_token",
        trusted_hf_mcp_servers=["trusted", "explicit"],
    )

    assert router.mcp_servers["trusted"]["headers"]["Authorization"] == (
        "Bearer hf_user_token"
    )
    assert router.mcp_servers["untrusted"].get("headers") is None
    assert router.mcp_servers["explicit"]["headers"]["Authorization"] == (
        "Bearer explicit"
    )
    assert router.mcp_server_credential_policies["trusted"].forwarded_hf_token is True
    assert router.mcp_server_credential_policies["untrusted"].forwarded_hf_token is False
    assert router.mcp_server_credential_policies["explicit"].forwarded_hf_token is False


async def test_mcp_tools_register_with_normalized_namespace_and_origin_metadata() -> None:
    router = ToolRouter(
        {"hf-hub": server_config()},
        hf_token="hf_user_token",
        trusted_hf_mcp_servers=["hf-hub"],
    )
    router.mcp_client = FakeMCPClient([mcp_tool("Dataset Search")])

    await router.register_mcp_tools()

    tool = router.tools["mcp__hf_hub__dataset_search"]
    origin = router.mcp_tool_origins["mcp__hf_hub__dataset_search"]

    assert "Dataset Search" not in router.tools
    assert tool.description == "Dataset Search description"
    assert origin.server_name == "hf-hub"
    assert origin.raw_tool_name == "Dataset Search"
    assert origin.client_tool_name == "Dataset Search"
    assert tool.metadata.source == "mcp"
    assert tool.metadata.mcp_origin == "hf-hub:Dataset Search"
    assert tool.metadata.mcp_server == "hf-hub"
    assert tool.metadata.mcp_tool == "Dataset Search"
    assert tool.metadata.mcp_trusted is True
    assert tool.metadata.mcp_forwarded_hf_token is True
    assert tool.metadata.credential_usage == ["mcp_server", "hf_token"]


async def test_mcp_raw_blocklist_and_builtin_collision_are_rejected() -> None:
    router = ToolRouter({"hf-hub": server_config()})
    existing_builtin = router.tools["sandbox_create"]
    blocked_name = NOT_ALLOWED_TOOL_NAMES[0]
    collision_name = "mcp__hf_hub__safe_tool"
    router.register_tool(
        router.tools["sandbox_create"].__class__(
            name=collision_name,
            description="existing built-in-like tool",
            parameters={"type": "object", "properties": {}},
            handler=existing_builtin.handler,
            metadata=existing_builtin.metadata,
        )
    )
    router.mcp_client = FakeMCPClient(
        [
            mcp_tool(blocked_name),
            mcp_tool("safe tool"),
        ]
    )

    await router.register_mcp_tools()

    assert f"mcp__hf_hub__{blocked_name}" not in router.tools
    assert router.tools[collision_name].description == "existing built-in-like tool"
    assert collision_name not in router.mcp_tool_origins


async def test_duplicate_namespaced_mcp_names_are_rejected() -> None:
    router = ToolRouter({"hf-hub": server_config()})
    router.mcp_client = FakeMCPClient(
        [
            mcp_tool("safe-tool"),
            mcp_tool("safe tool"),
        ]
    )

    await router.register_mcp_tools()

    tool = router.tools["mcp__hf_hub__safe_tool"]
    origin = router.mcp_tool_origins["mcp__hf_hub__safe_tool"]

    assert tool.description == "safe-tool description"
    assert origin.raw_tool_name == "safe-tool"


async def test_calling_namespaced_mcp_tool_uses_original_client_tool_name() -> None:
    fake_client = FakeMCPClient([mcp_tool("Dataset Search")])
    router = ToolRouter({"hf-hub": server_config()})
    router.mcp_client = fake_client
    router._mcp_initialized = True
    await router.register_mcp_tools()

    result = await router.call_tool_result(
        "mcp__hf_hub__dataset_search",
        {"query": "trl"},
        policy_approved=True,
    )

    assert result.success is True
    assert fake_client.calls == [("Dataset Search", {"query": "trl"})]
