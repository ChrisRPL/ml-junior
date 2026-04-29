from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from agent.core.events import AgentEvent


class SQLiteEventStore:
    """Append-only SQLite store for internal AgentEvent envelopes."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def append(self, event: AgentEvent) -> AgentEvent:
        """Persist a redacted event envelope and return the stored copy."""
        stored_event = event.redacted_copy()

        with self._connection:
            self._connection.execute(_INSERT_EVENT_SQL, _event_row(stored_event))

        return stored_event

    def append_many(self, events: Iterable[AgentEvent]) -> list[AgentEvent]:
        """Persist redacted event envelopes atomically and return stored copies."""
        stored_events = [event.redacted_copy() for event in events]
        if not stored_events:
            return []

        with self._connection:
            self._connection.executemany(
                _INSERT_EVENT_SQL,
                [_event_row(event) for event in stored_events],
            )

        return stored_events

    def replay(
        self,
        session_id: str,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentEvent]:
        """Return session events ordered by sequence after the given cursor."""
        query = """
            SELECT
                id,
                session_id,
                sequence,
                timestamp,
                event_type,
                schema_version,
                redaction_status,
                data_json
            FROM agent_events
            WHERE session_id = ? AND sequence > ?
            ORDER BY sequence ASC
        """
        params: Sequence[Any]
        params = (session_id, after_sequence)

        if limit is not None:
            if limit < 0:
                raise ValueError("limit must be non-negative")
            query += " LIMIT ?"
            params = (session_id, after_sequence, limit)

        rows = self._connection.execute(query, params).fetchall()
        return [self._event_from_row(row) for row in rows]

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_events (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK (sequence >= 1),
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
                    redaction_status TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, sequence)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_agent_events_session_sequence
                ON agent_events (session_id, sequence)
                """
            )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> AgentEvent:
        return AgentEvent(
            id=row["id"],
            session_id=row["session_id"],
            sequence=row["sequence"],
            timestamp=row["timestamp"],
            event_type=row["event_type"],
            schema_version=row["schema_version"],
            redaction_status=row["redaction_status"],
            data=json.loads(row["data_json"]),
        )


_INSERT_EVENT_SQL = """
    INSERT INTO agent_events (
        id,
        session_id,
        sequence,
        timestamp,
        event_type,
        schema_version,
        redaction_status,
        data_json
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


def _event_row(event: AgentEvent) -> tuple[Any, ...]:
    data_json = json.dumps(
        event.data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return (
        event.id,
        event.session_id,
        event.sequence,
        event.timestamp.isoformat(),
        event.event_type,
        event.schema_version,
        event.redaction_status,
        data_json,
    )
