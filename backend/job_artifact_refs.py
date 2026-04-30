from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from agent.core.events import AgentEvent
from agent.core.redaction import redact_value
from backend.models import ActiveJobRecord, ArtifactRefRecord


ACTIVE_JOB_RECORDED_EVENT = "active_job.recorded"
ARTIFACT_REF_RECORDED_EVENT = "artifact_ref.recorded"

TERMINAL_ACTIVE_JOB_STATUSES = {"completed", "failed", "cancelled"}

JobArtifactRecord: TypeAlias = ActiveJobRecord | ArtifactRefRecord
JobArtifactRecordT = TypeVar(
    "JobArtifactRecordT",
    ActiveJobRecord,
    ArtifactRefRecord,
)


class JobArtifactRefError(ValueError):
    """Raised when job/artifact reference event data is invalid."""


def generate_active_job_id() -> str:
    """Return an opaque active job identifier."""
    return f"active-job-{uuid.uuid4().hex}"


def generate_artifact_id() -> str:
    """Return an opaque artifact identifier."""
    return f"artifact-{uuid.uuid4().hex}"


def active_job_recorded_payload(record: ActiveJobRecord) -> dict[str, Any]:
    """Serialize an active job record into an AgentEvent payload."""
    return _record_payload(record)


def artifact_ref_recorded_payload(record: ArtifactRefRecord) -> dict[str, Any]:
    """Serialize an artifact reference record into an AgentEvent payload."""
    return _record_payload(record)


def active_job_record_from_event(event: AgentEvent) -> ActiveJobRecord:
    """Validate an active_job.recorded event as an active job record."""
    if event.event_type != ACTIVE_JOB_RECORDED_EVENT:
        raise JobArtifactRefError(f"Expected {ACTIVE_JOB_RECORDED_EVENT}")

    record = ActiveJobRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise JobArtifactRefError(
            "active job event session_id does not match record session_id"
        )
    return record


def artifact_ref_record_from_event(event: AgentEvent) -> ArtifactRefRecord:
    """Validate an artifact_ref.recorded event as an artifact reference record."""
    if event.event_type != ARTIFACT_REF_RECORDED_EVENT:
        raise JobArtifactRefError(f"Expected {ARTIFACT_REF_RECORDED_EVENT}")

    record = ArtifactRefRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise JobArtifactRefError(
            "artifact ref event session_id does not match record session_id"
        )
    return record


