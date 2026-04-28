"""Backend session and SSE characterization tests for Phase 0."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Callable

import pytest
from fastapi import HTTPException
from litellm import Message

import session_manager as session_module
from agent.core.events import AgentEvent
from agent.core.session import Event
from backend.event_store import SQLiteEventStore
from backend.session_store import SESSION_ACTIVE, SESSION_CLOSED, SQLiteSessionStore
import routes.agent as agent_routes
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
    def __init__(
        self,
        mcp_servers: dict[str, Any] | None = None,
        hf_token: str | None = None,
        trusted_hf_mcp_servers: list[str] | None = None,
    ):
        self.mcp_servers = mcp_servers or {}
        self.hf_token = hf_token
        self.trusted_hf_mcp_servers = trusted_hf_mcp_servers or []
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
        self.session_id = "agent-internal-before-alignment"
        self._next_event_sequence = 1

    async def send_event(self, event: Event) -> None:
        if isinstance(event, AgentEvent):
            envelope = event.model_copy(
                update={
                    "session_id": self.session_id,
                    "sequence": self._next_event_sequence,
                }
            )
        else:
            envelope = AgentEvent.from_legacy(
                event,
                session_id=self.session_id,
                sequence=self._next_event_sequence,
            )
        self._next_event_sequence += 1
        await self.event_queue.put(envelope.redacted_copy())

    def cancel(self) -> None:
        self._cancelled = True

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled


class FakeAgentEvent:
    def __init__(
        self,
        event_type: str,
        data: dict[str, Any],
        metadata: dict[str, Any],
    ):
        self.event_type = event_type
        self.data = data
        self.metadata = metadata

    def to_legacy_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "metadata": self.metadata,
        }


class FakeSseAgentEvent(FakeAgentEvent):
    to_legacy_dict = None

    def to_legacy_sse(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "data": self.data,
            "metadata": self.metadata,
        }


class FakeRequest:
    def __init__(
        self,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        query_params: dict[str, str] | None = None,
    ):
        self._body = body
        self.headers = headers or {}
        self.query_params = query_params or {}

    async def json(self) -> dict[str, Any]:
        return self._body


class RouteBroadcaster:
    def __init__(self) -> None:
        self.subscribed = False
        self.unsubscribed: list[int] = []
        self.queues: dict[int, asyncio.Queue] = {}
        self._next_id = 0

    def subscribe(self) -> tuple[int, asyncio.Queue]:
        self.subscribed = True
        self._next_id += 1
        queue: asyncio.Queue = asyncio.Queue()
        self.queues[self._next_id] = queue
        return self._next_id, queue

    def unsubscribe(self, sub_id: int) -> None:
        self.unsubscribed.append(sub_id)


class RouteSessionManager:
    def __init__(self, broadcaster: RouteBroadcaster):
        self.broadcaster = broadcaster
        self.sessions = {
            "session-a": SimpleNamespace(
                is_active=True,
                broadcaster=broadcaster,
            )
        }
        self.user_inputs: list[tuple[str, str]] = []
        self.approvals: list[tuple[str, list[dict[str, Any]]]] = []

    async def submit_user_input(self, session_id: str, text: str) -> bool:
        assert self.broadcaster.subscribed is True
        self.user_inputs.append((session_id, text))
        queue = self.broadcaster.queues[1]
        await queue.put({"event_type": "turn_complete", "data": {"text": text}})
        return True

    async def submit_approval(
        self, session_id: str, approvals: list[dict[str, Any]]
    ) -> bool:
        assert self.broadcaster.subscribed is True
        self.approvals.append((session_id, approvals))
        queue = self.broadcaster.queues[1]
        await queue.put(
            {"event_type": "approval_required", "data": {"approved": approvals}}
        )
        return True


class ReplayRouteSessionManager:
    def __init__(
        self,
        broadcaster: RouteBroadcaster,
        events: list[AgentEvent],
    ) -> None:
        self.sessions = {
            "session-a": SimpleNamespace(
                is_active=True,
                broadcaster=broadcaster,
            )
        }
        self._events = events
        self.replay_calls: list[tuple[str, int]] = []

    def replay_events(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
    ) -> list[AgentEvent]:
        self.replay_calls.append((session_id, after_sequence))
        return [
            event
            for event in self._events
            if event.session_id == session_id and event.sequence > after_sequence
        ]


def _decode_sse_event(chunk: str | bytes) -> dict[str, Any]:
    text = chunk.decode() if isinstance(chunk, bytes) else chunk
    event_id = None
    data_lines = []
    for line in text.strip().splitlines():
        if line.startswith("id: "):
            event_id = line.removeprefix("id: ")
        if line.startswith("data: "):
            data_lines.append(line.removeprefix("data: "))
    assert data_lines
    return {"id": event_id, "data": json.loads("\n".join(data_lines))}


def _decode_sse_chunk(chunk: str | bytes) -> dict[str, Any]:
    return _decode_sse_event(chunk)["data"]


@pytest.fixture
def manager(test_config, tmp_path) -> session_module.SessionManager:
    mgr = session_module.SessionManager(
        event_store=SQLiteEventStore(tmp_path / "events.sqlite"),
        session_store=SQLiteSessionStore(tmp_path / "sessions.sqlite"),
    )
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
        await _wait_until(lambda: len(manager.event_store.replay(first)) == 1)

        assert manager.active_session_count == 2
        assert manager.sessions[first].session.session_id == first
        assert manager.event_store.replay(first)[0].session_id == first
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
        durable_first = manager.session_store.get(first)
        assert durable_first is not None
        assert durable_first.status == SESSION_CLOSED
        assert manager.list_sessions(user_id="alice") == [
            {
                "session_id": first,
                "created_at": durable_first.created_at.isoformat(),
                "is_active": False,
                "is_processing": False,
                "message_count": 0,
                "user_id": "alice",
                "pending_approval": None,
                "model": "test/alternate",
            }
        ]
        assert manager.active_session_count == 1
        assert await manager.delete_session(first) is False
    finally:
        await manager.delete_session(first)
        await manager.delete_session(second)


async def test_session_manager_lists_durable_metadata_after_restart(
    test_config,
    tmp_path,
    offline_session_constructors,
):
    database_path = tmp_path / "sessions.sqlite"
    manager = session_module.SessionManager(
        event_store=SQLiteEventStore(tmp_path / "events.sqlite"),
        session_store_path=database_path,
    )
    manager.config = test_config
    session_id = await manager.create_session(
        user_id="alice",
        hf_token="hf_alice",
        model="test/alternate",
    )

    try:
        await _wait_until(lambda: manager.sessions[session_id].broadcaster is not None)
        created = manager.session_store.get(session_id)
        assert created is not None
        assert created.owner_id == "alice"
        assert created.model == "test/alternate"
        assert created.status == SESSION_ACTIVE

        restarted = session_module.SessionManager(session_store_path=database_path)
        restarted.config = test_config
        restarted_sessions = restarted.list_sessions(user_id="alice")

        assert restarted.sessions == {}
        assert restarted_sessions == [
            {
                "session_id": session_id,
                "created_at": created.created_at.isoformat(),
                "is_active": False,
                "is_processing": False,
                "message_count": 0,
                "user_id": "alice",
                "pending_approval": None,
                "model": "test/alternate",
            }
        ]
        assert restarted.verify_session_access(session_id, "alice") is True
        assert await restarted.submit_user_input(session_id, "not restored") is False
    finally:
        await manager.delete_session(session_id)


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
        pending_approval={
            "tool_calls": [tool_call],
            "policy": {
                "tc_123": {
                    "risk": "medium",
                    "side_effects": ["remote_compute"],
                    "rollback": "Cancel the job.",
                    "budget_impact": "May incur CPU compute costs.",
                    "credential_usage": ["hf_token"],
                    "reason": "CPU job launch requires approval.",
                }
            },
        },
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
            "risk": "medium",
            "side_effects": ["remote_compute"],
            "rollback": "Cancel the job.",
            "budget_impact": "May incur CPU compute costs.",
            "credential_usage": ["hf_token"],
            "reason": "CPU job launch requires approval.",
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


async def test_sse_response_strips_envelope_metadata_from_public_payload():
    class TrackingBroadcaster:
        def __init__(self):
            self.unsubscribed: list[int] = []

        def unsubscribe(self, sub_id: int) -> None:
            self.unsubscribed.append(sub_id)

    broadcaster = TrackingBroadcaster()
    event_queue = asyncio.Queue()
    await event_queue.put(
        FakeAgentEvent(
            event_type="turn_complete",
            data={"ok": True},
            metadata={"sequence": 12, "created_at": "internal"},
        )
    )

    response = _sse_response(broadcaster, event_queue, sub_id=7)
    chunks = [
        _decode_sse_chunk(chunk)
        async for chunk in response.body_iterator
    ]

    assert chunks == [{"event_type": "turn_complete", "data": {"ok": True}}]
    assert broadcaster.unsubscribed == [7]


async def test_sse_response_supports_to_legacy_sse_envelope_method():
    class TrackingBroadcaster:
        def __init__(self):
            self.unsubscribed: list[int] = []

        def unsubscribe(self, sub_id: int) -> None:
            self.unsubscribed.append(sub_id)

    broadcaster = TrackingBroadcaster()
    event_queue = asyncio.Queue()
    await event_queue.put(
        FakeSseAgentEvent(
            event_type="turn_complete",
            data={"ok": True},
            metadata={"sequence": 12, "created_at": "internal"},
        )
    )

    response = _sse_response(broadcaster, event_queue, sub_id=7)
    chunks = [_decode_sse_chunk(chunk) async for chunk in response.body_iterator]

    assert chunks == [{"event_type": "turn_complete", "data": {"ok": True}}]
    assert broadcaster.unsubscribed == [7]


async def test_sse_response_emits_sequence_id_for_enveloped_events():
    class TrackingBroadcaster:
        def __init__(self):
            self.unsubscribed: list[int] = []

        def unsubscribe(self, sub_id: int) -> None:
            self.unsubscribed.append(sub_id)

    broadcaster = TrackingBroadcaster()
    event_queue = asyncio.Queue()
    await event_queue.put(
        AgentEvent(
            session_id="session-a",
            sequence=4,
            event_type="turn_complete",
            data={"history_size": 2},
        )
    )

    response = _sse_response(broadcaster, event_queue, sub_id=7)
    chunks = [_decode_sse_event(chunk) async for chunk in response.body_iterator]

    assert chunks == [
        {
            "id": "4",
            "data": {
                "event_type": "turn_complete",
                "data": {"history_size": 2},
            },
        }
    ]
    assert broadcaster.unsubscribed == [7]


async def test_sse_response_deduplicates_live_event_after_replay_boundary():
    class TrackingBroadcaster:
        def __init__(self):
            self.unsubscribed: list[int] = []

        def unsubscribe(self, sub_id: int) -> None:
            self.unsubscribed.append(sub_id)

    replay_event = AgentEvent(
        session_id="session-a",
        sequence=2,
        event_type="processing",
        data={"message": "from store"},
    )
    duplicate_live_event = replay_event.model_copy()
    terminal_live_event = AgentEvent(
        session_id="session-a",
        sequence=3,
        event_type="turn_complete",
        data={"history_size": 2},
    )
    broadcaster = TrackingBroadcaster()
    event_queue = asyncio.Queue()
    await event_queue.put(duplicate_live_event)
    await event_queue.put(terminal_live_event)

    response = _sse_response(
        broadcaster,
        event_queue,
        sub_id=7,
        replay_events=[replay_event],
        after_sequence=1,
    )
    chunks = [_decode_sse_event(chunk) async for chunk in response.body_iterator]

    assert chunks == [
        {
            "id": "2",
            "data": {
                "event_type": "processing",
                "data": {"message": "from store"},
            },
        },
        {
            "id": "3",
            "data": {
                "event_type": "turn_complete",
                "data": {"history_size": 2},
            },
        },
    ]
    assert broadcaster.unsubscribed == [7]


async def test_chat_sse_text_route_subscribes_before_submit_and_closes(
    monkeypatch,
):
    broadcaster = RouteBroadcaster()
    fake_manager = RouteSessionManager(broadcaster)
    quota_calls: list[str] = []

    async def fake_quota(_user, _agent_session):
        quota_calls.append("called")

    monkeypatch.setattr(agent_routes, "session_manager", fake_manager)
    monkeypatch.setattr(agent_routes, "_check_session_access", lambda *_args: None)
    monkeypatch.setattr(agent_routes, "_enforce_claude_quota", fake_quota)

    response = await agent_routes.chat_sse(
        "session-a",
        FakeRequest({"text": "hello"}),
        {"user_id": "dev"},
    )

    chunks = [
        _decode_sse_chunk(chunk)
        async for chunk in response.body_iterator
    ]

    assert quota_calls == ["called"]
    assert fake_manager.user_inputs == [("session-a", "hello")]
    assert fake_manager.approvals == []
    assert chunks == [{"event_type": "turn_complete", "data": {"text": "hello"}}]
    assert broadcaster.unsubscribed == [1]


async def test_chat_sse_approvals_route_formats_and_skips_quota(monkeypatch):
    broadcaster = RouteBroadcaster()
    fake_manager = RouteSessionManager(broadcaster)

    async def fail_if_called(_user, _agent_session):
        raise AssertionError("approval submission should not charge quota")

    monkeypatch.setattr(agent_routes, "session_manager", fake_manager)
    monkeypatch.setattr(agent_routes, "_check_session_access", lambda *_args: None)
    monkeypatch.setattr(agent_routes, "_enforce_claude_quota", fail_if_called)

    response = await agent_routes.chat_sse(
        "session-a",
        FakeRequest(
            {
                "approvals": [
                    {
                        "tool_call_id": "tc_1",
                        "approved": True,
                        "feedback": "ok",
                        "edited_script": "print('edited')",
                    }
                ]
            }
        ),
        {"user_id": "dev"},
    )

    chunks = [
        _decode_sse_chunk(chunk)
        async for chunk in response.body_iterator
    ]

    assert fake_manager.user_inputs == []
    assert fake_manager.approvals == [
        (
            "session-a",
            [
                {
                    "tool_call_id": "tc_1",
                    "approved": True,
                    "feedback": "ok",
                    "edited_script": "print('edited')",
                }
            ],
        )
    ]
    assert chunks == [
        {
            "event_type": "approval_required",
            "data": {
                "approved": [
                    {
                        "tool_call_id": "tc_1",
                        "approved": True,
                        "feedback": "ok",
                        "edited_script": "print('edited')",
                    }
                ]
            },
        }
    ]
    assert broadcaster.unsubscribed == [1]


async def test_chat_sse_quota_error_unsubscribes_before_raising(monkeypatch):
    broadcaster = RouteBroadcaster()
    fake_manager = RouteSessionManager(broadcaster)

    async def fail_quota(_user, _agent_session):
        raise HTTPException(status_code=429, detail="quota")

    monkeypatch.setattr(agent_routes, "session_manager", fake_manager)
    monkeypatch.setattr(agent_routes, "_check_session_access", lambda *_args: None)
    monkeypatch.setattr(agent_routes, "_enforce_claude_quota", fail_quota)

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.chat_sse(
            "session-a",
            FakeRequest({"text": "hello"}),
            {"user_id": "dev"},
        )

    assert exc_info.value.status_code == 429
    assert fake_manager.user_inputs == []
    assert broadcaster.unsubscribed == [1]


@pytest.mark.parametrize(
    ("query_params", "headers", "expected_after", "expected_ids"),
    [
        ({"after_sequence": "1"}, {}, 1, ["2", "3"]),
        ({"after": "2"}, {}, 2, ["3"]),
        ({}, {"Last-Event-ID": "1"}, 1, ["2", "3"]),
    ],
)
async def test_subscribe_events_replays_after_explicit_cursor(
    monkeypatch,
    query_params,
    headers,
    expected_after,
    expected_ids,
):
    events = [
        AgentEvent(
            session_id="session-a",
            sequence=1,
            event_type="ready",
            data={"message": "Agent initialized"},
        ),
        AgentEvent(
            session_id="session-a",
            sequence=2,
            event_type="processing",
            data={"message": "working"},
        ),
        AgentEvent(
            session_id="session-a",
            sequence=3,
            event_type="turn_complete",
            data={"history_size": 2},
        ),
    ]
    broadcaster = RouteBroadcaster()
    fake_manager = ReplayRouteSessionManager(broadcaster, events)

    monkeypatch.setattr(agent_routes, "session_manager", fake_manager)
    monkeypatch.setattr(agent_routes, "_check_session_access", lambda *_args: None)

    response = await agent_routes.subscribe_events(
        "session-a",
        FakeRequest({}, headers=headers, query_params=query_params),
        {"user_id": "dev"},
    )
    chunks = [_decode_sse_event(chunk) async for chunk in response.body_iterator]

    assert fake_manager.replay_calls == [("session-a", expected_after)]
    assert [chunk["id"] for chunk in chunks] == expected_ids
    assert [chunk["data"]["event_type"] for chunk in chunks] == [
        event.event_type
        for event in events
        if event.sequence > expected_after
    ]
    assert all(set(chunk["data"]) == {"event_type", "data"} for chunk in chunks)
    assert broadcaster.unsubscribed == [1]


async def test_subscribe_events_without_cursor_stays_live_only(monkeypatch):
    stored_terminal = AgentEvent(
        session_id="session-a",
        sequence=2,
        event_type="turn_complete",
        data={"history_size": 2},
    )
    live_terminal = AgentEvent(
        session_id="session-a",
        sequence=3,
        event_type="turn_complete",
        data={"history_size": 3},
    )
    broadcaster = RouteBroadcaster()
    fake_manager = ReplayRouteSessionManager(broadcaster, [stored_terminal])

    monkeypatch.setattr(agent_routes, "session_manager", fake_manager)
    monkeypatch.setattr(agent_routes, "_check_session_access", lambda *_args: None)

    response = await agent_routes.subscribe_events(
        "session-a",
        FakeRequest({}),
        {"user_id": "dev"},
    )
    await broadcaster.queues[1].put(live_terminal)

    chunks = [_decode_sse_event(chunk) async for chunk in response.body_iterator]

    assert fake_manager.replay_calls == []
    assert chunks == [
        {
            "id": "3",
            "data": {
                "event_type": "turn_complete",
                "data": {"history_size": 3},
            },
        }
    ]
    assert broadcaster.unsubscribed == [1]


async def test_get_session_messages_returns_redacted_copies_without_mutating_context(
    monkeypatch,
):
    secret = "hf_messagessecret123456789"
    raw_content = f"Use HF_TOKEN={secret} from /Users/alice/project"
    message = Message(role="user", content=raw_content)
    fake_manager = SimpleNamespace(
        sessions={
            "session-a": SimpleNamespace(
                is_active=True,
                session=SimpleNamespace(
                    context_manager=SimpleNamespace(items=[message])
                ),
            )
        }
    )

    monkeypatch.setattr(agent_routes, "session_manager", fake_manager)
    monkeypatch.setattr(agent_routes, "_check_session_access", lambda *_args: None)

    result = await agent_routes.get_session_messages("session-a", {"user_id": "dev"})

    assert secret not in str(result)
    assert "/Users/alice" not in str(result)
    assert "[REDACTED]" in result[0]["content"]
    assert "/Users/[USER]/project" in result[0]["content"]
    assert message.content == raw_content


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
        await source.put(
            FakeAgentEvent(
                event_type="after_first_subscribe",
                data={"n": 1},
                metadata={"sequence": 1},
            )
        )

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


async def test_event_broadcaster_persists_without_subscribers_and_terminal_events(
    tmp_path,
):
    source = asyncio.Queue()
    store = SQLiteEventStore(tmp_path / "events.sqlite")
    broadcaster = session_module.EventBroadcaster(source, event_store=store)
    task = asyncio.create_task(broadcaster.run())

    try:
        await source.put(
            AgentEvent(
                session_id="session-a",
                sequence=1,
                event_type="processing",
                data={"message": "before subscriber"},
            )
        )
        await _wait_until(lambda: len(store.replay("session-a")) == 1)

        sub_id, subscriber = broadcaster.subscribe()
        await source.put(
            AgentEvent(
                session_id="session-a",
                sequence=2,
                event_type="turn_complete",
                data={"history_size": 3},
            )
        )

        broadcasted = await _queue_get(subscriber)
        assert isinstance(broadcasted, AgentEvent)
        assert broadcasted.sequence == 2
        assert session_module.event_to_legacy_dict(broadcasted) == {
            "event_type": "turn_complete",
            "data": {"history_size": 3},
        }
        assert [
            (event.sequence, event.event_type)
            for event in store.replay("session-a")
        ] == [
            (1, "processing"),
            (2, "turn_complete"),
        ]
        broadcaster.unsubscribe(sub_id)
    finally:
        task.cancel()
        await task
        assert task.done()
