from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agent.core.redaction import redact_value
from backend.budget_ledger import (
    BudgetLedgerError,
    BudgetLimitRecord,
    BudgetRecord,
    BudgetUsageRecord,
    _record_payload,
)


class SQLiteBudgetLedgerStore:
    """Append-only SQLite store for inert budget limit and usage records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def append_limit(self, record: BudgetLimitRecord) -> BudgetLimitRecord:
        """Persist one redacted budget limit record and return the stored copy."""
        record = BudgetLimitRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("limit_id", record.limit_id)

        record_json = self._insert_record(
            table_name="budget_limit_records",
            id_column="limit_id",
            id_value=record.limit_id,
            record=record,
            duplicate_label="budget limit",
        )
        return _budget_limit_record_from_json(record_json)

    def append_usage(self, record: BudgetUsageRecord) -> BudgetUsageRecord:
        """Persist one redacted budget usage record and return the stored copy."""
        record = BudgetUsageRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("usage_id", record.usage_id)

        record_json = self._insert_record(
            table_name="budget_usage_records",
            id_column="usage_id",
            id_value=record.usage_id,
            record=record,
            duplicate_label="budget usage",
        )
        return _budget_usage_record_from_json(record_json)

    def list_limits(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[BudgetLimitRecord]:
        """Return session budget limit records in append order."""
        rows = self._list_rows("budget_limit_records", session_id, limit)
        return [_budget_limit_record_from_json(row["record_json"]) for row in rows]

    def list_usage(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[BudgetUsageRecord]:
        """Return session budget usage records in append order."""
        rows = self._list_rows("budget_usage_records", session_id, limit)
        return [_budget_usage_record_from_json(row["record_json"]) for row in rows]

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_limit_records (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    limit_id TEXT NOT NULL,
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
                    UNIQUE (session_id, limit_id, source_event_sequence_key)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_budget_limit_records_session_sequence
                ON budget_limit_records (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS budget_usage_records (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    usage_id TEXT NOT NULL,
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
                    UNIQUE (session_id, usage_id, source_event_sequence_key)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_budget_usage_records_session_sequence
                ON budget_usage_records (session_id, ledger_sequence)
                """
            )

    def _insert_record(
        self,
        *,
        table_name: str,
        id_column: str,
        id_value: str,
        record: BudgetRecord,
        duplicate_label: str,
    ) -> str:
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
                raise BudgetLedgerError(
                    f"{duplicate_label} already exists: "
                    f"session_id={record.session_id} "
                    f"{id_column}={id_value} "
                    f"source_event_sequence={record.source_event_sequence}"
                ) from exc
            raise
        return record_json

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
                raise BudgetLedgerError("limit must be non-negative")
            query += " LIMIT ?"
            params = (session_id, limit)

        return self._connection.execute(query, params).fetchall()


def _redacted_record_json(record: BudgetRecord) -> tuple[str, str]:
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


def _budget_limit_record_from_json(value: str) -> BudgetLimitRecord:
    return BudgetLimitRecord.model_validate(json.loads(value))


def _budget_usage_record_from_json(value: str) -> BudgetUsageRecord:
    return BudgetUsageRecord.model_validate(json.loads(value))


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise BudgetLedgerError(f"{name} must be a non-empty string")


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