def project_active_jobs(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[ActiveJobRecord]:
    """Project current non-terminal active jobs from supplied events only."""
    latest: dict[str, tuple[tuple[int, str], ActiveJobRecord]] = {}
    for event in _ordered_session_events(session_id, events, ACTIVE_JOB_RECORDED_EVENT):
        record = active_job_record_from_event(event)
        latest[record.job_id] = ((event.sequence, str(event.id)), record)

    return [
        record
        for _, record in sorted(latest.values(), key=lambda value: value[0])
        if record.status not in TERMINAL_ACTIVE_JOB_STATUSES
    ]


def project_artifact_refs(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[ArtifactRefRecord]:
    """Project latest artifact references from supplied events only."""
    latest: dict[str, tuple[tuple[int, str], ArtifactRefRecord]] = {}
    for event in _ordered_session_events(
        session_id,
        events,
        ARTIFACT_REF_RECORDED_EVENT,
    ):
        record = artifact_ref_record_from_event(event)
        latest[record.artifact_id] = ((event.sequence, str(event.id)), record)

    return [record for _, record in sorted(latest.values(), key=lambda value: value[0])]


class SQLiteJobArtifactRefStore:
    """Append-only SQLite store for inert active-job and artifact records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def append_active_job(self, record: ActiveJobRecord) -> ActiveJobRecord:
        """Persist one redacted active-job record and return the stored copy."""
        record = ActiveJobRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("job_id", record.job_id)

        self._insert_record(
            table_name="active_job_records",
            id_column="job_id",
            id_value=record.job_id,
            record=record,
            duplicate_label="active job",
        )

        stored = self._get_record(
            "active_job_records",
            "job_id",
            record.session_id,
            record.job_id,
            record.source_event_sequence,
            _active_job_record_from_json,
        )
        if stored is None:
            raise JobArtifactRefError("active job was not stored")
        return stored

    def append_artifact_ref(self, record: ArtifactRefRecord) -> ArtifactRefRecord:
        """Persist one redacted artifact reference record and return stored copy."""
        record = ArtifactRefRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("artifact_id", record.artifact_id)

        self._insert_record(
            table_name="artifact_ref_records",
            id_column="artifact_id",
            id_value=record.artifact_id,
            record=record,
            duplicate_label="artifact ref",
        )

        stored = self._get_record(
            "artifact_ref_records",
            "artifact_id",
            record.session_id,
            record.artifact_id,
            record.source_event_sequence,
            _artifact_ref_record_from_json,
        )
        if stored is None:
            raise JobArtifactRefError("artifact ref was not stored")
        return stored

    def list_active_jobs(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ActiveJobRecord]:
        """Return session active-job records in append order."""
        rows = self._list_rows("active_job_records", session_id, limit)
        return [_active_job_record_from_json(row["record_json"]) for row in rows]

    def list_artifact_refs(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ArtifactRefRecord]:
        """Return session artifact-reference records in append order."""
        rows = self._list_rows("artifact_ref_records", session_id, limit)
        return [_artifact_ref_record_from_json(row["record_json"]) for row in rows]

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS active_job_records (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    source_event_sequence INTEGER CHECK (
                        source_event_sequence IS NULL
                        OR source_event_sequence >= 1
                    ),
                    source_event_sequence_key INTEGER NOT NULL CHECK (
                        source_event_sequence_key >= 0
                    ),
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, job_id, source_event_sequence_key)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_active_job_records_session_sequence
                ON active_job_records (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS artifact_ref_records (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    source_event_sequence INTEGER CHECK (
                        source_event_sequence IS NULL
                        OR source_event_sequence >= 1
                    ),
                    source_event_sequence_key INTEGER NOT NULL CHECK (
                        source_event_sequence_key >= 0
                    ),
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, artifact_id, source_event_sequence_key)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifact_ref_records_session_sequence
                ON artifact_ref_records (session_id, ledger_sequence)
                """
            )

    def _insert_record(
        self,
        *,
        table_name: str,
        id_column: str,
        id_value: str,
        record: JobArtifactRecord,
        duplicate_label: str,
    ) -> None:
        record_json, redaction_status = _redacted_record_json(record)

        try:
            with self._connection:
                self._connection.execute(
                    f"""
                    INSERT INTO {table_name} (
                        session_id,
                        {id_column},
                        source_event_sequence,
                        source_event_sequence_key,
                        record_json,
                        redaction_status
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        id_value,
                        record.source_event_sequence,
                        _source_event_sequence_key(record.source_event_sequence),
                        record_json,
                        redaction_status,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_error(exc, f"{table_name}.session_id"):
                raise JobArtifactRefError(
                    f"{duplicate_label} already exists: "
                    f"session_id={record.session_id} "
                    f"{id_column}={id_value} "
                    f"source_event_sequence={record.source_event_sequence}"
                ) from exc
            raise

    def _get_record(
        self,
        table_name: str,
        id_column: str,
        session_id: str,
        record_id: str,
        source_event_sequence: int | None,
        parser: Callable[[str], JobArtifactRecordT],
    ) -> JobArtifactRecordT | None:
        row = self._connection.execute(
            f"""
            SELECT record_json
            FROM {table_name}
            WHERE session_id = ?
                AND {id_column} = ?
                AND source_event_sequence_key = ?
            """,
            (
                session_id,
                record_id,
                _source_event_sequence_key(source_event_sequence),
            ),
        ).fetchone()
        if row is None:
            return None
        return parser(row["record_json"])

    def _list_rows(
        self,
        table_name: str,
        session_id: str,
        limit: int | None,
    ) -> list[sqlite3.Row]:
        query = f"""
            SELECT record_json
            FROM {table_name}
            WHERE session_id = ?
            ORDER BY ledger_sequence ASC
        """
        params: Sequence[Any] = (session_id,)

        if limit is not None:
            if limit < 0:
                raise JobArtifactRefError("limit must be non-negative")
            query += " LIMIT ?"
            params = (session_id, limit)

        return self._connection.execute(query, params).fetchall()


def _ordered_session_events(
    session_id: str,
    events: Sequence[AgentEvent],
    event_type: str,
) -> list[AgentEvent]:
    return sorted(
        [
            event
            for event in events
            if event.session_id == session_id and event.event_type == event_type
        ],
        key=lambda event: (event.sequence, str(event.id)),
    )


def _record_payload(record: ActiveJobRecord | ArtifactRefRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_json(record: JobArtifactRecord) -> tuple[str, str]:
    result = redact_value(_record_payload(record))
    redaction_status = _stronger_redaction_status(
        record.redaction_status,
        result.status,
    )
    value = result.value
    if isinstance(value, dict):
        value = {**value, "redaction_status": redaction_status}
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        redaction_status,
    )


def _active_job_record_from_json(value: str) -> ActiveJobRecord:
    return ActiveJobRecord.model_validate(json.loads(value))


def _artifact_ref_record_from_json(value: str) -> ArtifactRefRecord:
    return ArtifactRefRecord.model_validate(json.loads(value))


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise JobArtifactRefError(f"{name} must be a non-empty string")


def _source_event_sequence_key(source_event_sequence: int | None) -> int:
    return source_event_sequence if source_event_sequence is not None else 0


def _stronger_redaction_status(left: str, right: str) -> str:
    if "redacted" in (left, right):
        return "redacted"
    if "partial" in (left, right):
        return "partial"
    return "none"


def _is_duplicate_error(exc: sqlite3.IntegrityError, table_column: str) -> bool:
    message = str(exc).lower()
    return "unique" in message and table_column in message
