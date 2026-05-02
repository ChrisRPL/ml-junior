"""Read-only CLI handoff preview renderers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.core.events import AgentEvent
from agent.core.redaction import redact_string
from backend.project_continuity import generate_handoff_summary
from backend.workflow_state import build_workflow_state


class HandoffCommandError(RuntimeError):
    """Raised when current-session handoff preview cannot be projected safely."""


def render_handoff_command(
    command: str,
    arguments: str = "",
    *,
    session: Any = None,
) -> str:
    """Render a supported read-only handoff command for the current session."""

    if command == "/handoff preview":
        return render_handoff_preview(arguments, session=session)
    raise ValueError(f"Unsupported handoff command: {command}")


def render_handoff_preview(arguments: str = "", *, session: Any = None) -> str:
    """Render a stdout-only handoff preview from current-session events."""

    if arguments.strip():
        return "Handoff preview\n  Usage: /handoff preview"
    if session is None:
        return "Handoff preview\n  no active session"

    try:
        session_id = _session_id(session)
        events = _recorded_events(session, session_id)
        workflow_state = build_workflow_state(session_id=session_id, events=events)
        summary = generate_handoff_summary(
            workflow_state=workflow_state,
            events=events,
        )
    except Exception as exc:
        raise HandoffCommandError(f"Unable to render handoff preview: {exc}") from exc

    lines = [
        "Handoff preview",
        f"  session: {_safe_text(summary.session_id)}",
        f"  status: {_safe_text(workflow_state.status)}",
        f"  last event: {summary.source_event_sequence or 0}",
        f"  goal: {_safe_text(summary.goal or '-')}",
        f"  phase: {_format_phase(summary.current_phase)}",
        f"  next action: {_safe_text(summary.next_action)}",
        _counts_line(workflow_state, summary),
    ]
    decisions = _handoff_decisions(workflow_state, summary)
    evidence = _handoff_evidence(summary)
    artifacts = _handoff_artifacts(workflow_state, summary)
    lines.extend(_section("completed phases", summary.completed_phases, _format_phase_item))
    lines.extend(_section("blockers", workflow_state.blockers, _format_blocker))
    lines.extend(_section("pending approvals", workflow_state.pending_approvals, _format_approval))
    lines.extend(_section("active jobs", summary.jobs, _format_job))
    lines.extend(_section("decisions", decisions, _format_decision))
    lines.extend(_section("evidence", evidence, _format_evidence))
    lines.extend(_section("artifacts", artifacts, _format_artifact))
    lines.extend(_section("failures", summary.failures, _format_failure))
    lines.extend(_section("risks", summary.risks, _format_risk))
    return "\n".join(lines)


def _session_id(session: Any) -> str:
    session_id = getattr(session, "session_id", None)
    if not session_id:
        raise HandoffCommandError("active session has no id")
    return str(session_id)


def _recorded_events(session: Any, session_id: str) -> list[AgentEvent]:
    logged_events = list(getattr(session, "logged_events", []) or [])
    event_metadata = list(getattr(session, "event_metadata", []) or [])

    events: list[AgentEvent] = []
    for index, logged in enumerate(logged_events):
        if not isinstance(logged, dict):
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
            event_type=str(logged.get("event_type") or "unknown"),
            schema_version=int(metadata.get("schema_version") or 1),
            redaction_status=metadata.get("redaction_status") or "none",
            data=logged.get("data") or {},
        )
        events.append(event.redacted_copy())
    return events


def _counts_line(workflow_state: Any, summary: Any) -> str:
    evidence = _handoff_evidence(summary)
    decisions = _handoff_decisions(workflow_state, summary)
    artifacts = _handoff_artifacts(workflow_state, summary)
    return (
        "  counts: "
        f"completed_phases={len(summary.completed_phases)} "
        f"blockers={len(workflow_state.blockers)} "
        f"pending_approvals={len(workflow_state.pending_approvals)} "
        f"jobs={len(summary.jobs)} "
        f"decisions={len(decisions)} "
        f"evidence={len(evidence)} "
        f"artifacts={len(artifacts)} "
        f"failures={len(summary.failures)} "
        f"risks={len(summary.risks)}"
    )


def _handoff_decisions(workflow_state: Any, summary: Any) -> list[dict[str, Any]]:
    return _dedupe_rows(
        [
            *summary.decisions,
            *_evidence_summary_rows(workflow_state, "decision_id"),
        ],
        key_names=("decision_id", "id"),
    )


def _handoff_artifacts(workflow_state: Any, summary: Any) -> list[dict[str, Any]]:
    canonical_artifacts = [
        row
        for row in _evidence_summary_rows(workflow_state, "artifact_id")
        if not any(
            row.get(key)
            for key in (
                "evidence_id",
                "link_id",
                "decision_id",
                "proof_bundle_id",
                "verdict_id",
                "claim_id",
            )
        )
    ]
    return _dedupe_rows(
        [*summary.artifacts, *canonical_artifacts],
        key_names=("artifact_id", "id"),
    )


def _handoff_evidence(summary: Any) -> list[dict[str, Any]]:
    return [
        row
        for row in summary.evidence
        if not _is_dedicated_decision_or_artifact(row)
    ]


def _evidence_summary_rows(workflow_state: Any, id_key: str) -> list[dict[str, Any]]:
    summary = getattr(workflow_state, "evidence_summary", {}) or {}
    return [
        row
        for row in summary.get("items", [])
        if isinstance(row, dict) and row.get(id_key)
    ]


def _dedupe_rows(
    rows: list[dict[str, Any]],
    *,
    key_names: tuple[str, ...],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in rows:
        key = next((str(row[name]) for name in key_names if row.get(name)), repr(row))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _is_dedicated_decision_or_artifact(item: dict[str, Any]) -> bool:
    if item.get("decision_id"):
        return True
    return bool(
        item.get("artifact_id")
        and not any(
            item.get(key)
            for key in (
                "evidence_id",
                "link_id",
                "proof_bundle_id",
                "verdict_id",
                "claim_id",
            )
        )
    )


def _format_phase(phase: dict[str, Any] | None) -> str:
    if not phase:
        return "-"
    phase_id = _safe_text(phase.get("phase_id") or "-")
    status = _safe_text(phase.get("status") or "-")
    name = _safe_text(phase.get("phase_name") or phase_id)
    return f"{phase_id} ({name}, {status})"


def _format_phase_item(item: dict[str, Any]) -> str:
    phase_id = _safe_text(item.get("phase_id") or "-")
    name = _safe_text(item.get("phase_name") or phase_id)
    sequence = item.get("source_event_sequence") or "-"
    return f"{phase_id} ({name}) seq:{sequence}"


def _format_blocker(item: dict[str, Any]) -> str:
    parts = [
        _safe_text(item.get("type") or item.get("source") or "blocker"),
    ]
    if item.get("phase_id"):
        parts.append(f"phase:{_safe_text(item.get('phase_id'))}")
    missing = item.get("missing_outputs")
    if isinstance(missing, list) and missing:
        parts.append(f"missing:{_safe_text(','.join(str(value) for value in missing))}")
    return " ".join(parts)


def _format_job(item: dict[str, Any]) -> str:
    job_id = item.get("job_id") or item.get("tool_call_id") or "-"
    status = item.get("status") or "-"
    parts = [f"{_safe_text(job_id)} {_safe_text(status)}"]
    if item.get("tool"):
        parts.append(f"tool:{_safe_text(item.get('tool'))}")
    if item.get("provider"):
        parts.append(f"provider:{_safe_text(item.get('provider'))}")
    return " ".join(parts)


def _format_approval(item: dict[str, Any]) -> str:
    tool_call_id = item.get("tool_call_id") or item.get("approval_id") or "-"
    tool = item.get("tool") or "-"
    return f"{_safe_text(tool_call_id)} tool:{_safe_text(tool)}"


def _format_decision(item: dict[str, Any]) -> str:
    decision_id = item.get("decision_id") or item.get("id") or "-"
    text = item.get("decision") or item.get("text") or item.get("title") or "-"
    return f"{_safe_text(decision_id)} {_safe_text(text)}"


def _format_evidence(item: dict[str, Any]) -> str:
    for key in (
        "evidence_id",
        "link_id",
        "artifact_id",
        "metric_id",
        "log_id",
        "decision_id",
        "proof_bundle_id",
        "verdict_id",
        "claim_id",
    ):
        if item.get(key):
            label = key.removesuffix("_id")
            return f"{label}:{_safe_text(item.get(key))}"
    return _safe_text(item)


def _format_artifact(item: dict[str, Any]) -> str:
    artifact_id = item.get("artifact_id") or item.get("id") or "-"
    ref = item.get("ref_uri") or item.get("uri") or item.get("path")
    if ref:
        return f"{_safe_text(artifact_id)} ref:{_safe_text(ref)}"
    return _safe_text(artifact_id)


def _format_failure(item: dict[str, Any]) -> str:
    failure_id = item.get("failure_id") or item.get("phase_id") or item.get("type")
    status = item.get("status") or item.get("error") or "-"
    return f"{_safe_text(failure_id or 'failure')} {_safe_text(status)}"


def _format_risk(item: dict[str, Any]) -> str:
    risk_id = item.get("risk_id") or item.get("type") or item.get("source")
    status = item.get("status") or item.get("severity") or "-"
    return f"{_safe_text(risk_id or 'risk')} {_safe_text(status)}"


def _section(
    title: str,
    items: list[dict[str, Any]],
    formatter: Any,
    *,
    limit: int = 5,
) -> list[str]:
    lines = [f"  {title}:"]
    if not items:
        return lines + ["    -"]
    for item in items[:limit]:
        lines.append(f"    {formatter(item)}")
    remaining = len(items) - limit
    if remaining > 0:
        lines.append(f"    ... {remaining} more")
    return lines


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
