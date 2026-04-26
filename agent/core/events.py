from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


@dataclass
class Event:
    """Legacy event shape used by existing agent call sites."""

    event_type: str
    data: dict[str, Any] | None = None


class RedactionStatus(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    REDACTED = "redacted"


class EventPayload(BaseModel):
    """Base class for typed event payloads.

    Current UI payloads are still compatibility-first, so known payloads are
    validated for required fields while extra fields remain allowed.
    """

    model_config = ConfigDict(extra="allow")


class EmptyPayload(EventPayload):
    pass


class MessagePayload(EventPayload):
    message: str


class AssistantContentPayload(EventPayload):
    content: str


class ToolCallPayload(EventPayload):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str


class ToolOutputPayload(EventPayload):
    tool: str
    tool_call_id: str
    output: str
    success: bool


class ToolLogPayload(EventPayload):
    tool: str
    log: str
    agent_id: str | None = None
    label: str | None = None


class ApprovalToolPayload(EventPayload):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    tool_call_id: str


class ApprovalRequiredPayload(EventPayload):
    tools: list[ApprovalToolPayload]
    count: int


class ToolStateChangePayload(EventPayload):
    tool_call_id: str
    tool: str
    state: str
    jobUrl: str | None = None


class TurnCompletePayload(EventPayload):
    history_size: int


class CompactedPayload(EventPayload):
    old_tokens: int
    new_tokens: int


class ErrorPayload(EventPayload):
    error: str


class PlanItemPayload(EventPayload):
    id: str
    content: str
    status: str


class PlanUpdatePayload(EventPayload):
    plan: list[PlanItemPayload]


EVENT_PAYLOAD_MODELS: dict[str, type[EventPayload]] = {
    "ready": MessagePayload,
    "processing": MessagePayload,
    "assistant_message": AssistantContentPayload,
    "assistant_chunk": AssistantContentPayload,
    "assistant_stream_end": EmptyPayload,
    "tool_call": ToolCallPayload,
    "tool_output": ToolOutputPayload,
    "tool_log": ToolLogPayload,
    "approval_required": ApprovalRequiredPayload,
    "tool_state_change": ToolStateChangePayload,
    "turn_complete": TurnCompletePayload,
    "compacted": CompactedPayload,
    "error": ErrorPayload,
    "shutdown": EmptyPayload,
    "interrupted": EmptyPayload,
    "undo_complete": EmptyPayload,
    "plan_update": PlanUpdatePayload,
}


class AgentEvent(BaseModel):
    """Internal event envelope for queueing and future persistence."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    session_id: str
    sequence: int = Field(ge=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    event_type: str = Field(min_length=1)
    schema_version: int = Field(default=1, ge=1)
    redaction_status: RedactionStatus = RedactionStatus.NONE
    data: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_known_payload(self) -> AgentEvent:
        payload_model = EVENT_PAYLOAD_MODELS.get(self.event_type)
        if payload_model is None:
            return self
        payload = payload_model.model_validate(self.data or {})
        self.data = payload.model_dump(exclude_none=True)
        return self

    @classmethod
    def from_legacy(
        cls,
        event: Event,
        *,
        session_id: str,
        sequence: int,
    ) -> AgentEvent:
        return cls(
            session_id=session_id,
            sequence=sequence,
            event_type=event.event_type,
            data=event.data or {},
        )

    def to_legacy_sse(self) -> dict[str, Any]:
        """Serialize to the current SSE payload shape."""
        return {"event_type": self.event_type, "data": self.data}

    def to_legacy_dict(self) -> dict[str, Any]:
        """Alias for callers that do not need to know SSE naming."""
        return self.to_legacy_sse()
