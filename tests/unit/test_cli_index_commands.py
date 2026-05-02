from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agent.core.events import AgentEvent
from agent.core.index_commands import (
    render_artifact_index,
    render_index_command,
    render_metric_index,
    render_run_detail,
    render_run_index,
)
from backend.experiment_ledger import (
    EXPERIMENT_RUN_RECORDED_EVENT,
    experiment_run_recorded_payload,
)
from backend.job_artifact_refs import (
    ARTIFACT_REF_RECORDED_EVENT,
    artifact_ref_recorded_payload,
)
from backend.models import (
    ArtifactRefRecord,
    ExperimentRunRecord,
    canonical_artifact_ref_uri,
)


def test_run_index_renders_current_session_runs_ordered_and_filtered() -> None:
    secret = "hf_runsecret123456789"
    session = _session_from_events(
        make_run_event(
            sequence=3,
            run_id="run-2",
            hypothesis="Compare lower learning rate",
            status="completed",
            tracking_uri=f"https://tracking.example/runs/run-2?token={secret}",
        ),
        make_artifact_event(
            sequence=1,
            artifact_id="artifact-1",
            label="Metrics",
            uri="https://artifacts.example/metrics.json",
        ),
        make_run_event(
            sequence=2,
            run_id="run-1",
            hypothesis="Train baseline",
            status="running",
            tracking_uri="https://tracking.example/runs/run-1",
        ),
    )

    output = render_run_index(session=session)
    filtered = render_index_command("/runs", "lower", session=session)

    assert output.startswith("Experiment runs\n")
    assert output.index("run-1") < output.index("run-2")
    assert "running  phase:train  metrics:accuracy=0.91" in output
    assert "runtime:local" in output
    assert secret not in output
    assert "run-2" in filtered
    assert "run-1" not in filtered


def test_artifact_index_renders_latest_refs_ordered_and_filtered() -> None:
    secret = "hf_artifactsecret123456789"
    session = _session_from_events(
        make_artifact_event(
            sequence=1,
            artifact_id="artifact-1",
            label="Initial checkpoint",
            uri="https://artifacts.example/old.pt",
        ),
        make_artifact_event(
            sequence=2,
            artifact_id="artifact-2",
            label="Metrics",
            uri="https://artifacts.example/metrics.json",
        ),
        make_artifact_event(
            sequence=3,
            artifact_id="artifact-1",
            label="Best checkpoint",
            uri=f"https://artifacts.example/best.pt?token={secret}",
        ),
    )

    output = render_artifact_index(session=session)
    filtered = render_index_command("/artifacts", "best", session=session)

    assert output.startswith("Artifacts\n")
    assert output.index("artifact-2") < output.index("artifact-1")
    assert "Best checkpoint" in output
    assert "Initial checkpoint" not in output
    assert canonical_artifact_ref_uri("session-a", "artifact-1") in output
    assert secret not in output
    assert "artifact-1" in filtered
    assert "artifact-2" not in filtered


def test_run_detail_renders_latest_matching_run_without_secret_values() -> None:
    secret = "hf_rundetailsecret123456789"
    session = _session_from_events(
        make_run_event(
            sequence=1,
            run_id="run-1",
            hypothesis="Train baseline",
            status="running",
            tracking_uri="https://tracking.example/runs/run-1",
        ),
        make_run_event(
            sequence=2,
            run_id="run-1",
            hypothesis="Promote best checkpoint",
            status="completed",
            tracking_uri=f"https://tracking.example/runs/run-1?token={secret}",
            artifact_uri=f"https://artifacts.example/best.pt?token={secret}",
            log_uri=f"https://logs.example/run-1.txt?token={secret}",
        ),
    )

    output = render_run_detail("run-1", session=session)
    dispatched = render_index_command("/run show", "run-1", session=session)

    assert output.startswith("Experiment run run-1\n")
    assert "status: completed" in output
    assert "Promote best checkpoint" in output
    assert "Train baseline" not in output
    assert "config keys: [REDACTED],token" in output
    assert "accuracy: 0.91 source:tool" in output
    assert "artifact-run-1" in output
    assert "log-run-1" in output
    assert "tracking-run-1" in output
    assert secret not in output
    assert dispatched == output


