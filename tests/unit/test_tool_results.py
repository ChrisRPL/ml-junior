from __future__ import annotations

from mcp.types import EmbeddedResource, ImageContent, TextContent, TextResourceContents

from agent.core.tool_results import (
    ArtifactRef,
    MetricRecord,
    SideEffect,
    ToolResult,
    normalize_tool_result,
    tool_result_from_hf_dict,
    tool_result_from_legacy_tuple,
    tool_result_from_mcp_content,
)
from agent.core.tools import convert_mcp_content_to_string


def test_legacy_tuple_success_adapter_preserves_display_text_and_success():
    result = tool_result_from_legacy_tuple(("offline ok", True))

    assert result.display_text == "offline ok"
    assert result.success is True
    assert result.to_legacy_tuple() == ("offline ok", True)


def test_legacy_tuple_error_adapter_preserves_human_readable_error_output():
    result = tool_result_from_legacy_tuple(("bad input", False))

    assert result.display_text == "bad input"
    assert result.success is False
    assert result.to_legacy_tuple() == ("bad input", False)


def test_timeout_exception_creates_timeout_shaped_error_result():
    result = ToolResult.from_exception(TimeoutError("tool timed out"))

    assert result.success is False
    assert result.display_text == "tool timed out"
    assert result.error is not None
    assert result.error.kind == "timeout"
    assert result.error.code == "TimeoutError"


def test_tool_result_supports_artifacts_metrics_side_effects_and_metadata():
    result = ToolResult(
        display_text="uploaded model",
        success=True,
        artifacts=[
            ArtifactRef(
                kind="url",
                uri="https://huggingface.co/org/model",
                name="model",
            )
        ],
        metrics=[MetricRecord(name="files", value=3, unit="count")],
        side_effects=[
            SideEffect(
                kind="upload",
                description="Uploaded files to a model repository",
                target="org/model",
            )
        ],
        raw={"ok": True},
        metadata={"repo_id": "org/model"},
    )

    assert result.artifacts[0].uri == "https://huggingface.co/org/model"
    assert result.metrics[0].value == 3
    assert result.side_effects[0].target == "org/model"
    assert result.raw == {"ok": True}
    assert result.metadata == {"repo_id": "org/model"}


def test_hf_style_dict_adapter_maps_formatted_error_and_counts():
    result = tool_result_from_hf_dict(
        {
            "formatted": "No datasets found",
            "isError": True,
            "totalResults": 0,
            "resultsShared": 0,
        }
    )

    assert result.display_text == "No datasets found"
    assert result.success is False
    assert result.error is not None
    assert result.error.message == "No datasets found"
    assert [(metric.name, metric.value) for metric in result.metrics] == [
        ("totalResults", 0),
        ("resultsShared", 0),
    ]
    assert result.to_legacy_tuple() == ("No datasets found", False)


def test_normalize_tool_result_accepts_hf_style_dicts():
    result = normalize_tool_result(
        {"formatted": "Found 2 papers", "totalResults": 2, "resultsShared": 2}
    )

    assert result.display_text == "Found 2 papers"
    assert result.success is True
    assert [(metric.name, metric.value) for metric in result.metrics] == [
        ("totalResults", 2),
        ("resultsShared", 2),
    ]


def test_mcp_content_adapter_preserves_existing_text_image_resource_display():
    content = [
        TextContent(type="text", text="text block"),
        ImageContent(type="image", data="aW1hZ2U=", mimeType="image/png"),
        EmbeddedResource(
            type="resource",
            resource=TextResourceContents(
                uri="file:///tmp/result.txt",
                mimeType="text/plain",
                text="resource text",
            ),
        ),
    ]

    result = tool_result_from_mcp_content(
        content,
        converter=convert_mcp_content_to_string,
    )

    assert result.display_text == "text block\n[Image: image/png]\nresource text"
    assert result.display_text == convert_mcp_content_to_string(content)
    assert result.success is True
    assert [(artifact.kind, artifact.mime_type) for artifact in result.artifacts] == [
        ("image", "image/png"),
        ("resource", "text/plain"),
    ]
    assert result.artifacts[1].uri == "file:///tmp/result.txt"
