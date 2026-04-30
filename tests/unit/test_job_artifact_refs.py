from __future__ import annotations

import sqlite3

import pytest

from agent.core.events import AgentEvent
from backend.job_artifact_refs import (
    ACTIVE_JOB_RECORDED_EVENT,
    ARTIFACT_REF_RECORDED_EVENT,
    JobArtifactRefError,
    SQLiteJobArtifactRefStore,
    active_job_record_from_event,
    active_job_recorded_payload,
    artifact_ref_record_from_event,
    artifact_ref_recorded_payload,
    generate_active_job_id,
    generate_artifact_id,
    project_active_jobs,
    project_artifact_refs,
)
from backend.models import ActiveJobRecord, ArtifactRefRecord


def test_generate_ids_return_unique_values_with_stable_prefixes():
    first_job = generate_active_job_id()
    second_job = generate_active_job_id()
    first_artifact = generate_artifact_id()
    second_artifact = generate_artifact_id()

    assert first_job.startswith("active-job-")
    assert second_job.startswith("active-job-")
    assert first_job != second_job
    assert first_artifact.startswith("artifact-")
    assert second_artifact.startswith("artifact-")
    assert first_artifact != second_artifact


def make_active_job(**overrides) -> ActiveJobRecord:
    values = {
        "session_id": "session-a",
        "job_id": "active-job-1",
        "source_event_sequence": 7,
        "tool_call_id": "tc-1",
        "tool": "hf_jobs",
        "provider": "huggingface_jobs",
        "status": "running",
        "url": "https://example.test/jobs/1",
        "label": "Training job",
        "metadata": {"queue": "cpu"},
        "redaction_status": "partial",
        "started_at": "2026-04-29T10:00:00Z",
        "updated_at": "2026-04-29T10:05:00Z",
        "completed_at": None,
    }
    values.update(overrides)
    return ActiveJobRecord.model_validate(values)


def make_artifact_ref(**overrides) -> ArtifactRefRecord:
    values = {
        "session_id": "session-a",
        "artifact_id": "artifact-1",
        "source_event_sequence": 8,
        "type": "model_checkpoint",
        "source": "job",
        "source_tool_call_id": "tc-1",
        "source_job_id": "active-job-1",
        "path": "/tmp/model.pt",
        "uri": "file:///tmp/model.pt",
        "digest": "sha256:model",
        "label": "Best checkpoint",
        "metadata": {"epoch": 3},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:10:00Z",
    }
    values.update(overrides)
    return ArtifactRefRecord.model_validate(values)


def make_active_job_event(
    record: ActiveJobRecord,
    *,
    sequence: int = 1,
    event_type: str = ACTIVE_JOB_RECORDED_EVENT,
    session_id: str | None = None,
    event_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=event_id or f"event-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=active_job_recorded_payload(record),
    )


def make_artifact_ref_event(
    record: ArtifactRefRecord,
    *,
    sequence: int = 1,
    event_type: str = ARTIFACT_REF_RECORDED_EVENT,
    session_id: str | None = None,
    event_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=event_id or f"event-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        event_type=event_type,
        data=artifact_ref_recorded_payload(record),
    )


def test_payloads_round_trip_from_records():
    active_job = make_active_job(job_id="active-job-roundtrip")
    artifact_ref = make_artifact_ref(artifact_id="artifact-roundtrip")

    active_job_payload = active_job_recorded_payload(active_job)
    artifact_ref_payload = artifact_ref_recorded_payload(artifact_ref)

    assert active_job_payload["session_id"] == "session-a"
    assert active_job_payload["job_id"] == "active-job-roundtrip"
    assert ActiveJobRecord.model_validate(active_job_payload) == active_job
    assert artifact_ref_payload["session_id"] == "session-a"
    assert artifact_ref_payload["artifact_id"] == "artifact-roundtrip"
    assert ArtifactRefRecord.model_validate(artifact_ref_payload) == artifact_ref


