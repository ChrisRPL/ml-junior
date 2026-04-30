from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from agent.core.events import AgentEvent

try:
    from progress_detector_types import ProgressEventRef
except ModuleNotFoundError:
    from backend.progress_detector_types import ProgressEventRef


def event_refs(events: Sequence[AgentEvent]) -> list[ProgressEventRef]:
    return [event_ref(event) for event in events]


def event_ref(event: AgentEvent) -> ProgressEventRef:
    return ProgressEventRef(
        event_id=str(event.id),
        sequence=event.sequence,
        event_type=event.event_type,
        timestamp=datetime_to_string(event_datetime(event)),
    )


def event_datetime(event: AgentEvent | None) -> datetime | None:
    if event is None:
        return None
    return coerce_datetime(event.timestamp)


def coerce_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return ensure_timezone(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return ensure_timezone(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def elapsed_seconds(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds()))


def datetime_to_string(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def stable_json(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return repr(value)


def truncate(value: str, limit: int = 500) -> str:
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."
