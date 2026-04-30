from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any

import pytest

from agent.core.events import AgentEvent
from backend import models as backend_models

if not hasattr(backend_models, "ExperimentRunRecord"):
    pytest.skip(
        "ExperimentRunRecord is owned by Worker 1 and is not available yet",
        allow_module_level=True,
    )
if not hasattr(backend_models, "DatasetSnapshotRecord") or not hasattr(
    backend_models,
    "CodeSnapshotRecord",
):
    pytest.skip(
        "Snapshot records are owned by Worker A and are not available yet",
        allow_module_level=True,
    )

from backend.experiment_ledger import (  # noqa: E402
    ARTIFACT_REF_RECORDED_EVENT,
    CODE_SNAPSHOT_RECORDED_EVENT,
    DATASET_SNAPSHOT_RECORDED_EVENT,
    EXPERIMENT_RUN_RECORDED_EVENT,
    LOG_REF_RECORDED_EVENT,
    METRIC_RECORDED_EVENT,
    ExperimentLedgerError,
    SQLiteExperimentLedgerStore,
    artifact_ref_record_from_event,
    artifact_ref_recorded_payload,
    code_snapshot_record_from_event,
    code_snapshot_recorded_payload,
    dataset_snapshot_record_from_event,
    dataset_snapshot_recorded_payload,
    generate_log_id,
    generate_metric_id,
    generate_code_snapshot_id,
    generate_dataset_snapshot_id,
    experiment_run_recorded_payload,
    generate_experiment_run_id,
    log_ref_record_from_event,
    log_ref_recorded_payload,
    metric_record_from_event,
    metric_recorded_payload,
    project_artifact_refs,
    project_code_snapshots,
    project_dataset_snapshots,
    project_experiment_runs,
    project_log_refs,
    project_metrics,
    run_record_from_event,
)
from backend.models import (  # noqa: E402
    ArtifactRefRecord,
    CodeSnapshotRecord,
    DatasetSnapshotRecord,
    ExperimentRunRecord,
    LogRefRecord,
    MetricRecord,
)


def test_generate_experiment_run_id_returns_unique_run_id():
    first = generate_experiment_run_id()
    second = generate_experiment_run_id()

    assert first.startswith("run-")
    assert second.startswith("run-")
    assert first != second


def test_generate_snapshot_ids_return_unique_ids_with_stable_prefixes():
    first_dataset = generate_dataset_snapshot_id()
    second_dataset = generate_dataset_snapshot_id()
    first_code = generate_code_snapshot_id()
    second_code = generate_code_snapshot_id()

    assert first_dataset.startswith("dataset-snapshot-")
    assert second_dataset.startswith("dataset-snapshot-")
    assert first_dataset != second_dataset
    assert first_code.startswith("code-snapshot-")
    assert second_code.startswith("code-snapshot-")
    assert first_code != second_code


def test_generate_standalone_metric_and_log_ids_return_unique_stable_prefixes():
    first_metric = generate_metric_id()
    second_metric = generate_metric_id()
    first_log = generate_log_id()
    second_log = generate_log_id()

    assert first_metric.startswith("metric-")
    assert second_metric.startswith("metric-")
    assert first_metric != second_metric
    assert first_log.startswith("log-")
    assert second_log.startswith("log-")
    assert first_log != second_log


def make_event(
    record: ExperimentRunRecord,
    *,
    sequence: int = 1,
    event_type: str = EXPERIMENT_RUN_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=experiment_run_recorded_payload(record),
    )


def make_dataset_snapshot_event(
    record: DatasetSnapshotRecord,
    *,
    sequence: int = 1,
    event_type: str = DATASET_SNAPSHOT_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-dataset-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=dataset_snapshot_recorded_payload(record),
    )


def make_code_snapshot_event(
    record: CodeSnapshotRecord,
    *,
    sequence: int = 1,
    event_type: str = CODE_SNAPSHOT_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-code-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=code_snapshot_recorded_payload(record),
    )


