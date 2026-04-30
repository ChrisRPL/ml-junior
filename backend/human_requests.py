from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from backend.models import HumanRequestRecord


HUMAN_REQUEST_REQUESTED_EVENT = "human_request.requested"
HUMAN_REQUEST_RESOLVED_EVENT = "human_request.resolved"
HUMAN_REQUEST_EVENT_TYPES = {
    HUMAN_REQUEST_REQUESTED_EVENT,
    HUMAN_REQUEST_RESOLVED_EVENT,
}
TERMINAL_HUMAN_REQUEST_STATUSES = {"answered", "expired", "canceled"}


class HumanRequestError(ValueError):
    """Raised when inert human request event data is invalid."""


def generate_human_request_id() -> str:
    """Return an opaque human request identifier."""
    return f"human-request-{uuid.uuid4().hex}"


def human_request_requested_payload(record: HumanRequestRecord) -> dict[str, Any]:
    """Serialize an active human request record into an AgentEvent payload."""
    if record.status != "requested":
        raise HumanRequestError("requested payload requires status=requested")
    if record.summary is None:
        raise HumanRequestError("requested payload requires summary")
    return _record_payload(record)


def human_request_resolved_payload(record: HumanRequestRecord) -> dict[str, Any]:
    """Serialize a resolved human request record into an AgentEvent payload."""
    if record.status not in TERMINAL_HUMAN_REQUEST_STATUSES:
        raise HumanRequestError("resolved payload requires terminal status")
    return _record_payload(record)


def human_request_record_from_event(event: Any) -> HumanRequestRecord:
    """Validate a human_request.* event as an inert human request record."""
    if event.event_type not in HUMAN_REQUEST_EVENT_TYPES:
        raise HumanRequestError("Expected human_request.* event")

    record = HumanRequestRecord.model_validate(event.data or {})
    if record.session_id != event.session_id:
        raise HumanRequestError(
            "human request event session_id does not match record session_id"
        )
    if event.event_type == HUMAN_REQUEST_REQUESTED_EVENT:
        _validate_requested_record(record)
    else:
        _validate_resolved_record(record)
    if record.source_event_sequence is None:
        record = record.model_copy(update={"source_event_sequence": event.sequence})
    return record


def project_human_requests(
    session_id: str,
    events: Sequence[Any],
) -> list[HumanRequestRecord]:
    """Project latest human requests from supplied durable events only."""
    latest: dict[str, tuple[tuple[int, str], HumanRequestRecord]] = {}
    for event in _ordered_human_request_events(session_id, events):
        record = human_request_record_from_event(event)
        previous = latest.get(record.request_id)
        if previous is not None:
            record = _merge_record(previous[1], record)
        latest[record.request_id] = ((event.sequence, str(event.id)), record)

    return [record for _, record in sorted(latest.values(), key=lambda value: value[0])]


def _validate_requested_record(record: HumanRequestRecord) -> None:
    if record.status != "requested":
        raise HumanRequestError("human_request.requested requires status=requested")
    if record.summary is None:
        raise HumanRequestError("human_request.requested requires summary")


def _validate_resolved_record(record: HumanRequestRecord) -> None:
    if record.status not in TERMINAL_HUMAN_REQUEST_STATUSES:
        raise HumanRequestError("human_request.resolved requires terminal status")


def _merge_record(
    previous: HumanRequestRecord,
    current: HumanRequestRecord,
) -> HumanRequestRecord:
    if current.status == "requested":
        return current

    previous_data = previous.model_dump(mode="json", exclude_none=True)
    current_data = current.model_dump(mode="json", exclude_none=True)
    for key in ("summary", "channel", "created_at"):
        if key not in current_data and key in previous_data:
            current_data[key] = previous_data[key]
    return HumanRequestRecord.model_validate(current_data)


def _ordered_human_request_events(
    session_id: str,
    events: Sequence[Any],
) -> list[Any]:
    return sorted(
        [
            event
            for event in events
            if event.session_id == session_id
            and event.event_type in HUMAN_REQUEST_EVENT_TYPES
        ],
        key=lambda event: (event.sequence, str(event.id)),
    )


def _record_payload(record: HumanRequestRecord) -> dict[str, Any]:
    return record.model_dump(mode="json", exclude_none=True)
