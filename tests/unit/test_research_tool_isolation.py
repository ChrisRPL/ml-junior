"""Research subagent isolation tests."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest
from litellm.types.utils import ChatCompletionMessageToolCall, Function

from agent.core.policy import RiskLevel
from agent.core.tools import ToolRouter
from agent.tools import research_tool
from agent.tools.hf_repo_files_tool import HF_REPO_FILES_TOOL_SPEC
from tests.helpers.fakes import FakeCompletion


class FakeAcompletion:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        return self.responses.pop(0)


class FakeRouter:
    def __init__(
        self,
        *,
        specs: list[dict[str, Any]] | None = None,
        decision: Any | None = None,
        call_result: tuple[str, bool] = ("tool-ok", True),
        fail_policy: bool = False,
        fail_call: bool = False,
    ) -> None:
        self._specs = specs or [tool_spec("read"), hf_repo_files_spec()]
        self.decision = decision or SimpleNamespace(
            allowed=True,
            requires_approval=False,
            risk="read_only",
            reason="read-only test policy",
        )
        self.call_result = call_result
        self.fail_policy = fail_policy
        self.fail_call = fail_call
        self.policy_calls: list[tuple[str, dict[str, Any], Any, Any]] = []
        self.calls: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def get_tool_specs_for_llm(self) -> list[dict[str, Any]]:
        return self._specs

    def evaluate_policy(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        config: Any = None,
        session: Any = None,
    ) -> Any:
        if self.fail_policy:
            raise AssertionError("research must not invoke router policy")
        self.policy_calls.append((tool_name, tool_args, config, session))
        if callable(self.decision):
            return self.decision(tool_name, tool_args, config, session)
        return self.decision

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        **kwargs: Any,
    ) -> tuple[str, bool]:
        if self.fail_call:
            raise AssertionError("research must not execute blocked tools")
        if "policy_approved" in kwargs:
            raise AssertionError("research must not pass policy_approved=True")
        self.calls.append((tool_name, arguments, kwargs))
        return self.call_result


class FakeSession:
    def __init__(self, router: FakeRouter, config: Any | None = None) -> None:
        self.tool_router = router
        self.config = config or SimpleNamespace(
            model_name="test/model",
            reasoning_effort=None,
        )
        self.hf_token = None
        self.events: list[Any] = []

    async def send_event(self, event: Any) -> None:
        self.events.append(event)


def tool_spec(name: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"Fake {name} tool",
            "parameters": {"type": "object", "properties": {}},
        },
    }


def hf_repo_files_spec() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": HF_REPO_FILES_TOOL_SPEC["name"],
            "description": HF_REPO_FILES_TOOL_SPEC["description"],
            "parameters": HF_REPO_FILES_TOOL_SPEC["parameters"],
        },
    }


def llm_message(content: str | None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def llm_tool_call(tool_call_id: str, name: str, arguments: dict[str, Any]) -> Any:
    return ChatCompletionMessageToolCall(
        id=tool_call_id,
        type="function",
        function=Function(name=name, arguments=json.dumps(arguments)),
    )


def patch_research_runtime(
    monkeypatch: pytest.MonkeyPatch, fake_llm: FakeAcompletion
) -> None:
    monkeypatch.setattr(research_tool, "acompletion", fake_llm)
    monkeypatch.setattr(
        research_tool,
        "_resolve_llm_params",
        lambda model_name, hf_token, reasoning_effort=None: {"model": model_name},
    )
    monkeypatch.setattr(
        research_tool,
        "with_prompt_caching",
        lambda messages, tools, model: (messages, tools),
    )


async def run_research_tool_call(
    monkeypatch: pytest.MonkeyPatch,
    router: FakeRouter,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    config: Any | None = None,
) -> tuple[tuple[str, bool], FakeAcompletion]:
    fake_llm = FakeAcompletion(
        FakeCompletion(
            llm_message(None, [llm_tool_call("tc_subtool", tool_name, arguments)]),
            finish_reason="tool_calls",
        ),
        FakeCompletion(llm_message("final summary")),
    )
    patch_research_runtime(monkeypatch, fake_llm)
    session = FakeSession(router, config=config)

    result = await research_tool.research_handler(
        {"task": "research isolation test"},
        session=session,
        tool_call_id="tc_research",
    )

    return result, fake_llm


def message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    return str(getattr(message, "content", ""))


def last_tool_result(fake_llm: FakeAcompletion) -> str:
    return message_content(fake_llm.calls[-1]["messages"][-1])


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "list", "repo_id": "org/repo"},
        {"operation": "read", "repo_id": "org/repo", "path": "README.md"},
    ],
)
def test_real_router_keeps_hf_repo_file_reads_read_only(
    arguments: dict[str, Any],
) -> None:
    router = ToolRouter({})

    decision = router.evaluate_policy("hf_repo_files", arguments)

    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.risk is RiskLevel.READ_ONLY
    assert decision.side_effects == []
    assert decision.credential_usage == ["hf_token"]


async def test_research_specs_do_not_expose_bash_and_hf_repo_files_is_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = FakeRouter(specs=[tool_spec("bash"), tool_spec("read"), hf_repo_files_spec()])
    fake_llm = FakeAcompletion(FakeCompletion(llm_message("done")))
    patch_research_runtime(monkeypatch, fake_llm)

    output, success = await research_tool.research_handler(
        {"task": "inspect docs"},
        session=FakeSession(router),
    )

    tools = fake_llm.calls[0]["tools"]
    names = [tool["function"]["name"] for tool in tools]
    hf_spec = next(tool for tool in tools if tool["function"]["name"] == "hf_repo_files")
    hf_properties = hf_spec["function"]["parameters"]["properties"]

    assert (output, success) == ("done", True)
    assert "bash" not in names
    assert "bash" not in research_tool.RESEARCH_TOOL_NAMES
    assert hf_properties["operation"]["enum"] == ["list", "read"]
    assert {"content", "patterns", "create_pr", "commit_message"}.isdisjoint(
        hf_properties
    )
    assert "upload" not in hf_spec["function"]["description"].lower()
    assert "delete" not in hf_spec["function"]["description"].lower()
    assert "upload/delete are not available in research" in (
        research_tool.RESEARCH_SYSTEM_PROMPT.lower()
    )


async def test_research_blocks_fabricated_bash_without_router_policy_or_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = FakeRouter(fail_policy=True, fail_call=True)

    result, fake_llm = await run_research_tool_call(
        monkeypatch,
        router,
        "bash",
        {"command": "echo pwned"},
    )

    assert result == ("final summary", True)
    assert router.policy_calls == []
    assert router.calls == []
    assert "not available for research" in last_tool_result(fake_llm)


@pytest.mark.parametrize("operation", ["upload", "delete"])
async def test_research_blocks_hf_repo_files_mutations_without_router_policy_or_execution(
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    router = FakeRouter(fail_policy=True, fail_call=True)

    result, fake_llm = await run_research_tool_call(
        monkeypatch,
        router,
        "hf_repo_files",
        {"operation": operation, "repo_id": "org/repo", "path": "README.md"},
    )

    assert result == ("final summary", True)
    assert router.policy_calls == []
    assert router.calls == []
    assert "read-only in research" in last_tool_result(fake_llm)


@pytest.mark.parametrize(
    "arguments",
    [
        {"operation": "list", "repo_id": "org/repo"},
        {"operation": "read", "repo_id": "org/repo", "path": "README.md"},
    ],
)
async def test_research_allows_hf_repo_files_list_and_read_after_policy(
    monkeypatch: pytest.MonkeyPatch,
    arguments: dict[str, Any],
) -> None:
    router = FakeRouter(call_result=("repo file output", True))

    result, _fake_llm = await run_research_tool_call(
        monkeypatch,
        router,
        "hf_repo_files",
        arguments,
    )

    assert result == ("final summary", True)
    assert [(name, args) for name, args, _config, _session in router.policy_calls] == [
        ("hf_repo_files", arguments)
    ]
    assert [(name, args) for name, args, _kwargs in router.calls] == [
        ("hf_repo_files", arguments)
    ]
    assert "policy_approved" not in router.calls[0][2]


async def test_research_blocks_policy_approval_required_tools_without_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = FakeRouter(
        decision=SimpleNamespace(
            allowed=True,
            requires_approval=True,
            risk="read_only",
            reason="approval required by router",
        ),
        fail_call=True,
    )

    result, fake_llm = await run_research_tool_call(
        monkeypatch,
        router,
        "read",
        {"path": "/tmp/file.py"},
    )

    assert result == ("final summary", True)
    assert [(name, args) for name, args, _config, _session in router.policy_calls] == [
        ("read", {"path": "/tmp/file.py"})
    ]
    assert router.calls == []
    assert "approval required by router" in last_tool_result(fake_llm)


@pytest.mark.parametrize(
    "config",
    [
        SimpleNamespace(model_name="test/model", reasoning_effort=None, yolo_mode=True),
        SimpleNamespace(model_name="test/model", reasoning_effort=None, autonomy="full"),
    ],
)
async def test_yolo_and_autonomy_cannot_weaken_research_risk_gate(
    monkeypatch: pytest.MonkeyPatch,
    config: Any,
) -> None:
    def auto_approved_high_risk(
        _tool_name: str,
        _tool_args: dict[str, Any],
        seen_config: Any,
        _session: Any,
    ) -> Any:
        assert seen_config is config
        return SimpleNamespace(
            allowed=True,
            requires_approval=False,
            risk="high",
            reason="Auto-approved by yolo/autonomy mode.",
        )

    router = FakeRouter(decision=auto_approved_high_risk, fail_call=True)

    result, fake_llm = await run_research_tool_call(
        monkeypatch,
        router,
        "read",
        {"path": "/tmp/file.py"},
        config=config,
    )

    assert result == ("final summary", True)
    assert [(name, args) for name, args, _config, _session in router.policy_calls] == [
        ("read", {"path": "/tmp/file.py"})
    ]
    assert router.calls == []
    assert "effective risk is 'high'" in last_tool_result(fake_llm)