def make_metric_event(
    record: MetricRecord,
    *,
    sequence: int = 1,
    event_type: str = METRIC_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-metric-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=metric_recorded_payload(record),
    )


def make_log_ref_event(
    record: LogRefRecord,
    *,
    sequence: int = 1,
    event_type: str = LOG_REF_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-log-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=log_ref_recorded_payload(record),
    )


def make_artifact_ref_event(
    record: ArtifactRefRecord,
    *,
    sequence: int = 1,
    event_type: str = ARTIFACT_REF_RECORDED_EVENT,
    session_id: str | None = None,
) -> AgentEvent:
    return AgentEvent(
        id=f"event-artifact-{sequence}",
        session_id=session_id or record.session_id,
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=event_type,
        data=artifact_ref_recorded_payload(record),
    )


def make_record(
    *,
    session_id: str = "session-a",
    run_id: str = "run-1",
    **overrides: Any,
) -> ExperimentRunRecord:
    values = _valid_record_payload(session_id=session_id, run_id=run_id)
    values.update(overrides)
    return ExperimentRunRecord.model_validate(values)


def make_dataset_snapshot(
    *,
    session_id: str = "session-a",
    snapshot_id: str = "dataset-snapshot-1",
    **overrides: Any,
) -> DatasetSnapshotRecord:
    values = _valid_dataset_snapshot_payload(
        session_id=session_id,
        snapshot_id=snapshot_id,
    )
    values.update(overrides)
    return DatasetSnapshotRecord.model_validate(values)


def make_code_snapshot(
    *,
    session_id: str = "session-a",
    snapshot_id: str = "code-snapshot-1",
    **overrides: Any,
) -> CodeSnapshotRecord:
    values = _valid_code_snapshot_payload(
        session_id=session_id,
        snapshot_id=snapshot_id,
    )
    values.update(overrides)
    return CodeSnapshotRecord.model_validate(values)


def make_metric(
    *,
    session_id: str = "session-a",
    metric_id: str = "metric-1",
    **overrides: Any,
) -> MetricRecord:
    values = _valid_metric_payload(session_id=session_id, metric_id=metric_id)
    values.update(overrides)
    return MetricRecord.model_validate(values)


def make_log_ref(
    *,
    session_id: str = "session-a",
    log_id: str = "log-1",
    **overrides: Any,
) -> LogRefRecord:
    values = _valid_log_ref_payload(session_id=session_id, log_id=log_id)
    values.update(overrides)
    return LogRefRecord.model_validate(values)


def make_artifact_ref(
    *,
    session_id: str = "session-a",
    artifact_id: str = "artifact-1",
    **overrides: Any,
) -> ArtifactRefRecord:
    values = _valid_artifact_ref_payload(
        session_id=session_id,
        artifact_id=artifact_id,
    )
    values.update(overrides)
    return ArtifactRefRecord.model_validate(values)


def test_payload_round_trips_from_record():
    record = make_record(run_id="run-roundtrip")

    payload = experiment_run_recorded_payload(record)

    assert payload["session_id"] == "session-a"
    assert payload["run_id"] == "run-roundtrip"
    assert ExperimentRunRecord.model_validate(payload) == record


def test_snapshot_payloads_round_trip_from_records():
    dataset = make_dataset_snapshot(snapshot_id="dataset-roundtrip")
    code = make_code_snapshot(snapshot_id="code-roundtrip")

    dataset_payload = dataset_snapshot_recorded_payload(dataset)
    code_payload = code_snapshot_recorded_payload(code)

    assert dataset_payload["session_id"] == "session-a"
    assert dataset_payload["snapshot_id"] == "dataset-roundtrip"
    assert dataset_payload["schema"] == {"columns": [{"name": "text", "type": "str"}]}
    assert DatasetSnapshotRecord.model_validate(dataset_payload) == dataset
    assert code_payload["session_id"] == "session-a"
    assert code_payload["snapshot_id"] == "code-roundtrip"
    assert CodeSnapshotRecord.model_validate(code_payload) == code


