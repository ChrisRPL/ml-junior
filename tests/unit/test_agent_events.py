from __future__ import annotations

import json

import pytest
from litellm import Message
from pydantic import ValidationError

from agent.core.events import AgentEvent, EVENT_PAYLOAD_MODELS
from agent.core.session import Event, Session


def make_session(event_queue, test_config, fake_tool_router) -> Session:
    return Session(
        event_queue,
        config=test_config,
        tool_router=fake_tool_router,
        stream=False,
    )


async def test_send_event_envelopes_legacy_event_with_session_sequence(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    await session.send_event(Event("processing", {"message": "one"}))
    await session.send_event(Event("assistant_message", {"content": "two"}))

    events = await event_collector(event_queue)

    assert [event.event_type for event in events] == [
        "processing",
        "assistant_message",
    ]
    assert [event.data for event in events] == [
        {"message": "one"},
        {"content": "two"},
    ]
    assert [event.sequence for event in events] == [1, 2]
    assert {event.session_id for event in events} == {session.session_id}
    assert all(isinstance(event, AgentEvent) for event in events)
    assert all(event.schema_version == 1 for event in events)
    assert all(event.redaction_status == "none" for event in events)
    assert events[0].id != events[1].id


async def test_legacy_sse_serialization_omits_envelope_metadata(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    await session.send_event(Event("turn_complete", {"history_size": 3}))

    [event] = await event_collector(event_queue)

    assert event.to_legacy_sse() == {
        "event_type": "turn_complete",
        "data": {"history_size": 3},
    }
    assert set(event.to_legacy_sse()) == {"event_type", "data"}


async def test_logged_events_remain_legacy_trajectory_shape(
    event_queue,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    await session.send_event(Event("error", {"error": "boom"}))

    assert len(session.logged_events) == 1
    assert session.logged_events[0]["event_type"] == "error"
    assert session.logged_events[0]["data"] == {"error": "boom"}
    assert "timestamp" in session.logged_events[0]
    assert "sequence" not in session.logged_events[0]
    assert "redaction_status" not in session.logged_events[0]


async def test_send_event_nowait_uses_same_envelope_and_log_path(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)

    session.send_event_nowait(Event("tool_log", {"tool": "sandbox", "log": "ready"}))

    [event] = await event_collector(event_queue)
    assert isinstance(event, AgentEvent)
    assert event.session_id == session.session_id
    assert event.sequence == 1
    assert event.to_legacy_sse() == {
        "event_type": "tool_log",
        "data": {"tool": "sandbox", "log": "ready"},
    }
    assert session.logged_events == [
        {
            "timestamp": event.timestamp.isoformat(),
            "event_type": "tool_log",
            "data": {"tool": "sandbox", "log": "ready"},
        }
    ]


async def test_events_are_redacted_before_queue_and_log(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_eventsecret123456789"

    await session.send_event(
        Event(
            "tool_output",
            {
                "tool": "hf_jobs",
                "tool_call_id": "tc_1",
                "output": f"Authorization: Bearer {secret}",
                "success": True,
            },
        )
    )

    [event] = await event_collector(event_queue)

    assert event.redaction_status == "partial"
    assert secret not in event.data["output"]
    assert event.to_legacy_sse() == {
        "event_type": "tool_output",
        "data": {
            "tool": "hf_jobs",
            "tool_call_id": "tc_1",
            "output": "Authorization: Bearer [REDACTED]",
            "success": True,
        },
    }
    assert secret not in str(session.logged_events)
    assert session.logged_events[0]["data"] == event.data


async def test_trajectory_includes_redacted_event_metadata_without_changing_events(
    event_queue,
    event_collector,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_exportsecret123456789"

    await session.send_event(
        Event(
            "tool_output",
            {
                "tool": "hf_jobs",
                "tool_call_id": "tc_export",
                "output": f"Authorization: Bearer {secret}",
                "success": True,
            },
        )
    )

    [event] = await event_collector(event_queue)
    trajectory = session.get_trajectory()

    assert trajectory["events"] == session.logged_events
    assert trajectory["events"][0] == {
        "timestamp": event.timestamp.isoformat(),
        "event_type": "tool_output",
        "data": {
            "tool": "hf_jobs",
            "tool_call_id": "tc_export",
            "output": "Authorization: Bearer [REDACTED]",
            "success": True,
        },
    }
    assert trajectory["event_metadata"] == [
        {
            "logged_event_index": 0,
            "event_id": event.id,
            "event_type": "tool_output",
            "sequence": 1,
            "timestamp": event.timestamp.isoformat(),
            "schema_version": 1,
            "redaction_status": "partial",
        }
    ]
    assert secret not in str(trajectory)


async def test_local_trajectory_save_exports_event_metadata_without_raw_secret(
    event_queue,
    fake_tool_router,
    test_config,
    tmp_path,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_savedsecret123456789"

    await session.send_event(
        Event(
            "tool_output",
            {
                "tool": "hf_jobs",
                "tool_call_id": "tc_saved",
                "output": f"Authorization: Bearer {secret}",
                "success": True,
            },
        )
    )

    filepath = session.save_trajectory_local(directory=str(tmp_path))

    assert filepath is not None
    saved = json.loads((tmp_path / filepath.split("/")[-1]).read_text())
    assert saved["events"] == session.logged_events
    assert saved["event_metadata"][0]["redaction_status"] == "partial"
    assert saved["event_metadata"][0]["logged_event_index"] == 0
    assert "redaction_status" not in saved["events"][0]
    assert secret not in json.dumps(saved)


def test_trajectory_redacts_messages_without_mutating_live_context(
    event_queue,
    fake_tool_router,
    test_config,
):
    session = make_session(event_queue, test_config, fake_tool_router)
    secret = "hf_contextsecret123456789"
    raw_content = f"Use HF_TOKEN={secret} from /Users/alice/project"
    session.context_manager.add_message(Message(role="user", content=raw_content))

    trajectory = session.get_trajectory()

    assert secret in session.context_manager.items[-1].content
    assert "/Users/alice/project" in session.context_manager.items[-1].content
    assert secret not in str(trajectory["messages"])
    assert "/Users/alice" not in str(trajectory["messages"])
    assert "HF_TOKEN=[REDACTED]" in str(trajectory["messages"])
    assert "/Users/[USER]/project" in str(trajectory["messages"])


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("ready", {"message": "Agent initialized"}),
        ("processing", {"message": "Processing user input"}),
        ("assistant_message", {"content": "done"}),
        ("assistant_chunk", {"content": "chunk"}),
        ("assistant_stream_end", {}),
        (
            "tool_call",
            {"tool": "echo", "arguments": {"value": 1}, "tool_call_id": "tc_1"},
        ),
        (
            "tool_output",
            {
                "tool": "echo",
                "tool_call_id": "tc_1",
                "output": "ok",
                "success": True,
            },
        ),
        ("tool_log", {"tool": "system", "log": "working"}),
        (
            "approval_required",
            {
                "tools": [
                    {
                        "tool": "hf_jobs",
                        "arguments": {"operation": "run"},
                        "tool_call_id": "tc_2",
                    }
                ],
                "count": 1,
            },
        ),
        (
            "tool_state_change",
            {"tool": "hf_jobs", "tool_call_id": "tc_2", "state": "running"},
        ),
        ("turn_complete", {"history_size": 4}),
        ("compacted", {"old_tokens": 20, "new_tokens": 10}),
        ("error", {"error": "boom"}),
        ("shutdown", {}),
        ("interrupted", {}),
        ("undo_complete", {}),
        (
            "plan_update",
            {"plan": [{"id": "1", "content": "Do it", "status": "pending"}]},
        ),
    ],
)
def test_current_event_payloads_are_modeled(event_type, payload):
    event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type=event_type,
        data=payload,
    )

    assert event.event_type in EVENT_PAYLOAD_MODELS
    assert event.data == payload


def test_known_event_payloads_validate_required_fields():
    with pytest.raises(ValidationError):
        AgentEvent(
            session_id="session-a",
            sequence=1,
            event_type="assistant_message",
            data={},
        )


def test_unknown_event_types_remain_compatible_for_migration():
    event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type="experimental_event",
        data={"anything": True},
    )

    assert event.to_legacy_sse() == {
        "event_type": "experimental_event",
        "data": {"anything": True},
    }
