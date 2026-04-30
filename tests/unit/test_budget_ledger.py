from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from agent.core.events import AgentEvent
from backend.budget_ledger import (
    BUDGET_LIMIT_RECORDED_EVENT,
    BUDGET_USAGE_RECORDED_EVENT,
    BudgetLedgerError,
    BudgetLimitRecord,
    BudgetUsageRecord,
    budget_limit_record_from_event,
    budget_limit_recorded_payload,
    budget_usage_record_from_event,
    budget_usage_recorded_payload,
    generate_budget_limit_id,
    generate_budget_usage_id,
    project_budget_limits,
    project_budget_usage,
)


def _valid_limit_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": " session-a ",
        "limit_id": " limit-1 ",
        "source_event_sequence": 4,
        "scope": "session",
        "scope_id": "session-a",
        "resource": "llm_cost",
        "limit": 25.0,
        "unit": "usd",
        "period": "session",
        "source": "flow_template",
        "metadata": {"template_id": "fine-tune-model"},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": " 2026-04-29T10:00:00Z ",
    }
    payload.update(overrides)
    return payload


def _valid_usage_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "session_id": " session-a ",
        "usage_id": " usage-1 ",
        "source_event_sequence": 5,
        "scope": "job",
        "scope_id": " job-1 ",
        "resource": "gpu_time",
        "amount": 0.5,
        "unit": "gpu_hours",
        "source": "provider_usage",
        "provider": "huggingface_jobs",
        "limit_id": " limit-1 ",
        "tool_call_id": " tc-1 ",
        "job_id": " job-1 ",
        "occurred_at": " 2026-04-29T10:05:00Z ",
        "metadata": {"hardware": "cpu-basic"},
        "privacy_class": "private",
        "redaction_status": "partial",
        "created_at": " 2026-04-29T10:06:00Z ",
    }
    payload.update(overrides)
    return payload


def _make_limit_event(
    record: BudgetLimitRecord,
    *,
    sequence: int = 1,
    event_type: str = BUDGET_LIMIT_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-limit-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=budget_limit_recorded_payload(record),
    )


def _make_usage_event(
    record: BudgetUsageRecord,
    *,
    sequence: int = 1,
    event_type: str = BUDGET_USAGE_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-usage-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=budget_usage_recorded_payload(record),
    )


def test_generate_budget_ids_return_unique_stable_prefixes():
    first_limit = generate_budget_limit_id()
    second_limit = generate_budget_limit_id()
    first_usage = generate_budget_usage_id()
    second_usage = generate_budget_usage_id()

    assert first_limit.startswith("budget-limit-")
    assert second_limit.startswith("budget-limit-")
    assert first_limit != second_limit
    assert first_usage.startswith("budget-usage-")
    assert second_usage.startswith("budget-usage-")
    assert first_usage != second_usage


def test_budget_limit_record_validates_and_payload_normalizes():
    record = BudgetLimitRecord.model_validate(_valid_limit_payload())
    payload = budget_limit_recorded_payload(record)

    assert record.session_id == "session-a"
    assert record.limit_id == "limit-1"
    assert record.created_at == "2026-04-29T10:00:00Z"
    assert payload["session_id"] == "session-a"
    assert payload["limit_id"] == "limit-1"
    assert payload["unit"] == "usd"


def test_budget_usage_record_validates_and_payload_normalizes():
    record = BudgetUsageRecord.model_validate(_valid_usage_payload())
    payload = budget_usage_recorded_payload(record)

    assert record.session_id == "session-a"
    assert record.usage_id == "usage-1"
    assert record.scope_id == "job-1"
    assert record.job_id == "job-1"
    assert payload["provider"] == "huggingface_jobs"
    assert payload["occurred_at"] == "2026-04-29T10:05:00Z"


@pytest.mark.parametrize(
    ("record_type", "payload_factory", "field", "value"),
    [
        (BudgetLimitRecord, _valid_limit_payload, "unexpected", True),
        (BudgetUsageRecord, _valid_usage_payload, "unexpected", True),
        (BudgetLimitRecord, _valid_limit_payload, "limit", 0),
        (BudgetUsageRecord, _valid_usage_payload, "amount", -0.01),
        (BudgetLimitRecord, _valid_limit_payload, "source_event_sequence", 0),
        (BudgetUsageRecord, _valid_usage_payload, "redaction_status", "complete"),
    ],
)
def test_budget_records_reject_malformed_payloads(
    record_type,
    payload_factory,
    field,
    value,
):
    payload = payload_factory()
    payload[field] = value

    with pytest.raises(ValidationError):
        record_type.model_validate(payload)


