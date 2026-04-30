from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, TypeAlias, TypeVar

from agent.core.events import AgentEvent
from agent.core.redaction import redact_value
from backend.models import EvidenceClaimLinkRecord, EvidenceItemRecord


EVIDENCE_ITEM_RECORDED_EVENT = "evidence_item.recorded"
EVIDENCE_CLAIM_LINK_RECORDED_EVENT = "evidence_claim_link.recorded"

EvidenceRecord: TypeAlias = EvidenceItemRecord | EvidenceClaimLinkRecord
EvidenceRecordT = TypeVar(
    "EvidenceRecordT",
    EvidenceItemRecord,
    EvidenceClaimLinkRecord,
)


class EvidenceLedgerError(ValueError):
    """Raised when inert evidence ledger data is invalid or conflicts."""


def generate_evidence_id() -> str:
    """Return an opaque evidence item identifier."""
    return f"evidence-{uuid.uuid4().hex}"


def generate_evidence_claim_link_id() -> str:
    """Return an opaque evidence claim link identifier."""
    return f"evidence-link-{uuid.uuid4().hex}"


def evidence_item_recorded_payload(record: EvidenceItemRecord) -> dict[str, Any]:
    """Serialize an evidence item record into an AgentEvent payload."""
    return _record_payload(record)


def evidence_claim_link_recorded_payload(
    record: EvidenceClaimLinkRecord,
) -> dict[str, Any]:
    """Serialize an evidence claim link record into an AgentEvent payload."""
    return _record_payload(record)


def evidence_item_record_from_event(event: AgentEvent) -> EvidenceItemRecord:
    """Validate an evidence_item.recorded event as an evidence item record."""
    if event.event_type != EVIDENCE_ITEM_RECORDED_EVENT:
        raise EvidenceLedgerError(f"Expected {EVIDENCE_ITEM_RECORDED_EVENT}")

    record = EvidenceItemRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise EvidenceLedgerError(
            "evidence item event session_id does not match record session_id"
        )
    return record


def evidence_claim_link_record_from_event(
    event: AgentEvent,
) -> EvidenceClaimLinkRecord:
    """Validate an evidence_claim_link.recorded event as a claim link record."""
    if event.event_type != EVIDENCE_CLAIM_LINK_RECORDED_EVENT:
        raise EvidenceLedgerError(f"Expected {EVIDENCE_CLAIM_LINK_RECORDED_EVENT}")

    record = EvidenceClaimLinkRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise EvidenceLedgerError(
            "evidence claim link event session_id does not match record session_id"
        )
    return record


def project_evidence_items(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[EvidenceItemRecord]:
    """Project evidence item records from supplied events only."""
    records = [
        evidence_item_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            EVIDENCE_ITEM_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_ids(records, "evidence_id", "evidence item")
    return records


def project_evidence_claim_links(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[EvidenceClaimLinkRecord]:
    """Project evidence claim link records from supplied events only."""
    records = [
        evidence_claim_link_record_from_event(event)
        for event in _ordered_session_events(
            session_id,
            events,
            EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
        )
    ]
    _reject_duplicate_ids(records, "link_id", "evidence claim link")
    return records


class SQLiteEvidenceLedgerStore:
    """Append-only SQLite store for inert evidence ledger records."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.database_path)
        self._connection.row_factory = sqlite3.Row
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def create_evidence_item(self, record: EvidenceItemRecord) -> EvidenceItemRecord:
        """Persist a redacted evidence item record and return the stored copy."""
        record = EvidenceItemRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("evidence_id", record.evidence_id)

        self._insert_record(
            table_name="evidence_items",
            id_column="evidence_id",
            id_value=record.evidence_id,
            record=record,
            duplicate_label="evidence item",
        )

        stored = self.get_evidence_item(record.session_id, record.evidence_id)
        if stored is None:
            raise EvidenceLedgerError("evidence item was not stored")
        return stored

    def create_claim_link(
        self,
        record: EvidenceClaimLinkRecord,
    ) -> EvidenceClaimLinkRecord:
        """Persist a redacted evidence claim link and return the stored copy."""
        record = EvidenceClaimLinkRecord.model_validate(record)
        _validate_required_text("session_id", record.session_id)
        _validate_required_text("link_id", record.link_id)

        self._insert_record(
            table_name="evidence_claim_links",
            id_column="link_id",
            id_value=record.link_id,
            record=record,
            duplicate_label="evidence claim link",
        )

        stored = self.get_claim_link(record.session_id, record.link_id)
        if stored is None:
            raise EvidenceLedgerError("evidence claim link was not stored")
        return stored

    def get_evidence_item(
        self,
        session_id: str,
        evidence_id: str,
    ) -> EvidenceItemRecord | None:
        """Return one evidence item by session and evidence id, or None."""
        return self._get_record(
            "evidence_items",
            "evidence_id",
            session_id,
            evidence_id,
            _evidence_item_record_from_json,
        )

    def get_claim_link(
        self,
        session_id: str,
        link_id: str,
    ) -> EvidenceClaimLinkRecord | None:
        """Return one evidence claim link by session and link id, or None."""
        return self._get_record(
            "evidence_claim_links",
            "link_id",
            session_id,
            link_id,
            _evidence_claim_link_record_from_json,
        )

    def list_evidence_items(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[EvidenceItemRecord]:
        """Return session evidence items in append order."""
        rows = self._list_rows("evidence_items", session_id, limit)
        return [_evidence_item_record_from_json(row["record_json"]) for row in rows]

    def list_claim_links(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[EvidenceClaimLinkRecord]:
        """Return session evidence claim links in append order."""
        rows = self._list_rows("evidence_claim_links", session_id, limit)
        return [
            _evidence_claim_link_record_from_json(row["record_json"]) for row in rows
        ]

    def _initialize_schema(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_items (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, evidence_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_evidence_items_session_sequence
                ON evidence_items (session_id, ledger_sequence)
                """
            )
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS evidence_claim_links (
                    ledger_sequence INTEGER PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    link_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    redaction_status TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (session_id, link_id)
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_evidence_claim_links_session_sequence
                ON evidence_claim_links (session_id, ledger_sequence)
                """
            )

    def _insert_record(
        self,
        *,
        table_name: str,
        id_column: str,
        id_value: str,
        record: EvidenceRecord,
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
                raise EvidenceLedgerError(
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
        parser: Callable[[str], EvidenceRecordT],
    ) -> EvidenceRecordT | None:
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
                raise EvidenceLedgerError("limit must be non-negative")
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
    records: Sequence[EvidenceRecord],
    id_field: str,
    label: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = getattr(record, id_field)
        if record_id in seen:
            raise EvidenceLedgerError(f"duplicate {label} id: {record_id}")
        seen.add(record_id)


def _record_payload(record: EvidenceRecord) -> dict[str, Any]:
    return record.model_dump(mode="json")


def _redacted_record_json(record: EvidenceRecord) -> tuple[str, str]:
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


def _evidence_item_record_from_json(value: str) -> EvidenceItemRecord:
    return EvidenceItemRecord.model_validate(json.loads(value))


def _evidence_claim_link_record_from_json(value: str) -> EvidenceClaimLinkRecord:
    return EvidenceClaimLinkRecord.model_validate(json.loads(value))


def _validate_required_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value:
        raise EvidenceLedgerError(f"{name} must be a non-empty string")


def _is_duplicate_error(exc: sqlite3.IntegrityError, table_column: str) -> bool:
    message = str(exc).lower()
    return "unique" in message and table_column in message
