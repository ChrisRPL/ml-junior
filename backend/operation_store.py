from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.core.redaction import REDACTION_NONE, redact_value

OPERATION_PENDING = "pending"
OPERATION_RUNNING = "running"
OPERATION_SUCCEEDED = "succeeded"
OPERATION_FAILED = "failed"
OPERATION_CANCELLED = "cancelled"

OPERATION_STATUSES = frozenset(
    {
        OPERATION_PENDING,
        OPERATION_RUNNING,
        OPERATION_SUCCEEDED,
        OPERATION_FAILED,
        OPERATION_CANCELLED,
    }
)
TERMINAL_OPERATION_STATUSES = frozenset(
    {OPERATION_SUCCEEDED, OPERATION_FAILED, OPERATION_CANCELLED}
)

_ALLOWED_STATUS_TRANSITIONS: dict[str, frozenset[str]] = {
    OPERATION_PENDING: frozenset(
        {
            OPERATION_RUNNING,
            OPERATION_SUCCEEDED,
            OPERATION_FAILED,
            OPERATION_CANCELLED,
        }
    ),
    OPERATION_RUNNING: frozenset(
        {OPERATION_SUCCEEDED, OPERATION_FAILED, OPERATION_CANCELLED}
    ),
    OPERATION_SUCCEEDED: frozenset(),
    OPERATION_FAILED: frozenset(),
    OPERATION_CANCELLED: frozenset(),
}

_UNSET = object()


class OperationStoreError(Exception):
    """Base error for durable operation store failures."""


class OperationNotFoundError(OperationStoreError):
    """Raised when an operation id does not exist."""


class OperationTransitionError(OperationStoreError):
    """Raised when a status transition is not allowed."""


@dataclass(frozen=True)
class OperationRecord:
    id: str
    session_id: str
    operation_type: str
    status: str
    idempotency_key: str | None
    payload: Any
    created_at: datetime
    updated_at: datetime
    result: Any | None = None
    error: Any | None = None
    payload_redaction_status: str = REDACTION_NONE
    result_redaction_status: str = REDACTION_NONE
    error_redaction_status: str = REDACTION_NONE