def test_event_to_record_validation_rejects_wrong_type_and_session_mismatch():
    active_job = make_active_job(job_id="active-job-validate")
    artifact_ref = make_artifact_ref(artifact_id="artifact-validate")

    assert active_job_record_from_event(make_active_job_event(active_job)) == active_job
    assert (
        artifact_ref_record_from_event(make_artifact_ref_event(artifact_ref))
        == artifact_ref
    )

    with pytest.raises(JobArtifactRefError, match=ACTIVE_JOB_RECORDED_EVENT):
        active_job_record_from_event(
            make_active_job_event(active_job, event_type="phase.completed")
        )
    with pytest.raises(JobArtifactRefError, match=ARTIFACT_REF_RECORDED_EVENT):
        artifact_ref_record_from_event(
            make_artifact_ref_event(artifact_ref, event_type="phase.completed")
        )

    with pytest.raises(JobArtifactRefError, match="session_id"):
        active_job_record_from_event(
            make_active_job_event(
                make_active_job(session_id="session-b"),
                session_id="session-a",
            )
        )
    with pytest.raises(JobArtifactRefError, match="session_id"):
        artifact_ref_record_from_event(
            make_artifact_ref_event(
                make_artifact_ref(session_id="session-b"),
                session_id="session-a",
            )
        )


def test_projection_filters_orders_dedupes_and_excludes_terminal_jobs():
    queued = make_active_job(
        job_id="active-job-1",
        status="queued",
        updated_at="2026-04-29T10:01:00Z",
    )
    terminal_update = make_active_job(
        job_id="active-job-1",
        status="completed",
        updated_at="2026-04-29T10:05:00Z",
        completed_at="2026-04-29T10:05:00Z",
    )
    second_initial = make_active_job(job_id="active-job-2", status="queued")
    second_latest = make_active_job(job_id="active-job-2", status="running")
    third = make_active_job(job_id="active-job-3", status="running")
    other_session = make_active_job(session_id="session-b", job_id="active-job-b")
    wrong_type = make_active_job(job_id="active-job-wrong")
    terminal_only = make_active_job(job_id="active-job-4", status="failed")
    events = [
        make_active_job_event(wrong_type, sequence=1, event_type="phase.completed"),
        make_active_job_event(terminal_only, sequence=2),
        make_active_job_event(second_latest, sequence=6),
        make_active_job_event(queued, sequence=3),
        make_active_job_event(other_session, sequence=7),
        make_active_job_event(third, sequence=5),
        make_active_job_event(second_initial, sequence=4),
        make_active_job_event(terminal_update, sequence=8),
    ]

    projected = project_active_jobs("session-a", events)

    assert [record.job_id for record in projected] == [
        "active-job-3",
        "active-job-2",
    ]
    assert [record.status for record in projected] == ["running", "running"]


def test_artifact_projection_filters_orders_and_dedupes_latest_refs():
    first_initial = make_artifact_ref(
        artifact_id="artifact-1",
        label="Initial checkpoint",
    )
    first_latest = make_artifact_ref(
        artifact_id="artifact-1",
        label="Final checkpoint",
    )
    second = make_artifact_ref(artifact_id="artifact-2", label="Metrics")
    other_session = make_artifact_ref(session_id="session-b", artifact_id="artifact-b")
    wrong_type = make_artifact_ref(artifact_id="artifact-wrong")
    events = [
        make_artifact_ref_event(wrong_type, sequence=1, event_type="phase.completed"),
        make_artifact_ref_event(first_initial, sequence=3),
        make_artifact_ref_event(first_latest, sequence=6),
        make_artifact_ref_event(other_session, sequence=5),
        make_artifact_ref_event(second, sequence=4),
    ]

    projected = project_artifact_refs("session-a", events)

    assert [record.artifact_id for record in projected] == [
        "artifact-2",
        "artifact-1",
    ]
    assert [record.label for record in projected] == ["Metrics", "Final checkpoint"]