def test_metric_index_renders_run_metrics_and_filters_without_secret_values() -> None:
    secret = "hf_metricsecret123456789"
    session = _session_from_events(
        make_run_event(
            sequence=1,
            run_id="run-1",
            hypothesis="Train baseline",
            status="completed",
            tracking_uri=f"https://tracking.example/runs/run-1?token={secret}",
            metrics=[
                {
                    "name": "accuracy",
                    "value": 0.91,
                    "source": "tool",
                    "step": 1,
                    "unit": "ratio",
                    "recorded_at": "2026-01-02T03:04:01+00:00",
                },
                {"name": "loss", "value": 0.12, "source": "tool"},
            ],
        ),
        make_run_event(
            sequence=2,
            run_id="run-2",
            hypothesis="Compare lower learning rate",
            status="running",
            tracking_uri="https://tracking.example/runs/run-2",
            metrics=[{"name": "loss", "value": 0.2, "source": "tool"}],
        ),
    )

    output = render_metric_index(session=session)
    filtered_by_run = render_index_command("/metrics", "run-2", session=session)
    filtered_by_metric = render_index_command("/metrics", "accuracy", session=session)

    assert output.startswith("Metrics\n")
    assert "run-1  accuracy=0.91  source:tool  step:1  unit:ratio" in output
    assert "recorded:2026-01-02T03:04:01+00:00" in output
    assert "run-1  loss=0.12  source:tool" in output
    assert "run-2  loss=0.2  source:tool" in output
    assert secret not in output
    assert "run-2" in filtered_by_run
    assert "run-1" not in filtered_by_run
    assert "accuracy=0.91" in filtered_by_metric
    assert "loss=0.12" not in filtered_by_metric


def test_index_commands_handle_empty_and_missing_sessions() -> None:
    empty_session = _session_from_events()
    missing_secret = "hf_missingsecret123456789"

    assert render_run_index(session=None) == "Experiment runs\n  no active session"
    assert render_run_detail("run-1", session=None) == (
        "Experiment run\n  no active session"
    )
    assert render_run_detail(session=empty_session) == (
        "Experiment run\n  Usage: /run show <id>"
    )
    assert render_run_detail("missing", session=empty_session) == (
        "Experiment run\n  run not found: missing"
    )
    assert render_run_detail(missing_secret, session=empty_session) == (
        "Experiment run\n  run not found: [REDACTED]"
    )
    assert render_artifact_index(session=empty_session) == (
        "Artifacts\n  no artifacts recorded for this session"
    )
    assert render_metric_index(session=None) == "Metrics\n  no active session"
    assert render_metric_index(session=empty_session) == (
        "Metrics\n  no metrics recorded for this session"
    )
    assert render_run_index("failed", session=empty_session) == (
        "Experiment runs\n  no runs match filter: failed"
    )
    assert render_metric_index("loss", session=empty_session) == (
        "Metrics\n  no metrics match filter: loss"
    )


def test_index_command_dispatch_rejects_unexpected_commands() -> None:
    with pytest.raises(ValueError, match="Unsupported index command"):
        render_index_command("/run compare", "run-1", session=_session_from_events())