def test_standalone_payloads_round_trip_from_records():
    metric = make_metric(metric_id="metric-roundtrip")
    log_ref = make_log_ref(log_id="log-roundtrip")
    artifact_ref = make_artifact_ref(artifact_id="artifact-roundtrip")

    metric_payload = metric_recorded_payload(metric)
    log_payload = log_ref_recorded_payload(log_ref)
    artifact_payload = artifact_ref_recorded_payload(artifact_ref)

    assert metric_payload["session_id"] == "session-a"
    assert metric_payload["metric_id"] == "metric-roundtrip"
    assert MetricRecord.model_validate(metric_payload) == metric
    assert log_payload["session_id"] == "session-a"
    assert log_payload["log_id"] == "log-roundtrip"
    assert LogRefRecord.model_validate(log_payload) == log_ref
    assert artifact_payload["session_id"] == "session-a"
    assert artifact_payload["artifact_id"] == "artifact-roundtrip"
    assert ArtifactRefRecord.model_validate(artifact_payload) == artifact_ref


def test_event_to_record_validation_rejects_wrong_type_and_session_mismatch():
    record = make_record(run_id="run-validate")

    assert run_record_from_event(make_event(record)) == record

    with pytest.raises(ExperimentLedgerError, match=EXPERIMENT_RUN_RECORDED_EVENT):
        run_record_from_event(
            make_event(record, event_type="phase.completed", sequence=2)
        )

    mismatched = make_record(session_id="session-b", run_id="run-validate")
    with pytest.raises(ExperimentLedgerError, match="session_id"):
        run_record_from_event(make_event(mismatched, session_id="session-a"))


def test_snapshot_events_reject_wrong_type_and_session_mismatch():
    dataset = make_dataset_snapshot(snapshot_id="dataset-validate")
    code = make_code_snapshot(snapshot_id="code-validate")

    assert dataset_snapshot_record_from_event(
        make_dataset_snapshot_event(dataset)
    ) == dataset
    assert code_snapshot_record_from_event(make_code_snapshot_event(code)) == code

    with pytest.raises(ExperimentLedgerError, match=DATASET_SNAPSHOT_RECORDED_EVENT):
        dataset_snapshot_record_from_event(
            make_dataset_snapshot_event(
                dataset,
                event_type="phase.completed",
                sequence=2,
            )
        )
    with pytest.raises(ExperimentLedgerError, match=CODE_SNAPSHOT_RECORDED_EVENT):
        code_snapshot_record_from_event(
            make_code_snapshot_event(
                code,
                event_type="phase.completed",
                sequence=2,
            )
        )

    with pytest.raises(ExperimentLedgerError, match="session_id"):
        dataset_snapshot_record_from_event(
            make_dataset_snapshot_event(
                make_dataset_snapshot(
                    session_id="session-b",
                    snapshot_id="dataset-validate",
                ),
                session_id="session-a",
            )
        )
    with pytest.raises(ExperimentLedgerError, match="session_id"):
        code_snapshot_record_from_event(
            make_code_snapshot_event(
                make_code_snapshot(session_id="session-b", snapshot_id="code-validate"),
                session_id="session-a",
            )
        )


