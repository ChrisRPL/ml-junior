"""Read-only CLI renderer for current-session ledger events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.core.events import AgentEvent
from agent.core.redaction import redact_string


class LedgerCommandError(RuntimeError):
    """Raised when current-session ledger events cannot be read safely."""


def render_ledger_command(
    command: str,
    arguments: str = "",
    *,
    session: Any = None,
) -> str:
    """Render a supported read-only ledger command for the current session."""

    if command == "/ledger":
        return render_ledger_index(arguments, session=session)
    raise ValueError(f"Unsupported ledger command: {command}")


def render_ledger_index(arguments: str = "", *, session: Any = None) -> str:
    """Render redacted event-envelope metadata from the current CLI session."""

    if session is None:
        return "Ledger\n  no active session"

    try:
        session_id = _session_id(session)
        events = _recorded_events(session, session_id)
    except Exception as exc:
        raise LedgerCommandError(f"Unable to render ledger: {exc}") from exc

    query = arguments.strip()
    if query:
        events = [event for event in events if _matches_event(query, event)]

    lines = ["Ledger"]
    if not events:
        lines.append(_empty_line(query))
        return "\n".join(lines)

    lines.append(f"  counts: events={len(events)}")
    for event in events:
        lines.extend(_format_event(event))
    return "\n".join(lines)


def _session_id(session: Any) -> str:
    session_id = getattr(session, "session_id", None)
    if not session_id:
        raise LedgerCommandError("active session has no id")
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
    return sorted(events, key=lambda event: event.sequence)


def _format_event(event: AgentEvent) -> list[str]:
    parts = [
        f"  {event.sequence}",
        _safe_text(event.id),
        _safe_text(event.event_type),
        f"redaction:{_safe_text(event.redaction_status)}",
        f"schema:{event.schema_version}",
    ]
    if event.timestamp:
        parts.append(f"at:{_safe_text(event.timestamp.isoformat())}")

    lines = ["  ".join(parts)]
    refs = _event_refs(event.data)
    if refs:
        lines.append(f"    refs: {'  '.join(refs)}")
    data_keys = _data_keys(event.data)
    if data_keys:
        lines.append(f"    data keys: {_safe_text(','.join(data_keys))}")
    return lines


def _event_refs(data: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key, label in (
        ("session_id", "session"),
        ("phase_id", "phase"),
        ("run_id", "run"),
        ("tool", "tool"),
        ("tool_call_id", "tool_call"),
        ("operation_id", "operation"),
        ("checkpoint_id", "checkpoint"),
        ("fork_point_id", "fork"),
        ("handoff_id", "handoff"),
        ("evidence_id", "evidence"),
        ("claim_id", "claim"),
        ("decision_id", "decision"),
        ("assumption_id", "assumption"),
        ("artifact_id", "artifact"),
        ("metric_id", "metric"),
        ("log_id", "log"),
        ("proof_bundle_id", "proof_bundle"),
        ("verdict_id", "verdict"),
    ):
        value = data.get(key)
        if value:
            refs.append(f"{label}:{_safe_text(value)}")
    return refs


def _data_keys(data: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in data.keys())


def _matches_event(query: str, event: AgentEvent) -> bool:
    needle = query.lower()
    return needle in " ".join(_flatten_strings(event.model_dump(mode="json"))).lower()


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [_safe_text(value)]
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
    return [_safe_text(value)]


def _empty_line(query: str) -> str:
    if query:
        return f"  no ledger events match filter: {_safe_text(query)}"
    return "  no ledger events recorded for this session"


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