async def test_main_handler_dispatches_read_only_index_commands(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    monkeypatch.delenv("MLJ_BACKEND_BASE_URL", raising=False)
    monkeypatch.delenv("MLJ_BACKEND_SESSION_ID", raising=False)
    monkeypatch.delenv("MLJ_BACKEND_BEARER_TOKEN", raising=False)

    calls = []
    session = object()

    def fake_render(command: str, arguments: str, **kwargs) -> str:
        calls.append((command, arguments, kwargs.get("session")))
        return "index body"

    monkeypatch.setattr(main_module, "render_index_command", fake_render)

    first = await main_module._handle_slash_command(
        "/runs completed",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )
    second = await main_module._handle_slash_command(
        "/run show run-1",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )
    third = await main_module._handle_slash_command(
        "/metrics run-1",
        config=object(),
        session_holder=[session],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert first is None
    assert second is None
    assert third is None
    assert calls == [
        ("/runs", "completed", session),
        ("/run show", "run-1", session),
        ("/metrics", "run-1", session),
    ]
    assert capsys.readouterr().out.count("index body") == 3


async def test_main_handler_dispatches_backend_index_commands_when_opted_in(
    monkeypatch,
    capsys,
) -> None:
    import agent.main as main_module

    monkeypatch.setenv("MLJ_BACKEND_BASE_URL", "http://backend.example")
    monkeypatch.setenv("MLJ_BACKEND_SESSION_ID", "session-a")
    monkeypatch.setenv("MLJ_BACKEND_BEARER_TOKEN", "hf_backendtoken123456789")

    calls = []

    async def fake_backend_render(command: str, arguments: str, **kwargs) -> str:
        backend_config = kwargs["config"]
        calls.append(
            (
                command,
                arguments,
                backend_config.base_url,
                backend_config.session_id,
                backend_config.bearer_token,
            )
        )
        return "backend index body"

    def fail_local_render(*_args, **_kwargs) -> str:
        raise AssertionError("local renderer should not be used in backend mode")

    monkeypatch.setattr(
        main_module,
        "render_backend_index_command",
        fake_backend_render,
    )
    monkeypatch.setattr(main_module, "render_index_command", fail_local_render)

    result = await main_module._handle_slash_command(
        "/runs completed",
        config=object(),
        session_holder=[object()],
        submission_queue=asyncio.Queue(),
        submission_id=[0],
    )

    assert result is None
    assert calls == [
        (
            "/runs",
            "completed",
            "http://backend.example",
            "session-a",
            "hf_backendtoken123456789",
        )
    ]
    assert "backend index body" in capsys.readouterr().out


def _session_from_events(*events: AgentEvent):
    redacted = [event.redacted_copy() for event in events]
    return SimpleNamespace(
        session_id="session-a",
        logged_events=[
            {
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type,
                "data": event.data,
            }
            for event in redacted
        ],
        event_metadata=[
            {
                "event_id": event.id,
                "sequence": event.sequence,
                "timestamp": event.timestamp.isoformat(),
                "schema_version": event.schema_version,
                "redaction_status": event.redaction_status,
            }
            for event in redacted
        ],
    )


def make_run_event(
    *,
    sequence: int,
    run_id: str,
    hypothesis: str,
    status: str,
    tracking_uri: str,
    artifact_uri: str | None = None,
    log_uri: str | None = None,
    metrics: list[dict[str, object]] | None = None,
) -> AgentEvent:
    record_data = {
        "session_id": "session-a",
        "run_id": run_id,
        "hypothesis": hypothesis,
        "status": status,
        "source_event_sequence": sequence,
        "phase_id": "train",
        "config": {"api_key": tracking_uri, "token": tracking_uri},
        "runtime": {
            "provider": "local",
            "started_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        },
        "metrics": metrics
        if metrics is not None
        else [{"name": "accuracy", "value": 0.91, "source": "tool"}],
        "external_tracking_refs": [
            {
                "tracking_id": f"tracking-{run_id}",
                "source": "external_tracking",
                "provider": "tracking-provider",
                "uri": tracking_uri,
            }
        ],
        "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
    }
    if artifact_uri:
        record_data["artifact_refs"] = [
            {
                "artifact_id": f"artifact-{run_id}",
                "type": "model_checkpoint",
                "source": "remote_uri",
                "uri": artifact_uri,
            }
        ]
    if log_uri:
        record_data["log_refs"] = [
            {
                "log_id": f"log-{run_id}",
                "source": "remote_uri",
                "uri": log_uri,
            }
        ]

    record = ExperimentRunRecord.model_validate(record_data)
    return AgentEvent(
        id=f"event-run-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=EXPERIMENT_RUN_RECORDED_EVENT,
        data=experiment_run_recorded_payload(record),
    )


def make_artifact_event(
    *,
    sequence: int,
    artifact_id: str,
    label: str,
    uri: str,
) -> AgentEvent:
    record = ArtifactRefRecord.model_validate(
        {
            "session_id": "session-a",
            "artifact_id": artifact_id,
            "source_event_sequence": sequence,
            "type": "model_checkpoint",
            "source": "remote_uri",
            "ref_uri": canonical_artifact_ref_uri("session-a", artifact_id),
            "locator": {"type": "remote_uri", "uri": uri},
            "uri": uri,
            "label": label,
            "privacy_class": "private",
            "redaction_status": "none",
            "created_at": f"2026-01-02T03:04:{sequence:02d}+00:00",
        }
    )
    return AgentEvent(
        id=f"event-artifact-{sequence}",
        session_id="session-a",
        sequence=sequence,
        timestamp=datetime(2026, 1, 2, 3, 4, sequence, tzinfo=timezone.utc),
        event_type=ARTIFACT_REF_RECORDED_EVENT,
        data=artifact_ref_recorded_payload(record),
    )
