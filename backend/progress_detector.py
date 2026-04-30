from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from agent.core.events import AgentEvent

try:
    from models import WorkflowState
except ModuleNotFoundError:
    from backend.models import WorkflowState

try:
    from progress_detector_helpers import (
        coerce_datetime,
        datetime_to_string,
        elapsed_seconds,
        event_datetime,
        event_ref,
        event_refs,
        stable_json,
        truncate,
    )
    from progress_detector_types import (
        ACTIVE_PHASE_STATUSES,
        ACTIVE_WORKFLOW_STATUSES,
        ARTIFACT_EVENT_TYPES,
        FAILED_STATES,
        MATERIAL_PROGRESS_EVENT_TYPES,
        POLLING_STATES,
        POLLING_WORDS,
        ProgressDetectorReport,
        ProgressDetectorThresholds,
        ProgressFinding,
        ProgressFindingEvidence,
    )
except ModuleNotFoundError:
    from backend.progress_detector_helpers import (
        coerce_datetime,
        datetime_to_string,
        elapsed_seconds,
        event_datetime,
        event_ref,
        event_refs,
        stable_json,
        truncate,
    )
    from backend.progress_detector_types import (
        ACTIVE_PHASE_STATUSES,
        ACTIVE_WORKFLOW_STATUSES,
        ARTIFACT_EVENT_TYPES,
        FAILED_STATES,
        MATERIAL_PROGRESS_EVENT_TYPES,
        POLLING_STATES,
        POLLING_WORDS,
        ProgressDetectorReport,
        ProgressDetectorThresholds,
        ProgressFinding,
        ProgressFindingEvidence,
    )


def detect_progress_findings(
    *,
    workflow_state: WorkflowState,
    events: Sequence[AgentEvent],
    now: datetime | str | None = None,
    thresholds: ProgressDetectorThresholds | None = None,
) -> ProgressDetectorReport:
    """Return advisory progress/stuck findings without mutating runtime state."""

    detector_thresholds = thresholds or ProgressDetectorThresholds()
    ordered_events = _ordered_session_events(workflow_state.session_id, events)
    observed_at = (
        coerce_datetime(now)
        or _latest_event_datetime(ordered_events)
        or coerce_datetime(workflow_state.updated_at)
    )

    findings = [
        *_detect_repeated_identical_errors(ordered_events, detector_thresholds),
        *_detect_stale_no_artifact_progress(
            workflow_state,
            ordered_events,
            observed_at,
            detector_thresholds,
        ),
        *_detect_long_active_phase(
            workflow_state,
            observed_at,
            detector_thresholds,
        ),
        *_detect_polling_loop_signals(ordered_events, detector_thresholds),
    ]

    return ProgressDetectorReport(
        session_id=workflow_state.session_id,
        observed_at=datetime_to_string(observed_at),
        finding_count=len(findings),
        findings=findings,
    )


def _detect_repeated_identical_errors(
    events: Sequence[AgentEvent],
    thresholds: ProgressDetectorThresholds,
) -> list[ProgressFinding]:
    grouped: dict[str, list[tuple[AgentEvent, str]]] = {}
    for event in events:
        message = _error_message(event)
        if message is None:
            continue
        grouped.setdefault(_normalize_error(message), []).append((event, message))

    findings: list[ProgressFinding] = []
    for normalized_error, grouped_events in sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), item[1][0][0].sequence),
    ):
        if len(grouped_events) < thresholds.repeated_error_count:
            continue
        events_for_error = [event for event, _ in grouped_events]
        first_message = grouped_events[0][1]
        findings.append(
            ProgressFinding(
                kind="repeated_identical_error",
                title="Repeated identical error",
                summary=(
                    "The same error text appeared "
                    f"{len(grouped_events)} times in the supplied events."
                ),
                evidence=[
                    ProgressFindingEvidence(
                        source="event",
                        summary="Repeated error events share the same normalized text.",
                        event_refs=event_refs(events_for_error),
                        details={
                            "count": len(grouped_events),
                            "normalized_error": normalized_error,
                            "message": truncate(first_message),
                            "event_types": sorted(
                                {event.event_type for event in events_for_error}
                            ),
                        },
                    )
                ],
                recommended_next_action=(
                    "Stop retrying the exact same step; inspect the repeated error "
                    "and change the failing input, tool call, or implementation "
                    "before trying again."
                ),
            )
        )
    return findings


