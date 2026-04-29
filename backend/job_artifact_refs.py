from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from agent.core.events import AgentEvent
from backend.models import ActiveJobRecord, ArtifactRefRecord


ACTIVE_JOB_RECORDED_EVENT = "active_job.recorded"
ARTIFACT_REF_RECORDED_EVENT = "artifact_ref.recorded"

TERMINAL_ACTIVE_JOB_STATUSES = {"completed", "failed", "cancelled"}


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
