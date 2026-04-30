from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

if TYPE_CHECKING:
    from agent.core.events import AgentEvent
    from backend.budget_ledger_store import SQLiteBudgetLedgerStore


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


def _validate_finite_number(name: str, value: int | float) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{name} must be finite")


def __getattr__(name: str) -> Any:
    if name == "SQLiteBudgetLedgerStore":
        from backend.budget_ledger_store import SQLiteBudgetLedgerStore

        globals()[name] = SQLiteBudgetLedgerStore
        return SQLiteBudgetLedgerStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