@pytest.mark.parametrize(
    ("record_type", "payload_factory", "path"),
    [
        (BudgetLimitRecord, _valid_limit_payload, ("session_id",)),
        (BudgetLimitRecord, _valid_limit_payload, ("limit_id",)),
        (BudgetUsageRecord, _valid_usage_payload, ("usage_id",)),
        (BudgetUsageRecord, _valid_usage_payload, ("scope_id",)),
        (BudgetUsageRecord, _valid_usage_payload, ("tool_call_id",)),
    ],
)
def test_budget_records_reject_empty_required_text(
    record_type,
    payload_factory,
    path,
):
    payload = payload_factory()
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""

    with pytest.raises(ValidationError):
        record_type.model_validate(payload)


def test_budget_records_reject_invalid_resource_unit_pair():
    with pytest.raises(ValidationError, match="unit"):
        BudgetLimitRecord.model_validate(_valid_limit_payload(unit="tokens"))

    with pytest.raises(ValidationError, match="unit"):
        BudgetUsageRecord.model_validate(_valid_usage_payload(unit="cpu_hours"))


def test_budget_records_reject_session_scope_mismatch():
    with pytest.raises(ValidationError, match="scope_id"):
        BudgetLimitRecord.model_validate(_valid_limit_payload(scope_id="session-b"))


def test_provider_usage_requires_provider():
    with pytest.raises(ValidationError, match="provider"):
        BudgetUsageRecord.model_validate(_valid_usage_payload(provider=None))


def test_budget_records_from_events_validate_event_type_and_session():
    limit = BudgetLimitRecord.model_validate(_valid_limit_payload())
    usage = BudgetUsageRecord.model_validate(_valid_usage_payload())

    assert budget_limit_record_from_event(_make_limit_event(limit)) == limit
    assert budget_usage_record_from_event(_make_usage_event(usage)) == usage

    with pytest.raises(BudgetLedgerError, match="Expected"):
        budget_limit_record_from_event(
            _make_limit_event(limit, event_type="budget.other_recorded")
        )

    with pytest.raises(BudgetLedgerError, match="session_id"):
        budget_usage_record_from_event(_make_usage_event(usage, session_id="session-b"))


def test_budget_limit_projection_is_ordered_filtered_and_duplicate_checked():
    first = BudgetLimitRecord.model_validate(_valid_limit_payload(limit_id="limit-1"))
    second = BudgetLimitRecord.model_validate(
        _valid_limit_payload(limit_id="limit-2", resource="llm_tokens", unit="tokens")
    )
    other_session = BudgetLimitRecord.model_validate(
        _valid_limit_payload(
            session_id="session-b",
            scope_id="session-b",
            limit_id="limit-3",
        )
    )

    projected = project_budget_limits(
        "session-a",
        [
            _make_limit_event(second, sequence=3),
            _make_limit_event(other_session, sequence=2),
            _make_limit_event(first, sequence=1),
        ],
    )

    assert [record.limit_id for record in projected] == ["limit-1", "limit-2"]

    with pytest.raises(BudgetLedgerError, match="duplicate budget limit"):
        project_budget_limits(
            "session-a",
            [_make_limit_event(first, sequence=1), _make_limit_event(first, sequence=2)],
        )


def test_budget_usage_projection_is_ordered_filtered_and_duplicate_checked():
    first = BudgetUsageRecord.model_validate(_valid_usage_payload(usage_id="usage-1"))
    second = BudgetUsageRecord.model_validate(
        _valid_usage_payload(usage_id="usage-2", amount=1.25)
    )
    other_session = BudgetUsageRecord.model_validate(
        _valid_usage_payload(
            session_id="session-b",
            usage_id="usage-3",
            scope="session",
            scope_id="session-b",
        )
    )

    projected = project_budget_usage(
        "session-a",
        [
            _make_usage_event(second, sequence=3),
            _make_usage_event(other_session, sequence=2),
            _make_usage_event(first, sequence=1),
        ],
    )

    assert [record.usage_id for record in projected] == ["usage-1", "usage-2"]

    with pytest.raises(BudgetLedgerError, match="duplicate budget usage"):
        project_budget_usage(
            "session-a",
            [_make_usage_event(first, sequence=1), _make_usage_event(first, sequence=2)],
        )
