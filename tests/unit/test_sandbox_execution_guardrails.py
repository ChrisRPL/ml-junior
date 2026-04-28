"""Sandbox execution path and redaction guardrails."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from agent.core.tools import ToolRouter
from agent.tools.sandbox_client import Sandbox, ToolResult


HF_TOKEN = "hf_sandboxsecret123456789"
GENERIC_SECRET = "plain-secret-value-123456789"


def _sandbox() -> Sandbox:
    sandbox = Sandbox(space_id="owner/sandbox-test", token=HF_TOKEN)
    sandbox._remember_secrets(GENERIC_SECRET)
    return sandbox


def test_sandbox_create_logs_are_redacted_without_network(monkeypatch) -> None:
    logs: list[str] = []

    class _Runtime:
        stage = "RUNNING"
        hardware = f"cpu-basic {GENERIC_SECRET}"

    class _FakeHfApi:
        def __init__(self, token: str | None = None) -> None:
            self.token = token

        def duplicate_space(self, **_kwargs: Any) -> None:
            return None

        def add_space_secret(self, *_args: Any, **_kwargs: Any) -> None:
            return None

        def get_space_runtime(self, _space_id: str) -> _Runtime:
            return _Runtime()

    monkeypatch.setattr("agent.tools.sandbox_client.HfApi", _FakeHfApi)
    monkeypatch.setattr(Sandbox, "_setup_server", staticmethod(lambda *_a, **kw: kw["log"](
        f"setup {HF_TOKEN} {GENERIC_SECRET}"
    )))
    monkeypatch.setattr(Sandbox, "_wait_for_api", lambda self, **_kw: None)

    sandbox = Sandbox.create(
        owner="owner",
        template=HF_TOKEN,
        token=HF_TOKEN,
        secrets={"HF_TOKEN": HF_TOKEN, "EXTRA_SECRET": GENERIC_SECRET},
        wait_timeout=1,
        log=logs.append,
    )

    rendered_logs = "\n".join(logs)
    assert sandbox.space_id.startswith("owner/sandbox-")
    assert HF_TOKEN not in rendered_logs
    assert GENERIC_SECRET not in rendered_logs
    assert "[REDACTED]" in rendered_logs


def test_sandbox_bash_rejects_work_dir_outside_allowed_roots(monkeypatch) -> None:
    sandbox = _sandbox()
    calls: list[tuple[str, dict[str, Any], float | None]] = []

    def fake_call(endpoint: str, payload: dict[str, Any], timeout: float | None = None):
        calls.append((endpoint, payload, timeout))
        return ToolResult(success=True, output="should not run")

    monkeypatch.setattr(sandbox, "_call", fake_call)

    result = sandbox.bash("pwd", work_dir="/etc")

    assert result.success is False
    assert calls == []
    assert "outside allowed roots" in result.error
    assert "/app" in result.error
    assert "/tmp" in result.error


def test_sandbox_read_write_edit_reject_paths_outside_allowed_roots(monkeypatch) -> None:
    sandbox = _sandbox()
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_call(endpoint: str, payload: dict[str, Any], timeout: float | None = None):
        calls.append((endpoint, payload))
        return ToolResult(success=True, output="should not run")

    monkeypatch.setattr(sandbox, "_call", fake_call)

    read_result = sandbox.read("/etc/passwd")
    write_result = sandbox.write("/var/tmp/file.txt", "content")
    edit_result = sandbox.edit("/home/user/file.txt", "old", "new")

    assert read_result.success is False
    assert write_result.success is False
    assert edit_result.success is False
    assert calls == []
    for result in (read_result, write_result, edit_result):
        assert "outside allowed roots" in result.error


def test_sandbox_relative_paths_are_normalized_and_read_before_write_is_preserved(
    monkeypatch,
) -> None:
    sandbox = _sandbox()
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_call(endpoint: str, payload: dict[str, Any], timeout: float | None = None):
        calls.append((endpoint, payload))
        if endpoint == "exists":
            return ToolResult(success=True, output="true")
        if endpoint == "read":
            return ToolResult(success=True, output="1\told\n")
        return ToolResult(success=True, output=f"{endpoint} ok")

    monkeypatch.setattr(sandbox, "_call", fake_call)

    blocked_write = sandbox.write("train.py", "new\n")
    read_result = sandbox.read("train.py")
    write_result = sandbox.write("train.py", "new\n")
    edit_result = sandbox.edit("train.py", "new", "newer")

    assert blocked_write.success is False
    assert "has not been read" in blocked_write.error
    assert read_result.success is True
    assert write_result.success is True
    assert edit_result.success is True
    assert calls[0] == ("exists", {"path": "/app/train.py"})
    assert calls[1][0] == "read"
    assert calls[1][1]["path"] == "/app/train.py"
    assert calls[2] == ("write", {"path": "/app/train.py", "content": "new\n"})
    assert calls[3][0] == "edit"
    assert calls[3][1]["path"] == "/app/train.py"


def test_sandbox_outputs_and_errors_are_redacted_before_return(monkeypatch) -> None:
    sandbox = _sandbox()

    def fake_call(endpoint: str, payload: dict[str, Any], timeout: float | None = None):
        return ToolResult(
            success=False,
            output=f"HF_TOKEN={HF_TOKEN}\nsecret={GENERIC_SECRET}",
            error=f"Authorization: Bearer {HF_TOKEN}; {GENERIC_SECRET}",
        )

    monkeypatch.setattr(sandbox, "_call", fake_call)

    result = sandbox.bash("env", work_dir="/app")

    assert result.success is False
    assert HF_TOKEN not in result.output
    assert HF_TOKEN not in result.error
    assert GENERIC_SECRET not in result.output
    assert GENERIC_SECRET not in result.error
    assert "HF_TOKEN=[REDACTED]" in result.output


async def test_sandbox_tool_handler_blocks_outside_paths_before_fake_remote_call() -> None:
    class _FakeSandbox:
        work_dir = "/app"
        _secret_values = {GENERIC_SECRET}

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
            self.calls.append((name, args))
            return ToolResult(success=True, output="should not run")

    sandbox = _FakeSandbox()
    session = SimpleNamespace(sandbox=sandbox, hf_token=HF_TOKEN)
    router = ToolRouter({})

    result = await router.call_tool_result(
        "read",
        {"path": "/etc/passwd"},
        session=session,
    )

    assert result.success is False
    assert sandbox.calls == []
    assert "outside allowed roots" in result.display_text


async def test_sandbox_tool_handler_redacts_fake_remote_output_and_normalizes_args() -> None:
    class _FakeSandbox:
        work_dir = "/app"
        _secret_values = {GENERIC_SECRET}

        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        def call_tool(self, name: str, args: dict[str, Any]) -> ToolResult:
            self.calls.append((name, args))
            return ToolResult(
                success=True,
                output=f"token={HF_TOKEN}\nsecret={GENERIC_SECRET}",
            )

    sandbox = _FakeSandbox()
    session = SimpleNamespace(sandbox=sandbox, hf_token=HF_TOKEN)
    router = ToolRouter({})

    result = await router.call_tool_result(
        "bash",
        {"command": "pwd", "work_dir": "subdir"},
        session=session,
        policy_approved=True,
    )

    assert result.success is True
    assert HF_TOKEN not in result.display_text
    assert GENERIC_SECRET not in result.display_text
    assert "[REDACTED]" in result.display_text
    assert sandbox.calls == [
        ("bash", {"command": "pwd", "work_dir": "/app/subdir"})
    ]
