from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.core.events import AgentEvent
from agent.core.tool_results import ToolResult
from backend.artifact_producers import (
    ArtifactRefAppendAdapter,
    artifact_ref_record_from_producer_metadata,
    artifact_ref_recorded_event_from_producer_metadata,
)
from backend.event_store import SQLiteEventStore
from backend.job_artifact_refs import artifact_ref_record_from_event
from backend.models import canonical_artifact_ref_uri


def test_recorded_event_factory_round_trips_local_path_artifact_ref():
    path = "/tmp/mlj-producer/no-scan/metrics.json"
    metadata = _metadata(
        artifact_id="artifact-local-event",
        source="local_path",
        locator={"type": "local_path", "path": path},
        path=path,
        digest="sha256:caller-supplied",
        size_bytes=123,
    )

    event = artifact_ref_recorded_event_from_producer_metadata(
        metadata,
        sequence=21,
        event_id="event-artifact-local",
    )
    record = artifact_ref_record_from_event(event)

    assert event.id == "event-artifact-local"
    assert event.session_id == "session-a"
    assert event.sequence == 21
    assert event.event_type == "artifact_ref.recorded"
    assert event.data["ref_uri"] == canonical_artifact_ref_uri(
        "session-a",
        "artifact-local-event",
    )
    assert record.ref_uri == event.data["ref_uri"]
    assert record.path == path
    assert record.uri is None
    assert record.digest == "sha256:caller-supplied"
    assert record.size_bytes == 123


@pytest.mark.parametrize(
    ("artifact_id", "source", "locator", "explicit_uri"),
    [
        (
            "artifact-sandbox-event",
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
            "artifact-hf-event",
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
    ],
)
def test_recorded_event_factory_round_trips_remote_locators(
    artifact_id,
    source,
    locator,
    explicit_uri,
):
    event = artifact_ref_recorded_event_from_producer_metadata(
        _metadata(
            artifact_id=artifact_id,
            source=source,
            locator=locator,
            uri=explicit_uri,
        ),
        sequence=22,
    )
    record = artifact_ref_record_from_event(event)

    assert event.data["ref_uri"] == canonical_artifact_ref_uri(
        "session-a",
        artifact_id,
    )
    assert record.source == source
    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True) == locator
    assert record.uri == explicit_uri


def test_recorded_event_factory_round_trips_event_ref_metadata():
    event = artifact_ref_recorded_event_from_producer_metadata(
        _metadata(
            artifact_id="artifact-event-ref-event",
            source="event_ref",
            locator={
                "type": "event_ref",
                "event_id": "event-tool-output-1",
                "sequence": 11,
            },
            producer={
                "source_event_sequence": 11,
                "tool_call_id": "tc-1",
                "tool": "writer",
            },
        ),
        sequence=23,
    )
    record = artifact_ref_record_from_event(event)

    assert record.ref_uri == canonical_artifact_ref_uri(
        "session-a",
        "artifact-event-ref-event",
    )
    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True) == {
        "type": "event_ref",
        "event_id": "event-tool-output-1",
        "sequence": 11,
    }
    assert record.source_event_sequence == 11
    assert record.path is None
    assert record.uri is None


def test_recorded_event_factory_rejects_session_mismatch():
    with pytest.raises(ValueError, match="session_id"):
        artifact_ref_recorded_event_from_producer_metadata(
            _metadata(
                artifact_id="artifact-session-mismatch",
                source="remote_uri",
                locator={"type": "remote_uri", "uri": "https://example.test/a.json"},
            ),
            sequence=24,
            session_id="session-b",
        )


def test_recorded_event_factory_rejects_invalid_event_sequence():
    with pytest.raises(ValidationError):
        artifact_ref_recorded_event_from_producer_metadata(
            _metadata(
                artifact_id="artifact-invalid-sequence",
                source="remote_uri",
                locator={"type": "remote_uri", "uri": "https://example.test/a.json"},
            ),
            sequence=0,
        )


