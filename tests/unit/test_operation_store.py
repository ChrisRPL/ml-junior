from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.operation_store import (
    OPERATION_CANCELLED,
    OPERATION_FAILED,
    OPERATION_PENDING,
    OPERATION_RUNNING,
    OPERATION_SUCCEEDED,
    OperationNotFoundError,
    OperationTransitionError,
    SQLiteOperationStore,
)


class DeterministicClock:
    def __init__(self) -> None:
        self._current = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        value = self._current
        self._current += timedelta(seconds=1)
        return value


def make_store(tmp_path) -> SQLiteOperationStore:
    return SQLiteOperationStore(tmp_path / "operations.sqlite", clock=DeterministicClock())


def test_create_lookup_and_list_by_session(tmp_path):
    store = make_store(tmp_path)

    first = store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        idempotency_key="idem-1",
        payload={"dataset": "owner/public", "epochs": 3},
    )
    store.create(
        operation_id="op-other",
        session_id="session-b",
        operation_type="github-issue",
        payload={"repo": "owner/repo"},
    )
    second = store.create(
        operation_id="op-2",
        session_id="session-a",
        operation_type="github-pr",
        payload={"repo": "owner/repo", "title": "Fix"},
    )

    assert first.status == OPERATION_PENDING
    assert first.payload == {"dataset": "owner/public", "epochs": 3}
    assert first.result is None
    assert first.error is None
    assert store.get("op-1") == first
    assert store.get("missing") is None
    assert store.get_by_idempotency_key("idem-1") == first
    assert store.get_by_idempotency_key("missing") is None
    assert store.list_by_session("session-a") == [first, second]


def test_status_transitions_are_deterministic(tmp_path):
    store = make_store(tmp_path)
    created = store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        payload={"job": "queued"},
    )

    running = store.transition_status("op-1", OPERATION_RUNNING)
    succeeded = store.transition_status(
        "op-1",
        OPERATION_SUCCEEDED,
        result={"job_id": "job-123", "state": "complete"},
    )

    assert created.status == OPERATION_PENDING
    assert running.status == OPERATION_RUNNING
    assert succeeded.status == OPERATION_SUCCEEDED
    assert succeeded.result == {"job_id": "job-123", "state": "complete"}
    assert created.created_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert created.updated_at == created.created_at
    assert running.created_at == created.created_at
    assert running.updated_at == datetime(2026, 1, 2, 3, 4, 6, tzinfo=timezone.utc)
    assert succeeded.updated_at == datetime(2026, 1, 2, 3, 4, 7, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("start_status", "allowed_status"),
    [
        (OPERATION_PENDING, OPERATION_RUNNING),
        (OPERATION_PENDING, OPERATION_SUCCEEDED),
        (OPERATION_PENDING, OPERATION_FAILED),
        (OPERATION_PENDING, OPERATION_CANCELLED),
        (OPERATION_RUNNING, OPERATION_SUCCEEDED),
        (OPERATION_RUNNING, OPERATION_FAILED),
        (OPERATION_RUNNING, OPERATION_CANCELLED),
    ],
)
def test_allowed_status_transitions(tmp_path, start_status, allowed_status):
    store = make_store(tmp_path)
    store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        status=start_status,
        payload={},
    )

    updated = store.transition_status("op-1", allowed_status)

    assert updated.status == allowed_status


@pytest.mark.parametrize(
    ("start_status", "blocked_status"),
    [
        (OPERATION_RUNNING, OPERATION_PENDING),
        (OPERATION_SUCCEEDED, OPERATION_RUNNING),
        (OPERATION_FAILED, OPERATION_RUNNING),
        (OPERATION_CANCELLED, OPERATION_RUNNING),
    ],
)
def test_invalid_status_transitions_fail_cleanly(tmp_path, start_status, blocked_status):
    store = make_store(tmp_path)
    original = store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        status=start_status,
        payload={},
    )

    with pytest.raises(OperationTransitionError):
        store.transition_status("op-1", blocked_status)

    assert store.get("op-1") == original


def test_missing_operation_transition_fails_cleanly(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(OperationNotFoundError):
        store.transition_status("missing", OPERATION_RUNNING)


def test_repeated_same_status_transition_is_noop_without_payload_changes(tmp_path):
    store = make_store(tmp_path)
    original = store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        payload={"job": "queued"},
    )

    repeated = store.transition_status("op-1", OPERATION_PENDING)

    assert repeated == original


def test_payload_result_and_error_are_redacted_before_sqlite_persistence(tmp_path):
    database_path = tmp_path / "operations.sqlite"
    store = SQLiteOperationStore(database_path, clock=DeterministicClock())
    hf_secret = "hf_operationsecret123456789"
    github_secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"

    created = store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        idempotency_key="idem-1",
        payload={
            "headers": {"Authorization": f"Bearer {hf_secret}"},
            "github_token": github_secret,
            "prompt": f"use bearer {hf_secret}",
        },
    )
    updated = store.transition_status(
        "op-1",
        OPERATION_FAILED,
        result={"logs": f"Authorization: Bearer {hf_secret}"},
        error=f"GITHUB_TOKEN={github_secret}",
    )

    assert created.payload["headers"]["Authorization"] == "[REDACTED]"
    assert created.payload["github_token"] == "[REDACTED]"
    assert created.payload["prompt"] == "use bearer [REDACTED]"
    assert created.payload_redaction_status == "redacted"
    assert updated.result == {"logs": "Authorization: Bearer [REDACTED]"}
    assert updated.error == "GITHUB_TOKEN=[REDACTED]"
    assert updated.result_redaction_status == "partial"
    assert updated.error_redaction_status == "partial"

    connection = sqlite3.connect(database_path)
    try:
        stored_payload = connection.execute(
            "SELECT payload_json, result_json, error_json FROM durable_operations "
            "WHERE id = ?",
            ("op-1",),
        ).fetchone()
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert hf_secret not in str(stored_payload)
    assert github_secret not in str(stored_payload)
    assert hf_secret not in database_dump
    assert github_secret not in database_dump
    assert "Authorization: Bearer [REDACTED]" in database_dump
    assert "GITHUB_TOKEN=[REDACTED]" in database_dump


def test_unique_idempotency_key_is_enforced(tmp_path):
    store = make_store(tmp_path)
    store.create(
        operation_id="op-1",
        session_id="session-a",
        operation_type="hf-job",
        idempotency_key="idem-1",
        payload={},
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.create(
            operation_id="op-2",
            session_id="session-a",
            operation_type="hf-job",
            idempotency_key="idem-1",
            payload={},
        )


def test_list_by_session_rejects_negative_limit(tmp_path):
    store = make_store(tmp_path)

    with pytest.raises(ValueError):
        store.list_by_session("session-a", limit=-1)
