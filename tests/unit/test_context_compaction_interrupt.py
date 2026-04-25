"""Offline coverage for context compaction and interruption cleanup."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from typing import Any

os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "true")

from litellm import ChatCompletionMessageToolCall as ToolCall
from litellm import Message

from agent.config import Config
from agent.context_manager.manager import ContextManager
from agent.core.agent_loop import Handlers
from agent.core.session import Session
from tests.helpers.fakes import FakeCompletion


def _context_manager(*, untouched_messages: int) -> ContextManager:
    cm = ContextManager(
        model_max_tokens=100,
        compact_size=0.1,
        untouched_messages=untouched_messages,
        tool_specs=[],
        hf_token=None,
    )
    cm.running_context_usage = 95
    return cm


def _patch_compaction_boundaries(
    monkeypatch: Any,
    *,
    summary: str = "summary of compacted history",
    seen_messages: list[Message] | None = None,
) -> None:
    async def fake_summarize(
        messages: list[Message],
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[str, int]:
        if seen_messages is not None:
            seen_messages[:] = list(messages)
        return summary, 5

    monkeypatch.setattr(
        "agent.context_manager.manager.summarize_messages",
        fake_summarize,
    )
    monkeypatch.setattr("litellm.token_counter", lambda **_kwargs: 41)


def _tool_call(tool_call_id: str, name: str, arguments: dict[str, Any]) -> ToolCall:
    return ToolCall(
        id=tool_call_id,
        type="function",
        function={"name": name, "arguments": json.dumps(arguments)},
    )


def _assert_tool_call_pairing_is_valid(messages: list[Message]) -> None:
    for index, message in enumerate(messages):
        if getattr(message, "role", None) != "assistant":
            continue
        tool_calls = getattr(message, "tool_calls", None)
        if not tool_calls:
            continue

        expected_ids = [tool_call.id for tool_call in tool_calls]
        following_tool_ids: list[str] = []
        for following in messages[index + 1 :]:
            if getattr(following, "role", None) != "tool":
                break
            following_tool_ids.append(getattr(following, "tool_call_id", None))

        assert following_tool_ids[: len(expected_ids)] == expected_ids


class _FakeToolRouter:
    def __init__(
        self,
        handlers: dict[
            str,
            Callable[[dict[str, Any]], Awaitable[tuple[str, bool]]],
        ],
    ) -> None:
        self.handlers = handlers
        self.calls: list[tuple[str, dict[str, Any], str | None]] = []

    def get_tool_specs_for_llm(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": f"Fake {name} tool",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
            for name in self.handlers
        ]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        session: Any = None,
        tool_call_id: str | None = None,
    ) -> tuple[str, bool]:
        self.calls.append((tool_name, arguments, tool_call_id))
        return await self.handlers[tool_name](arguments)


class _FakeSandbox:
    def __init__(self) -> None:
        self.kill_all_calls = 0

    def kill_all(self) -> str:
        self.kill_all_calls += 1
        return "killed"


async def test_compaction_preserves_original_goal_and_recent_messages(
    monkeypatch: Any,
) -> None:
    summarized_messages: list[Message] = []
    _patch_compaction_boundaries(
        monkeypatch,
        summary="summary of old implementation details",
        seen_messages=summarized_messages,
    )
    cm = _context_manager(untouched_messages=3)
    original_goal = "User goal: build a deterministic offline QA harness."
    recent_messages = [
        "Recent user request: keep only focused tests.",
        "Recent assistant note: tests will monkeypatch network boundaries.",
        "Recent user constraint: write only this test file.",
    ]

    cm.add_message(Message(role="user", content=original_goal))
    cm.add_message(Message(role="assistant", content="Old implementation note."))
    cm.add_message(Message(role="user", content="Old clarification."))
    cm.add_message(Message(role="assistant", content="Old resolved detail."))
    cm.add_message(Message(role="user", content=recent_messages[0]))
    cm.add_message(Message(role="assistant", content=recent_messages[1]))
    cm.add_message(Message(role="user", content=recent_messages[2]))

    await cm.compact(model_name="test/model", tool_specs=[], hf_token=None)

    compacted_contents = [message.content for message in cm.items]
    summarized_contents = [message.content for message in summarized_messages]
    assert compacted_contents[1] == original_goal
    assert compacted_contents[-3:] == recent_messages
    assert "summary of old implementation details" in compacted_contents
    assert original_goal not in summarized_contents
    assert not any(message in summarized_contents for message in recent_messages)
    assert cm.running_context_usage == 41


async def test_compaction_patches_dangling_recent_tool_call(
    monkeypatch: Any,
) -> None:
    _patch_compaction_boundaries(monkeypatch)
    cm = _context_manager(untouched_messages=2)
    call = _tool_call("call_recent", "echo", {"args": {"value": 1}})

    cm.add_message(Message(role="user", content="Original goal stays outside summary."))
    cm.add_message(Message(role="assistant", content="Old assistant note."))
    cm.add_message(Message(role="user", content="Old user question."))
    cm.add_message(Message(role="assistant", content="Old answer."))
    cm.add_message(Message(role="user", content="Recent user message."))
    cm.add_message(Message(role="assistant", content=None, tool_calls=[call]))

    await cm.compact(model_name="test/model", tool_specs=[], hf_token=None)

    messages = cm.get_messages()
    tool_results = [
        message
        for message in messages
        if getattr(message, "role", None) == "tool"
        and getattr(message, "tool_call_id", None) == "call_recent"
    ]
    assert len(tool_results) == 1
    assert tool_results[0].content == "Tool was not executed (interrupted or error)."
    _assert_tool_call_pairing_is_valid(messages)


async def test_interrupt_emits_interrupted_and_cleans_runtime_boundaries(
    monkeypatch: Any,
    event_queue: asyncio.Queue,
    event_collector: Callable[[asyncio.Queue], Awaitable[list[Any]]],
) -> None:
    started = asyncio.Event()
    never_finish = asyncio.Event()
    cancelled_jobs: list[tuple[str | None, str]] = []

    async def slow_tool(_args: dict[str, Any]) -> tuple[str, bool]:
        started.set()
        await never_finish.wait()
        return "unexpected", True

    class FakeHfApi:
        def __init__(self, token: str | None = None) -> None:
            self.token = token

        def cancel_job(self, job_id: str) -> None:
            cancelled_jobs.append((self.token, job_id))

    async def fake_acompletion(**_kwargs: Any) -> FakeCompletion:
        message = Message(
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call_slow", "slow", {"args": {"seconds": 60}}),
            ],
        )
        return FakeCompletion(message, finish_reason="tool_calls", total_tokens=12)

    monkeypatch.setattr("agent.core.agent_loop.acompletion", fake_acompletion)
    monkeypatch.setattr("huggingface_hub.HfApi", FakeHfApi)

    router = _FakeToolRouter({"slow": slow_tool})
    cm = ContextManager(
        model_max_tokens=1_000,
        compact_size=0.1,
        untouched_messages=5,
        tool_specs=router.get_tool_specs_for_llm(),
        hf_token=None,
    )
    session = Session(
        event_queue,
        config=Config(
            model_name="test/model",
            mcpServers={},
            save_sessions=False,
            max_iterations=2,
            reasoning_effort=None,
        ),
        tool_router=router,
        context_manager=cm,
        hf_token="hf_test_token",
        stream=False,
    )
    sandbox = _FakeSandbox()
    session.sandbox = sandbox
    session._running_job_ids.update({"job-a", "job-b"})

    run_task = asyncio.create_task(Handlers.run_agent(session, "run slow tool"))
    await asyncio.wait_for(started.wait(), timeout=1)

    session.cancel()
    await asyncio.wait_for(run_task, timeout=1)

    events = await event_collector(event_queue)
    event_types = [event.event_type for event in events]
    assert "interrupted" in event_types
    assert "turn_complete" not in event_types
    assert sandbox.kill_all_calls >= 1
    assert {job_id for _token, job_id in cancelled_jobs} == {"job-a", "job-b"}
    assert {token for token, _job_id in cancelled_jobs} == {"hf_test_token"}
    assert session._running_job_ids == set()
