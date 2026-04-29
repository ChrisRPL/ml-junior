from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent.core.events import AgentEvent
from agent.core.redaction import redact_value
from backend.models import ExperimentRunRecord


EXPERIMENT_RUN_RECORDED_EVENT = "experiment.run_recorded"


class ExperimentLedgerError(ValueError):
    """Raised when experiment run ledger data is invalid or conflicts."""


def generate_experiment_run_id() -> str:
    """Return an opaque experiment run identifier."""
    return f"run-{uuid.uuid4().hex}"


def experiment_run_recorded_payload(record: ExperimentRunRecord) -> dict[str, Any]:
    """Serialize an experiment run record into an AgentEvent payload."""
    return _record_payload(record)


def run_record_from_event(event: AgentEvent) -> ExperimentRunRecord:
    """Validate an experiment.run_recorded event as an experiment run record."""
    if event.event_type != EXPERIMENT_RUN_RECORDED_EVENT:
        raise ExperimentLedgerError(f"Expected {EXPERIMENT_RUN_RECORDED_EVENT}")

    record = ExperimentRunRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise ExperimentLedgerError(
            "experiment run event session_id does not match record session_id"
        )
    return record


def project_experiment_runs(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[ExperimentRunRecord]:
    """Project durable experiment run records from supplied events only."""
    return [
        run_record_from_event(event)
        for event in sorted(
            [
                event
                for event in events
                if event.session_id == session_id
                and event.event_type == EXPERIMENT_RUN_RECORDED_EVENT
            ],
            key=lambda event: (event.sequence, str(event.id)),
        )
    ]


class SQLiteExperimentLedgerStore:
    """Append-only SQLite store for experiment run records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def create(self, record: ExperimentRunRecord) -> ExperimentRunRecord:
        """Persist a redacted experiment run record and return the stored copy."""
        record = ExperimentRunRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("run_id", record.run_id)

        record_json, redaction_status = _redacted_record_json(record)

        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO experiment_runs (
                        session_id,
                        run_id,
                        record_json,
                        redaction_status
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        record.run_id,
                        record_json,
                        redaction_status,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_run_error(exc):
                raise ExperimentLedgerError(
                    f"experiment run already exists: "
                    f"session_id={record.session_id} run_id={record.run_id}"
                ) from exc
            raise

        stored = self.get(record.session_id, record.run_id)
        if stored is None:
            raise ExperimentLedgerError("experiment run was not stored")
        return stored

    def get(self, session_id: str, run_id: str) -> ExperimentRunRecord | None:
        """Return one experiment run by session and run id, or None."""
        row = self._connection.execute(
            """
            SELECT record_json
            FROM experiment_runs
            WHERE session_id = ? AND run_id = ?
            """,
            (session_id, run_id),
        ).fetchone()
        if row is None:
            return None
        return _record_from_json(row["record_json"])

    def list(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ExperimentRunRecord]:
        """Return session experiment runs in append order."""
        query = """
            SELECT record_json
            FROM experiment_runs
            WHERE session_id = ?
            ORDER BY ledger_sequence ASC
        """
        params: Sequence[Any] = (session_id,)

        if limit is not None:
            if limit < 0:
                raise ExperimentLedgerError("limit must be non-negative")
            query += " LIMIT ?"
            params = (session_id, limit)

        rows = self._connection.execute(query, params).fetchall()
        return [_record_from_json(row["record_json"]) for row in rows]

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_runs (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, run_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_experiment_runs_session_sequence
                ON experiment_runs (session_id, ledger_sequence)
                """
            )


def _record_payload(record: ExperimentRunRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_json(record: ExperimentRunRecord) -> tuple[str, str]:
    result = redact_value(_record_payload(record))
    return (
        json.dumps(
            result.value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        result.status,
    )


def _record_from_json(value: str) -> ExperimentRunRecord:
    return ExperimentRunRecord.model_validate(json.loads(value))


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ExperimentLedgerError(f"{name} must be a non-empty string")


def _is_duplicate_run_error(exc: sqlite3.IntegrityError) -> bool:
    message = str(exc).lower()
    return "unique" in message and "experiment_runs.session_id" in message
