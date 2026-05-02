"""Read-only CLI renderers for current-session evidence records."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.core.events import AgentEvent
from agent.core.redaction import redact_string
from backend.assumption_ledger import ASSUMPTION_RECORDED_EVENT
from backend.decision_proof_ledger import (
    DECISION_CARD_RECORDED_EVENT,
    PROOF_BUNDLE_RECORDED_EVENT,
)
from backend.evidence_ledger import (
    EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    EVIDENCE_ITEM_RECORDED_EVENT,
)
from backend.experiment_ledger import LOG_REF_RECORDED_EVENT, METRIC_RECORDED_EVENT
from backend.job_artifact_refs import ARTIFACT_REF_RECORDED_EVENT
from backend.verifier_ledger import VERIFIER_COMPLETED_EVENT
from backend.workflow_state import build_workflow_state


class EvidenceCommandError(RuntimeError):
    """Raised when current-session evidence cannot be projected safely."""


_EVIDENCE_SUMMARY_EVENT_TYPES = {
    ARTIFACT_REF_RECORDED_EVENT,
    ASSUMPTION_RECORDED_EVENT,
    DECISION_CARD_RECORDED_EVENT,
    EVIDENCE_CLAIM_LINK_RECORDED_EVENT,
    EVIDENCE_ITEM_RECORDED_EVENT,
    LOG_REF_RECORDED_EVENT,
    METRIC_RECORDED_EVENT,
    PROOF_BUNDLE_RECORDED_EVENT,
    VERIFIER_COMPLETED_EVENT,
}


def render_evidence_command(
    command: str,
    arguments: str = "",
    *,
    session: Any = None,
) -> str:
    """Render a supported read-only evidence command for the current session."""

    if command == "/evidence":
        return render_evidence_index(arguments, session=session)
    if command == "/decisions":
        return render_decision_index(arguments, session=session)
    if command == "/assumptions":
        return render_assumption_index(arguments, session=session)
    raise ValueError(f"Unsupported evidence command: {command}")


def render_evidence_index(arguments: str = "", *, session: Any = None) -> str:
    """Render explicit evidence records from the current CLI session."""

    if session is None:
        return "Evidence\n  no active session"

    try:
        session_id = _session_id(session)
        events = _recorded_evidence_events(session, session_id)
        state = build_workflow_state(session_id=session_id, events=events)
    except Exception as exc:
        raise EvidenceCommandError(f"Unable to render evidence: {exc}") from exc

    summary = state.evidence_summary
    items = [
        item
        for item in summary.get("items", [])
        if isinstance(item, dict)
    ]

    query = arguments.strip()
    if query:
        items = [item for item in items if _matches_item(query, item)]

    lines = ["Evidence"]
    if not items:
        lines.append(_empty_line(query))
        return "\n".join(lines)

    counts = _counts_line(summary)
    if counts:
        lines.append(counts)

    for item in items:
        lines.extend(_format_item(item))
    return "\n".join(lines)


def render_decision_index(arguments: str = "", *, session: Any = None) -> str:
    """Render decision-card records from the current CLI session."""

    if session is None:
        return "Decisions\n  no active session"

    try:
        session_id = _session_id(session)
        events = _recorded_evidence_events(session, session_id)
        state = build_workflow_state(session_id=session_id, events=events)
    except Exception as exc:
        raise EvidenceCommandError(f"Unable to render decisions: {exc}") from exc

    query = arguments.strip()
    decisions = [
        item
        for item in state.evidence_summary.get("items", [])
        if isinstance(item, dict) and _item_type(item) == "decision"
    ]
    if query:
        decisions = [item for item in decisions if _matches_item(query, item)]

    lines = ["Decisions"]
    if not decisions:
        lines.append(_empty_decision_line(query))
        return "\n".join(lines)

    lines.append(f"  counts: decisions={len(decisions)}")
    for item in decisions:
        lines.extend(_format_decision_item(item))
    return "\n".join(lines)


def render_assumption_index(arguments: str = "", *, session: Any = None) -> str:
    """Render assumption records from the current CLI session."""

    if session is None:
        return "Assumptions\n  no active session"

    try:
        session_id = _session_id(session)
        events = _recorded_evidence_events(session, session_id)
        state = build_workflow_state(session_id=session_id, events=events)
    except Exception as exc:
        raise EvidenceCommandError(f"Unable to render assumptions: {exc}") from exc

    query = arguments.strip()
    assumptions = [
        item
        for item in state.evidence_summary.get("items", [])
        if isinstance(item, dict) and _item_type(item) == "assumption"
    ]
    if query:
        assumptions = [item for item in assumptions if _matches_item(query, item)]

    lines = ["Assumptions"]
    if not assumptions:
        lines.append(_empty_assumption_line(query))
        return "\n".join(lines)

    lines.append(f"  counts: assumptions={len(assumptions)}")
    for item in assumptions:
        lines.extend(_format_assumption_item(item))
    return "\n".join(lines)


def _session_id(session: Any) -> str:
    session_id = getattr(session, "session_id", None)
    if not session_id:
        raise EvidenceCommandError("active session has no id")
    return str(session_id)


def _recorded_evidence_events(session: Any, session_id: str) -> list[AgentEvent]:
    logged_events = list(getattr(session, "logged_events", []) or [])
    event_metadata = list(getattr(session, "event_metadata", []) or [])

    events: list[AgentEvent] = []
    for index, logged in enumerate(logged_events):
        event_type = logged.get("event_type")
        if event_type not in _EVIDENCE_SUMMARY_EVENT_TYPES:
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
            event_type=str(event_type),
            schema_version=int(metadata.get("schema_version") or 1),
            redaction_status=metadata.get("redaction_status") or "none",
            data=logged.get("data") or {},
        )
        events.append(event.redacted_copy())
    return events


def _format_item(item: dict[str, Any]) -> list[str]:
    item_type = _item_type(item)
    parts = [f"  {item_type}:{_safe_text(_item_id(item))}"]

    if item_type == "claim_link":
        parts.extend(
            [
                _safe_text(item.get("relation") or "context"),
                f"claim:{_safe_text(item.get('claim_id'))}",
                f"evidence:{_safe_text(item.get('evidence_id'))}",
            ]
        )
        if item.get("strength"):
            parts.append(f"strength:{_safe_text(item.get('strength'))}")
    elif item_type == "evidence":
        parts.extend(
            [
                _safe_text(item.get("kind") or "evidence"),
                f"source:{_safe_text(item.get('source') or '-')}",
            ]
        )
    elif item_type == "metric":
        parts.extend(
            [
                f"{_safe_text(item.get('name') or 'metric')}="
                f"{_safe_text(_display_value(item.get('value')))}",
                f"source:{_safe_text(item.get('source') or '-')}",
            ]
        )
        if item.get("step") is not None:
            parts.append(f"step:{item.get('step')}")
        if item.get("unit"):
            parts.append(f"unit:{_safe_text(item.get('unit'))}")
    elif item_type == "artifact":
        parts.extend(
            [
                _safe_text(item.get("type") or "artifact"),
                f"source:{_safe_text(item.get('source') or '-')}",
            ]
        )
        ref = item.get("ref_uri") or item.get("uri") or item.get("path")
        if ref:
            parts.append(f"ref:{_safe_text(ref)}")
    elif item_type == "log":
        parts.append(f"source:{_safe_text(item.get('source') or '-')}")
        ref = item.get("uri") or item.get("label")
        if ref:
            parts.append(f"ref:{_safe_text(ref)}")
    elif item_type == "decision":
        parts.append(f"status:{_safe_text(item.get('status') or '-')}")
    elif item_type == "assumption":
        parts.extend(
            [
                f"status:{_safe_text(item.get('status') or '-')}",
                f"confidence:{_safe_text(item.get('confidence') or '-')}",
            ]
        )
    elif item_type == "proof_bundle":
        parts.append(f"status:{_safe_text(item.get('status') or '-')}")
    elif item_type == "verifier":
        parts.extend(
            [
                f"verdict:{_safe_text(item.get('verdict') or '-')}",
                f"verifier:{_safe_text(item.get('verifier_id') or '-')}",
            ]
        )

    for key in (
        "run_id",
        "metric_id",
        "artifact_id",
        "log_id",
        "dataset_snapshot_id",
        "code_snapshot_id",
        "event_id",
    ):
        if key == _item_id_key(item):
            continue
        if item.get(key):
            parts.append(f"{key[:-3]}:{_safe_text(item.get(key))}")
    if item.get("uri"):
        parts.append(f"uri:{_safe_text(item.get('uri'))}")

    lines = ["  ".join(parts)]
    for text_key in ("title", "summary", "statement", "rationale", "decision"):
        if item.get(text_key):
            lines.append(f"    {text_key}: {_safe_text(item.get(text_key))}")
    if item.get("validation_notes"):
        lines.append(f"    validation_notes: {_safe_text(item.get('validation_notes'))}")
    return lines


def _format_decision_item(item: dict[str, Any]) -> list[str]:
    parts = [
        f"  decision:{_safe_text(_item_id(item))}",
        f"status:{_safe_text(item.get('status') or '-')}",
    ]
    if item.get("source_event_sequence") is not None:
        parts.append(f"event:{_safe_text(item.get('source_event_sequence'))}")
    for key, label in (
        ("evidence_ids", "evidence"),
        ("claim_ids", "claims"),
        ("artifact_ids", "artifacts"),
        ("proof_bundle_ids", "proof_bundles"),
    ):
        values = _list_values(item.get(key))
        if values:
            parts.append(f"{label}:{_safe_text(','.join(values))}")

    lines = ["  ".join(parts)]
    for text_key in ("title", "decision", "rationale", "summary"):
        if item.get(text_key):
            lines.append(f"    {text_key}: {_safe_text(item.get(text_key))}")
    return lines


def _format_assumption_item(item: dict[str, Any]) -> list[str]:
    parts = [
        f"  assumption:{_safe_text(_item_id(item))}",
        f"status:{_safe_text(item.get('status') or '-')}",
        f"confidence:{_safe_text(item.get('confidence') or '-')}",
    ]
    if item.get("source_event_sequence") is not None:
        parts.append(f"event:{_safe_text(item.get('source_event_sequence'))}")
    if item.get("phase_id"):
        parts.append(f"phase:{_safe_text(item.get('phase_id'))}")
    if item.get("run_id"):
        parts.append(f"run:{_safe_text(item.get('run_id'))}")
    for key, label in (
        ("decision_ids", "decisions"),
        ("evidence_ids", "evidence"),
        ("claim_ids", "claims"),
        ("artifact_ids", "artifacts"),
        ("proof_bundle_ids", "proof_bundles"),
    ):
        values = _list_values(item.get(key))
        if values:
            parts.append(f"{label}:{_safe_text(','.join(values))}")

    lines = ["  ".join(parts)]
    for text_key in ("title", "statement", "rationale", "validation_notes"):
        if item.get(text_key):
            lines.append(f"    {text_key}: {_safe_text(item.get(text_key))}")
    return lines


def _item_type(item: dict[str, Any]) -> str:
    if item.get("link_id"):
        return "claim_link"
    if item.get("evidence_id") and item.get("kind"):
        return "evidence"
    if item.get("artifact_id"):
        return "artifact"
    if item.get("metric_id"):
        return "metric"
    if item.get("log_id"):
        return "log"
    if item.get("decision_id"):
        return "decision"
    if item.get("assumption_id"):
        return "assumption"
    if item.get("proof_bundle_id"):
        return "proof_bundle"
    if item.get("verdict_id"):
        return "verifier"
    return "item"


def _item_id(item: dict[str, Any]) -> str:
    key = _item_id_key(item)
    if key is not None:
        return str(item[key])
    return "-"


def _item_id_key(item: dict[str, Any]) -> str | None:
    for key in (
        "link_id",
        "evidence_id",
        "artifact_id",
        "metric_id",
        "log_id",
        "decision_id",
        "assumption_id",
        "proof_bundle_id",
        "verdict_id",
    ):
        value = item.get(key)
        if value:
            return key
    return None


def _display_value(value: Any) -> Any:
    if value is None:
        return "-"
    return value


def _list_values(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item) for item in value if item is not None]


def _counts_line(summary: dict[str, Any]) -> str:
    counts = {
        "evidence": int(summary.get("evidence_count") or 0),
        "claim_links": int(summary.get("claim_link_count") or 0),
        "artifacts": int(summary.get("artifact_count") or 0),
        "metrics": int(summary.get("metric_count") or 0),
        "logs": int(summary.get("log_count") or 0),
        "decisions": int(summary.get("decision_card_count") or 0),
        "assumptions": int(summary.get("assumption_count") or 0),
        "proof_bundles": int(summary.get("proof_bundle_count") or 0),
        "verifiers": int(summary.get("verifier_count") or 0),
    }
    visible = [f"{key}={value}" for key, value in counts.items() if value]
    if not visible:
        return ""
    return f"  counts: {' '.join(visible)}"


def _matches_item(query: str, item: dict[str, Any]) -> bool:
    needle = query.lower()
    return needle in " ".join(_flatten_strings(item)).lower()


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        values: list[str] = []
        for key, child in value.items():
            values.append(str(key))
            values.extend(_flatten_strings(child))
        return values
    if isinstance(value, (list, tuple)):
        values = []
        for child in value:
            values.extend(_flatten_strings(child))
        return values
    if value is None:
        return []
    return [str(value)]


def _empty_line(query: str) -> str:
    if query:
        return f"  no evidence match filter: {_safe_text(query)}"
    return "  no evidence recorded for this session"


def _empty_decision_line(query: str) -> str:
    if query:
        return f"  no decisions match filter: {_safe_text(query)}"
    return "  no decisions recorded for this session"


def _empty_assumption_line(query: str) -> str:
    if query:
        return f"  no assumptions match filter: {_safe_text(query)}"
    return "  no assumptions recorded for this session"


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
