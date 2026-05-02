"""Read-only CLI renderers for current-session indexes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.core.events import AgentEvent
from agent.core.redaction import DEFAULT_REDACTION_POLICY, REDACTED, redact_string
from backend.experiment_ledger import (
    EXPERIMENT_RUN_RECORDED_EVENT,
    ExperimentLedgerError,
    project_experiment_runs,
)
from backend.job_artifact_refs import (
    ARTIFACT_REF_RECORDED_EVENT,
    JobArtifactRefError,
    project_artifact_refs,
)
from backend.models import ArtifactRefRecord, ExperimentRunRecord


class IndexCommandError(RuntimeError):
    """Raised when session index data cannot be read safely."""


def render_index_command(
    command: str,
    arguments: str = "",
    *,
    session: Any = None,
) -> str:
    """Render a supported read-only index command for the current CLI session."""

    if command == "/runs":
        return render_run_index(arguments, session=session)
    if command == "/run show":
        return render_run_detail(arguments, session=session)
    if command == "/metrics":
        return render_metric_index(arguments, session=session)
    if command == "/artifacts":
        return render_artifact_index(arguments, session=session)
    raise ValueError(f"Unsupported index command: {command}")


def render_run_index(arguments: str = "", *, session: Any = None) -> str:
    """Render experiment runs recorded in the current CLI session."""

    if session is None:
        return "Experiment runs\n  no active session"

    events = _recorded_events(session, EXPERIMENT_RUN_RECORDED_EVENT)
    try:
        runs = project_experiment_runs(session.session_id, events)
    except ExperimentLedgerError as exc:
        raise IndexCommandError(f"Unable to render experiment runs: {exc}") from exc

    return render_run_records(arguments, runs=runs)


def render_run_records(
    arguments: str = "",
    *,
    runs: list[ExperimentRunRecord],
) -> str:
    """Render supplied experiment run records."""

    query = arguments.strip()
    if query:
        runs = [run for run in runs if _matches_run(query, run)]
    lines = ["Experiment runs"]
    if not runs:
        lines.append(_empty_line("runs", query))
        return "\n".join(lines)

    for run in runs:
        parts = [
            f"  {_safe_text(run.run_id)}",
            _safe_text(run.status),
            f"phase:{_safe_text(run.phase_id or '-')}",
            f"metrics:{_format_metrics(run.metrics)}",
        ]
        if run.runtime is not None:
            parts.append(f"runtime:{_safe_text(run.runtime.provider)}")
        if run.created_at:
            parts.append(f"created:{_safe_text(run.created_at)}")
        lines.append("  ".join(parts))
        lines.append(f"    hypothesis: {_safe_text(run.hypothesis)}")
    return "\n".join(lines)


def render_artifact_index(arguments: str = "", *, session: Any = None) -> str:
    """Render artifact refs recorded in the current CLI session."""

    if session is None:
        return "Artifacts\n  no active session"

    events = _recorded_events(session, ARTIFACT_REF_RECORDED_EVENT)
    try:
        artifacts = project_artifact_refs(session.session_id, events)
    except JobArtifactRefError as exc:
        raise IndexCommandError(f"Unable to render artifacts: {exc}") from exc

    return render_artifact_records(arguments, artifacts=artifacts)


def render_artifact_records(
    arguments: str = "",
    *,
    artifacts: list[ArtifactRefRecord],
) -> str:
    """Render supplied artifact ref records."""

    query = arguments.strip()
    if query:
        artifacts = [
            artifact for artifact in artifacts if _matches_artifact(query, artifact)
        ]
    lines = ["Artifacts"]
    if not artifacts:
        lines.append(_empty_line("artifacts", query))
        return "\n".join(lines)

    for artifact in artifacts:
        ref = artifact.ref_uri or artifact.uri or artifact.path or "-"
        parts = [
            f"  {_safe_text(artifact.artifact_id)}",
            _safe_text(artifact.type),
            f"source:{_safe_text(artifact.source)}",
            f"lifecycle:{_safe_text(artifact.lifecycle or '-')}",
            f"ref:{_safe_text(ref)}",
        ]
        if artifact.label:
            parts.append(f"label:{_safe_text(artifact.label)}")
        lines.append("  ".join(parts))
    return "\n".join(lines)


def render_run_detail(arguments: str = "", *, session: Any = None) -> str:
    """Render one experiment run recorded in the current CLI session."""

    run_id = arguments.strip()
    if not run_id:
        return "Experiment run\n  Usage: /run show <id>"
    if session is None:
        return "Experiment run\n  no active session"

    events = _recorded_events(session, EXPERIMENT_RUN_RECORDED_EVENT)
    try:
        runs = project_experiment_runs(session.session_id, events)
    except ExperimentLedgerError as exc:
        raise IndexCommandError(f"Unable to render experiment run: {exc}") from exc

    run = next((item for item in reversed(runs) if item.run_id == run_id), None)
    if run is None:
        return f"Experiment run\n  run not found: {_safe_text(run_id)}"

    return render_run_record_detail(run)


def render_run_record_detail(run: ExperimentRunRecord) -> str:
    """Render one supplied experiment run record."""

    lines = [
        f"Experiment run {_safe_text(run.run_id)}",
        f"  status: {_safe_text(run.status)}",
        f"  hypothesis: {_safe_text(run.hypothesis)}",
        f"  phase: {_safe_text(run.phase_id or '-')}",
        f"  created: {_safe_text(run.created_at or '-')}",
        f"  source event: {run.source_event_sequence or '-'}",
    ]
    if run.runtime is not None:
        runtime_parts = [_safe_text(run.runtime.provider)]
        if run.runtime.started_at:
            runtime_parts.append(f"started:{_safe_text(run.runtime.started_at)}")
        if run.runtime.ended_at:
            runtime_parts.append(f"ended:{_safe_text(run.runtime.ended_at)}")
        if run.runtime.duration_seconds is not None:
            runtime_parts.append(f"duration:{run.runtime.duration_seconds}s")
        lines.append(f"  runtime: {'  '.join(runtime_parts)}")
    else:
        lines.append("  runtime: -")

    lines.append(f"  config keys: {_format_mapping_keys(run.config)}")
    lines.extend(_format_run_metrics(run))
    lines.extend(_format_run_artifacts(run))
    lines.extend(_format_run_logs(run))
    lines.extend(_format_run_tracking_refs(run))
    return "\n".join(lines)


def render_metric_index(arguments: str = "", *, session: Any = None) -> str:
    """Render metrics recorded on current-session experiment runs."""

    if session is None:
        return "Metrics\n  no active session"

    events = _recorded_events(session, EXPERIMENT_RUN_RECORDED_EVENT)
    try:
        runs = project_experiment_runs(session.session_id, events)
    except ExperimentLedgerError as exc:
        raise IndexCommandError(f"Unable to render metrics: {exc}") from exc

    return render_metric_records(arguments, runs=runs)


def render_metric_records(
    arguments: str = "",
    *,
    runs: list[ExperimentRunRecord],
) -> str:
    """Render metrics attached to supplied experiment run records."""

    query = arguments.strip()
    metric_rows = [
        (run, metric)
        for run in runs
        for metric in run.metrics
        if not query or _matches_metric(query, run, metric)
    ]

    lines = ["Metrics"]
    if not metric_rows:
        lines.append(_empty_line("metrics", query))
        return "\n".join(lines)

    for run, metric in metric_rows:
        parts = [
            f"  {_safe_text(run.run_id)}",
            f"{_safe_text(metric.name)}={_safe_text(metric.value)}",
            f"source:{_safe_text(metric.source)}",
        ]
        if metric.step is not None:
            parts.append(f"step:{metric.step}")
        if metric.unit:
            parts.append(f"unit:{_safe_text(metric.unit)}")
        if metric.recorded_at:
            parts.append(f"recorded:{_safe_text(metric.recorded_at)}")
        lines.append("  ".join(parts))
    return "\n".join(lines)


def _recorded_events(session: Any, event_type: str) -> list[AgentEvent]:
    logged_events = list(getattr(session, "logged_events", []) or [])
    event_metadata = list(getattr(session, "event_metadata", []) or [])
    session_id = getattr(session, "session_id", None)
    if not session_id:
        raise IndexCommandError("Unable to render index: active session has no id")

    events: list[AgentEvent] = []
    for index, logged in enumerate(logged_events):
        if logged.get("event_type") != event_type:
            continue

        metadata = event_metadata[index] if index < len(event_metadata) else {}
        sequence = metadata.get("sequence")
        if not isinstance(sequence, int) or sequence < 1:
            sequence = len(events) + 1
        timestamp = _parse_timestamp(
            metadata.get("timestamp") or logged.get("timestamp")
        )
        event = AgentEvent(
            id=str(metadata.get("event_id") or f"session-event-{sequence}"),
            session_id=session_id,
            sequence=sequence,
            timestamp=timestamp,
            event_type=event_type,
            schema_version=int(metadata.get("schema_version") or 1),
            redaction_status=metadata.get("redaction_status") or "none",
            data=logged.get("data") or {},
        )
        events.append(event.redacted_copy())
    return events


def _matches_run(query: str, run: ExperimentRunRecord) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            run.run_id,
            run.status,
            run.phase_id,
            run.hypothesis,
            *(metric.name for metric in run.metrics),
        )
    )
    return query.lower() in haystack.lower()


def _matches_artifact(query: str, artifact: ArtifactRefRecord) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            artifact.artifact_id,
            artifact.type,
            artifact.source,
            artifact.lifecycle,
            artifact.ref_uri,
            artifact.uri,
            artifact.path,
            artifact.label,
        )
    )
    return query.lower() in haystack.lower()


def _matches_metric(query: str, run: ExperimentRunRecord, metric: Any) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in (
            run.run_id,
            run.status,
            run.phase_id,
            run.hypothesis,
            metric.name,
            metric.value,
            metric.source,
            metric.step,
            metric.unit,
            metric.recorded_at,
        )
    )
    return query.lower() in haystack.lower()


def _format_metrics(metrics: list[Any]) -> str:
    if not metrics:
        return "-"
    return ",".join(
        f"{_safe_text(metric.name)}={_safe_text(metric.value)}"
        for metric in metrics[:3]
    )


def _format_run_metrics(run: ExperimentRunRecord) -> list[str]:
    lines = ["  metrics:"]
    if not run.metrics:
        return lines + ["    -"]
    for metric in run.metrics:
        source = f" source:{_safe_text(metric.source)}" if metric.source else ""
        lines.append(
            f"    {_safe_text(metric.name)}: {_safe_text(metric.value)}{source}"
        )
    return lines


def _format_run_artifacts(run: ExperimentRunRecord) -> list[str]:
    lines = ["  artifacts:"]
    if not run.artifact_refs:
        return lines + ["    -"]
    for artifact in run.artifact_refs:
        ref = artifact.uri or artifact.digest or "-"
        lines.append(
            f"    {_safe_text(artifact.artifact_id)}  {_safe_text(artifact.type)}  "
            f"source:{_safe_text(artifact.source)}  ref:{_safe_text(ref)}"
        )
    return lines


def _format_run_logs(run: ExperimentRunRecord) -> list[str]:
    lines = ["  logs:"]
    if not run.log_refs:
        return lines + ["    -"]
    for log_ref in run.log_refs:
        lines.append(
            f"    {_safe_text(log_ref.log_id)}  {_safe_text(log_ref.source)}  "
            f"ref:{_safe_text(log_ref.uri or '-')}"
        )
    return lines


def _format_run_tracking_refs(run: ExperimentRunRecord) -> list[str]:
    lines = ["  tracking:"]
    if not run.external_tracking_refs:
        return lines + ["    -"]
    for ref in run.external_tracking_refs:
        uri = ref.uri or "-"
        lines.append(
            f"    {_safe_text(ref.tracking_id)}  {_safe_text(ref.provider)}  "
            f"uri:{_safe_text(uri)}"
        )
    return lines


def _format_mapping_keys(values: dict[str, Any]) -> str:
    if not values:
        return "-"
    return ",".join(sorted(_safe_key(key) for key in values))


def _empty_line(label: str, query: str) -> str:
    if query:
        return f"  no {label} match filter: {_safe_text(query)}"
    return f"  no {label} recorded for this session"


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _safe_text(value: Any) -> str:
    return redact_string(str(value)).value


def _safe_key(value: Any) -> str:
    text = str(value)
    if DEFAULT_REDACTION_POLICY.is_secret_key(text):
        return REDACTED
    return _safe_text(text)