def _detect_stale_no_artifact_progress(
    workflow_state: WorkflowState,
    events: Sequence[AgentEvent],
    observed_at: datetime | None,
    thresholds: ProgressDetectorThresholds,
) -> list[ProgressFinding]:
    if observed_at is None or not _workflow_is_active(workflow_state):
        return []

    active_since = _active_since(workflow_state, events)
    if active_since is None:
        return []

    last_material_progress = _last_event_of_type(events, MATERIAL_PROGRESS_EVENT_TYPES)
    last_artifact = _last_event_of_type(events, ARTIFACT_EVENT_TYPES)
    progress_reference = event_datetime(last_material_progress) or active_since
    seconds_without_progress = elapsed_seconds(progress_reference, observed_at)
    active_seconds = elapsed_seconds(active_since, observed_at)
    artifact_count = _artifact_count(workflow_state, events)

    if (
        seconds_without_progress < thresholds.stale_progress_seconds
        and not (
            artifact_count == 0
            and active_seconds >= thresholds.stale_progress_seconds
        )
    ):
        return []

    event_refs = []
    if last_material_progress is not None:
        event_refs.append(event_ref(last_material_progress))
    if last_artifact is not None and last_artifact != last_material_progress:
        event_refs.append(event_ref(last_artifact))
    latest_event = events[-1] if events else None
    if (
        latest_event is not None
        and latest_event is not last_material_progress
        and latest_event is not last_artifact
    ):
        event_refs.append(event_ref(latest_event))

    return [
        ProgressFinding(
            kind="stale_no_artifact_progress",
            title="Stale or no-artifact progress",
            summary=(
                "The workflow is active, but supplied events show no recent "
                "material progress or no recorded artifacts."
            ),
            evidence=[
                ProgressFindingEvidence(
                    source="derived",
                    summary="Active workflow age exceeds the stale progress threshold.",
                    event_refs=event_refs,
                    details={
                        "active_since": datetime_to_string(active_since),
                        "observed_at": datetime_to_string(observed_at),
                        "active_seconds": active_seconds,
                        "seconds_without_progress": seconds_without_progress,
                        "artifact_count": artifact_count,
                        "last_material_progress_sequence": (
                            last_material_progress.sequence
                            if last_material_progress is not None
                            else None
                        ),
                        "last_artifact_sequence": (
                            last_artifact.sequence if last_artifact is not None else None
                        ),
                        "threshold_seconds": thresholds.stale_progress_seconds,
                    },
                )
            ],
            recommended_next_action=(
                "Record a concrete artifact, metric, or log if work is advancing; "
                "otherwise reassess the active step before continuing."
            ),
        )
    ]


def _detect_long_active_phase(
    workflow_state: WorkflowState,
    observed_at: datetime | None,
    thresholds: ProgressDetectorThresholds,
) -> list[ProgressFinding]:
    if observed_at is None or workflow_state.phase.status != "active":
        return []

    started_at = coerce_datetime(workflow_state.phase.started_at)
    if started_at is None:
        return []

    active_seconds = elapsed_seconds(started_at, observed_at)
    if active_seconds < thresholds.long_active_phase_seconds:
        return []

    return [
        ProgressFinding(
            kind="long_active_phase",
            title="Long active phase",
            summary="The current phase has remained active beyond the threshold.",
            evidence=[
                ProgressFindingEvidence(
                    source="workflow",
                    summary="Workflow phase status is active for a long duration.",
                    details={
                        "phase_id": workflow_state.phase.id,
                        "phase_label": workflow_state.phase.label,
                        "started_at": workflow_state.phase.started_at,
                        "observed_at": datetime_to_string(observed_at),
                        "active_seconds": active_seconds,
                        "threshold_seconds": thresholds.long_active_phase_seconds,
                    },
                )
            ],
            recommended_next_action=(
                "Review expected outputs for the active phase; split it, mark it "
                "blocked with evidence, or move to the next phase if complete."
            ),
        )
    ]


def _detect_polling_loop_signals(
    events: Sequence[AgentEvent],
    thresholds: ProgressDetectorThresholds,
) -> list[ProgressFinding]:
    grouped: dict[str, list[tuple[AgentEvent, str]]] = {}
    for event in events:
        signal = _polling_signal(event)
        if signal is None:
            continue
        signature, label = signal
        grouped.setdefault(signature, []).append((event, label))

    findings: list[ProgressFinding] = []
    for signature, grouped_events in sorted(
        grouped.items(),
        key=lambda item: (-len(item[1]), item[1][0][0].sequence),
    ):
        if len(grouped_events) < thresholds.polling_signal_count:
            continue
        signal_events = [event for event, _ in grouped_events]
        if _has_material_progress_between(events, signal_events[0], signal_events[-1]):
            continue
        findings.append(
            ProgressFinding(
                kind="polling_loop_signal",
                title="Polling loop signal",
                summary=(
                    "Repeated polling-like events occurred without material "
                    "progress between them."
                ),
                evidence=[
                    ProgressFindingEvidence(
                        source="event",
                        summary=grouped_events[0][1],
                        event_refs=event_refs(signal_events),
                        details={
                            "count": len(grouped_events),
                            "signature": signature,
                            "threshold_count": thresholds.polling_signal_count,
                            "first_sequence": signal_events[0].sequence,
                            "last_sequence": signal_events[-1].sequence,
                        },
                    )
                ],
                recommended_next_action=(
                    "Replace repeated status checks with a bounded wait, inspect "
                    "the underlying job state, or ask the user whether to continue."
                ),
            )
        )
    return findings