def test_standalone_events_reject_wrong_type_and_session_mismatch():
    metric = make_metric(metric_id="metric-validate")
    log_ref = make_log_ref(log_id="log-validate")
    artifact_ref = make_artifact_ref(artifact_id="artifact-validate")

    assert metric_record_from_event(make_metric_event(metric)) == metric
    assert log_ref_record_from_event(make_log_ref_event(log_ref)) == log_ref
    assert (
        artifact_ref_record_from_event(make_artifact_ref_event(artifact_ref))
        == artifact_ref
    )

    with pytest.raises(ExperimentLedgerError, match=METRIC_RECORDED_EVENT):
        metric_record_from_event(
            make_metric_event(metric, event_type="phase.completed", sequence=2)
        )
    with pytest.raises(ExperimentLedgerError, match=LOG_REF_RECORDED_EVENT):
        log_ref_record_from_event(
            make_log_ref_event(log_ref, event_type="phase.completed", sequence=2)
        )
    with pytest.raises(ExperimentLedgerError, match=ARTIFACT_REF_RECORDED_EVENT):
        artifact_ref_record_from_event(
            make_artifact_ref_event(
                artifact_ref,
                event_type="phase.completed",
                sequence=2,
            )
        )

    with pytest.raises(ExperimentLedgerError, match="session_id"):
        metric_record_from_event(
            make_metric_event(
                make_metric(session_id="session-b", metric_id="metric-validate"),
                session_id="session-a",
            )
        )
    with pytest.raises(ExperimentLedgerError, match="session_id"):
        log_ref_record_from_event(
            make_log_ref_event(
                make_log_ref(session_id="session-b", log_id="log-validate"),
                session_id="session-a",
            )
        )
    with pytest.raises(ExperimentLedgerError, match="session_id"):
        artifact_ref_record_from_event(
            make_artifact_ref_event(
                make_artifact_ref(
                    session_id="session-b",
                    artifact_id="artifact-validate",
                ),
                session_id="session-a",
            )
        )


def test_projection_filters_by_session_and_type_ordered_by_event_sequence():
    first = make_record(run_id="run-1")
    second = make_record(run_id="run-2")
    other_session = make_record(session_id="session-b", run_id="run-b")
    wrong_type = make_record(run_id="run-wrong")
    events = [
        make_event(wrong_type, sequence=1, event_type="phase.completed"),
        make_event(second, sequence=3),
        make_event(other_session, sequence=1),
        make_event(first, sequence=2),
    ]

    projected = project_experiment_runs("session-a", events)

    assert [record.run_id for record in projected] == ["run-1", "run-2"]


def test_snapshot_projections_filter_by_session_and_type_ordered_by_event_sequence():
    first_dataset = make_dataset_snapshot(snapshot_id="dataset-1")
    second_dataset = make_dataset_snapshot(snapshot_id="dataset-2")
    other_dataset = make_dataset_snapshot(
        session_id="session-b",
        snapshot_id="dataset-b",
    )
    wrong_dataset = make_dataset_snapshot(snapshot_id="dataset-wrong")
    first_code = make_code_snapshot(snapshot_id="code-1")
    second_code = make_code_snapshot(snapshot_id="code-2")
    other_code = make_code_snapshot(session_id="session-b", snapshot_id="code-b")
    wrong_code = make_code_snapshot(snapshot_id="code-wrong")
    events = [
        make_dataset_snapshot_event(
            wrong_dataset,
            sequence=1,
            event_type="phase.completed",
        ),
        make_dataset_snapshot_event(second_dataset, sequence=3),
        make_dataset_snapshot_event(other_dataset, sequence=1),
        make_dataset_snapshot_event(first_dataset, sequence=2),
        make_code_snapshot_event(
            wrong_code,
            sequence=4,
            event_type="phase.completed",
        ),
        make_code_snapshot_event(second_code, sequence=6),
        make_code_snapshot_event(other_code, sequence=4),
        make_code_snapshot_event(first_code, sequence=5),
    ]

    dataset_projected = project_dataset_snapshots("session-a", events)
    code_projected = project_code_snapshots("session-a", events)

    assert [record.snapshot_id for record in dataset_projected] == [
        "dataset-1",
        "dataset-2",
    ]
    assert [record.snapshot_id for record in code_projected] == ["code-1", "code-2"]


