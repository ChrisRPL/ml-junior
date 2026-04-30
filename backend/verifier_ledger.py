from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent.core.events import AgentEvent
from agent.core.redaction import redact_value
from backend.models import VerifierVerdictRecord


VERIFIER_COMPLETED_EVENT = "verifier.completed"


class VerifierLedgerError(ValueError):
    """Raised when inert verifier verdict ledger data is invalid or conflicts."""


def generate_verdict_id() -> str:
    """Return an opaque verifier verdict identifier."""
    return f"verdict-{uuid.uuid4().hex}"


def generate_verifier_id() -> str:
    """Return an opaque verifier identifier."""
    return f"verifier-{uuid.uuid4().hex}"


def verifier_completed_payload(record: VerifierVerdictRecord) -> dict[str, Any]:
    """Serialize a verifier verdict record into an AgentEvent payload."""
    return _record_payload(record)


def verifier_verdict_record_from_event(event: AgentEvent) -> VerifierVerdictRecord:
    """Validate a verifier.completed event as a verifier verdict record."""
    if event.event_type != VERIFIER_COMPLETED_EVENT:
        raise VerifierLedgerError(f"Expected {VERIFIER_COMPLETED_EVENT}")

    record = VerifierVerdictRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise VerifierLedgerError(
            "verifier completed event session_id does not match record session_id"
        )
    return record


def project_verifier_verdicts(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[VerifierVerdictRecord]:
    """Project verifier verdict records from supplied events only."""
    records = [
        verifier_verdict_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            VERIFIER_COMPLETED_EVENT,
        )
    ]
    _reject_duplicate_verdict_ids(records)
    return records


class SQLiteVerifierLedgerStore:
    """Append-only SQLite store for inert verifier verdict records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def create(self, record: VerifierVerdictRecord) -> VerifierVerdictRecord:
        """Persist a redacted verifier verdict record and return the stored copy."""
        record = VerifierVerdictRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("verdict_id", record.verdict_id)

        record_json, redaction_status = _redacted_record_json(record)

        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO verifier_verdicts (
                        session_id,
                        verdict_id,
                        record_json,
                        redaction_status
                    )
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        record.session_id,
                        record.verdict_id,
                        record_json,
                        redaction_status,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if _is_duplicate_error(exc):
                raise VerifierLedgerError(
                    f"verifier verdict already exists: "
                    f"session_id={record.session_id} verdict_id={record.verdict_id}"
                ) from exc
            raise

        stored = self.get(record.session_id, record.verdict_id)
        if stored is None:
            raise VerifierLedgerError("verifier verdict was not stored")
        return stored

    def get(
        self,
        session_id: str,
        verdict_id: str,
    ) -> VerifierVerdictRecord | None:
        """Return one verifier verdict by session and verdict id, or None."""
        row = self._connection.execute(
            """
            SELECT record_json
            FROM verifier_verdicts
            WHERE session_id = ? AND verdict_id = ?
            """,
            (session_id, verdict_id),
        ).fetchone()
        if row is None:
            return None
        return _record_from_json(row["record_json"])

    def list(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[VerifierVerdictRecord]:
        """Return session verifier verdicts in append order."""
        query = """
            SELECT record_json
            FROM verifier_verdicts
            WHERE session_id = ?
            ORDER BY ledger_sequence ASC
        """
        params: Sequence[Any] = (session_id,)

        if limit is not None:
            if limit < 0:
                raise VerifierLedgerError("limit must be non-negative")
            query += " LIMIT ?"
            params = (session_id, limit)

        rows = self._connection.execute(query, params).fetchall()
        return [_record_from_json(row["record_json"]) for row in rows]

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS verifier_verdicts (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    verdict_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, verdict_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_verifier_verdicts_session_sequence
                ON verifier_verdicts (session_id, ledger_sequence)
                """
            )


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


def _reject_duplicate_verdict_ids(records: Sequence[VerifierVerdictRecord]) -> None:
    seen: set[str] = set()
    for record in records:
        if record.verdict_id in seen:
            raise VerifierLedgerError(
                f"duplicate verifier verdict id: {record.verdict_id}"
            )
        seen.add(record.verdict_id)


def _record_payload(record: VerifierVerdictRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_json(record: VerifierVerdictRecord) -> tuple[str, str]:
    result = redact_value(_record_payload(record))
    redaction_status = _stronger_redaction_status(
        record.redaction_status,
        result.status,
    )
    if isinstance(result.value, dict):
        result.value["redaction_status"] = redaction_status
    return (
        json.dumps(
            result.value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ),
        redaction_status,
    )


def _record_from_json(value: str) -> VerifierVerdictRecord:
    return VerifierVerdictRecord.model_validate(json.loads(value))


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise VerifierLedgerError(f"{name} must be a non-empty string")


def _is_duplicate_error(exc: sqlite3.IntegrityError) -> bool:
    message = str(exc).lower()
    return "unique" in message and "verifier_verdicts.session_id" in message


def _stronger_redaction_status(left: str, right: str) -> str:
    order = {"none": 0, "partial": 1, "redacted": 2}
    left_value = str(left)
    right_value = str(right)
    if order.get(left_value, 0) >= order.get(right_value, 0):
        return left_value
    return right_value
