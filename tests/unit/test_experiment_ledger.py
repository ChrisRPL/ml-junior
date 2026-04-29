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
    CODE_SNAPSHOT_RECORDED_EVENT,
    DATASET_SNAPSHOT_RECORDED_EVENT,
    EXPERIMENT_RUN_RECORDED_EVENT,
    ExperimentLedgerError,
    SQLiteExperimentLedgerStore,
    code_snapshot_record_from_event,
    code_snapshot_recorded_payload,
    dataset_snapshot_record_from_event,
    dataset_snapshot_recorded_payload,
    generate_code_snapshot_id,
    generate_dataset_snapshot_id,
    experiment_run_recorded_payload,
    generate_experiment_run_id,
    project_code_snapshots,
    project_dataset_snapshots,
    project_experiment_runs,
    run_record_from_event,
)
from backend.models import (  # noqa: E402
    CodeSnapshotRecord,
    DatasetSnapshotRecord,
    ExperimentRunRecord,
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

    assert tables == {"experiment_runs", "dataset_snapshots", "code_snapshots"}


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
