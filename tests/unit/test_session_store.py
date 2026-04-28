from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.session_store import (
    SESSION_ACTIVE,
    SESSION_CLOSED,
    SessionNotFoundError,
    SQLiteSessionStore,
)


class DeterministicClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


def make_store(tmp_path) -> SQLiteSessionStore:
    return SQLiteSessionStore(tmp_path / "sessions.sqlite", clock=DeterministicClock())


def test_create_lookup_list_and_owner_filtering(tmp_path):
    store = make_store(tmp_path)

    first = store.create(
        session_id="session-a",
        owner_id="user-1",
        model="claude-3-5-sonnet",
    )
    store.create(
        session_id="session-other",
        owner_id="user-2",
        model="gpt-4.1",
    )
    second = store.create(
        session_id="session-b",
        owner_id="user-1",
        model="claude-3-5-sonnet",
        status=SESSION_CLOSED,
    )

    assert first.status == SESSION_ACTIVE
    assert first.pending_approval_refs == []
    assert first.active_job_refs == []
    assert first.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert first.updated_at == first.created_at
    assert store.get("session-a") == first
    assert store.get("missing") is None
    assert store.list(owner_id="user-1") == [first, second]
    assert store.list(status=SESSION_CLOSED) == [second]
    assert store.list(owner_id="user-1", limit=1) == [first]


def test_status_and_ref_updates_use_deterministic_clock(tmp_path):
    store = make_store(tmp_path)
    created = store.create(
        session_id="session-a",
        owner_id="user-1",
        model="claude-3-5-sonnet",
    )

    closed = store.update_status("session-a", SESSION_CLOSED)
    pending = store.update_pending_approval_refs(
        "session-a",
        [{"tool_call_id": "tc-1", "operation_id": "op-1"}],
    )
    active = store.update_active_job_refs(
        "session-a",
        [{"job_id": "job-1", "operation_id": "op-1"}],
    )

    assert closed.status == SESSION_CLOSED
    assert pending.pending_approval_refs == [
        {"tool_call_id": "tc-1", "operation_id": "op-1"}
    ]
    assert active.active_job_refs == [{"job_id": "job-1", "operation_id": "op-1"}]
    assert created.updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert closed.updated_at == datetime(2026, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
    assert pending.updated_at == datetime(2026, 1, 2, 3, 4, 7, tzinfo=timezone.utc)
    assert active.updated_at == datetime(2026, 1, 2, 3, 4, 8, tzinfo=timezone.utc)


def test_close_and_reopen_persists_sessions(tmp_path):
    database_path = tmp_path / "sessions.sqlite"
    store = SQLiteSessionStore(database_path, clock=DeterministicClock())
    created = store.create(
        session_id="session-a",
        owner_id="user-1",
        model="claude-3-5-sonnet",
        pending_approval_refs=[{"tool_call_id": "tc-1"}],
        active_job_refs=[{"job_id": "job-1"}],
    )
    store.close()

    reopened = SQLiteSessionStore(database_path, clock=DeterministicClock())
    try:
        assert reopened.get("session-a") == created
        assert reopened.list(owner_id="user-1") == [created]
    finally:
        reopened.close()


def test_json_refs_are_redacted_before_sqlite_persistence(tmp_path):
    database_path = tmp_path / "sessions.sqlite"
    store = SQLiteSessionStore(database_path, clock=DeterministicClock())
    hf_secret = "hf_sessionsecret123456789"

    created = store.create(
        session_id="session-a",
        owner_id="user-1",
        model="claude-3-5-sonnet",
        pending_approval_refs=[
            {
                "tool_call_id": "tc-1",
                "headers": {"Authorization": f"Bearer {hf_secret}"},
            }
        ],
    )
    updated = store.update_active_job_refs(
        "session-a",
        [{"job_id": "job-1", "logs": f"Authorization: Bearer {hf_secret}"}],
    )

    assert created.pending_approval_refs == [
        {"tool_call_id": "tc-1", "headers": {"Authorization": "[REDACTED]"}}
    ]
    assert created.pending_approval_refs_redaction_status == "redacted"
    assert updated.active_job_refs == [
        {"job_id": "job-1", "logs": "Authorization: Bearer [REDACTED]"}
    ]
    assert updated.active_job_refs_redaction_status == "partial"

    connection = sqlite3.connect(database_path)
    try:
        stored_refs = connection.execute(
            "SELECT pending_approval_refs_json, active_job_refs_json "
            "FROM durable_sessions WHERE id = ?",
            ("session-a",),
        ).fetchone()
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert hf_secret not in str(stored_refs)
    assert hf_secret not in database_dump
    assert "Authorization: Bearer [REDACTED]" in database_dump


@pytest.mark.parametrize(
    "kwargs",
    [
        {"session_id": "", "owner_id": "user-1", "model": "claude-3-5-sonnet"},
        {"session_id": "   ", "owner_id": "user-1", "model": "claude-3-5-sonnet"},
        {"session_id": "session-a", "owner_id": "", "model": "claude-3-5-sonnet"},
        {"session_id": "session-a", "owner_id": "user-1", "model": ""},
    ],
)
def test_create_rejects_invalid_required_text(tmp_path, kwargs):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.create(**kwargs)


def test_invalid_statuses_fail_cleanly(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.create(
            session_id="session-a",
            owner_id="user-1",
            model="claude-3-5-sonnet",
            status="running",
        )

    store.create(
        session_id="session-a",
        owner_id="user-1",
        model="claude-3-5-sonnet",
    )

    with pytest.raises(ValueError):
        store.update_status("session-a", "running")
    with pytest.raises(ValueError):
        store.list(status="running")


def test_missing_session_updates_fail_cleanly(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(SessionNotFoundError):
        store.update_status("missing", SESSION_CLOSED)
    with pytest.raises(SessionNotFoundError):
        store.update_pending_approval_refs("missing", [])
    with pytest.raises(SessionNotFoundError):
        store.update_active_job_refs("missing", [])


def test_list_rejects_invalid_limit(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.list(limit=-1)
