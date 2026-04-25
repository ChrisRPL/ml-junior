from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from agent.config import Config
from agent.core import agent_loop
from agent.core.agent_loop import Handlers
from agent.core.session import Session
from tests.helpers.fakes import FakeCompletion


class FakeAcompletion:
    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if not self.responses:
            raise AssertionError("Unexpected LLM call")
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeStream:
    def __init__(self, *chunks: Any) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def llm_message(content: str | None, tool_calls: list[Any] | None = None) -> Any:
    return SimpleNamespace(content=content, tool_calls=tool_calls)


def llm_tool_call(tool_call_id: str, name: str, arguments: str) -> Any:
    return SimpleNamespace(
        id=tool_call_id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def stream_chunk(
    content: str | None = None,
    finish_reason: str | None = None,
    total_tokens: int | None = None,
) -> Any:
    usage = None
    if total_tokens is not None:
        usage = SimpleNamespace(total_tokens=total_tokens)
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=None),
                finish_reason=finish_reason,
            )
        ],
        usage=usage,
    )


def stream_usage(total_tokens: int) -> Any:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(total_tokens=total_tokens),
    )


def event_types(events) -> list[str]:
    return [event.event_type for event in events]


def make_session(event_queue, config: Config, tool_router, stream: bool = False) -> Session:
    return Session(
        event_queue,
        config=config,
        tool_router=tool_router,
        stream=stream,
    )


def patch_agent_runtime(monkeypatch, fake_llm: FakeAcompletion) -> None:
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


async def test_run_agent_returns_normal_final_assistant_response(
    monkeypatch,
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    fake_llm = FakeAcompletion(
        FakeCompletion(llm_message("Final answer."), total_tokens=23)
    )
    patch_agent_runtime(monkeypatch, fake_llm)
    session = make_session(event_queue, test_config, fake_tool_router)

    result = await Handlers.run_agent(session, "hello")

    events = await event_collector(event_queue)
    assert result == "Final answer."
    assert fake_tool_router.calls == []
    assert event_types(events) == [
        "processing",
        "assistant_message",
        "turn_complete",
    ]
    assert events[1].data == {"content": "Final answer."}
    assert events[-1].data == {"history_size": len(session.context_manager.items)}
    assert [msg.role for msg in session.context_manager.items[-2:]] == [
        "user",
        "assistant",
    ]


async def test_run_agent_executes_one_successful_tool_call_then_continues(
    monkeypatch,
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    tool_call = llm_tool_call(
        "tc_echo",
        "echo",
        json.dumps({"value": 1}),
    )
    fake_llm = FakeAcompletion(
        FakeCompletion(llm_message(None, [tool_call]), finish_reason="tool_calls"),
        FakeCompletion(llm_message("Tool result handled."), total_tokens=31),
    )
    patch_agent_runtime(monkeypatch, fake_llm)
    session = make_session(event_queue, test_config, fake_tool_router)

    result = await Handlers.run_agent(session, "use the tool")

    events = await event_collector(event_queue)
    assert result == "Tool result handled."
    assert len(fake_llm.calls) == 2
    assert fake_llm.calls[0]["stream"] is False
    assert fake_tool_router.calls == [("echo", {"value": 1}, "tc_echo")]
    assert event_types(events) == [
        "processing",
        "tool_call",
        "tool_output",
        "assistant_message",
        "turn_complete",
    ]
    assert events[1].data == {
        "tool": "echo",
        "arguments": {"value": 1},
        "tool_call_id": "tc_echo",
    }
    assert events[2].data == {
        "tool": "echo",
        "tool_call_id": "tc_echo",
        "output": "echo:{'value': 1}",
        "success": True,
    }


async def test_malformed_tool_json_returns_tool_error_without_router_call(
    monkeypatch,
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    malformed_call = llm_tool_call("tc_bad", "echo", '{"value":')
    fake_llm = FakeAcompletion(
        FakeCompletion(llm_message(None, [malformed_call]), finish_reason="tool_calls"),
        FakeCompletion(llm_message("Recovered after malformed args."), total_tokens=29),
    )
    patch_agent_runtime(monkeypatch, fake_llm)
    session = make_session(event_queue, test_config, fake_tool_router)

    result = await Handlers.run_agent(session, "call malformed tool")

    events = await event_collector(event_queue)
    assert result == "Recovered after malformed args."
    assert fake_tool_router.calls == []
    assert event_types(events) == [
        "processing",
        "tool_call",
        "tool_output",
        "assistant_message",
        "turn_complete",
    ]
    assert events[1].data == {
        "tool": "echo",
        "arguments": {},
        "tool_call_id": "tc_bad",
    }
    assert events[2].data["success"] is False
    assert events[2].data["tool_call_id"] == "tc_bad"
    assert "malformed JSON" in events[2].data["output"]
    tool_messages = [
        msg for msg in session.context_manager.items if msg.role == "tool"
    ]
    assert len(tool_messages) == 1
    assert tool_messages[0].tool_call_id == "tc_bad"


async def test_streaming_final_response_emits_chunks_stream_end_and_turn_complete(
    monkeypatch,
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    fake_llm = FakeAcompletion(
        FakeStream(
            stream_chunk("Streamed "),
            stream_chunk("answer.", finish_reason="stop"),
            stream_usage(37),
        )
    )
    patch_agent_runtime(monkeypatch, fake_llm)
    session = make_session(event_queue, test_config, fake_tool_router, stream=True)

    result = await Handlers.run_agent(session, "stream please")

    events = await event_collector(event_queue)
    assert result == "Streamed answer."
    assert fake_llm.calls[0]["stream"] is True
    assert event_types(events) == [
        "processing",
        "assistant_chunk",
        "assistant_chunk",
        "assistant_stream_end",
        "turn_complete",
    ]
    assert [events[1].data, events[2].data] == [
        {"content": "Streamed "},
        {"content": "answer."},
    ]
    assert events[3].data == {}


async def test_llm_error_emits_error_event_without_turn_complete(
    monkeypatch,
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    fake_llm = FakeAcompletion(RuntimeError("offline boom"))
    patch_agent_runtime(monkeypatch, fake_llm)
    session = make_session(event_queue, test_config, fake_tool_router)

    result = await Handlers.run_agent(session, "fail")

    events = await event_collector(event_queue)
    assert result is None
    assert fake_tool_router.calls == []
    assert event_types(events) == ["processing", "error"]
    assert "offline boom" in events[1].data["error"]


async def test_max_iteration_stop_completes_turn_without_final_response(
    monkeypatch,
    event_queue,
    event_collector,
    fake_tool_router,
):
    config = Config(
        model_name="test/model",
        mcpServers={},
        save_sessions=False,
        max_iterations=1,
        reasoning_effort=None,
    )
    tool_call = llm_tool_call("tc_loop", "echo", json.dumps({"loop": True}))
    fake_llm = FakeAcompletion(
        FakeCompletion(llm_message(None, [tool_call]), finish_reason="tool_calls"),
        FakeCompletion(llm_message("Should not be consumed.")),
    )
    patch_agent_runtime(monkeypatch, fake_llm)
    session = make_session(event_queue, config, fake_tool_router)

    result = await Handlers.run_agent(session, "keep looping")

    events = await event_collector(event_queue)
    assert result is None
    assert len(fake_llm.calls) == 1
    assert len(fake_llm.responses) == 1
    assert fake_tool_router.calls == [("echo", {"loop": True}, "tc_loop")]
    assert event_types(events) == [
        "processing",
        "tool_call",
        "tool_output",
        "turn_complete",
    ]
