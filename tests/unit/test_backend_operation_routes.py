from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

import routes.agent as agent_routes
import session_manager as session_module
from agent.core.session import Event
from backend.event_store import SQLiteEventStore
from models import ToolApproval
from backend.operation_store import (
    OPERATION_FAILED,
    OPERATION_PENDING,
    OPERATION_SUCCEEDED,
    SQLiteOperationStore,
)


class FakeContextManager:
    def __init__(self, *, truncate_result: bool = True) -> None:
        self.items: list[Any] = []
        self.truncate_result = truncate_result
        self.truncate_calls: list[int] = []

    def truncate_to_user_message(self, user_message_index: int) -> bool:
        self.truncate_calls.append(user_message_index)
        return self.truncate_result


class FakeSession:
    def __init__(self, *, truncate_result: bool = True) -> None:
        self.config = SimpleNamespace(model_name="test/model")
        self.context_manager = FakeContextManager(truncate_result=truncate_result)
        self.pending_approval = None
        self.is_running = True
        self.sandbox = None
        self.cancelled = False
        self.events: list[Event] = []

    def cancel(self) -> None:
        self.cancelled = True

    async def send_event(self, event: Event) -> None:
        self.events.append(event)


class FakeBroadcaster:
    def __init__(self) -> None:
        self.queues: dict[int, asyncio.Queue] = {}
        self.unsubscribed: list[int] = []
        self._next_id = 0

    def subscribe(self) -> tuple[int, asyncio.Queue]:
        self._next_id += 1
        queue: asyncio.Queue = asyncio.Queue()
        self.queues[self._next_id] = queue
        return self._next_id, queue

    def unsubscribe(self, sub_id: int) -> None:
        self.unsubscribed.append(sub_id)


class FakeRequest:
    def __init__(self, body: dict[str, Any]) -> None:
        self._body = body
        self.headers: dict[str, str] = {}
        self.query_params: dict[str, str] = {}

    async def json(self) -> dict[str, Any]:
        return self._body


class FakeToolRouter:
    def __init__(self) -> None:
        self.entered = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.entered = False


@pytest.fixture
def operation_manager(test_config, tmp_path):
    operation_store = SQLiteOperationStore(tmp_path / "operations.sqlite")
    manager = session_module.SessionManager(
        event_store=SQLiteEventStore(tmp_path / "events.sqlite"),
        operation_store=operation_store,
    )
    manager.config = test_config
    return manager, operation_store, tmp_path / "operations.sqlite"


def _install_session(
    manager: session_module.SessionManager,
    *,
    session_id: str = "session-a",
    truncate_result: bool = True,
) -> tuple[FakeSession, FakeBroadcaster]:
    fake_session = FakeSession(truncate_result=truncate_result)
    broadcaster = FakeBroadcaster()
    manager.sessions[session_id] = session_module.AgentSession(
        session_id=session_id,
        session=fake_session,
        tool_router=FakeToolRouter(),
        submission_queue=asyncio.Queue(),
        user_id="alice",
        broadcaster=broadcaster,
    )
    return fake_session, broadcaster


async def _consume_terminal_sse(response, broadcaster: FakeBroadcaster) -> dict[str, Any]:
    sub_id = broadcaster._next_id
    await broadcaster.queues[sub_id].put(
        {"event_type": "turn_complete", "data": {"ok": True}}
    )
    chunks = []
    async for chunk in response.body_iterator:
        text = chunk.decode() if isinstance(chunk, bytes) else chunk
        chunks.append(json.loads(text.removeprefix("data: ").strip()))
    assert broadcaster.unsubscribed[-1] == sub_id
    return chunks[-1]


async def test_route_actions_create_durable_operation_records_and_keep_responses(
    operation_manager,
    monkeypatch,
):
    manager, store, database_path = operation_manager
    fake_session, broadcaster = _install_session(manager)
    monkeypatch.setattr(agent_routes, "session_manager", manager)

    hf_secret = "hf_operationsecret123456789"
    github_secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    user = {"user_id": "alice", "plan": "free"}

    submit_response = await agent_routes.submit_input(
        agent_routes.SubmitRequest(
            session_id="session-a",
            text=f"use bearer {hf_secret}",
        ),
        user,
    )
    approval_response = await agent_routes.submit_approval(
        agent_routes.ApprovalRequest(
            session_id="session-a",
            approvals=[
                ToolApproval(
                    tool_call_id="tc_1",
                    approved=True,
                    feedback="ok",
                    edited_script=f"print('{github_secret}')",
                )
            ],
        ),
        user,
    )
    chat_response = await agent_routes.chat_sse(
        "session-a",
        FakeRequest({"text": "hello"}),
        user,
    )
    chat_terminal = await _consume_terminal_sse(chat_response, broadcaster)
    chat_approval_response = await agent_routes.chat_sse(
        "session-a",
        FakeRequest(
            {
                "approvals": [
                    {
                        "tool_call_id": "tc_2",
                        "approved": False,
                        "feedback": "no",
                        "edited_script": None,
                    }
                ]
            }
        ),
        user,
    )
    await _consume_terminal_sse(chat_approval_response, broadcaster)
    interrupt_response = await agent_routes.interrupt_session("session-a", user)
    undo_response = await agent_routes.undo_session("session-a", user)
    truncate_response = await agent_routes.truncate_session(
        "session-a",
        agent_routes.TruncateRequest(user_message_index=2),
        user,
    )
    compact_response = await agent_routes.compact_session("session-a", user)
    shutdown_response = await agent_routes.shutdown_session("session-a", user)

    assert submit_response == {"status": "submitted", "session_id": "session-a"}
    assert approval_response == {"status": "submitted", "session_id": "session-a"}
    assert chat_terminal == {"event_type": "turn_complete", "data": {"ok": True}}
    assert interrupt_response == {"status": "interrupted", "session_id": "session-a"}
    assert undo_response == {"status": "undo_requested", "session_id": "session-a"}
    assert truncate_response == {"status": "truncated", "session_id": "session-a"}
    assert compact_response == {"status": "compact_requested", "session_id": "session-a"}
    assert shutdown_response == {
        "status": "shutdown_requested",
        "session_id": "session-a",
    }
    assert fake_session.cancelled is True
    assert fake_session.context_manager.truncate_calls == [2]

    records = store.list_by_session("session-a")
    assert [record.operation_type for record in records] == [
        "user_input",
        "exec_approval",
        "user_input",
        "exec_approval",
        "interrupt",
        "undo",
        "truncate",
        "compact",
        "shutdown",
    ]
    assert [record.status for record in records] == [
        OPERATION_PENDING,
        OPERATION_PENDING,
        OPERATION_PENDING,
        OPERATION_PENDING,
        OPERATION_SUCCEEDED,
        OPERATION_PENDING,
        OPERATION_SUCCEEDED,
        OPERATION_PENDING,
        OPERATION_PENDING,
    ]
    assert records[0].payload == {"text": "use bearer [REDACTED]"}
    assert records[1].payload["approvals"][0]["edited_script"] == "print('[REDACTED]')"
    assert records[4].result == {"cancelled": True}
    assert records[6].result == {"truncated": True, "user_message_index": 2}

    connection = sqlite3.connect(database_path)
    try:
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert hf_secret not in database_dump
    assert github_secret not in database_dump


