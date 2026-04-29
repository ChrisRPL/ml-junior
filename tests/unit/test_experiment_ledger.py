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

from backend.experiment_ledger import (  # noqa: E402
    EXPERIMENT_RUN_RECORDED_EVENT,
    ExperimentLedgerError,
    SQLiteExperimentLedgerStore,
    experiment_run_recorded_payload,
    generate_experiment_run_id,
    project_experiment_runs,
    run_record_from_event,
)
from backend.models import ExperimentRunRecord  # noqa: E402


def test_generate_experiment_run_id_returns_unique_run_id():
    first = generate_experiment_run_id()
    second = generate_experiment_run_id()

    assert first.startswith("run-")
    assert second.startswith("run-")
    assert first != second


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


def make_record(
    *,
    session_id: str = "session-a",
    run_id: str = "run-1",
    **overrides: Any,
) -> ExperimentRunRecord:
    values = _valid_record_payload(session_id=session_id, run_id=run_id)
    values.update(overrides)
    return ExperimentRunRecord.model_validate(values)


def test_payload_round_trips_from_record():
    record = make_record(run_id="run-roundtrip")

    payload = experiment_run_recorded_payload(record)

    assert payload["session_id"] == "session-a"
    assert payload["run_id"] == "run-roundtrip"
    assert ExperimentRunRecord.model_validate(payload) == record


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


def test_duplicate_run_is_rejected(tmp_path):
    store = SQLiteExperimentLedgerStore(tmp_path / "experiments.sqlite")
    record = make_record(run_id="run-duplicate")
    store.create(record)

    with pytest.raises(ExperimentLedgerError, match="already exists"):
        store.create(record)


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


def test_sqlite_store_owns_only_experiment_runs_table(tmp_path):
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

    assert tables == {"experiment_runs"}


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
