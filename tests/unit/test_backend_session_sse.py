"""Backend session and SSE characterization tests for Phase 0."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Callable

import pytest

import session_manager as session_module
from agent.core.session import Event
from routes.agent import _sse_response


async def _wait_until(predicate: Callable[[], bool], timeout: float = 1.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


async def _queue_get(queue: asyncio.Queue, timeout: float = 1.0) -> Any:
    return await asyncio.wait_for(queue.get(), timeout=timeout)


class FakeToolRouter:
    def __init__(self, mcp_servers: dict[str, Any] | None = None, hf_token: str | None = None):
        self.mcp_servers = mcp_servers or {}
        self.hf_token = hf_token
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.entered = False


class FakeSession:
    def __init__(
        self,
        event_queue: asyncio.Queue,
        config: Any,
        tool_router: FakeToolRouter,
        hf_token: str | None = None,
    ):
        self.event_queue = event_queue
        self.config = config
        self.tool_router = tool_router
        self.hf_token = hf_token
        self.context_manager = SimpleNamespace(items=[])
        self.pending_approval = None
        self.is_running = True
        self.sandbox = None
        self._cancelled = False

    async def send_event(self, event: Event) -> None:
        await self.event_queue.put(event)

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


@pytest.fixture
def manager(test_config) -> session_module.SessionManager:
    mgr = session_module.SessionManager()
    mgr.config = test_config
    return mgr


@pytest.fixture
def offline_session_constructors(monkeypatch):
    monkeypatch.setattr(session_module, "ToolRouter", FakeToolRouter)
    monkeypatch.setattr(session_module, "Session", FakeSession)


async def test_session_manager_create_list_delete_behavior(
    manager,
    offline_session_constructors,
):
    first = await manager.create_session(
        user_id="alice",
        hf_token="hf_alice",
        model="test/alternate",
    )
    second = await manager.create_session(user_id="bob")

    try:
        await _wait_until(lambda: manager.sessions[first].broadcaster is not None)
        await _wait_until(lambda: manager.sessions[second].broadcaster is not None)

        assert manager.active_session_count == 2
        assert manager.sessions[first].session.hf_token == "hf_alice"
        assert manager.sessions[first].session.config.model_name == "test/alternate"

        alice_sessions = manager.list_sessions(user_id="alice")
        assert [item["session_id"] for item in alice_sessions] == [first]
        assert {item["session_id"] for item in manager.list_sessions(user_id="dev")} == {
            first,
            second,
        }

        assert await manager.delete_session(first) is True
        assert first not in manager.sessions
        assert manager.active_session_count == 1
        assert await manager.delete_session(first) is False
    finally:
        await manager.delete_session(first)
        await manager.delete_session(second)


def test_pending_approval_is_included_in_session_info(manager):
    tool_call = SimpleNamespace(
        id="tc_123",
        function=SimpleNamespace(
            name="hf_jobs",
            arguments=json.dumps({"operation": "run", "hardware": "cpu-basic"}),
        ),
    )
    fake_session = SimpleNamespace(
        config=SimpleNamespace(model_name="test/model"),
        context_manager=SimpleNamespace(items=["user", "assistant"]),
        pending_approval={"tool_calls": [tool_call]},
    )
    manager.sessions["session-a"] = session_module.AgentSession(
        session_id="session-a",
        session=fake_session,
        tool_router=SimpleNamespace(),
        submission_queue=asyncio.Queue(),
        user_id="alice",
    )

    info = manager.get_session_info("session-a")

    assert info is not None
    assert info["message_count"] == 2
    assert info["pending_approval"] == [
        {
            "tool": "hf_jobs",
            "tool_call_id": "tc_123",
            "arguments": {"operation": "run", "hardware": "cpu-basic"},
        }
    ]


async def test_sse_response_closes_and_unsubscribes_on_terminal_event():
    class TrackingBroadcaster:
        def __init__(self):
            self.unsubscribed: list[int] = []

        def unsubscribe(self, sub_id: int) -> None:
            self.unsubscribed.append(sub_id)

    broadcaster = TrackingBroadcaster()
    event_queue = asyncio.Queue()
    await event_queue.put({"event_type": "assistant_stream", "data": {"delta": "hi"}})
    await event_queue.put({"event_type": "turn_complete", "data": {"ok": True}})
    await event_queue.put({"event_type": "assistant_stream", "data": {"delta": "late"}})

    response = _sse_response(broadcaster, event_queue, sub_id=7)

    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)

    assert len(chunks) == 2
    assert json.loads(chunks[0].removeprefix("data: ").strip()) == {
        "event_type": "assistant_stream",
        "data": {"delta": "hi"},
    }
    assert json.loads(chunks[1].removeprefix("data: ").strip()) == {
        "event_type": "turn_complete",
        "data": {"ok": True},
    }
    assert broadcaster.unsubscribed == [7]
    assert event_queue.qsize() == 1


async def test_interrupt_sets_session_cancellation(manager):
    fake_session = FakeSession(
        event_queue=asyncio.Queue(),
        config=SimpleNamespace(model_name="test/model"),
        tool_router=FakeToolRouter(),
    )
    manager.sessions["session-a"] = session_module.AgentSession(
        session_id="session-a",
        session=fake_session,
        tool_router=SimpleNamespace(),
        submission_queue=asyncio.Queue(),
        user_id="alice",
    )

    assert fake_session.is_cancelled is False
    assert await manager.interrupt("session-a") is True
    assert fake_session.is_cancelled is True
    assert await manager.interrupt("missing") is False

    manager.sessions["session-a"].is_active = False
    assert await manager.interrupt("session-a") is False


async def test_event_broadcaster_current_subscribers_only_transient_reconnect():
    source = asyncio.Queue()
    broadcaster = session_module.EventBroadcaster(source)
    task = asyncio.create_task(broadcaster.run())

    try:
        await source.put(Event(event_type="before_subscribe", data={"n": 0}))
        await _wait_until(source.empty)

        first_id, first_queue = broadcaster.subscribe()
        await source.put(Event(event_type="after_first_subscribe", data={"n": 1}))

        assert await _queue_get(first_queue) == {
            "event_type": "after_first_subscribe",
            "data": {"n": 1},
        }

        second_id, second_queue = broadcaster.subscribe()
        await source.put(Event(event_type="after_reconnect", data={"n": 2}))

        assert await _queue_get(first_queue) == {
            "event_type": "after_reconnect",
            "data": {"n": 2},
        }
        assert await _queue_get(second_queue) == {
            "event_type": "after_reconnect",
            "data": {"n": 2},
        }
        assert first_queue.empty()
        assert second_queue.empty()

        broadcaster.unsubscribe(first_id)
        await source.put(Event(event_type="second_only", data={"n": 3}))

        assert await _queue_get(second_queue) == {
            "event_type": "second_only",
            "data": {"n": 3},
        }
        assert first_queue.empty()

        broadcaster.unsubscribe(second_id)
    finally:
        task.cancel()
        await task
        assert task.done()
