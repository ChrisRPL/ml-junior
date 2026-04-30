from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from agent.core.events import AgentEvent
from agent.core.redaction import redact_value
from backend.models import (
    ArtifactRefRecord,
    CodeSnapshotRecord,
    DatasetSnapshotRecord,
    ExperimentRunRecord,
    LogRefRecord,
    MetricRecord,
)


EXPERIMENT_RUN_RECORDED_EVENT = "experiment.run_recorded"
DATASET_SNAPSHOT_RECORDED_EVENT = "dataset_snapshot.recorded"
CODE_SNAPSHOT_RECORDED_EVENT = "code_snapshot.recorded"
METRIC_RECORDED_EVENT = "metric.recorded"
LOG_REF_RECORDED_EVENT = "log_ref.recorded"
ARTIFACT_REF_RECORDED_EVENT = "artifact_ref.recorded"

LedgerRecord: TypeAlias = (
    ExperimentRunRecord
    | DatasetSnapshotRecord
    | CodeSnapshotRecord
    | MetricRecord
    | LogRefRecord
    | ArtifactRefRecord
)
LedgerRecordT = TypeVar(
    "LedgerRecordT",
    ExperimentRunRecord,
    DatasetSnapshotRecord,
    CodeSnapshotRecord,
    MetricRecord,
    LogRefRecord,
    ArtifactRefRecord,
)


class ExperimentLedgerError(ValueError):
    """Raised when experiment run ledger data is invalid or conflicts."""


def generate_experiment_run_id() -> str:
    """Return an opaque experiment run identifier."""
    return f"run-{uuid.uuid4().hex}"


def generate_dataset_snapshot_id() -> str:
    """Return an opaque dataset snapshot identifier."""
    return f"dataset-snapshot-{uuid.uuid4().hex}"


def generate_code_snapshot_id() -> str:
    """Return an opaque code snapshot identifier."""
    return f"code-snapshot-{uuid.uuid4().hex}"


def generate_metric_id() -> str:
    """Return an opaque metric identifier."""
    return f"metric-{uuid.uuid4().hex}"


def generate_log_id() -> str:
    """Return an opaque log reference identifier."""
    return f"log-{uuid.uuid4().hex}"


def experiment_run_recorded_payload(record: ExperimentRunRecord) -> dict[str, Any]:
    """Serialize an experiment run record into an AgentEvent payload."""
    return _record_payload(record)


def dataset_snapshot_recorded_payload(
    record: DatasetSnapshotRecord,
) -> dict[str, Any]:
    """Serialize a dataset snapshot record into an AgentEvent payload."""
    return _record_payload(record)


def code_snapshot_recorded_payload(record: CodeSnapshotRecord) -> dict[str, Any]:
    """Serialize a code snapshot record into an AgentEvent payload."""
    return _record_payload(record)


def metric_recorded_payload(record: MetricRecord) -> dict[str, Any]:
    """Serialize a standalone metric record into an AgentEvent payload."""
    return _record_payload(record)


def log_ref_recorded_payload(record: LogRefRecord) -> dict[str, Any]:
    """Serialize a standalone log reference record into an AgentEvent payload."""
    return _record_payload(record)


def artifact_ref_recorded_payload(record: ArtifactRefRecord) -> dict[str, Any]:
    """Serialize a canonical artifact reference record into an AgentEvent payload."""
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


def dataset_snapshot_record_from_event(event: AgentEvent) -> DatasetSnapshotRecord:
    """Validate a dataset_snapshot.recorded event as a dataset snapshot record."""
    if event.event_type != DATASET_SNAPSHOT_RECORDED_EVENT:
        raise ExperimentLedgerError(f"Expected {DATASET_SNAPSHOT_RECORDED_EVENT}")

    record = DatasetSnapshotRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise ExperimentLedgerError(
            "dataset snapshot event session_id does not match record session_id"
        )
    return record


