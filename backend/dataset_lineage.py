from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

DatasetFileChangeType = Literal["added", "removed", "modified", "unchanged"]


class DatasetLineageModel(BaseModel):
    """Closed-schema base for inert caller-supplied dataset lineage records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DatasetExamplePolicy(DatasetLineageModel):
    """Records example handling without carrying raw dataset examples."""

    status: Literal["omitted", "redacted"] = "omitted"
    reason: NonEmptyStr = "sensitive_by_default"


class DatasetManifestFile(DatasetLineageModel):
    """Metadata for one caller-supplied dataset file."""

    path: NonEmptyStr
    size_bytes: int = Field(ge=0)
    digest: NonEmptyStr | None = None
    media_type: NonEmptyStr | None = None
    record_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    example_policy: DatasetExamplePolicy = Field(default_factory=DatasetExamplePolicy)


class DatasetManifest(DatasetLineageModel):
    """Caller-supplied dataset manifest; no files are discovered or read here."""

    manifest_id: NonEmptyStr
    dataset_id: NonEmptyStr | None = None
    snapshot_id: NonEmptyStr | None = None
    source: Literal["caller_supplied"] = "caller_supplied"
    files: list[DatasetManifestFile] = Field(default_factory=list)
    privacy_class: Literal["public", "private", "sensitive", "unknown"] = "unknown"
    redaction_status: Literal["none", "partial", "redacted"] = "redacted"
    metadata: dict[str, Any] = Field(default_factory=dict)
    example_policy: DatasetExamplePolicy = Field(default_factory=DatasetExamplePolicy)

    @model_validator(mode="after")
    def _reject_duplicate_file_paths(self) -> Self:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for file in self.files:
            if file.path in seen:
                duplicates.add(file.path)
            seen.add(file.path)
        if duplicates:
            paths = ", ".join(sorted(duplicates))
            raise ValueError(
                f"dataset manifest contains duplicate file paths: {paths}"
            )
        return self


class DatasetManifestSizeStats(DatasetLineageModel):
    file_count: int = Field(ge=0)
    total_size_bytes: int = Field(ge=0)


class DatasetManifestChangeStats(DatasetLineageModel):
    file_count: int = Field(ge=0)
    before_size_bytes: int = Field(ge=0)
    after_size_bytes: int = Field(ge=0)
    size_delta_bytes: int

    @model_validator(mode="after")
    def _validate_delta(self) -> Self:
        expected = self.after_size_bytes - self.before_size_bytes
        if self.size_delta_bytes != expected:
            raise ValueError(
                "size_delta_bytes must equal after_size_bytes - before_size_bytes"
            )
        return self


class DatasetManifestDiffStats(DatasetLineageModel):
    before: DatasetManifestSizeStats
    after: DatasetManifestSizeStats
    added: DatasetManifestChangeStats
    removed: DatasetManifestChangeStats
    modified: DatasetManifestChangeStats
    unchanged: DatasetManifestChangeStats
    total_size_delta_bytes: int

    @model_validator(mode="after")
    def _validate_total_delta(self) -> Self:
        expected = self.after.total_size_bytes - self.before.total_size_bytes
        if self.total_size_delta_bytes != expected:
            raise ValueError(
                "total_size_delta_bytes must equal after.total_size_bytes - "
                "before.total_size_bytes"
            )
        return self


class DatasetManifestFileDiff(DatasetLineageModel):
    change_type: DatasetFileChangeType
    path: NonEmptyStr
    before: DatasetManifestFile | None = None
    after: DatasetManifestFile | None = None
    size_delta_bytes: int

    @model_validator(mode="after")
    def _validate_change_shape(self) -> Self:
        before_size = self.before.size_bytes if self.before is not None else 0
        after_size = self.after.size_bytes if self.after is not None else 0
        expected_delta = after_size - before_size
        if self.size_delta_bytes != expected_delta:
            raise ValueError(
                "size_delta_bytes must equal after.size_bytes - before.size_bytes"
            )

        if self.before is not None and self.before.path != self.path:
            raise ValueError("before file path must match diff path")
        if self.after is not None and self.after.path != self.path:
            raise ValueError("after file path must match diff path")

        if self.change_type == "added":
            if self.before is not None or self.after is None:
                raise ValueError("added file diff requires only after")
        elif self.change_type == "removed":
            if self.before is None or self.after is not None:
                raise ValueError("removed file diff requires only before")
        else:
            if self.before is None or self.after is None:
                raise ValueError(
                    f"{self.change_type} file diff requires before and after"
                )
        return self


class DatasetManifestDiff(DatasetLineageModel):
    """Pure diff of two caller-supplied manifests."""

    before_manifest_id: NonEmptyStr
    after_manifest_id: NonEmptyStr
    added: list[DatasetManifestFileDiff] = Field(default_factory=list)
    removed: list[DatasetManifestFileDiff] = Field(default_factory=list)
    modified: list[DatasetManifestFileDiff] = Field(default_factory=list)
    unchanged: list[DatasetManifestFileDiff] = Field(default_factory=list)
    stats: DatasetManifestDiffStats

    @model_validator(mode="after")
    def _validate_change_buckets(self) -> Self:
        for field_name, change_type in (
            ("added", "added"),
            ("removed", "removed"),
            ("modified", "modified"),
            ("unchanged", "unchanged"),
        ):
            for entry in getattr(self, field_name):
                if entry.change_type != change_type:
                    raise ValueError(
                        f"{field_name} entries must have change_type={change_type}"
                    )
        return self


def diff_dataset_manifests(
    before: DatasetManifest,
    after: DatasetManifest,
) -> DatasetManifestDiff:
    """Return a deterministic diff for two supplied manifests."""

    before = DatasetManifest.model_validate(before)
    after = DatasetManifest.model_validate(after)
    before_files = _files_by_path(before)
    after_files = _files_by_path(after)

    added: list[DatasetManifestFileDiff] = []
    removed: list[DatasetManifestFileDiff] = []
    modified: list[DatasetManifestFileDiff] = []
    unchanged: list[DatasetManifestFileDiff] = []

    for path in sorted(before_files.keys() | after_files.keys()):
        before_file = before_files.get(path)
        after_file = after_files.get(path)
        if before_file is None and after_file is not None:
            added.append(
                DatasetManifestFileDiff(
                    change_type="added",
                    path=path,
                    after=after_file,
                    size_delta_bytes=after_file.size_bytes,
                )
            )
        elif before_file is not None and after_file is None:
            removed.append(
                DatasetManifestFileDiff(
                    change_type="removed",
                    path=path,
                    before=before_file,
                    size_delta_bytes=-before_file.size_bytes,
                )
            )
        elif before_file is not None and after_file is not None:
            change_type: Literal["modified", "unchanged"]
            if _file_fingerprint(before_file) == _file_fingerprint(after_file):
                change_type = "unchanged"
                bucket = unchanged
            else:
                change_type = "modified"
                bucket = modified
            bucket.append(
                DatasetManifestFileDiff(
                    change_type=change_type,
                    path=path,
                    before=before_file,
                    after=after_file,
                    size_delta_bytes=after_file.size_bytes - before_file.size_bytes,
                )
            )

    return DatasetManifestDiff(
        before_manifest_id=before.manifest_id,
        after_manifest_id=after.manifest_id,
        added=added,
        removed=removed,
        modified=modified,
        unchanged=unchanged,
        stats=DatasetManifestDiffStats(
            before=_manifest_size_stats(before.files),
            after=_manifest_size_stats(after.files),
            added=_change_stats(added),
            removed=_change_stats(removed),
            modified=_change_stats(modified),
            unchanged=_change_stats(unchanged),
            total_size_delta_bytes=_total_size(after.files) - _total_size(before.files),
        ),
    )


def _files_by_path(manifest: DatasetManifest) -> dict[str, DatasetManifestFile]:
    return {file.path: file for file in manifest.files}


def _file_fingerprint(file: DatasetManifestFile) -> str:
    payload = file.model_dump(mode="json", exclude={"path"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _manifest_size_stats(files: list[DatasetManifestFile]) -> DatasetManifestSizeStats:
    return DatasetManifestSizeStats(
        file_count=len(files),
        total_size_bytes=_total_size(files),
    )


def _change_stats(
    entries: list[DatasetManifestFileDiff],
) -> DatasetManifestChangeStats:
    before_size = sum(entry.before.size_bytes for entry in entries if entry.before)
    after_size = sum(entry.after.size_bytes for entry in entries if entry.after)
    return DatasetManifestChangeStats(
        file_count=len(entries),
        before_size_bytes=before_size,
        after_size_bytes=after_size,
        size_delta_bytes=after_size - before_size,
    )


def _total_size(files: list[DatasetManifestFile]) -> int:
    return sum(file.size_bytes for file in files)


__all__ = [
    "DatasetExamplePolicy",
    "DatasetFileChangeType",
    "DatasetLineageModel",
    "DatasetManifest",
    "DatasetManifestChangeStats",
    "DatasetManifestDiff",
    "DatasetManifestDiffStats",
    "DatasetManifestFile",
    "DatasetManifestFileDiff",
    "DatasetManifestSizeStats",
    "diff_dataset_manifests",
]
