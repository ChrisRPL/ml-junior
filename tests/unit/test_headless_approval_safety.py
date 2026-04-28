"""Headless CLI approval safety tests."""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from agent import main as agent_main
from agent.config import Config
from agent.core.session import OpType


def config_for_headless(**overrides: Any) -> Config:
    values: dict[str, Any] = {
        "model_name": "test/model",
        "mcpServers": {},
        "save_sessions": False,
        "reasoning_effort": None,
    }
    values.update(overrides)
    return Config(**values)


class FakeToolRouter:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        self.tools: dict[str, Any] = {}

    async def __aenter__(self) -> "FakeToolRouter":
        return self

    async def __aexit__(self, *_args: Any) -> None:
        return None


def install_headless_runtime(
    monkeypatch: pytest.MonkeyPatch,
    *,
    operations: list[OpType],
    approvals: list[dict[str, Any]],
    yolo_modes: list[bool],
) -> None:
    monkeypatch.setattr(agent_main, "_get_hf_token", lambda: "hf_test_token")
    monkeypatch.setattr(agent_main, "load_config", lambda _path: config_for_headless())
    monkeypatch.setattr(agent_main, "ToolRouter", FakeToolRouter)

    async def fake_submission_loop(
        submission_queue: asyncio.Queue,
        event_queue: asyncio.Queue,
        *,
        config: Config,
        **_kwargs: Any,
    ) -> None:
        yolo_modes.append(config.yolo_mode)
        await event_queue.put(SimpleNamespace(event_type="ready", data={}))

        user_submission = await asyncio.wait_for(submission_queue.get(), timeout=1.0)
        operations.append(user_submission.operation.op_type)
        assert user_submission.operation.op_type == OpType.USER_INPUT
        assert user_submission.operation.data == {"text": "train"}

        await event_queue.put(
            SimpleNamespace(
                event_type="approval_required",
                data={
                    "count": 1,
                    "tools": [
                        {
                            "tool": "hf_jobs",
                            "tool_call_id": "tc_job",
                            "arguments": {
                                "operation": "run",
                                "hardware_flavor": "a10g-large",
                            },
                            "reason": "GPU job launch requires approval.",
                        }
                    ],
                },
            )
        )

        next_submission = await asyncio.wait_for(submission_queue.get(), timeout=1.0)
        operations.append(next_submission.operation.op_type)

        if next_submission.operation.op_type == OpType.EXEC_APPROVAL:
            approvals.extend(next_submission.operation.data["approvals"])
            await event_queue.put(
                SimpleNamespace(
                    event_type="turn_complete",
                    data={"history_size": 2},
                )
            )
            shutdown_submission = await asyncio.wait_for(
                submission_queue.get(), timeout=1.0
            )
            operations.append(shutdown_submission.operation.op_type)
            assert shutdown_submission.operation.op_type == OpType.SHUTDOWN
            return

        assert next_submission.operation.op_type == OpType.SHUTDOWN

    monkeypatch.setattr(agent_main, "submission_loop", fake_submission_loop)


async def test_headless_default_exits_on_required_approval_without_enabling_yolo(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    operations: list[OpType] = []
    approvals: list[dict[str, Any]] = []
    yolo_modes: list[bool] = []
    install_headless_runtime(
        monkeypatch,
        operations=operations,
        approvals=approvals,
        yolo_modes=yolo_modes,
    )

    result = await asyncio.wait_for(
        agent_main.headless_main("train", stream=False),
        timeout=2.0,
    )

    assert result == 2
    assert yolo_modes == [False]
    assert operations == [OpType.USER_INPUT, OpType.SHUTDOWN]
    assert approvals == []

    stderr = capsys.readouterr().err
    assert "approval required" in stderr.lower()
    assert "Pending tools" in stderr
    assert "hf_jobs" in stderr
    assert "tc_job" in stderr
    assert "GPU job launch requires approval." in stderr
    assert "--yolo" in stderr
    assert "--auto-approve" in stderr


async def test_headless_auto_approve_flag_preserves_auto_approval_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operations: list[OpType] = []
    approvals: list[dict[str, Any]] = []
    yolo_modes: list[bool] = []
    install_headless_runtime(
        monkeypatch,
        operations=operations,
        approvals=approvals,
        yolo_modes=yolo_modes,
    )

    result = await asyncio.wait_for(
        agent_main.headless_main("train", stream=False, auto_approve=True),
        timeout=2.0,
    )

    assert result == 0
    assert yolo_modes == [True]
    assert operations == [
        OpType.USER_INPUT,
        OpType.EXEC_APPROVAL,
        OpType.SHUTDOWN,
    ]
    assert approvals == [
        {
            "tool_call_id": "tc_job",
            "approved": True,
            "feedback": None,
        }
    ]


@pytest.mark.parametrize(
    ("extra_args", "expected_auto_approve"),
    [
        ([], False),
        (["--yolo"], True),
        (["--auto-approve"], True),
    ],
)
def test_cli_headless_auto_approve_flags(
    monkeypatch: pytest.MonkeyPatch,
    extra_args: list[str],
    expected_auto_approve: bool,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_headless_main(prompt: str, **kwargs: Any) -> int:
        captured["prompt"] = prompt
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(agent_main, "headless_main", fake_headless_main)
    monkeypatch.setattr(sys, "argv", ["ml-intern", *extra_args, "--no-stream", "train"])

    with pytest.raises(SystemExit) as exc_info:
        agent_main.cli()

    assert exc_info.value.code == 0
    assert captured["prompt"] == "train"
    assert captured["auto_approve"] is expected_auto_approve
    assert captured["stream"] is False