def code_snapshot_record_from_event(event: AgentEvent) -> CodeSnapshotRecord:
    """Validate a code_snapshot.recorded event as a code snapshot record."""
    if event.event_type != CODE_SNAPSHOT_RECORDED_EVENT:
        raise ExperimentLedgerError(f"Expected {CODE_SNAPSHOT_RECORDED_EVENT}")

    record = CodeSnapshotRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise ExperimentLedgerError(
            "code snapshot event session_id does not match record session_id"
        )
    return record


def metric_record_from_event(event: AgentEvent) -> MetricRecord:
    """Validate a metric.recorded event as a standalone metric record."""
    if event.event_type != METRIC_RECORDED_EVENT:
        raise ExperimentLedgerError(f"Expected {METRIC_RECORDED_EVENT}")

    record = MetricRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise ExperimentLedgerError(
            "metric event session_id does not match record session_id"
        )
    return record


def log_ref_record_from_event(event: AgentEvent) -> LogRefRecord:
    """Validate a log_ref.recorded event as a standalone log reference record."""
    if event.event_type != LOG_REF_RECORDED_EVENT:
        raise ExperimentLedgerError(f"Expected {LOG_REF_RECORDED_EVENT}")

    record = LogRefRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise ExperimentLedgerError(
            "log ref event session_id does not match record session_id"
        )
    return record


