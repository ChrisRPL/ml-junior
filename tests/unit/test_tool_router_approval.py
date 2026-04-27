"""Tool router and approval behavior characterization tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from agent.config import Config
from agent.core import agent_loop
from agent.core.agent_loop import (
    Handlers,
    PolicyDecision,
    PolicyEngine,
    ToolMetadata,
    _needs_approval,
)
from agent.core.session import Session
from agent.core.tool_results import ArtifactRef, MetricRecord, SideEffect, ToolResult
from agent.core.tools import NOT_ALLOWED_TOOL_NAMES, ToolRouter, ToolSpec, tool_metadata
from tests.helpers.fakes import FakeCompletion


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


class FakeAcompletion:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        return self.responses.pop(0)


def llm_message(content: str | None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def llm_tool_call(tool_call_id: str, name: str, arguments: dict[str, Any]) -> Any:
    return SimpleNamespace(
        id=tool_call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def patch_agent_runtime(monkeypatch: pytest.MonkeyPatch, fake_llm: FakeAcompletion) -> None:
    async def no_compaction(session: Session) -> None:
        return None

    def resolve_params(
        model_name: str,
        hf_token: str | None,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        return {"model": model_name}

    monkeypatch.setattr(agent_loop, "acompletion", fake_llm)
    monkeypatch.setattr(agent_loop, "_resolve_llm_params", resolve_params)
    monkeypatch.setattr(agent_loop, "_compact_and_notify", no_compaction)


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
    ("tool_name", "tool_args"),
    [
        ("read", {"path": "/tmp/model.py"}),
        ("research", {"task": "inspect current APIs"}),
        ("explore_hf_docs", {"query": "transformers trainer"}),
        ("fetch_hf_docs", {"url": "https://huggingface.co/docs/transformers"}),
        ("hf_papers", {"operation": "search", "query": "LoRA"}),
        ("hf_inspect_dataset", {"dataset": "stanfordnlp/imdb"}),
        ("github_find_examples", {"query": "trl sft"}),
        ("github_list_repos", {"owner": "huggingface"}),
        ("github_read_file", {"repo": "huggingface/trl", "path": "README.md"}),
        ("plan_tool", {"todos": []}),
        ("hf_repo_files", {"operation": "read", "repo_id": "org/repo", "path": "README.md"}),
        ("hf_repo_git", {"operation": "list_refs", "repo_id": "org/repo"}),
    ],
)
def test_policy_allows_read_only_autonomous_execution(
    tool_name: str, tool_args: dict[str, Any]
):
    decision = PolicyEngine.evaluate(tool_name, tool_args, config_for_approval())

    assert decision.requires_approval is False
    assert _needs_approval(tool_name, tool_args, config_for_approval()) is False


@pytest.mark.parametrize(
    ("tool_name", "tool_args", "side_effect"),
    [
        ("bash", {"command": "python train.py"}, "local_exec"),
        ("write", {"path": "/tmp/model.py", "content": "print('ok')"}, "local_write"),
        (
            "edit",
            {"path": "/tmp/model.py", "old_str": "old", "new_str": "new"},
            "local_write",
        ),
    ],
)
def test_policy_requires_approval_for_local_shell_and_writes(
    tool_name: str, tool_args: dict[str, Any], side_effect: str
):
    decision = PolicyEngine.evaluate(tool_name, tool_args, config_for_approval())

    assert decision.requires_approval is True
    assert _needs_approval(tool_name, tool_args, config_for_approval()) is True
    assert side_effect in decision.side_effects


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
    [
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
    ],
)
def test_needs_approval_hf_repo_git_write_operations(operation: str):
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
    ["list_refs", "list_prs", "get_pr"],
)
def test_needs_approval_hf_repo_git_read_operations(operation: str):
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


@pytest.mark.parametrize("operation", ["upload_file", "create_repo"])
def test_needs_approval_hf_private_repo_write_operations(operation: str):
    assert (
        _needs_approval(
            "hf_private_repos",
            {"operation": operation, "args": {"repo_id": "org/private-repo"}},
            config_for_approval(),
        )
        is True
    )


def test_needs_approval_hf_private_upload_respects_auto_file_upload():
    config = config_for_approval(auto_file_upload=True)

    assert (
        _needs_approval(
            "hf_private_repos",
            {"operation": "upload_file", "args": {"repo_id": "org/private-repo"}},
            config,
        )
        is False
    )


@pytest.mark.parametrize("operation", ["check_repo", "list_files", "read_file"])
def test_needs_approval_hf_private_repo_read_operations(operation: str):
    assert (
        _needs_approval(
            "hf_private_repos",
            {"operation": operation, "args": {"repo_id": "org/private-repo"}},
            config_for_approval(),
        )
        is False
    )


def test_policy_requires_approval_for_mcp_tools_by_default():
    router = SimpleNamespace(
        tools={"custom_mcp_tool": SimpleNamespace(handler=None)}
    )

    decision = PolicyEngine.evaluate(
        "custom_mcp_tool",
        {"value": 1},
        config_for_approval(),
        tool_router=router,
    )

    assert decision.requires_approval is True
    assert "mcp_server" in decision.credential_usage
    assert _needs_approval("custom_mcp_tool", {"value": 1}, config_for_approval()) is True


@pytest.mark.parametrize(
    ("tool_name", "tool_args"),
    [
        ("sandbox_create", {}),
        ("bash", {"command": "python train.py"}),
        ("write", {"path": "/tmp/model.py", "content": "print('ok')"}),
        ("hf_jobs", {"operation": "run", "hardware_flavor": "a10g-large"}),
        ("hf_repo_files", {"operation": "delete", "repo_id": "org/repo"}),
        ("hf_repo_git", {"operation": "delete_branch", "repo_id": "org/repo"}),
        ("custom_mcp_tool", {"value": 1}),
    ],
)
def test_needs_approval_yolo_mode_bypasses_current_approval_gates(
    tool_name: str, tool_args: dict[str, Any]
):
    config = config_for_approval(yolo_mode=True)

    assert _needs_approval(tool_name, tool_args, config) is False


async def test_run_agent_uses_router_policy_and_emits_rich_approval_payload(
    monkeypatch,
    event_queue,
    event_collector,
):
    tool_call = llm_tool_call(
        "tc_job",
        "hf_jobs",
        {
            "operation": "run",
            "hardware_flavor": "a10g-large",
            "script": "print('train')",
        },
    )
    fake_llm = FakeAcompletion(
        FakeCompletion(llm_message(None, [tool_call]), finish_reason="tool_calls")
    )
    patch_agent_runtime(monkeypatch, fake_llm)

    class PolicyRouter:
        def __init__(self) -> None:
            self.policy_calls: list[tuple[str, dict[str, Any]]] = []

        def get_tool_specs_for_llm(self) -> list[dict[str, Any]]:
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "hf_jobs",
                        "description": "fake jobs tool",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ]

        def evaluate_policy(
            self,
            tool_name: str,
            tool_args: dict[str, Any],
            config: Config | None = None,
        ) -> PolicyDecision:
            self.policy_calls.append((tool_name, tool_args))
            return PolicyDecision(
                requires_approval=True,
                risk="high",
                side_effects=["remote_compute", "remote_write"],
                rollback="manual",
                budget_impact="high",
                credential_usage=["hf_token"],
                reason="router policy: GPU job launch",
            )

        async def call_tool(self, *_args: Any, **_kwargs: Any) -> tuple[str, bool]:
            raise AssertionError("approval-gated tool should not execute")

    router = PolicyRouter()
    session = Session(
        event_queue,
        config=config_for_approval(max_iterations=3),
        tool_router=router,
        stream=False,
    )

    result = await Handlers.run_agent(session, "launch job")

    events = await event_collector(event_queue)
    approval_event = next(event for event in events if event.event_type == "approval_required")
    approval_tool = approval_event.data["tools"][0]

    assert result is None
    assert router.policy_calls == [
        (
            "hf_jobs",
            {
                "operation": "run",
                "hardware_flavor": "a10g-large",
                "script": "print('train')",
            },
        )
    ]
    assert approval_tool["tool"] == "hf_jobs"
    assert approval_tool["arguments"]["script"] == "print('train')"
    assert approval_tool["risk"] == "high"
    assert approval_tool["side_effects"] == ["remote_compute", "remote_write"]
    assert approval_tool["rollback"] == "manual"
    assert approval_tool["budget_impact"] == "high"
    assert approval_tool["credential_usage"] == ["hf_token"]
    assert approval_tool["reason"] == "router policy: GPU job launch"
    assert session.pending_approval["policy"]["tc_job"] == {
        "risk": "high",
        "side_effects": ["remote_compute", "remote_write"],
        "rollback": "manual",
        "budget_impact": "high",
        "credential_usage": ["hf_token"],
        "reason": "router policy: GPU job launch",
    }


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
            metadata=tool_metadata(
                risk="read_only",
                side_effect="none",
                rollback="not_needed",
                budget="none",
                read_only=True,
            ),
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


async def test_call_tool_result_routes_registered_handler_with_structured_result():
    async def handler(arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            display_text=f"created {arguments['name']}",
            success=True,
            artifacts=[ArtifactRef(kind="file", uri="file:///tmp/model.json")],
            metrics=[MetricRecord(name="files", value=1)],
            side_effects=[
                SideEffect(
                    kind="write",
                    description="Created model metadata",
                    target="/tmp/model.json",
                )
            ],
        )

    router = ToolRouter({})
    router.register_tool(
        ToolSpec(
            name="structured_create",
            description="Structured test handler",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            metadata=tool_metadata(
                risk="read_only",
                side_effect="none",
                rollback="not_needed",
                budget="none",
                read_only=True,
            ),
        )
    )

    result = await router.call_tool_result("structured_create", {"name": "model"})
    output, success = await router.call_tool("structured_create", {"name": "model"})

    assert result.display_text == "created model"
    assert result.success is True
    assert result.artifacts[0].uri == "file:///tmp/model.json"
    assert result.metrics[0].name == "files"
    assert result.side_effects[0].target == "/tmp/model.json"
    assert (output, success) == ("created model", True)


async def test_call_tool_result_normalizes_hf_style_handler_dict():
    async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "formatted": f"Found {arguments['count']} results",
            "totalResults": arguments["count"],
            "resultsShared": 1,
        }

    router = ToolRouter({})
    router.register_tool(
        ToolSpec(
            name="hf_style",
            description="HF style test handler",
            parameters={"type": "object", "properties": {}},
            handler=handler,
            metadata=tool_metadata(
                risk="read_only",
                side_effect="none",
                rollback="not_needed",
                budget="none",
                read_only=True,
            ),
        )
    )

    result = await router.call_tool_result("hf_style", {"count": 4})

    assert result.display_text == "Found 4 results"
    assert result.success is True
    assert [(metric.name, metric.value) for metric in result.metrics] == [
        ("totalResults", 4),
        ("resultsShared", 1),
    ]


async def test_call_tool_routes_actual_plan_tool_and_emits_plan_update():
    events: list[Any] = []

    class FakeSession:
        async def send_event(self, event: Any) -> None:
            events.append(event)

    router = ToolRouter({})
    todos = [
        {"id": "1", "content": "Write characterization test", "status": "completed"}
    ]

    output, success = await router.call_tool(
        "plan_tool",
        {"todos": todos},
        session=FakeSession(),
        tool_call_id="tc_plan",
    )

    assert success is True
    assert "Write characterization test" in output
    assert [(event.event_type, event.data) for event in events] == [
        ("plan_update", {"plan": todos})
    ]


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
