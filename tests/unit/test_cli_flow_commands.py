from __future__ import annotations

import asyncio
import builtins
import sys
import tomllib
from pathlib import Path

import pytest

from agent.core.commands import COMMAND_REGISTRY
from agent.core.flow_commands import (
    FlowCommandBackendUnavailable,
    render_flow_catalog,
    render_flow_command,
    render_flow_preview,
)


EXPECTED_BUILTIN_IDS = [
    "build-evaluation-harness",
    "dataset-audit",
    "fine-tune-model",
    "implement-architecture",
    "literature-overview",
    "reproduce-paper",
]


def test_package_includes_backend_flow_templates() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert "backend*" in pyproject["tool"]["setuptools"]["packages"]["find"]["include"]
    assert pyproject["tool"]["setuptools"]["package-data"]["backend"] == [
        "builtin_flow_templates/*.json"
    ]


def test_flow_catalog_renders_builtin_ids_and_planned_mutating_commands() -> None:
    output = render_flow_catalog()

    assert output.startswith("Built-in flows\n")
    for template_id in EXPECTED_BUILTIN_IDS:
        assert template_id in output
    assert "/flows                 implemented read-only" in output
    assert "/flow preview <id>     implemented read-only" in output
    assert "/flow start <id>       planned" in output
    assert "/flow pause [id]       planned" in output
    assert "/flow resume [id]      planned" in output
    assert "/flow fork <id> [name] planned" in output


def test_flow_preview_renders_read_only_template_surfaces() -> None:
    loaded_before = set(sys.modules)

    output = render_flow_preview("fine-tune-model")

    assert "Flow: Fine-Tune Model (fine-tune-model, v1)" in output
    assert "Inputs\n  base_model (string, required)" in output
    assert "Budgets\n  gpu_h:6.0, runs:5, wall_h:18.0, llm_usd:15.0" in output
    assert "Phases\n  1. goal-and-base-model - Goal And Base Model [pending]" in output
    assert "approvals: launch-training" in output
    assert "Approvals\n  launch-training (medium) launch fine-tuning-job" in output
    assert "Verifiers\n  model-choice-justified (manual, required)" in output
    loaded_by_preview = set(sys.modules) - loaded_before
    assert "backend.main" not in loaded_by_preview
    assert "backend.routes.agent" not in loaded_by_preview


def test_flow_preview_requires_id_and_reports_known_missing_ids() -> None:
    assert render_flow_preview(" ") == (
        "Usage: /flow preview <id>\nRun /flows to list built-in flow ids."
    )

    output = render_flow_preview("missing-flow")

    assert "Flow not found: missing-flow" in output
    assert "Unknown built-in flow template: missing-flow" in output
    assert "Known flows: build-evaluation-harness, dataset-audit" in output


def test_flow_command_dispatch_rejects_unexpected_commands() -> None:
    with pytest.raises(ValueError, match="Unsupported flow command"):
        render_flow_command("/flow start", "fine-tune-model")


def test_mutating_flow_commands_remain_planned() -> None:
    registry = {command.name: command for command in COMMAND_REGISTRY}

    assert registry["/flows"].implemented is True
    assert registry["/flow preview"].implemented is True
    for name in {"/flow start", "/flow pause", "/flow resume", "/flow fork"}:
        assert registry[name].implemented is False
        assert registry[name].mutates_state is True


async def test_main_handler_dispatches_read_only_flow_commands(monkeypatch, capsys) -> None:
    import agent.main as main_module

    calls = []

    def fake_render(command: str, arguments: str) -> str:
        calls.append((command, arguments))
        return "preview body"

    monkeypatch.setattr(main_module, "render_flow_command", fake_render)

    result = await main_module._handle_slash_command(
        "/flow preview fine-tune-model",
        config=object(),
        session_holder=[],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/flow preview", "fine-tune-model")]
    assert "preview body" in capsys.readouterr().out

    result = await main_module._handle_slash_command(
        "/flow start fine-tune-model",
        config=object(),
        session_holder=[],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [("/flow preview", "fine-tune-model")]
    assert "/flow start is not implemented yet." in capsys.readouterr().out


def test_backend_import_unavailable_reports_packaging_boundary(monkeypatch) -> None:
    import agent.core.flow_commands as flow_commands

    real_import = builtins.__import__

    def blocked_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "backend.flow_templates":
            raise ModuleNotFoundError(name="backend")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    with pytest.raises(FlowCommandBackendUnavailable, match="unavailable"):
        flow_commands._load_flow_helpers()
