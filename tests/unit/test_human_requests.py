from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agent.core.events import AgentEvent
from backend.human_requests import (
    HUMAN_REQUEST_REQUESTED_EVENT,
    HUMAN_REQUEST_RESOLVED_EVENT,
    HumanRequestError,
    human_request_record_from_event,
    human_request_requested_payload,
    human_request_resolved_payload,
    project_human_requests,
)
from backend.models import HumanRequestRecord


def make_event(
    *,
    sequence: int,
    event_type: str,
    data: dict,
    session_id: str = "session-a",
    event_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=event_id or f"event-{sequence}",
        session_id=session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=data,
    )


def make_record(
    *,
    request_id: str = "hr-1",
    status: str = "requested",
    sequence: int = 1,
    summary: str | None = "Need dataset choice",
    session_id: str = "session-a",
) -> HumanRequestRecord:
    return HumanRequestRecord(
        session_id=session_id,
        request_id=request_id,
        source_event_sequence=sequence,
        status=status,
        channel="in_app",
        summary=summary,
        metadata={},
        privacy_class="unknown",
        redaction_status="none",
        created_at="2026-01-02T03:04:01+00:00",
        updated_at=f"2026-01-02T03:04:{sequence:02d}+00:00",
        resolved_at=(
            f"2026-01-02T03:04:{sequence:02d}+00:00"
            if status != "requested"
            else None
        ),
        resolution_summary="Answered in chat" if status == "answered" else None,
    )


def test_requested_payload_helper_builds_valid_event_payload():
    payload = human_request_requested_payload(make_record())

    event = make_event(
        sequence=1,
        event_type=HUMAN_REQUEST_REQUESTED_EVENT,
        data=payload,
    )

    assert event.data == payload
    assert human_request_record_from_event(event).model_dump(mode="json") == {
        **payload,
        "resolved_at": None,
        "resolution_summary": None,
    }


def test_resolved_payload_helper_builds_valid_event_payload():
    payload = human_request_resolved_payload(
        make_record(status="answered", sequence=2, summary=None)
    )

    event = make_event(
        sequence=2,
        event_type=HUMAN_REQUEST_RESOLVED_EVENT,
        data=payload,
    )

    assert event.data == payload
    assert human_request_record_from_event(event).status == "answered"


def test_payload_helpers_reject_wrong_lifecycle_status():
    with pytest.raises(HumanRequestError, match="status=requested"):
        human_request_requested_payload(make_record(status="answered"))

    with pytest.raises(HumanRequestError, match="terminal status"):
        human_request_resolved_payload(make_record(status="requested"))


def test_record_from_event_rejects_wrong_type_and_session_mismatch():
    payload = human_request_requested_payload(make_record())

    with pytest.raises(HumanRequestError, match="human_request"):
        human_request_record_from_event(
            make_event(sequence=1, event_type="experimental_event", data={})
        )

    with pytest.raises(HumanRequestError, match="session_id"):
        human_request_record_from_event(
            make_event(
                sequence=1,
                event_type=HUMAN_REQUEST_REQUESTED_EVENT,
                data=payload,
                session_id="session-b",
            )
        )


def test_project_human_requests_preserves_request_fields_when_resolved():
    requested = make_event(
        sequence=1,
        event_type=HUMAN_REQUEST_REQUESTED_EVENT,
        data=human_request_requested_payload(make_record(sequence=1)),
    )
    resolved = make_event(
        sequence=2,
        event_type=HUMAN_REQUEST_RESOLVED_EVENT,
        data=human_request_resolved_payload(
            make_record(status="answered", sequence=2, summary=None)
        ),
    )

    [record] = project_human_requests("session-a", [resolved, requested])

    assert record.status == "answered"
    assert record.summary == "Need dataset choice"
    assert record.channel == "in_app"
    assert record.resolved_at == "2026-01-02T03:04:02+00:00"


def test_project_human_requests_uses_latest_event_per_request_and_filters_session():
    events = [
        make_event(
            sequence=1,
            event_type=HUMAN_REQUEST_REQUESTED_EVENT,
            data=human_request_requested_payload(
                make_record(request_id="hr-1", sequence=1)
            ),
        ),
        make_event(
            sequence=2,
            event_type=HUMAN_REQUEST_REQUESTED_EVENT,
            data=human_request_requested_payload(
                make_record(request_id="hr-2", sequence=2, summary="Need metric")
            ),
        ),
        make_event(
            sequence=3,
            event_type=HUMAN_REQUEST_RESOLVED_EVENT,
            data=human_request_resolved_payload(
                make_record(request_id="hr-1", status="answered", sequence=3)
            ),
        ),
        make_event(
            sequence=4,
            event_type=HUMAN_REQUEST_REQUESTED_EVENT,
            data=human_request_requested_payload(
                make_record(request_id="hr-1", sequence=4, summary="Need follow-up")
            ),
        ),
        make_event(
            sequence=5,
            event_type=HUMAN_REQUEST_REQUESTED_EVENT,
            data=human_request_requested_payload(
                make_record(request_id="hr-other", sequence=5, session_id="session-b")
            ),
            session_id="session-b",
        ),
    ]

    records = project_human_requests("session-a", events)

    assert [(record.request_id, record.status, record.summary) for record in records] == [
        ("hr-2", "requested", "Need metric"),
        ("hr-1", "requested", "Need follow-up"),
    ]