async def test_inactive_session_routes_keep_404_without_operation_record(
    operation_manager,
    monkeypatch,
):
    manager, store, _database_path = operation_manager
    _install_session(manager)
    manager.sessions["session-a"].is_active = False
    monkeypatch.setattr(agent_routes, "session_manager", manager)

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.submit_input(
            agent_routes.SubmitRequest(session_id="session-a", text="hello"),
            {"user_id": "alice", "plan": "free"},
        )

    assert exc_info.value.status_code == 404
    assert store.list_by_session("session-a") == []


async def test_truncate_out_of_range_keeps_404_and_records_failed_operation(
    operation_manager,
    monkeypatch,
):
    manager, store, _database_path = operation_manager
    _install_session(manager, truncate_result=False)
    monkeypatch.setattr(agent_routes, "session_manager", manager)

    with pytest.raises(HTTPException) as exc_info:
        await agent_routes.truncate_session(
            "session-a",
            agent_routes.TruncateRequest(user_message_index=99),
            {"user_id": "alice", "plan": "free"},
        )

    records = store.list_by_session("session-a")
    assert exc_info.value.status_code == 404
    assert [record.operation_type for record in records] == ["truncate"]
    assert records[0].status == OPERATION_FAILED
    assert records[0].error["user_message_index"] == 99


async def test_session_loop_marks_queued_operation_succeeded(
    operation_manager,
    monkeypatch,
):
    manager, store, _database_path = operation_manager
    fake_session, _broadcaster = _install_session(manager)
    event_queue: asyncio.Queue = asyncio.Queue()
    processed: list[str] = []

    async def fake_process_submission(_session, submission) -> bool:
        processed.append(submission.id)
        return False

    monkeypatch.setattr(session_module, "process_submission", fake_process_submission)

    task = asyncio.create_task(
        manager._run_session(
            "session-a",
            manager.sessions["session-a"].submission_queue,
            event_queue,
            manager.sessions["session-a"].tool_router,
        )
    )
    try:
        while manager.sessions["session-a"].broadcaster is None:
            await asyncio.sleep(0)
        assert await manager.submit_user_input("session-a", "hello") is True
        await asyncio.wait_for(task, timeout=1)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    records = store.list_by_session("session-a")
    assert processed == [records[0].id]
    assert records[0].operation_type == "user_input"
    assert records[0].status == OPERATION_SUCCEEDED
    assert records[0].result == {"should_continue": False}
    assert fake_session.events[0].event_type == "ready"


async def test_session_loop_marks_queued_operation_failed_on_agent_error(
    operation_manager,
    monkeypatch,
):
    manager, store, _database_path = operation_manager
    fake_session, _broadcaster = _install_session(manager)
    event_queue: asyncio.Queue = asyncio.Queue()

    async def fake_process_submission(session, _submission) -> bool:
        session.is_running = False
        raise RuntimeError("HF_TOKEN=hf_operationsecret123456789")

    monkeypatch.setattr(session_module, "process_submission", fake_process_submission)

    task = asyncio.create_task(
        manager._run_session(
            "session-a",
            manager.sessions["session-a"].submission_queue,
            event_queue,
            manager.sessions["session-a"].tool_router,
        )
    )
    try:
        while manager.sessions["session-a"].broadcaster is None:
            await asyncio.sleep(0)
        assert await manager.submit_user_input("session-a", "hello") is True
        await asyncio.wait_for(task, timeout=1)
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    records = store.list_by_session("session-a")
    assert records[0].operation_type == "user_input"
    assert records[0].status == OPERATION_FAILED
    assert records[0].error == {
        "type": "RuntimeError",
        "message": "HF_TOKEN=[REDACTED]",
    }
    assert fake_session.events[-1].event_type == "error"
