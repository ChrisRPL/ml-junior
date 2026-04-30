from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.core.events import AgentEvent
from agent.core.tool_results import ToolResult
from backend.artifact_producers import artifact_ref_record_from_producer_metadata
from backend.models import canonical_artifact_ref_uri


def test_local_path_producer_metadata_builds_canonical_artifact_ref():
    path = "/tmp/mlj-producer/no-scan/metrics.json"
    metadata = _metadata(
        artifact_id="artifact-local",
        source="local_path",
        locator={"type": "local_path", "path": path},
        path=path,
        digest="sha256:caller-supplied",
        size_bytes=123,
    )

    record = artifact_ref_record_from_producer_metadata(metadata)

    assert record.ref_uri == canonical_artifact_ref_uri("session-a", "artifact-local")
    assert record.source == "local_path"
    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True) == {
        "type": "local_path",
        "path": path,
    }
    assert record.path == path
    assert record.uri is None
    assert record.digest == "sha256:caller-supplied"
    assert record.size_bytes == 123
    assert record.source_event_sequence == 7
    assert record.source_tool_call_id == "tc-1"
    assert record.source_job_id == "active-job-1"
    assert record.producer == {
        "source_event_sequence": 7,
        "tool_call_id": "tc-1",
        "job_id": "active-job-1",
        "tool": "train",
        "provider": "local",
    }


@pytest.mark.parametrize(
    ("artifact_id", "source", "locator", "explicit_uri"),
    [
        (
            "artifact-sandbox",
            "sandbox",
            {
                "type": "sandbox",
                "sandbox_id": "user/mlj-sandbox-1",
                "path": "/app/out/report.json",
                "uri": "sandbox://user/mlj-sandbox-1/app/out/report.json",
            },
            "sandbox://user/mlj-sandbox-1/app/out/report.json",
        ),
        (
            "artifact-hf",
            "hf_hub",
            {
                "type": "hf_hub",
                "repo_id": "org/model",
                "repo_type": "model",
                "revision": "abc123",
                "path": "eval_results.yaml",
                "uri": "hf-hub://model/org/model@abc123/eval_results.yaml",
            },
            "hf-hub://model/org/model@abc123/eval_results.yaml",
        ),
        (
            "artifact-remote",
            "remote_uri",
            {
                "type": "remote_uri",
                "uri": "https://artifacts.example.test/run/metrics.json",
            },
            "https://artifacts.example.test/run/metrics.json",
        ),
    ],
)
def test_remote_producer_metadata_preserves_typed_locator_and_explicit_uri(
    artifact_id,
    source,
    locator,
    explicit_uri,
):
    record = artifact_ref_record_from_producer_metadata(
        _metadata(
            artifact_id=artifact_id,
            source=source,
            locator=locator,
            uri=explicit_uri,
        )
    )

    assert record.ref_uri == canonical_artifact_ref_uri("session-a", artifact_id)
    assert record.source == source
    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True) == locator
    assert record.uri == explicit_uri
    assert record.path is None


def test_event_ref_producer_metadata_uses_explicit_event_identity_only():
    event = AgentEvent(
        id="event-tool-output-1",
        session_id="session-a",
        sequence=11,
        event_type="tool_output",
        data={
            "tool": "writer",
            "tool_call_id": "tc-1",
            "output": "created /tmp/should-not-be-inferred.json",
            "success": True,
        },
    )
    metadata = _metadata(
        artifact_id="artifact-event",
        source="event_ref",
        locator={
            "type": "event_ref",
            "event_id": event.id,
            "sequence": event.sequence,
        },
        producer={
            "source_event_sequence": event.sequence,
            "tool_call_id": "tc-1",
            "tool": "writer",
        },
    )

    record = artifact_ref_record_from_producer_metadata(metadata)

    assert record.ref_uri == canonical_artifact_ref_uri("session-a", "artifact-event")
    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True) == {
        "type": "event_ref",
        "event_id": "event-tool-output-1",
        "sequence": 11,
    }
    assert record.source_event_sequence == 11
    assert record.path is None
    assert record.uri is None


def test_compatibility_path_and_uri_are_not_copied_from_locator():
    record = artifact_ref_record_from_producer_metadata(
        _metadata(
            artifact_id="artifact-no-compat",
            source="sandbox",
            locator={
                "type": "sandbox",
                "sandbox_id": "user/mlj-sandbox-2",
                "path": "/app/out/report.json",
                "uri": "sandbox://user/mlj-sandbox-2/app/out/report.json",
            },
        )
    )

    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True)["path"] == (
        "/app/out/report.json"
    )
    assert record.path is None
    assert record.uri is None


@pytest.mark.parametrize("field", ["session_id", "artifact_id"])
def test_rejects_missing_session_or_artifact_identity(field):
    metadata = _metadata(
        artifact_id="artifact-missing",
        source="remote_uri",
        locator={"type": "remote_uri", "uri": "https://example.test/a.json"},
    )
    metadata.pop(field)

    with pytest.raises(ValidationError):
        artifact_ref_record_from_producer_metadata(metadata)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda metadata: metadata.update(
            {"ref_uri": canonical_artifact_ref_uri("session-b", "artifact-1")}
        ),
        lambda metadata: metadata.update(
            {
                "source": "remote_uri",
                "locator": {"type": "local_path", "path": "/tmp/out.json"},
            }
        ),
        lambda metadata: metadata.update(
            {
                "source_event_sequence": 8,
                "producer": {"source_event_sequence": 7, "tool_call_id": "tc-1"},
            }
        ),
        lambda metadata: metadata.update(
            {
                "source_tool_call_id": "tc-2",
                "producer": {"source_event_sequence": 7, "tool_call_id": "tc-1"},
            }
        ),
        lambda metadata: metadata.update(
            {
                "source_job_id": "active-job-2",
                "producer": {"source_event_sequence": 7, "job_id": "active-job-1"},
            }
        ),
    ],
)
def test_rejects_ambiguous_artifact_or_producer_identity(mutation):
    metadata = _metadata(
        artifact_id="artifact-1",
        source="remote_uri",
        locator={"type": "remote_uri", "uri": "https://example.test/a.json"},
    )
    mutation(metadata)

    with pytest.raises(ValidationError):
        artifact_ref_record_from_producer_metadata(metadata)


def test_rejects_text_only_tool_output_instead_of_inferring_artifacts():
    result = ToolResult(
        display_text="wrote /tmp/metrics.json and https://example.test/model.pt",
        success=True,
    )

    with pytest.raises(ValidationError):
        artifact_ref_record_from_producer_metadata(result.model_dump())


def _metadata(
    *,
    artifact_id: str,
    source: str,
    locator: dict,
    producer: dict | None = None,
    **overrides,
) -> dict:
    metadata = {
        "session_id": "session-a",
        "artifact_id": artifact_id,
        "type": "model_checkpoint",
        "source": source,
        "locator": locator,
        "producer": producer
        or {
            "source_event_sequence": 7,
            "tool_call_id": "tc-1",
            "job_id": "active-job-1",
            "tool": "train",
            "provider": "local",
        },
        "label": "Best checkpoint",
        "mime_type": "application/json",
        "metadata": {"caller": "unit-test"},
        "privacy_class": "private",
        "redaction_status": "none",
    }
    metadata.update(overrides)
    return metadata
