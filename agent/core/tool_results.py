"""Structured tool results with legacy tuple compatibility."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ToolError(BaseModel):
    """Structured error detail for failed tool calls."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    message: str
    code: str | None = None
    kind: str = "error"
    retryable: bool | None = None
    raw: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_exception(cls, exc: BaseException) -> "ToolError":
        kind = "timeout" if _is_timeout_exception(exc) else "exception"
        return cls(
            message=str(exc),
            code=exc.__class__.__name__,
            kind=kind,
            raw=exc,
        )


class ArtifactRef(BaseModel):
    """Reference to an artifact produced by a tool."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    kind: str
    uri: str | None = None
    name: str | None = None
    mime_type: str | None = None
    display_text: str | None = None
    data: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetricRecord(BaseModel):
    """Named numeric or textual metric emitted by a tool."""

    name: str
    value: int | float | str | bool | None = None
    unit: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SideEffect(BaseModel):
    """Description of an externally visible action performed by a tool."""

    kind: str
    description: str
    target: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Structured result model that can still be exposed as `(str, bool)`."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    display_text: str = ""
    success: bool = True
    error: ToolError | None = None
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    metrics: list[MetricRecord] = Field(default_factory=list)
    side_effects: list[SideEffect] = Field(default_factory=list)
    raw: Any | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_legacy_tuple(self) -> tuple[str, bool]:
        return self.display_text, self.success

    @classmethod
    def from_error(
        cls,
        message: str,
        *,
        code: str | None = None,
        kind: str = "error",
        raw: Any | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ToolResult":
        error = ToolError(
            message=message,
            code=code,
            kind=kind,
            raw=raw,
            metadata=metadata or {},
        )
        return cls(
            display_text=message,
            success=False,
            error=error,
            raw=raw,
            metadata=metadata or {},
        )

    @classmethod
    def from_exception(
        cls,
        exc: BaseException,
        *,
        display_prefix: str | None = None,
    ) -> "ToolResult":
        error = ToolError.from_exception(exc)
        display_text = error.message
        if display_prefix:
            display_text = f"{display_prefix}: {display_text}"
        return cls(
            display_text=display_text,
            success=False,
            error=error,
            raw=exc,
        )


def tool_result_from_legacy_tuple(value: tuple[Any, Any]) -> ToolResult:
    output, success = value
    return ToolResult(display_text=str(output), success=bool(success), raw=value)


def tool_result_from_hf_dict(value: dict[str, Any]) -> ToolResult:
    display_text = str(value.get("formatted", ""))
    is_error = bool(value.get("isError", False))
    metrics = []
    for key in ("totalResults", "resultsShared"):
        if key in value:
            metrics.append(MetricRecord(name=key, value=value[key]))

    error = None
    if is_error:
        error = ToolError(message=display_text, code="hf_tool_error", kind="error")

    return ToolResult(
        display_text=display_text,
        success=not is_error,
        error=error,
        metrics=metrics,
        raw=value,
    )


def tool_result_from_mcp_content(
    content: list[Any],
    *,
    is_error: bool = False,
    converter: Callable[[list[Any]], str] | None = None,
    raw: Any | None = None,
) -> ToolResult:
    display_text = (
        converter(content) if converter else _mcp_content_to_display_text(content)
    )
    artifacts = _mcp_artifacts(content)
    error = None
    if is_error:
        error = ToolError(message=display_text, code="mcp_tool_error", kind="error")
    return ToolResult(
        display_text=display_text,
        success=not is_error,
        error=error,
        artifacts=artifacts,
        raw=raw if raw is not None else content,
    )


def normalize_tool_result(value: Any) -> ToolResult:
    if isinstance(value, ToolResult):
        return value
    if _is_legacy_tuple(value):
        return tool_result_from_legacy_tuple(value)
    if isinstance(value, dict) and "formatted" in value:
        return tool_result_from_hf_dict(value)
    return ToolResult(display_text=str(value), success=True, raw=value)


def _is_legacy_tuple(value: Any) -> bool:
    return isinstance(value, tuple) and len(value) == 2 and isinstance(value[1], bool)


def _is_timeout_exception(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in exc.__class__.__name__.lower()


def _mcp_content_to_display_text(content: list[Any]) -> str:
    if not content:
        return ""

    parts: list[str] = []
    for item in content:
        item_type = getattr(item, "type", None)
        if item_type == "text" and hasattr(item, "text"):
            parts.append(item.text)
        elif item_type == "image":
            parts.append(f"[Image: {getattr(item, 'mimeType', 'unknown')}]")
        elif item_type == "resource":
            resource = getattr(item, "resource", None)
            parts.append(_resource_display_text(resource))
        else:
            parts.append(str(item))
    return "\n".join(parts)


def _resource_display_text(resource: Any) -> str:
    if resource is None:
        return "[Resource: unknown]"
    text = getattr(resource, "text", None)
    if text:
        return text
    blob = getattr(resource, "blob", None)
    if blob:
        return f"[Binary data: {getattr(resource, 'mimeType', 'unknown')}]"
    return f"[Resource: {getattr(resource, 'uri', 'unknown')}]"


def _mcp_artifacts(content: list[Any]) -> list[ArtifactRef]:
    artifacts: list[ArtifactRef] = []
    for item in content:
        item_type = getattr(item, "type", None)
        if item_type == "image":
            artifacts.append(
                ArtifactRef(
                    kind="image",
                    mime_type=getattr(item, "mimeType", None),
                    display_text=f"[Image: {getattr(item, 'mimeType', 'unknown')}]",
                    data=getattr(item, "data", None),
                )
            )
        elif item_type == "resource":
            resource = getattr(item, "resource", None)
            artifacts.append(
                ArtifactRef(
                    kind="resource",
                    uri=str(getattr(resource, "uri", "")) or None,
                    mime_type=getattr(resource, "mimeType", None),
                    display_text=_resource_display_text(resource),
                    data=getattr(resource, "blob", None),
                )
            )
    return artifacts