def test_standalone_projections_filter_by_session_and_type_ordered_by_sequence():
    first_metric = make_metric(metric_id="metric-1")
    second_metric = make_metric(metric_id="metric-2")
    other_metric = make_metric(session_id="session-b", metric_id="metric-b")
    wrong_metric = make_metric(metric_id="metric-wrong")
    first_log = make_log_ref(log_id="log-1")
    second_log = make_log_ref(log_id="log-2")
    other_log = make_log_ref(session_id="session-b", log_id="log-b")
    first_artifact = make_artifact_ref(artifact_id="artifact-1")
    second_artifact = make_artifact_ref(artifact_id="artifact-2")
    other_artifact = make_artifact_ref(
        session_id="session-b",
        artifact_id="artifact-b",
    )
    events = [
        make_metric_event(wrong_metric, sequence=1, event_type="phase.completed"),
        make_metric_event(second_metric, sequence=4),
        make_metric_event(other_metric, sequence=3),
        make_metric_event(first_metric, sequence=2),
        make_log_ref_event(second_log, sequence=7),
        make_log_ref_event(other_log, sequence=5),
        make_log_ref_event(first_log, sequence=6),
        make_artifact_ref_event(second_artifact, sequence=10),
        make_artifact_ref_event(other_artifact, sequence=8),
        make_artifact_ref_event(first_artifact, sequence=9),
    ]

    assert [record.metric_id for record in project_metrics("session-a", events)] == [
        "metric-1",
        "metric-2",
    ]
    assert [record.log_id for record in project_log_refs("session-a", events)] == [
        "log-1",
        "log-2",
    ]
    assert [
        record.artifact_id for record in project_artifact_refs("session-a", events)
    ] == ["artifact-1", "artifact-2"]


