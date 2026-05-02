from __future__ import annotations

import asyncio
import socket

import pytest

from agent.core.commands import COMMAND_REGISTRY
from agent.core.doctor_commands import render_doctor_command


def test_local_inference_doctor_renders_no_probe_metadata(monkeypatch) -> None:
    def fail_socket(*_args, **_kwargs):
        raise AssertionError("local inference doctor must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)

    output = render_doctor_command(
        "/doctor local-inference",
        env={},
    )

    assert "Local inference doctor" in output
    assert "mode: read-only metadata; no daemon probe" in output
    assert "ollama" in output
    assert "http://localhost:11434/v1/models" in output
    assert "llamacpp" in output
    assert "http://localhost:8080/v1/models" in output
    assert "status: unknown" in output


def test_local_inference_doctor_filters_runtime_and_model() -> None:
    output = render_doctor_command(
        "/doctor local-inference",
        "ollama local/ollama/llama3.2:latest",
        env={},
    )

    assert "ollama" in output
    assert "model: llama3.2:latest" in output
    assert "http://localhost:11434/v1/models" in output
    assert "llamacpp" not in output


def test_local_inference_doctor_reports_config_errors_redacted() -> None:
    output = render_doctor_command(
        "/doctor local-inference",
        "ollama",
        env={
            "MLJ_LOCAL_OLLAMA_BASE_URL": (
                "https://api.openai.com/v1?token=hf_doctorsecret123"
            )
        },
    )

    assert "status: config-error" in output
    assert "messages:" in output
    assert "hf_doctorsecret123" not in output
    assert "[REDACTED]" in output


def test_local_inference_doctor_rejects_ambiguous_args() -> None:
    output = render_doctor_command(
        "/doctor local-inference",
        "ollama local/llamacpp/qwen3-coder",
        env={},
    )

    assert "Runtime argument does not match" in output
    assert "Usage: /doctor local-inference" in output


def test_doctor_local_inference_command_is_implemented() -> None:
    registry = {command.name: command for command in COMMAND_REGISTRY}

    assert registry["/doctor"].implemented is False
    assert registry["/doctor local-inference"].implemented is True
    assert registry["/doctor local-inference"].mutates_state is False
    assert (
        registry["/doctor local-inference"].required_backend_capability
        == "project.local_inference_diagnostics"
    )


async def test_main_handler_dispatches_local_inference_doctor(monkeypatch, capsys) -> None:
    import agent.main as main_module

    calls = []

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("config")))
        return "doctor body"

    monkeypatch.setattr(main_module, "render_doctor_command", fake_render)
    config = object()

    result = await main_module._handle_slash_command(
        "/doctor local-inference ollama",
        config=config,
        session_holder=[],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/doctor local-inference", "ollama", config)]
    assert "doctor body" in capsys.readouterr().out


def test_doctor_command_dispatch_rejects_unexpected_commands() -> None:
    with pytest.raises(ValueError, match="Unsupported doctor command"):
        render_doctor_command("/doctor", env={})