def test_recorded_event_factory_does_not_copy_path_or_uri_from_locator():
    event = artifact_ref_recorded_event_from_producer_metadata(
        _metadata(
            artifact_id="artifact-no-compat-event",
            source="sandbox",
            locator={
                "type": "sandbox",
                "sandbox_id": "user/mlj-sandbox-2",
                "path": "/app/out/report.json",
                "uri": "sandbox://user/mlj-sandbox-2/app/out/report.json",
            },
        ),
        sequence=25,
    )
    record = artifact_ref_record_from_event(event)

    assert record.locator is not None
    assert record.locator.model_dump(exclude_none=True)["path"] == (
        "/app/out/report.json"
    )
    assert record.path is None
    assert record.uri is None


def test_recorded_event_factory_rejects_text_only_tool_output():
    result = ToolResult(
        display_text="wrote /tmp/metrics.json and https://example.test/model.pt",
        success=True,
    )

    with pytest.raises(ValidationError):
        artifact_ref_recorded_event_from_producer_metadata(
            result.model_dump(),
            sequence=26,
        )


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


def _make_memory_store() -> SQLiteEventStore:
    return SQLiteEventStore(":memory:")


def test_append_adapter_persists_artifact_ref_event() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)

    event = artifact_ref_recorded_event_from_producer_metadata(
        _metadata(
            artifact_id="artifact-append-1",
            source="local_path",
            locator={"type": "local_path", "path": "/tmp/metrics.json"},
        ),
        sequence=1,
    )

    stored = adapter.append(event)

    assert stored.session_id == event.session_id
    assert stored.sequence == event.sequence
    assert stored.event_type == "artifact_ref.recorded"

    replayed = store.replay("session-a")
    assert len(replayed) == 1
    assert replayed[0].sequence == 1
    assert replayed[0].event_type == "artifact_ref.recorded"


def test_append_adapter_redacts_before_persist() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)
    secret = "hf_supersecret_token_xyz"

    event = artifact_ref_recorded_event_from_producer_metadata(
        _metadata(
            artifact_id="artifact-append-redact",
            source="remote_uri",
            locator={
                "type": "remote_uri",
                "uri": f"https://example.test/model?token={secret}",
            },
            uri=f"https://example.test/model?token={secret}",
        ),
        sequence=1,
    )
    assert event.redaction_status == "none"

    stored = adapter.append(event)

    assert stored.redaction_status in ("partial", "redacted")
    assert secret not in repr(stored.data)
    replayed = store.replay("session-a")
    assert secret not in repr(replayed[0].data)


def test_append_adapter_preserves_ordering_evidence() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)

    adapter.append(
        artifact_ref_recorded_event_from_producer_metadata(
            _metadata(
                artifact_id="artifact-order-1",
                source="local_path",
                locator={"type": "local_path", "path": "/tmp/a.json"},
            ),
            sequence=1,
        )
    )
    adapter.append(
        artifact_ref_recorded_event_from_producer_metadata(
            _metadata(
                artifact_id="artifact-order-2",
                source="local_path",
                locator={"type": "local_path", "path": "/tmp/b.json"},
            ),
            sequence=2,
        )
    )

    replayed = store.replay("session-a")
    assert [e.sequence for e in replayed] == [1, 2]


def test_append_adapter_fails_closed_on_unsupported_event_type() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)

    bad_event = AgentEvent(
        session_id="session-a",
        sequence=1,
        event_type="tool.call",
        data={},
    )

    with pytest.raises(ValueError, match="unsupported artifact ref"):
        adapter.append(bad_event)

    assert store.replay("session-a") == []


def test_append_adapter_fails_closed_on_bad_sequence() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)

    event = AgentEvent.model_construct(
        session_id="session-a",
        sequence=0,
        event_type="artifact_ref.recorded",
        data={},
    )

    with pytest.raises(ValueError, match="sequence must be greater than or equal to 1"):
        adapter.append(event)

    assert store.replay("session-a") == []


def test_append_adapter_fails_closed_on_missing_session_id() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)

    event = AgentEvent.model_construct(
        session_id="",
        sequence=1,
        event_type="artifact_ref.recorded",
        data={},
    )

    with pytest.raises(ValueError, match="missing session_id"):
        adapter.append(event)

    assert store.replay("session-a") == []


def test_append_adapter_is_inert_without_explicit_call() -> None:
    store = _make_memory_store()
    adapter = ArtifactRefAppendAdapter(store.append)

    assert store.replay("session-a") == []
    # adapter exists but was never called
    assert store.replay("session-a") == []
