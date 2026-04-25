"""Reusable fakes for Phase 0 tests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class FakeChoice:
    message: Any
    finish_reason: str | None = "stop"


@dataclass
class FakeUsage:
    total_tokens: int = 17
    completion_tokens: int = 5


class FakeCompletion:
    """Minimal non-streaming LiteLLM response shape."""

    def __init__(
        self,
        message: Any,
        finish_reason: str | None = "stop",
        total_tokens: int = 17,
    ) -> None:
        self.choices = [FakeChoice(message=message, finish_reason=finish_reason)]
        self.usage = FakeUsage(total_tokens=total_tokens)