class SQLiteOperationStore:
    """SQLite store for durable operation records."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def create(
        self,
        *,
        operation_id: str,
        session_id: str,
        operation_type: str,
        payload: Any,
        idempotency_key: str | None = None,
        status: str = OPERATION_PENDING,
    ) -> OperationRecord:
        """Insert a redacted operation record and return the stored copy."""
        _validate_required_text("operation_id", operation_id)
        _validate_required_text("session_id", session_id)
        _validate_required_text("operation_type", operation_type)
        _validate_status(status)

        now = self._now()
        payload_json, payload_redaction_status = _redacted_json(payload)

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO durable_operations (
                    id,
                    session_id,
                    operation_type,
                    status,
                    idempotency_key,
                    payload_json,
                    payload_redaction_status,
                    result_json,
                    result_redaction_status,
                    error_json,
                    error_redaction_status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)
                """,
                (
                    operation_id,
                    session_id,
                    operation_type,
                    status,
                    idempotency_key,
                    payload_json,
                    payload_redaction_status,
                    REDACTION_NONE,
                    REDACTION_NONE,
                    now,
                    now,
                ),
            )

        record = self.get(operation_id)
        if record is None:
            raise OperationNotFoundError(operation_id)
        return record

    def get(self, operation_id: str) -> OperationRecord | None:
        """Return one operation by id, or None when absent."""
        row = self._connection.execute(
            """
            SELECT
                id,
                session_id,
                operation_type,
                status,
                idempotency_key,
                payload_json,
                payload_redaction_status,
                result_json,
                result_redaction_status,
                error_json,
                error_redaction_status,
                created_at,
                updated_at
            FROM durable_operations
            WHERE id = ?
            """,
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        return self._record_from_row(row)

    def get_by_idempotency_key(self, idempotency_key: str) -> OperationRecord | None:
        """Return one operation by idempotency key, or None when absent."""
        row = self._connection.execute(
            """
            SELECT
                id,
                session_id,
                operation_type,
                status,
                idempotency_key,
                payload_json,
                payload_redaction_status,
                result_json,
                result_redaction_status,
                error_json,
                error_redaction_status,
                created_at,
                updated_at
            FROM durable_operations
            WHERE idempotency_key = ?
            """,
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        return self._record_from_row(row)

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[OperationRecord]:
        """Return session operations ordered by creation time."""
        query = """
            SELECT
                id,
                session_id,
                operation_type,
                status,
                idempotency_key,
                payload_json,
                payload_redaction_status,
                result_json,
                result_redaction_status,
                error_json,
                error_redaction_status,
                created_at,
                updated_at
            FROM durable_operations
            WHERE session_id = ?
            ORDER BY created_at ASC, id ASC
        """
        params: Sequence[Any] = (session_id,)

        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            query += " LIMIT ?"
            params = (session_id, limit)

        rows = self._connection.execute(query, params).fetchall()
        return [self._record_from_row(row) for row in rows]

    def transition_status(
        self,
        operation_id: str,
        status: str,
        *,
        result: Any = _UNSET,
        error: Any = _UNSET,
    ) -> OperationRecord:
        """Move an operation to a new status with optional redacted result/error."""
        _validate_status(status)
        current = self.get(operation_id)
        if current is None:
            raise OperationNotFoundError(operation_id)

        if status != current.status:
            allowed = _ALLOWED_STATUS_TRANSITIONS[current.status]
            if status not in allowed:
                raise OperationTransitionError(
                    f"cannot transition operation {operation_id} "
                    f"from {current.status!r} to {status!r}"
                )

        if status == current.status and result is _UNSET and error is _UNSET:
            return current

        now = self._now()
        result_json = _UNSET
        result_redaction_status = _UNSET
        error_json = _UNSET
        error_redaction_status = _UNSET

        if result is not _UNSET:
            result_json, result_redaction_status = _redacted_json_or_null(result)
        if error is not _UNSET:
            error_json, error_redaction_status = _redacted_json_or_null(error)

        assignments = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]
        if result_json is not _UNSET:
            assignments.extend(["result_json = ?", "result_redaction_status = ?"])
            params.extend([result_json, result_redaction_status])
        if error_json is not _UNSET:
            assignments.extend(["error_json = ?", "error_redaction_status = ?"])
            params.extend([error_json, error_redaction_status])
        params.append(operation_id)

        with self._connection:
            self._connection.execute(
                f"""
                UPDATE durable_operations
                SET {", ".join(assignments)}
                WHERE id = ?
                """,
                params,
            )

        updated = self.get(operation_id)
        if updated is None:
            raise OperationNotFoundError(operation_id)
        return updated

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_operations (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    operation_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    payload_json TEXT NOT NULL,
                    payload_redaction_status TEXT NOT NULL,
                    result_json TEXT,
                    result_redaction_status TEXT NOT NULL,
                    error_json TEXT,
                    error_redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_operations_session_created
                ON durable_operations (session_id, created_at, id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_operations_status
                ON durable_operations (status)
                """
            )

    def _now(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> OperationRecord:
        return OperationRecord(
            id=row["id"],
            session_id=row["session_id"],
            operation_type=row["operation_type"],
            status=row["status"],
            idempotency_key=row["idempotency_key"],
            payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            result=_json_loads_or_none(row["result_json"]),
            error=_json_loads_or_none(row["error_json"]),
            payload_redaction_status=row["payload_redaction_status"],
            result_redaction_status=row["result_redaction_status"],
            error_redaction_status=row["error_redaction_status"],
        )


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _validate_status(status: str) -> None:
    if status not in OPERATION_STATUSES:
        raise ValueError(f"unknown operation status: {status}")


def _redacted_json(value: Any) -> tuple[str, str]:
    result = redact_value(value)
    return (
        json.dumps(
            result.value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        result.status,
    )


def _redacted_json_or_null(value: Any) -> tuple[str | None, str]:
    if value is None:
        return None, REDACTION_NONE
    return _redacted_json(value)


def _json_loads_or_none(value: str | None) -> Any | None:
    if value is None:
        return None
    return json.loads(value)