def test_sqlite_store_appends_lists_redacts_and_rejects_duplicate_rows(tmp_path):
    database_path = tmp_path / "job-artifact-refs.sqlite"
    store = SQLiteJobArtifactRefStore(database_path)
    secret = "hf_jobartifactsecret123456789"
    first_job = make_active_job(
        job_id="active-job-store",
        source_event_sequence=10,
        status="queued",
        metadata={
            "token": secret,
            "note": f"Authorization: Bearer {secret}",
        },
        redaction_status="none",
    )
    job_update = make_active_job(
        job_id="active-job-store",
        source_event_sequence=11,
        status="running",
        metadata={"queue": "gpu"},
    )
    other_session_job = make_active_job(
        session_id="session-b",
        job_id="active-job-other",
        source_event_sequence=12,
    )
    first_artifact = make_artifact_ref(
        artifact_id="artifact-store",
        source_event_sequence=20,
        path="/Users/alice/project/model.pt",
        uri=f"https://example.test/artifacts/1?token={secret}",
        metadata={"api_key": secret},
        redaction_status="none",
    )
    artifact_update = make_artifact_ref(
        artifact_id="artifact-store",
        source_event_sequence=21,
        label="Updated checkpoint",
    )

    created_job = store.append_active_job(first_job)
    store.append_active_job(job_update)
    store.append_active_job(other_session_job)
    created_artifact = store.append_artifact_ref(first_artifact)
    store.append_artifact_ref(artifact_update)

    assert created_job.redaction_status == "redacted"
    assert created_job.metadata["token"] == "[REDACTED]"
    assert secret not in str(created_job.model_dump())
    assert created_artifact.redaction_status == "redacted"
    assert created_artifact.metadata["api_key"] == "[REDACTED]"
    assert created_artifact.path == "/Users/[USER]/project/model.pt"
    assert created_artifact.uri == "https://example.test/artifacts/1?token=[REDACTED]"
    assert secret not in str(created_artifact.model_dump())

    assert [
        (record.job_id, record.source_event_sequence, record.status)
        for record in store.list_active_jobs("session-a")
    ] == [
        ("active-job-store", 10, "queued"),
        ("active-job-store", 11, "running"),
    ]
    assert store.list_active_jobs("session-a", limit=1) == [created_job]
    assert [record.job_id for record in store.list_active_jobs("session-b")] == [
        "active-job-other"
    ]
    assert [
        (record.artifact_id, record.source_event_sequence, record.label)
        for record in store.list_artifact_refs("session-a")
    ] == [
        ("artifact-store", 20, "Best checkpoint"),
        ("artifact-store", 21, "Updated checkpoint"),
    ]
    assert store.list_artifact_refs("session-a", limit=1) == [created_artifact]

    with pytest.raises(JobArtifactRefError, match="already exists"):
        store.append_active_job(first_job)
    with pytest.raises(JobArtifactRefError, match="already exists"):
        store.append_artifact_ref(first_artifact)

    connection = sqlite3.connect(database_path)
    try:
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert secret not in database_dump
    assert "[REDACTED]" in database_dump


def test_sqlite_store_rejects_duplicate_rows_without_source_event_sequence(tmp_path):
    store = SQLiteJobArtifactRefStore(tmp_path / "job-artifact-refs.sqlite")
    job = make_active_job(
        job_id="active-job-no-sequence",
        source_event_sequence=None,
    )
    artifact = make_artifact_ref(
        artifact_id="artifact-no-sequence",
        source_event_sequence=None,
    )

    store.append_active_job(job)
    store.append_artifact_ref(artifact)

    with pytest.raises(JobArtifactRefError, match="already exists"):
        store.append_active_job(job)
    with pytest.raises(JobArtifactRefError, match="already exists"):
        store.append_artifact_ref(artifact)


def test_sqlite_store_rejects_negative_limits(tmp_path):
    store = SQLiteJobArtifactRefStore(tmp_path / "job-artifact-refs.sqlite")

    with pytest.raises(JobArtifactRefError, match="limit"):
        store.list_active_jobs("session-a", limit=-1)
    with pytest.raises(JobArtifactRefError, match="limit"):
        store.list_artifact_refs("session-a", limit=-1)


def test_sqlite_store_owns_only_job_artifact_ref_tables(tmp_path):
    database_path = tmp_path / "job-artifact-refs.sqlite"
    SQLiteJobArtifactRefStore(database_path).close()

    connection = sqlite3.connect(database_path)
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        connection.close()

    assert tables == {"active_job_records", "artifact_ref_records"}
