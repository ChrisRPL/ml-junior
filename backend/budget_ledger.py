from __future__ import annotations

import json
import math
import sqlite3
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from agent.core.redaction import redact_value
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

if TYPE_CHECKING:
    from agent.core.events import AgentEvent


BUDGET_LIMIT_RECORDED_EVENT = "budget.limit_recorded"
BUDGET_USAGE_RECORDED_EVENT = "budget.usage_recorded"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
BudgetAmount = Annotated[int | float, Field(ge=0)]
BudgetLimitAmount = Annotated[int | float, Field(gt=0)]

BudgetScope: TypeAlias = Literal[
    "session",
    "project",
    "flow",
    "phase",
    "run",
    "tool_call",
    "job",
    "provider",
]
BudgetResource: TypeAlias = Literal[
    "llm_tokens",
    "llm_cost",
    "gpu_time",
    "cpu_time",
    "wall_time",
    "job_count",
    "tool_call_count",
    "storage",
]
BudgetUnit: TypeAlias = Literal[
    "tokens",
    "usd",
    "gpu_hours",
    "cpu_hours",
    "seconds",
    "count",
    "gb_hours",
]

_RESOURCE_UNITS: dict[str, frozenset[str]] = {
    "llm_tokens": frozenset({"tokens"}),
    "llm_cost": frozenset({"usd"}),
    "gpu_time": frozenset({"gpu_hours"}),
    "cpu_time": frozenset({"cpu_hours"}),
    "wall_time": frozenset({"seconds"}),
    "job_count": frozenset({"count"}),
    "tool_call_count": frozenset({"count"}),
    "storage": frozenset({"gb_hours"}),
}


class BudgetLedgerError(ValueError):
    """Raised when inert budget ledger data is invalid or conflicts."""


class BudgetLedgerRecord(BaseModel):
    """Closed-schema base for inert budget ledger records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class BudgetRecordBase(BudgetLedgerRecord):
    session_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    scope: BudgetScope
    scope_id: NonEmptyStr
    resource: BudgetResource
    unit: BudgetUnit
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"] = "unknown"
    redaction_status: Literal["none", "partial", "redacted"]
    created_at: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_scope_and_unit(self) -> BudgetRecordBase:
        if self.scope == "session" and self.scope_id != self.session_id:
            raise ValueError("scope_id must match session_id for session scope")
        if self.unit not in _RESOURCE_UNITS[self.resource]:
            raise ValueError(f"unit {self.unit!r} is invalid for {self.resource!r}")
        return self


class BudgetLimitRecord(BudgetRecordBase):
    """Inert budget limit record; it does not enforce or consume quota."""

    limit_id: NonEmptyStr
    limit: BudgetLimitAmount
    period: Literal["session", "day", "week", "month", "phase", "run", "job", "none"]
    source: Literal["flow_template", "user", "policy", "system", "manual"]

    @model_validator(mode="after")
    def validate_limit(self) -> BudgetLimitRecord:
        _validate_finite_number("limit", self.limit)
        return self


class BudgetUsageRecord(BudgetRecordBase):
    """Inert budget usage record; it only describes observed or estimated usage."""

    usage_id: NonEmptyStr
    amount: BudgetAmount
    source: Literal["provider_usage", "tool_report", "manual", "estimator", "external"]
    provider: Literal[
        "openai",
        "anthropic",
        "huggingface_jobs",
        "huggingface_hub",
        "local",
        "external",
        "unknown",
    ] | None = None
    limit_id: NonEmptyStr | None = None
    tool_call_id: NonEmptyStr | None = None
    job_id: NonEmptyStr | None = None
    occurred_at: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_usage(self) -> BudgetUsageRecord:
        _validate_finite_number("amount", self.amount)
        if self.source == "provider_usage" and self.provider is None:
            raise ValueError("provider is required for provider_usage records")
        return self


BudgetRecord: TypeAlias = BudgetLimitRecord | BudgetUsageRecord


def generate_budget_limit_id() -> str:
    """Return an opaque budget limit identifier."""
    return f"budget-limit-{uuid.uuid4().hex}"


def generate_budget_usage_id() -> str:
    """Return an opaque budget usage identifier."""
    return f"budget-usage-{uuid.uuid4().hex}"


def budget_limit_recorded_payload(record: BudgetLimitRecord) -> dict[str, Any]:
    """Serialize a budget limit record into an AgentEvent payload."""
    return _record_payload(BudgetLimitRecord.model_validate(record))


def budget_usage_recorded_payload(record: BudgetUsageRecord) -> dict[str, Any]:
    """Serialize a budget usage record into an AgentEvent payload."""
    return _record_payload(BudgetUsageRecord.model_validate(record))


def budget_limit_record_from_event(event: AgentEvent) -> BudgetLimitRecord:
    """Validate a budget.limit_recorded event as a budget limit record."""
    if event.event_type != BUDGET_LIMIT_RECORDED_EVENT:
        raise BudgetLedgerError(f"Expected {BUDGET_LIMIT_RECORDED_EVENT}")

    record = BudgetLimitRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise BudgetLedgerError(
            "budget limit event session_id does not match record session_id"
        )
    return record


def budget_usage_record_from_event(event: AgentEvent) -> BudgetUsageRecord:
    """Validate a budget.usage_recorded event as a budget usage record."""
    if event.event_type != BUDGET_USAGE_RECORDED_EVENT:
        raise BudgetLedgerError(f"Expected {BUDGET_USAGE_RECORDED_EVENT}")

    record = BudgetUsageRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise BudgetLedgerError(
            "budget usage event session_id does not match record session_id"
        )
    return record


def project_budget_limits(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[BudgetLimitRecord]:
    """Project budget limit records from supplied events only."""
    records = [
        budget_limit_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            BUDGET_LIMIT_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_ids(records, "limit_id", "budget limit")
    return records


def project_budget_usage(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[BudgetUsageRecord]:
    """Project budget usage records from supplied events only."""
    records = [
        budget_usage_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            BUDGET_USAGE_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_ids(records, "usage_id", "budget usage")
    return records


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


def _reject_duplicate_ids(
    records: Sequence[BudgetRecord],
    id_field: str,
    label: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = getattr(record, id_field)
        if record_id in seen:
            raise BudgetLedgerError(f"duplicate {label} id: {record_id}")
        seen.add(record_id)


def _record_payload(record: BudgetRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


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


def _validate_finite_number(name: str, value: int | float) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")
