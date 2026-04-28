from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent.core.redaction import REDACTION_NONE, redact_value

# Conservative durable-session states. Runtime lifecycle wiring can widen this
# only when session-manager semantics are ready to enforce the new states.
SESSION_ACTIVE = "active"
SESSION_CLOSED = "closed"
SESSION_STATUSES = frozenset({SESSION_ACTIVE, SESSION_CLOSED})


class SessionStoreError(Exception):
    """Base error for durable session store failures."""


class SessionNotFoundError(SessionStoreError):
    """Raised when a session id does not exist."""


@dataclass(frozen=True)
class SessionRecord:
    id: str
    owner_id: str
    model: str
    status: str
    created_at: datetime
    updated_at: datetime
    pending_approval_refs: Any
    active_job_refs: Any
    pending_approval_refs_redaction_status: str = REDACTION_NONE
    active_job_refs_redaction_status: str = REDACTION_NONE


class SQLiteSessionStore:
    """SQLite store for durable backend session metadata."""

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
        session_id: str,
        owner_id: str,
        model: str,
        status: str = SESSION_ACTIVE,
        pending_approval_refs: Any | None = None,
        active_job_refs: Any | None = None,
    ) -> SessionRecord:
        """Insert a redacted durable session record and return the stored copy."""
        _validate_required_text("session_id", session_id)
        _validate_required_text("owner_id", owner_id)
        _validate_required_text("model", model)
        _validate_status(status)

        now = self._now()
        pending_json, pending_redaction_status = _redacted_json(
            [] if pending_approval_refs is None else pending_approval_refs
        )
        active_json, active_redaction_status = _redacted_json(
            [] if active_job_refs is None else active_job_refs
        )

        with self._connection:
            self._connection.execute(
                """
                INSERT INTO durable_sessions (
                    id,
                    owner_id,
                    model,
                    status,
                    pending_approval_refs_json,
                    pending_approval_refs_redaction_status,
                    active_job_refs_json,
                    active_job_refs_redaction_status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    owner_id,
                    model,
                    status,
                    pending_json,
                    pending_redaction_status,
                    active_json,
                    active_redaction_status,
                    now,
                    now,
                ),
            )

        record = self.get(session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    def get(self, session_id: str) -> SessionRecord | None:
        """Return one session by id, or None when absent."""
        row = self._connection.execute(
            """
            SELECT
                id,
                owner_id,
                model,
                status,
                pending_approval_refs_json,
                pending_approval_refs_redaction_status,
                active_job_refs_json,
                active_job_refs_redaction_status,
                created_at,
                updated_at
            FROM durable_sessions
            WHERE id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return self._record_from_row(row)

    def list(
        self,
        *,
        owner_id: str | None = None,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[SessionRecord]:
        """Return sessions ordered by creation time, optionally filtered by owner."""
        if owner_id is not None:
            _validate_required_text("owner_id", owner_id)
        if status is not None:
            _validate_status(status)

        query = """
            SELECT
                id,
                owner_id,
                model,
                status,
                pending_approval_refs_json,
                pending_approval_refs_redaction_status,
                active_job_refs_json,
                active_job_refs_redaction_status,
                created_at,
                updated_at
            FROM durable_sessions
        """
        clauses: list[str] = []
        params: list[Any] = []
        if owner_id is not None:
            clauses.append("owner_id = ?")
            params.append(owner_id)
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC, id ASC"

        final_params: Sequence[Any] = tuple(params)
        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            query += " LIMIT ?"
            final_params = tuple([*params, limit])

        rows = self._connection.execute(query, final_params).fetchall()
        return [self._record_from_row(row) for row in rows]

    def update_status(self, session_id: str, status: str) -> SessionRecord:
        """Update a durable session status and return the updated record."""
        _validate_required_text("session_id", session_id)
        _validate_status(status)
        self._ensure_exists(session_id)

        with self._connection:
            self._connection.execute(
                """
                UPDATE durable_sessions
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, self._now(), session_id),
            )

        updated = self.get(session_id)
        if updated is None:
            raise SessionNotFoundError(session_id)
        return updated

    def update_pending_approval_refs(
        self,
        session_id: str,
        pending_approval_refs: Any,
    ) -> SessionRecord:
        """Replace pending approval refs after redaction and return the record."""
        return self._update_json_refs(
            session_id,
            json_column="pending_approval_refs_json",
            status_column="pending_approval_refs_redaction_status",
            value=pending_approval_refs,
        )

    def update_active_job_refs(
        self,
        session_id: str,
        active_job_refs: Any,
    ) -> SessionRecord:
        """Replace active job refs after redaction and return the record."""
        return self._update_json_refs(
            session_id,
            json_column="active_job_refs_json",
            status_column="active_job_refs_redaction_status",
            value=active_job_refs,
        )

    def _update_json_refs(
        self,
        session_id: str,
        *,
        json_column: str,
        status_column: str,
        value: Any,
    ) -> SessionRecord:
        _validate_required_text("session_id", session_id)
        self._ensure_exists(session_id)
        refs_json, redaction_status = _redacted_json(value)

        with self._connection:
            self._connection.execute(
                f"""
                UPDATE durable_sessions
                SET {json_column} = ?, {status_column} = ?, updated_at = ?
                WHERE id = ?
                """,
                (refs_json, redaction_status, self._now(), session_id),
            )

        updated = self.get(session_id)
        if updated is None:
            raise SessionNotFoundError(session_id)
        return updated

    def _ensure_exists(self, session_id: str) -> None:
        row = self._connection.execute(
            "SELECT 1 FROM durable_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise SessionNotFoundError(session_id)

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS durable_sessions (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    model TEXT NOT NULL,
                    status TEXT NOT NULL,
                    pending_approval_refs_json TEXT NOT NULL,
                    pending_approval_refs_redaction_status TEXT NOT NULL,
                    active_job_refs_json TEXT NOT NULL,
                    active_job_refs_redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_sessions_owner_created
                ON durable_sessions (owner_id, created_at, id)
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_durable_sessions_status
                ON durable_sessions (status)
                """
            )

    def _now(self) -> str:
        value = self._clock()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            owner_id=row["owner_id"],
            model=row["model"],
            status=row["status"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            pending_approval_refs=json.loads(row["pending_approval_refs_json"]),
            active_job_refs=json.loads(row["active_job_refs_json"]),
            pending_approval_refs_redaction_status=row[
                "pending_approval_refs_redaction_status"
            ],
            active_job_refs_redaction_status=row[
                "active_job_refs_redaction_status"
            ],
        )


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _validate_status(status: str) -> None:
    if status not in SESSION_STATUSES:
        raise ValueError(f"unknown session status: {status}")


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
