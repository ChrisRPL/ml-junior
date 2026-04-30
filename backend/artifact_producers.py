"""Pure adapter contract for explicit artifact producer metadata."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.models import (
    ArtifactLocator,
    ArtifactRefRecord,
    NonEmptyStr,
    canonical_artifact_ref_uri,
)


ArtifactProducerSource = Literal[
    "local_path",
    "sandbox",
    "hf_hub",
    "remote_uri",
    "event_ref",
]


class ArtifactProducerMetadata(BaseModel):
    """Explicit producer metadata accepted by the artifact adapter.

    The adapter does not inspect tool text, files, providers, or remote storage.
    Callers must provide the durable artifact identity and typed locator.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    source_event_sequence: int | None = Field(default=None, ge=1)
    tool_call_id: NonEmptyStr | None = None
    job_id: NonEmptyStr | None = None
    tool: NonEmptyStr | None = None
    provider: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_empty_producer_metadata(self) -> ArtifactProducerMetadata:
        if (
            self.source_event_sequence is None
            and self.tool_call_id is None
            and self.job_id is None
            and self.tool is None
            and self.provider is None
            and not self.metadata
        ):
            raise ValueError("producer metadata must not be empty")
        return self


class ArtifactProducerRefSpec(BaseModel):
    """Closed input shape for producer-supplied artifact metadata."""

    model_config = ConfigDict(extra="forbid", strict=True)

    session_id: NonEmptyStr
    artifact_id: NonEmptyStr
    source_event_sequence: int | None = Field(default=None, ge=1)
    type: NonEmptyStr
    source: ArtifactProducerSource
    locator: ArtifactLocator
    ref_uri: NonEmptyStr | None = None
    lifecycle: Literal[
        "planned",
        "recorded",
        "available",
        "consumed",
        "archived",
        "deleted",
        "unknown",
    ] | None = "recorded"
    mime_type: NonEmptyStr | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    producer: ArtifactProducerMetadata | None = None
    export_policy: dict[str, Any] | None = None
    source_tool_call_id: NonEmptyStr | None = None
    source_job_id: NonEmptyStr | None = None
    path: NonEmptyStr | None = None
    uri: NonEmptyStr | None = None
    digest: NonEmptyStr | None = None
    label: NonEmptyStr | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    privacy_class: Literal["public", "private", "sensitive", "unknown"] = "unknown"
    redaction_status: Literal["none", "partial", "redacted"] = "none"
    created_at: NonEmptyStr | None = None

    @model_validator(mode="after")
    def reject_ambiguous_identity_or_producer(self) -> ArtifactProducerRefSpec:
        canonical_ref_uri = canonical_artifact_ref_uri(
            self.session_id,
            self.artifact_id,
        )
        if self.ref_uri is not None and self.ref_uri != canonical_ref_uri:
            raise ValueError("ref_uri must match session_id and artifact_id")

        locator_type = getattr(self.locator, "type", None)
        if locator_type != self.source:
            raise ValueError("source must match locator.type")

        if self.producer is None:
            return self

        if (
            self.source_event_sequence is not None
            and self.producer.source_event_sequence is not None
            and self.source_event_sequence != self.producer.source_event_sequence
        ):
            raise ValueError(
                "source_event_sequence conflicts with producer.source_event_sequence"
            )
        if (
            self.source_tool_call_id is not None
            and self.producer.tool_call_id is not None
            and self.source_tool_call_id != self.producer.tool_call_id
        ):
            raise ValueError("source_tool_call_id conflicts with producer.tool_call_id")
        if (
            self.source_job_id is not None
            and self.producer.job_id is not None
            and self.source_job_id != self.producer.job_id
        ):
            raise ValueError("source_job_id conflicts with producer.job_id")
        return self


def artifact_ref_record_from_producer_metadata(
    metadata: Mapping[str, Any] | ArtifactProducerRefSpec,
) -> ArtifactRefRecord:
    """Build an ArtifactRefRecord from explicit producer metadata only."""

    spec = (
        metadata
        if isinstance(metadata, ArtifactProducerRefSpec)
        else ArtifactProducerRefSpec.model_validate(metadata)
    )
    producer = (
        spec.producer.model_dump(
            mode="json",
            exclude_defaults=True,
            exclude_none=True,
        )
        if spec.producer
        else None
    )
    source_event_sequence = spec.source_event_sequence
    source_tool_call_id = spec.source_tool_call_id
    source_job_id = spec.source_job_id
    if spec.producer is not None:
        source_event_sequence = (
            source_event_sequence
            if source_event_sequence is not None
            else spec.producer.source_event_sequence
        )
        source_tool_call_id = (
            source_tool_call_id
            if source_tool_call_id is not None
            else spec.producer.tool_call_id
        )
        source_job_id = (
            source_job_id if source_job_id is not None else spec.producer.job_id
        )

    return ArtifactRefRecord.model_validate(
        {
            "session_id": spec.session_id,
            "artifact_id": spec.artifact_id,
            "source_event_sequence": source_event_sequence,
            "type": spec.type,
            "source": spec.source,
            "ref_uri": canonical_artifact_ref_uri(spec.session_id, spec.artifact_id),
            "locator": spec.locator.model_dump(mode="json", exclude_none=True),
            "lifecycle": spec.lifecycle,
            "mime_type": spec.mime_type,
            "size_bytes": spec.size_bytes,
            "producer": producer,
            "export_policy": spec.export_policy,
            "source_tool_call_id": source_tool_call_id,
            "source_job_id": source_job_id,
            "path": spec.path,
            "uri": spec.uri,
            "digest": spec.digest,
            "label": spec.label,
            "metadata": spec.metadata,
            "privacy_class": spec.privacy_class,
            "redaction_status": spec.redaction_status,
            "created_at": spec.created_at,
        }
    )