def _ordered_session_events(
    session_id: str,
    events: Sequence[AgentEvent],
) -> list[AgentEvent]:
    seen_ids: set[str] = set()
    seen_sequences: set[int] = set()
    ordered: list[AgentEvent] = []
    for event in sorted(
        [event for event in events if event.session_id == session_id],
        key=lambda item: (item.sequence, str(item.id)),
    ):
        if event.id in seen_ids or event.sequence in seen_sequences:
            continue
        seen_ids.add(event.id)
        seen_sequences.add(event.sequence)
        ordered.append(event)
    return ordered


def _workflow_is_active(workflow_state: WorkflowState) -> bool:
    return (
        workflow_state.status in ACTIVE_WORKFLOW_STATUSES
        or workflow_state.phase.status in ACTIVE_PHASE_STATUSES
        or bool(workflow_state.active_jobs)
    )


def _active_since(
    workflow_state: WorkflowState,
    events: Sequence[AgentEvent],
) -> datetime | None:
    phase_started_at = coerce_datetime(workflow_state.phase.started_at)
    if phase_started_at is not None:
        return phase_started_at

    for event in events:
        if event.event_type in {"processing", "phase.started", "tool_call"}:
            timestamp = event_datetime(event)
            if timestamp is not None:
                return timestamp
    return coerce_datetime(workflow_state.updated_at)


def _artifact_count(
    workflow_state: WorkflowState,
    events: Sequence[AgentEvent],
) -> int:
    event_artifact_count = sum(
        1 for event in events if event.event_type in ARTIFACT_EVENT_TYPES
    )
    summary = workflow_state.evidence_summary
    summary_artifact_count = summary.get("artifact_count")
    if isinstance(summary_artifact_count, int):
        return max(event_artifact_count, summary_artifact_count)
    return event_artifact_count


def _last_event_of_type(
    events: Sequence[AgentEvent],
    event_types: set[str],
) -> AgentEvent | None:
    for event in reversed(events):
        if event.event_type in event_types:
            return event
    return None


def _latest_event_datetime(events: Sequence[AgentEvent]) -> datetime | None:
    for event in reversed(events):
        timestamp = event_datetime(event)
        if timestamp is not None:
            return timestamp
    return None


def _error_message(event: AgentEvent) -> str | None:
    data = event.data or {}
    if event.event_type == "error":
        return _first_text(data, ("error", "message", "detail"))

    if event.event_type == "tool_output" and data.get("success") is False:
        return _first_text(data, ("error", "message", "output"))

    if event.event_type == "tool_state_change":
        state = str(data.get("state") or data.get("status") or "").strip().lower()
        if state in FAILED_STATES:
            return _first_text(data, ("error", "message", "detail")) or state

    return None


def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_error(message: str) -> str:
    return re.sub(r"\s+", " ", message.strip()).casefold()


def _polling_signal(event: AgentEvent) -> tuple[str, str] | None:
    data = event.data or {}
    tool = str(data.get("tool") or "unknown").strip() or "unknown"

    if event.event_type == "tool_state_change":
        state = str(data.get("state") or data.get("status") or "").strip().lower()
        if state not in POLLING_STATES:
            return None
        target = str(data.get("job_id") or data.get("tool_call_id") or tool)
        return (
            f"tool_state_change:{tool}:{target}:{state}",
            f"Repeated {state} state changes for {tool}.",
        )

    if event.event_type != "tool_call":
        return None

    arguments = data.get("arguments")
    normalized_arguments = arguments if isinstance(arguments, dict) else {}
    combined = f"{tool} {stable_json(normalized_arguments)}".casefold()
    if not any(word in combined for word in POLLING_WORDS):
        return None

    return (
        f"tool_call:{tool}:{stable_json(normalized_arguments)}",
        f"Repeated polling-like calls for {tool}.",
    )

def _has_material_progress_between(
    all_events: Sequence[AgentEvent],
    first_event: AgentEvent,
    last_event: AgentEvent,
) -> bool:
    for event in all_events:
        if first_event.sequence < event.sequence < last_event.sequence:
            if event.event_type in MATERIAL_PROGRESS_EVENT_TYPES:
                return True
    return False
