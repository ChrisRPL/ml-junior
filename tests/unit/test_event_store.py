from __future__ import annotations

import sqlite3

from agent.core.events import AgentEvent
from backend.event_store import SQLiteEventStore


def make_event(
    *,
    session_id: str,
    sequence: int,
    event_type: str = "processing",
    data: dict | None = None,
) -> AgentEvent:
    payload = data if data is not None else {"message": f"{session_id}:{sequence}"}
    return AgentEvent(
        session_id=session_id,
        sequence=sequence,
        event_type=event_type,
        data=payload,
    )


def test_replay_returns_session_events_after_sequence_in_order(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite")

    store.append(make_event(session_id="session-a", sequence=1))
    store.append(make_event(session_id="session-b", sequence=1))
    store.append(
        make_event(
            session_id="session-a",
            sequence=2,
            event_type="assistant_message",
            data={"content": "two"},
        )
    )
    store.append(
        make_event(
            session_id="session-a",
            sequence=3,
            event_type="turn_complete",
            data={"history_size": 2},
        )
    )

    replayed = store.replay("session-a", after_sequence=1)

    assert [event.sequence for event in replayed] == [2, 3]
    assert [event.event_type for event in replayed] == [
        "assistant_message",
        "turn_complete",
    ]
    assert {event.session_id for event in replayed} == {"session-a"}


def test_replay_is_isolated_by_session(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite")

    store.append(make_event(session_id="session-a", sequence=1))
    store.append(make_event(session_id="session-b", sequence=1))
    store.append(make_event(session_id="session-a", sequence=2))
    store.append(make_event(session_id="session-b", sequence=2))

    replayed = store.replay("session-b")

    assert [event.sequence for event in replayed] == [1, 2]
    assert [event.data["message"] for event in replayed] == [
        "session-b:1",
        "session-b:2",
    ]
    assert {event.session_id for event in replayed} == {"session-b"}


def test_terminal_events_persist_like_regular_events(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.sqlite")

    store.append(
        make_event(
            session_id="session-a",
            sequence=1,
            event_type="error",
            data={"error": "boom"},
        )
    )
    store.append(
        make_event(
            session_id="session-a",
            sequence=2,
            event_type="interrupted",
            data={},
        )
    )
    store.append(
        make_event(
            session_id="session-a",
            sequence=3,
            event_type="turn_complete",
            data={"history_size": 9},
        )
    )

    replayed = store.replay("session-a")

    assert [event.event_type for event in replayed] == [
        "error",
        "interrupted",
        "turn_complete",
    ]
    assert [event.sequence for event in replayed] == [1, 2, 3]


def test_append_redacts_envelope_data_before_sqlite_persistence(tmp_path):
    database_path = tmp_path / "events.sqlite"
    store = SQLiteEventStore(database_path)
    secret = "hf_storesecret123456789"
    event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type="tool_output",
        data={
            "tool": "hf_jobs",
            "tool_call_id": "tc_1",
            "output": f"Authorization: Bearer {secret}",
            "success": True,
        },
    )

    stored_event = store.append(event)
    replayed = store.replay("session-a")

    assert secret in event.data["output"]
    assert stored_event.redaction_status == "partial"
    assert stored_event.data["output"] == "Authorization: Bearer [REDACTED]"
    assert replayed == [stored_event]

    connection = sqlite3.connect(database_path)
    try:
        stored_payload = connection.execute(
            "SELECT data_json FROM agent_events WHERE id = ?",
            (stored_event.id,),
        ).fetchone()[0]
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert secret not in stored_payload
    assert secret not in database_dump
    assert "Authorization: Bearer [REDACTED]" in stored_payload