def test_sqlite_create_get_list_works(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    first = make_record(run_id="run-1")
    second = make_record(run_id="run-2")
    other = make_record(session_id="session-b", run_id="run-b")

    created_first = store.create(first)
    created_second = store.create(second)
    store.create(other)

    assert created_first == first
    assert store.get("session-a", "run-1") == first
    assert store.get("session-a", "missing") is None
    assert store.list("session-a") == [created_first, created_second]
    assert store.list("session-a", limit=1) == [created_first]


def test_sqlite_create_get_list_works_for_dataset_snapshots(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    first = make_dataset_snapshot(snapshot_id="dataset-1")
    second = make_dataset_snapshot(snapshot_id="dataset-2")
    other = make_dataset_snapshot(session_id="session-b", snapshot_id="dataset-b")

    created_first = store.create_dataset_snapshot(first)
    created_second = store.create_dataset_snapshot(second)
    store.create_dataset_snapshot(other)

    assert created_first == first
    assert store.get_dataset_snapshot("session-a", "dataset-1") == first
    assert store.get_dataset_snapshot("session-a", "missing") is None
    assert store.list_dataset_snapshots("session-a") == [created_first, created_second]
    assert store.list_dataset_snapshots("session-a", limit=1) == [created_first]


def test_sqlite_create_get_list_works_for_code_snapshots(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    first = make_code_snapshot(snapshot_id="code-1")
    second = make_code_snapshot(snapshot_id="code-2")
    other = make_code_snapshot(session_id="session-b", snapshot_id="code-b")

    created_first = store.create_code_snapshot(first)
    created_second = store.create_code_snapshot(second)
    store.create_code_snapshot(other)

    assert created_first == first
    assert store.get_code_snapshot("session-a", "code-1") == first
    assert store.get_code_snapshot("session-a", "missing") is None
    assert store.list_code_snapshots("session-a") == [created_first, created_second]
    assert store.list_code_snapshots("session-a", limit=1) == [created_first]


def test_sqlite_create_get_list_works_for_standalone_records(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    first_metric = make_metric(metric_id="metric-1")
    second_metric = make_metric(metric_id="metric-2")
    first_log = make_log_ref(log_id="log-1")
    second_log = make_log_ref(log_id="log-2")
    first_artifact = make_artifact_ref(artifact_id="artifact-1")
    second_artifact = make_artifact_ref(artifact_id="artifact-2")

    created_metric = store.create_metric(first_metric)
    store.create_metric(second_metric)
    created_log = store.create_log_ref(first_log)
    store.create_log_ref(second_log)
    created_artifact = store.create_artifact_ref(first_artifact)
    store.create_artifact_ref(second_artifact)

    assert store.get_metric("session-a", "metric-1") == created_metric
    assert store.get_metric("session-a", "missing") is None
    assert [record.metric_id for record in store.list_metrics("session-a")] == [
        "metric-1",
        "metric-2",
    ]
    assert store.list_metrics("session-a", limit=1) == [created_metric]
    assert store.get_log_ref("session-a", "log-1") == created_log
    assert store.get_log_ref("session-a", "missing") is None
    assert [record.log_id for record in store.list_log_refs("session-a")] == [
        "log-1",
        "log-2",
    ]
    assert store.list_log_refs("session-a", limit=1) == [created_log]
    assert store.get_artifact_ref("session-a", "artifact-1") == created_artifact
    assert store.get_artifact_ref("session-a", "missing") is None
    assert [
        record.artifact_id for record in store.list_artifact_refs("session-a")
    ] == ["artifact-1", "artifact-2"]
    assert store.list_artifact_refs("session-a", limit=1) == [created_artifact]


def test_duplicate_run_is_rejected(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    record = make_record(run_id="run-duplicate")
    store.create(record)

    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create(record)


def test_duplicate_dataset_snapshot_is_rejected(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    record = make_dataset_snapshot(snapshot_id="dataset-duplicate")
    store.create_dataset_snapshot(record)

    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create_dataset_snapshot(record)


def test_duplicate_code_snapshot_is_rejected(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    record = make_code_snapshot(snapshot_id="code-duplicate")
    store.create_code_snapshot(record)

    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create_code_snapshot(record)


def test_duplicate_standalone_record_ids_are_rejected(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    metric = make_metric(metric_id="metric-duplicate")
    log_ref = make_log_ref(log_id="log-duplicate")
    artifact_ref = make_artifact_ref(artifact_id="artifact-duplicate")
    store.create_metric(metric)
    store.create_log_ref(log_ref)
    store.create_artifact_ref(artifact_ref)

    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create_metric(metric)
    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create_log_ref(log_ref)
    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create_artifact_ref(artifact_ref)


def test_persisted_json_redacts_config_secret(tmp_path):
    database_path = tmp_path / "experiments.sqlite"
    store = SQLiteExperimentLedgerStore(database_path)
    secret = "hf_experimentsecret123456789"
    record = make_record(
        run_id="run-secret",
        config={
            "api_key": secret,
            "headers": {"Authorization": f"Bearer {secret}"},
            "learning_rate": 0.001,
        },
    )

    created = store.create(record)

    assert secret not in str(created.model_dump())

    connection = sqlite3.connect(database_path)
    try:
        stored_json = connection.execute(
            "SELECT record_json FROM experiment_runs WHERE run_id = ?",
            ("run-secret",),
        ).fetchone()[0]
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert secret not in stored_json
    assert secret not in database_dump
    assert "[REDACTED]" in stored_json


def test_persisted_json_redacts_dataset_and_code_snapshot_secrets(tmp_path):
    database_path = tmp_path / "experiments.sqlite"
    store = SQLiteExperimentLedgerStore(database_path)
    dataset_secret = "hf_datasetsecret123456789"
    code_secret = "ghp_codesecret123456789"
    dataset = make_dataset_snapshot(
        snapshot_id="dataset-secret",
        lineage_refs=[{"api_key": dataset_secret}],
    )
    code = make_code_snapshot(
        snapshot_id="code-secret",
        generated_artifact_refs=[{"Authorization": f"Bearer {code_secret}"}],
    )

    created_dataset = store.create_dataset_snapshot(dataset)
    created_code = store.create_code_snapshot(code)

    assert dataset_secret not in str(created_dataset.model_dump())
    assert code_secret not in str(created_code.model_dump())

    connection = sqlite3.connect(database_path)
    try:
        dataset_json = connection.execute(
            "SELECT record_json FROM dataset_snapshots WHERE snapshot_id = ?",
            ("dataset-secret",),
        ).fetchone()[0]
        code_json = connection.execute(
            "SELECT record_json FROM code_snapshots WHERE snapshot_id = ?",
            ("code-secret",),
        ).fetchone()[0]
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert dataset_secret not in dataset_json
    assert code_secret not in code_json
    assert dataset_secret not in database_dump
    assert code_secret not in database_dump
    assert "[REDACTED]" in dataset_json
    assert "[REDACTED]" in code_json


def test_persisted_json_redacts_standalone_record_secrets(tmp_path):
    database_path = tmp_path / "experiments.sqlite"
    store = SQLiteExperimentLedgerStore(database_path)
    metric_secret = "hf_metricsecret123456789"
    log_secret = "ghp_logsecret123456789012345"
    artifact_secret = "sk-proj-artifactsecret123"
    metric = make_metric(
        metric_id="metric-secret",
        unit=f"bearer {metric_secret}",
    )
    log_ref = make_log_ref(
        log_id="log-secret",
        uri=f"https://logs.example/run?token={log_secret}",
    )
    artifact_ref = make_artifact_ref(
        artifact_id="artifact-secret",
        metadata={"api_key": artifact_secret},
    )

    created_metric = store.create_metric(metric)
    created_log = store.create_log_ref(log_ref)
    created_artifact = store.create_artifact_ref(artifact_ref)

    assert metric_secret not in str(created_metric.model_dump())
    assert log_secret not in str(created_log.model_dump())
    assert artifact_secret not in str(created_artifact.model_dump())

    connection = sqlite3.connect(database_path)
    try:
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert metric_secret not in database_dump
    assert log_secret not in database_dump
    assert artifact_secret not in database_dump
    assert "[REDACTED]" in database_dump


def test_run_creation_with_snapshot_refs_does_not_create_snapshot_rows(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    run = make_record(
        run_id="run-with-snapshot-refs",
        dataset_snapshot_refs=[
            {
                "snapshot_id": "dataset-ref-only",
                "source": "dataset_registry",
                "name": "training-set",
            }
        ],
        code_snapshot_refs=[
            {
                "snapshot_id": "code-ref-only",
                "source": "git",
                "git_commit": "abcdef123456",
            }
        ],
    )

    store.create(run)

    assert store.get_dataset_snapshot("session-a", "dataset-ref-only") is None
    assert store.get_code_snapshot("session-a", "code-ref-only") is None
    assert store.list_dataset_snapshots("session-a") == []
    assert store.list_code_snapshots("session-a") == []


def test_run_creation_with_nested_refs_does_not_create_standalone_rows(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    run = make_record(run_id="run-with-nested-records")

    store.create(run)

    assert store.get_metric("session-a", "accuracy") is None
    assert store.get_log_ref("session-a", "log-1") is None
    assert store.get_artifact_ref("session-a", "artifact-1") is None
    assert store.list_metrics("session-a") == []
    assert store.list_log_refs("session-a") == []
    assert store.list_artifact_refs("session-a") == []


def test_sqlite_store_owns_only_experiment_ledger_tables(tmp_path):
    database_path = tmp_path / "experiments.sqlite"
    SQLiteExperimentLedgerStore(database_path).close()

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

    assert tables == {
        "artifact_refs",
        "code_snapshots",
        "dataset_snapshots",
        "experiment_log_refs",
        "experiment_metrics",
        "experiment_runs",
    }


def _valid_metric_payload(
    *,
    session_id: str = "session-a",
    metric_id: str = "metric-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "metric_id": metric_id,
        "source_event_sequence": 8,
        "name": "accuracy",
        "value": 0.91,
        "source": "tool",
        "step": 3,
        "unit": "ratio",
        "recorded_at": "2026-04-29T10:12:00Z",
    }


def _valid_log_ref_payload(
    *,
    session_id: str = "session-a",
    log_id: str = "log-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "log_id": log_id,
        "source_event_sequence": 9,
        "source": "stdout",
        "uri": "file:///tmp/train.log",
        "label": "training log",
    }


def _valid_artifact_ref_payload(
    *,
    session_id: str = "session-a",
    artifact_id: str = "artifact-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "artifact_id": artifact_id,
        "source_event_sequence": 10,
        "type": "model_checkpoint",
        "source": "job",
        "source_tool_call_id": "tc-1",
        "source_job_id": "job-1",
        "path": "/tmp/model.pt",
        "uri": "file:///tmp/model.pt",
        "digest": "sha256:model",
        "label": "Best checkpoint",
        "metadata": {"epoch": 3},
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:13:00Z",
    }


def _valid_dataset_snapshot_payload(
    *,
    session_id: str = "session-a",
    snapshot_id: str = "dataset-snapshot-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "snapshot_id": snapshot_id,
        "source_event_sequence": 3,
        "source": "dataset_registry",
        "dataset_id": "dataset-123",
        "name": "training-set",
        "uri": "https://datasets.example/train",
        "split": "train",
        "revision": "v1",
        "schema": {"columns": [{"name": "text", "type": "str"}]},
        "sample_count": 42,
        "library_fingerprint": "fingerprint-123",
        "manifest_hash": "sha256:dataset-manifest",
        "license": "MIT",
        "lineage_refs": [{"source": "raw-corpus"}],
        "diff_refs": [{"source": "previous-snapshot"}],
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:10:00Z",
    }


def _valid_code_snapshot_payload(
    *,
    session_id: str = "session-a",
    snapshot_id: str = "code-snapshot-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "snapshot_id": snapshot_id,
        "source_event_sequence": 4,
        "source": "git",
        "repo": "ml-junior",
        "path": "/workspace/ml-junior",
        "uri": "https://git.example/ml-junior.git",
        "git_commit": "abcdef1234567890",
        "git_ref": "main",
        "diff_hash": "sha256:diff",
        "changed_files": ["backend/experiment_ledger.py"],
        "generated_artifact_refs": [{"artifact_id": "wheel-1"}],
        "manifest_hash": "sha256:code-manifest",
        "digest": "sha256:code",
        "privacy_class": "private",
        "redaction_status": "none",
        "created_at": "2026-04-29T10:11:00Z",
    }


def _valid_record_payload(
    *,
    session_id: str = "session-a",
    run_id: str = "run-1",
) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "run_id": run_id,
        "hypothesis": "Train baseline with frozen encoder",
        "status": "completed",
        "source_event_sequence": 7,
        "phase_id": "train",
        "dataset_snapshot_refs": [
            {
                "snapshot_id": "dataset-1",
                "source": "dataset_registry",
                "name": "training-set",
                "digest": "sha256:data",
            }
        ],
        "code_snapshot_refs": [
            {
                "snapshot_id": "code-1",
                "source": "git",
                "git_commit": "abcdef123456",
                "git_ref": "main",
            }
        ],
        "config": {"learning_rate": 0.001, "seed": 7},
        "seed": 1234,
        "runtime": {
            "provider": "local",
            "started_at": "2026-04-29T10:00:00Z",
            "ended_at": "2026-04-29T10:15:00Z",
            "duration_seconds": 900.0,
            "hardware": {"accelerator": "cpu"},
        },
        "metrics": [
            {
                "name": "accuracy",
                "value": 0.91,
                "source": "tool",
                "step": 3,
                "unit": "ratio",
            }
        ],
        "log_refs": [
            {
                "log_id": "log-1",
                "source": "stdout",
                "label": "training log",
            }
        ],
        "artifact_refs": [
            {
                "artifact_id": "artifact-1",
                "type": "model_checkpoint",
                "source": "local_path",
                "uri": "file:///tmp/model.pt",
            }
        ],
        "verifier_refs": [
            {
                "verifier_id": "verifier-1",
                "type": "metric",
                "status": "passed",
                "source": "flow_template",
            }
        ],
        "external_tracking_refs": [
            {
                "tracking_id": "tracking-1",
                "source": "external_tracking",
                "provider": "tracking-provider",
                "uri": "https://tracking.example/runs/tracking-1",
            }
        ],
        "created_at": "2026-04-29T10:16:00Z",
    }
