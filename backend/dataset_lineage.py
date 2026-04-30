from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

DatasetFileChangeType = Literal["added", "removed", "modified", "unchanged"]
DatasetLineageNodeKind = Literal["transform", "filter", "augment", "merge"]


class DatasetLineageModel(BaseModel):
    """Closed-schema base for inert caller-supplied dataset lineage records."""

    model_config = ConfigDict(extra="forbid", strict=True)


class DatasetLineageRef(DatasetLineageModel):
    """Reference to an inert lineage graph, optionally narrowed to one node."""

    lineage_id: NonEmptyStr
    node_id: NonEmptyStr | None = None


class DatasetLineageNodeRef(DatasetLineageModel):
    """Reference to a parent node inside the same lineage graph."""

    node_id: NonEmptyStr


class DatasetLineageManifestRef(DatasetLineageModel):
    """Reference to a caller-supplied manifest without reading dataset files."""

    manifest_id: NonEmptyStr


class DatasetLineageDiffRef(DatasetLineageModel):
    """Reference to a caller-supplied manifest diff by its manifest endpoints."""

    before_manifest_id: NonEmptyStr
    after_manifest_id: NonEmptyStr


class DatasetLineageNode(DatasetLineageModel):
    """One inert operation node in a caller-supplied dataset lineage DAG."""

    node_id: NonEmptyStr
    kind: DatasetLineageNodeKind
    parent_refs: list[DatasetLineageNodeRef] = Field(default_factory=list)
    input_manifest_refs: list[DatasetLineageManifestRef] = Field(default_factory=list)
    output_manifest_refs: list[DatasetLineageManifestRef] = Field(default_factory=list)
    diff_refs: list[DatasetLineageDiffRef] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _reject_duplicate_parent_refs(self) -> Self:
        duplicates = _duplicate_values(ref.node_id for ref in self.parent_refs)
        if duplicates:
            refs = ", ".join(duplicates)
            raise ValueError(
                f"dataset lineage node {self.node_id} contains duplicate "
                f"parent refs: {refs}"
            )
        return self


class DatasetLineageGraph(DatasetLineageModel):
    """Closed inert DAG schema for caller-supplied dataset lineage."""

    lineage_id: NonEmptyStr
    nodes: list[DatasetLineageNode] = Field(default_factory=list)
    manifest_refs: list[DatasetLineageManifestRef] = Field(default_factory=list)
    diff_refs: list[DatasetLineageDiffRef] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_node_ids_and_parent_graph(self) -> Self:
        duplicates = _duplicate_values(node.node_id for node in self.nodes)
        if duplicates:
            ids = ", ".join(duplicates)
            raise ValueError(
                f"dataset lineage graph contains duplicate node ids: {ids}"
            )

        nodes_by_id = {node.node_id: node for node in self.nodes}
        unknown_refs: list[tuple[str, str]] = []
        for node in self.nodes:
            for parent_ref in node.parent_refs:
                if parent_ref.node_id not in nodes_by_id:
                    unknown_refs.append((node.node_id, parent_ref.node_id))
        if unknown_refs:
            refs = ", ".join(
                f"{child}->{parent}" for child, parent in sorted(unknown_refs)
            )
            raise ValueError(
                f"dataset lineage graph contains unknown parent refs: {refs}"
            )

        parent_ids_by_node = {
            node.node_id: [ref.node_id for ref in node.parent_refs]
            for node in self.nodes
        }
        cycle = _find_lineage_cycle(parent_ids_by_node)
        if cycle:
            path = " -> ".join(cycle)
            raise ValueError(f"dataset lineage graph contains cycle: {path}")
        return self


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
    lineage_refs: list[DatasetLineageRef] = Field(default_factory=list)
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


def _duplicate_values(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _find_lineage_cycle(
    parent_ids_by_node: dict[str, list[str]],
) -> list[str] | None:
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def visit(node_id: str) -> list[str] | None:
        if node_id in visiting:
            cycle_start = stack.index(node_id)
            return stack[cycle_start:] + [node_id]
        if node_id in visited:
            return None

        visiting.add(node_id)
        stack.append(node_id)
        for parent_id in sorted(parent_ids_by_node[node_id]):
            cycle = visit(parent_id)
            if cycle:
                return cycle
        stack.pop()
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in sorted(parent_ids_by_node):
        cycle = visit(node_id)
        if cycle:
            return cycle
    return None


__all__ = [
    "DatasetExamplePolicy",
    "DatasetFileChangeType",
    "DatasetLineageDiffRef",
    "DatasetLineageGraph",
    "DatasetLineageManifestRef",
    "DatasetLineageModel",
    "DatasetLineageNode",
    "DatasetLineageNodeKind",
    "DatasetLineageNodeRef",
    "DatasetLineageRef",
    "DatasetManifest",
    "DatasetManifestChangeStats",
    "DatasetManifestDiff",
    "DatasetManifestDiffStats",
    "DatasetManifestFile",
    "DatasetManifestFileDiff",
    "DatasetManifestSizeStats",
    "diff_dataset_manifests",
]