def artifact_ref_record_from_event(event: AgentEvent) -> ArtifactRefRecord:
    """Validate an artifact_ref.recorded event as a canonical artifact ref record."""
    if event.event_type != ARTIFACT_REF_RECORDED_EVENT:
        raise ExperimentLedgerError(f"Expected {ARTIFACT_REF_RECORDED_EVENT}")

    record = ArtifactRefRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise ExperimentLedgerError(
            "artifact ref event session_id does not match record session_id"
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


def project_dataset_snapshots(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[DatasetSnapshotRecord]:
    """Project durable dataset snapshot records from supplied events only."""
    return [
        dataset_snapshot_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            DATASET_SNAPSHOT_RECORDED_EVENT,
        )
    ]


def project_code_snapshots(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[CodeSnapshotRecord]:
    """Project durable code snapshot records from supplied events only."""
    return [
        code_snapshot_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            CODE_SNAPSHOT_RECORDED_EVENT,
        )
    ]


def project_metrics(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[MetricRecord]:
    """Project standalone metric records from supplied events only."""
    return [
        metric_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            METRIC_RECORDED_EVENT,
        )
    ]


def project_log_refs(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[LogRefRecord]:
    """Project standalone log reference records from supplied events only."""
    return [
        log_ref_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            LOG_REF_RECORDED_EVENT,
        )
    ]


def project_artifact_refs(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[ArtifactRefRecord]:
    """Project canonical artifact reference records from supplied events only."""
    return [
        artifact_ref_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            ARTIFACT_REF_RECORDED_EVENT,
        )
    ]


class SQLiteExperimentLedgerStore:
    """Append-only SQLite store for inert experiment ledger records."""

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

    def create_dataset_snapshot(
        self,
        record: DatasetSnapshotRecord,
    ) -> DatasetSnapshotRecord:
        """Persist a redacted dataset snapshot record and return the stored copy."""
        record = DatasetSnapshotRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("snapshot_id", record.snapshot_id)

        record_json, redaction_status = _redacted_record_json(record)

        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO dataset_snapshots (
                        session_id,
                        snapshot_id,
                        record_json,
                        redaction_status
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        record.snapshot_id,
                        record_json,
                        redaction_status,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_error(exc, "dataset_snapshots.session_id"):
                raise ExperimentLedgerError(
                    f"dataset snapshot already exists: "
                    f"session_id={record.session_id} "
                    f"snapshot_id={record.snapshot_id}"
                ) from exc
            raise

        stored = self.get_dataset_snapshot(record.session_id, record.snapshot_id)
        if stored is None:
            raise ExperimentLedgerError("dataset snapshot was not stored")
        return stored

    def create_code_snapshot(self, record: CodeSnapshotRecord) -> CodeSnapshotRecord:
        """Persist a redacted code snapshot record and return the stored copy."""
        record = CodeSnapshotRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("snapshot_id", record.snapshot_id)

        record_json, redaction_status = _redacted_record_json(record)

        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO code_snapshots (
                        session_id,
                        snapshot_id,
                        record_json,
                        redaction_status
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        record.snapshot_id,
                        record_json,
                        redaction_status,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_error(exc, "code_snapshots.session_id"):
                raise ExperimentLedgerError(
                    f"code snapshot already exists: "
                    f"session_id={record.session_id} "
                    f"snapshot_id={record.snapshot_id}"
                ) from exc
            raise

        stored = self.get_code_snapshot(record.session_id, record.snapshot_id)
        if stored is None:
            raise ExperimentLedgerError("code snapshot was not stored")
        return stored

    def create_metric(self, record: MetricRecord) -> MetricRecord:
        """Persist a redacted standalone metric record and return the stored copy."""
        record = MetricRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("metric_id", record.metric_id)

        self._insert_record(
            table_name="experiment_metrics",
            id_column="metric_id",
            id_value=record.metric_id,
            record=record,
            duplicate_label="metric",
        )

        stored = self.get_metric(record.session_id, record.metric_id)
        if stored is None:
            raise ExperimentLedgerError("metric was not stored")
        return stored

    def create_log_ref(self, record: LogRefRecord) -> LogRefRecord:
        """Persist a redacted standalone log reference and return the stored copy."""
        record = LogRefRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("log_id", record.log_id)

        self._insert_record(
            table_name="experiment_log_refs",
            id_column="log_id",
            id_value=record.log_id,
            record=record,
            duplicate_label="log ref",
        )

        stored = self.get_log_ref(record.session_id, record.log_id)
        if stored is None:
            raise ExperimentLedgerError("log ref was not stored")
        return stored

    def create_artifact_ref(self, record: ArtifactRefRecord) -> ArtifactRefRecord:
        """Persist a redacted canonical artifact ref and return the stored copy."""
        record = ArtifactRefRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("artifact_id", record.artifact_id)

        self._insert_record(
            table_name="artifact_refs",
            id_column="artifact_id",
            id_value=record.artifact_id,
            record=record,
            duplicate_label="artifact ref",
        )

        stored = self.get_artifact_ref(record.session_id, record.artifact_id)
        if stored is None:
            raise ExperimentLedgerError("artifact ref was not stored")
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

    def get_dataset_snapshot(
        self,
        session_id: str,
        snapshot_id: str,
    ) -> DatasetSnapshotRecord | None:
        """Return one dataset snapshot by session and snapshot id, or None."""
        row = self._connection.execute(
            """
            SELECT record_json
            FROM dataset_snapshots
            WHERE session_id = ? AND snapshot_id = ?
            """,
            (session_id, snapshot_id),
        ).fetchone()
        if row is None:
            return None
        return _dataset_snapshot_record_from_json(row["record_json"])

    def get_code_snapshot(
        self,
        session_id: str,
        snapshot_id: str,
    ) -> CodeSnapshotRecord | None:
        """Return one code snapshot by session and snapshot id, or None."""
        row = self._connection.execute(
            """
            SELECT record_json
            FROM code_snapshots
            WHERE session_id = ? AND snapshot_id = ?
            """,
            (session_id, snapshot_id),
        ).fetchone()
        if row is None:
            return None
        return _code_snapshot_record_from_json(row["record_json"])

    def get_metric(self, session_id: str, metric_id: str) -> MetricRecord | None:
        """Return one standalone metric by session and metric id, or None."""
        return self._get_record(
            "experiment_metrics",
            "metric_id",
            session_id,
            metric_id,
            _metric_record_from_json,
        )

    def get_log_ref(self, session_id: str, log_id: str) -> LogRefRecord | None:
        """Return one standalone log reference by session and log id, or None."""
        return self._get_record(
            "experiment_log_refs",
            "log_id",
            session_id,
            log_id,
            _log_ref_record_from_json,
        )

    def get_artifact_ref(
        self,
        session_id: str,
        artifact_id: str,
    ) -> ArtifactRefRecord | None:
        """Return one canonical artifact reference by session and artifact id."""
        return self._get_record(
            "artifact_refs",
            "artifact_id",
            session_id,
            artifact_id,
            _artifact_ref_record_from_json,
        )

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

    def list_dataset_snapshots(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[DatasetSnapshotRecord]:
        """Return session dataset snapshots in append order."""
        rows = self._list_rows("dataset_snapshots", session_id, limit)
        return [_dataset_snapshot_record_from_json(row["record_json"]) for row in rows]

    def list_code_snapshots(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[CodeSnapshotRecord]:
        """Return session code snapshots in append order."""
        rows = self._list_rows("code_snapshots", session_id, limit)
        return [_code_snapshot_record_from_json(row["record_json"]) for row in rows]

    def list_metrics(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[MetricRecord]:
        """Return session standalone metrics in append order."""
        rows = self._list_rows("experiment_metrics", session_id, limit)
        return [_metric_record_from_json(row["record_json"]) for row in rows]

    def list_log_refs(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[LogRefRecord]:
        """Return session standalone log references in append order."""
        rows = self._list_rows("experiment_log_refs", session_id, limit)
        return [_log_ref_record_from_json(row["record_json"]) for row in rows]

    def list_artifact_refs(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[ArtifactRefRecord]:
        """Return session canonical artifact references in append order."""
        rows = self._list_rows("artifact_refs", session_id, limit)
        return [_artifact_ref_record_from_json(row["record_json"]) for row in rows]

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
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dataset_snapshots (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, snapshot_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_dataset_snapshots_session_sequence
                ON dataset_snapshots (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS code_snapshots (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    snapshot_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, snapshot_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_code_snapshots_session_sequence
                ON code_snapshots (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_metrics (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    metric_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, metric_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_experiment_metrics_session_sequence
                ON experiment_metrics (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS experiment_log_refs (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    log_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, log_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_experiment_log_refs_session_sequence
                ON experiment_log_refs (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS artifact_refs (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, artifact_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_artifact_refs_session_sequence
                ON artifact_refs (session_id, ledger_sequence)
                """
            )

    def _insert_record(
        self,
        *,
        table_name: str,
        id_column: str,
        id_value: str,
        record: LedgerRecord,
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
                        record_json,
                        redaction_status
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        id_value,
                        record_json,
                        redaction_status,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_error(exc, f"{table_name}.session_id"):
                raise ExperimentLedgerError(
                    f"{duplicate_label} already exists: "
                    f"session_id={record.session_id} {id_column}={id_value}"
                ) from exc
            raise

    def _get_record(
        self,
        table_name: str,
        id_column: str,
        session_id: str,
        record_id: str,
        parser: Callable[[str], LedgerRecordT],
    ) -> LedgerRecordT | None:
        row = self._connection.execute(
            f"""
            SELECT record_json
            FROM {table_name}
            WHERE session_id = ? AND {id_column} = ?
            """,
            (session_id, record_id),
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
                raise ExperimentLedgerError("limit must be non-negative")
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


def _record_payload(
    record: LedgerRecord,
) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_json(
    record: LedgerRecord,
) -> tuple[str, str]:
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


def _dataset_snapshot_record_from_json(value: str) -> DatasetSnapshotRecord:
    return DatasetSnapshotRecord.model_validate(json.loads(value))


def _code_snapshot_record_from_json(value: str) -> CodeSnapshotRecord:
    return CodeSnapshotRecord.model_validate(json.loads(value))


def _metric_record_from_json(value: str) -> MetricRecord:
    return MetricRecord.model_validate(json.loads(value))


def _log_ref_record_from_json(value: str) -> LogRefRecord:
    return LogRefRecord.model_validate(json.loads(value))


def _artifact_ref_record_from_json(value: str) -> ArtifactRefRecord:
    return ArtifactRefRecord.model_validate(json.loads(value))


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ExperimentLedgerError(f"{name} must be a non-empty string")


def _is_duplicate_run_error(exc: sqlite3.IntegrityError) -> bool:
    return _is_duplicate_error(exc, "experiment_runs.session_id")


def _is_duplicate_error(exc: sqlite3.IntegrityError, table_column: str) -> bool:
    message = str(exc).lower()
    return "unique" in message and table_column in message
