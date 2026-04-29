from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from agent.core.events import AgentEvent
from backend.phase_gates import PhaseTransitionResult


PHASE_EVENT_TYPES = frozenset(
    {
        "phase.not_started",
        "phase.pending",
        "phase.started",
        "phase.blocked",
        "phase.completed",
        "phase.failed",
        "phase.verified",
    }
)


class PhaseEventPersistenceError(ValueError):
    """Raised when planned phase event payloads cannot be persisted."""


class PhaseEventSink(Protocol):
    """Durable event sink for pre-sequenced phase AgentEvents."""

    def append_many(self, events: Sequence[AgentEvent]) -> Sequence[AgentEvent]:
        """Persist event envelopes atomically and return stored copies."""


def phase_transition_agent_events(
    result: PhaseTransitionResult,
    *,
    start_sequence: int,
) -> tuple[AgentEvent, ...]:
    """Convert pure phase transition payloads into pre-sequenced AgentEvents."""
    if start_sequence < 1:
        raise PhaseEventPersistenceError("start_sequence must be >= 1")

    session_id: str | None = None
    events: list[AgentEvent] = []
    for offset, raw_event in enumerate(result.events):
        event_type = raw_event.get("event_type")
        if event_type not in PHASE_EVENT_TYPES:
            raise PhaseEventPersistenceError(f"Unsupported phase event: {event_type}")

        data = raw_event.get("data")
        if not isinstance(data, Mapping):
            raise PhaseEventPersistenceError("Phase event data must be a mapping")

        event_session_id = data.get("session_id")
        if event_session_id is None:
            raise PhaseEventPersistenceError("Phase event data missing session_id")
        event_session_id = str(event_session_id)
        if session_id is None:
            session_id = event_session_id
        elif session_id != event_session_id:
            raise PhaseEventPersistenceError("Phase events must share one session_id")

        events.append(
            AgentEvent(
                session_id=event_session_id,
                sequence=start_sequence + offset,
                event_type=str(event_type),
                data=dict(data),
            )
        )

    return tuple(events)


def persist_phase_transition_events(
    event_sink: PhaseEventSink,
    result: PhaseTransitionResult,
    *,
    start_sequence: int,
) -> tuple[AgentEvent, ...]:
    """Persist planned phase transition events through a durable event sink."""
    events = phase_transition_agent_events(result, start_sequence=start_sequence)
    return tuple(event_sink.append_many(events))
