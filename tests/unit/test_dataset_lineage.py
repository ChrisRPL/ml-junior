from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.dataset_lineage import (
    DatasetExamplePolicy,
    DatasetManifest,
    DatasetManifestChangeStats,
    DatasetManifestDiff,
    DatasetManifestFile,
    DatasetManifestFileDiff,
    diff_dataset_manifests,
)


def make_file(
    path: str,
    *,
    size_bytes: int,
    digest: str | None = None,
    **overrides,
) -> DatasetManifestFile:
    values = {
        "path": path,
        "size_bytes": size_bytes,
        "digest": digest or f"sha256:{path}",
    }
    values.update(overrides)
    return DatasetManifestFile.model_validate(values)


def make_manifest(
    manifest_id: str,
    files: list[DatasetManifestFile],
    **overrides,
) -> DatasetManifest:
    values = {
        "manifest_id": manifest_id,
        "dataset_id": "dataset-a",
        "files": files,
    }
    values.update(overrides)
    return DatasetManifest.model_validate(values)


def test_manifest_and_file_models_are_closed_with_redacted_examples_by_default():
    manifest = make_manifest(
        "manifest-a",
        [
            make_file("train.jsonl", size_bytes=10),
        ],
    )

    assert manifest.source == "caller_supplied"
    assert manifest.redaction_status == "redacted"
    assert manifest.example_policy == DatasetExamplePolicy()
    assert manifest.files[0].example_policy == DatasetExamplePolicy()
    assert "examples" not in manifest.model_dump(mode="json")
    assert "examples" not in manifest.files[0].model_dump(mode="json")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatasetManifest.model_validate(
            {
                "manifest_id": "manifest-extra",
                "files": [],
                "unexpected": "value",
            }
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatasetManifestFile.model_validate(
            {
                "path": "private.jsonl",
                "size_bytes": 1,
                "example": {"email": "redacted@example.test"},
            }
        )


def test_manifest_rejects_duplicate_paths():
    with pytest.raises(ValidationError, match="duplicate file paths: data.jsonl"):
        make_manifest(
            "manifest-duplicates",
            [
                make_file("data.jsonl", size_bytes=1, digest="sha256:a"),
                make_file("data.jsonl", size_bytes=2, digest="sha256:b"),
            ],
        )


def test_diff_is_deterministic_for_all_file_change_types_and_size_stats():
    before = make_manifest(
        "manifest-before",
        [
            make_file("removed.jsonl", size_bytes=20, digest="sha256:old-removed"),
            make_file("unchanged.jsonl", size_bytes=10, digest="sha256:same"),
            make_file("modified.jsonl", size_bytes=30, digest="sha256:old"),
        ],
    )
    after = make_manifest(
        "manifest-after",
        [
            make_file("modified.jsonl", size_bytes=45, digest="sha256:new"),
            make_file("added.jsonl", size_bytes=7, digest="sha256:added"),
            make_file("unchanged.jsonl", size_bytes=10, digest="sha256:same"),
        ],
    )

    diff = diff_dataset_manifests(before, after)

    assert diff.before_manifest_id == "manifest-before"
    assert diff.after_manifest_id == "manifest-after"
    assert [entry.path for entry in diff.added] == ["added.jsonl"]
    assert [entry.path for entry in diff.removed] == ["removed.jsonl"]
    assert [entry.path for entry in diff.modified] == ["modified.jsonl"]
    assert [entry.path for entry in diff.unchanged] == ["unchanged.jsonl"]
    assert diff.added[0].size_delta_bytes == 7
    assert diff.removed[0].size_delta_bytes == -20
    assert diff.modified[0].size_delta_bytes == 15
    assert diff.unchanged[0].size_delta_bytes == 0

    assert diff.stats.before.file_count == 3
    assert diff.stats.before.total_size_bytes == 60
    assert diff.stats.after.file_count == 3
    assert diff.stats.after.total_size_bytes == 62
    assert diff.stats.total_size_delta_bytes == 2
    assert diff.stats.added == DatasetManifestChangeStats(
        file_count=1,
        before_size_bytes=0,
        after_size_bytes=7,
        size_delta_bytes=7,
    )
    assert diff.stats.removed == DatasetManifestChangeStats(
        file_count=1,
        before_size_bytes=20,
        after_size_bytes=0,
        size_delta_bytes=-20,
    )
    assert diff.stats.modified == DatasetManifestChangeStats(
        file_count=1,
        before_size_bytes=30,
        after_size_bytes=45,
        size_delta_bytes=15,
    )
    assert diff.stats.unchanged == DatasetManifestChangeStats(
        file_count=1,
        before_size_bytes=10,
        after_size_bytes=10,
        size_delta_bytes=0,
    )


def test_diff_marks_metadata_only_changes_as_modified():
    before = make_manifest(
        "manifest-before",
        [
            make_file(
                "data.jsonl",
                size_bytes=10,
                digest="sha256:same",
                metadata={"split": "train"},
            ),
        ],
    )
    after = make_manifest(
        "manifest-after",
        [
            make_file(
                "data.jsonl",
                size_bytes=10,
                digest="sha256:same",
                metadata={"split": "validation"},
            ),
        ],
    )

    diff = diff_dataset_manifests(before, after)

    assert [entry.path for entry in diff.modified] == ["data.jsonl"]
    assert diff.unchanged == []


def test_diff_models_are_closed_and_validate_change_shapes():
    after_file = make_file("added.jsonl", size_bytes=7)

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatasetManifestFileDiff.model_validate(
            {
                "change_type": "added",
                "path": "added.jsonl",
                "after": after_file,
                "size_delta_bytes": 7,
                "unexpected": True,
            }
        )

    with pytest.raises(ValidationError, match="requires only after"):
        DatasetManifestFileDiff.model_validate(
            {
                "change_type": "added",
                "path": "added.jsonl",
                "before": after_file,
                "after": after_file,
                "size_delta_bytes": 0,
            }
        )

    with pytest.raises(ValidationError, match="change_type=added"):
        DatasetManifestDiff.model_validate(
            {
                "before_manifest_id": "before",
                "after_manifest_id": "after",
                "added": [
                    {
                        "change_type": "removed",
                        "path": "added.jsonl",
                        "before": after_file,
                        "size_delta_bytes": -7,
                    }
                ],
                "stats": {
                    "before": {"file_count": 0, "total_size_bytes": 0},
                    "after": {"file_count": 0, "total_size_bytes": 0},
                    "added": {
                        "file_count": 0,
                        "before_size_bytes": 0,
                        "after_size_bytes": 0,
                        "size_delta_bytes": 0,
                    },
                    "removed": {
                        "file_count": 0,
                        "before_size_bytes": 0,
                        "after_size_bytes": 0,
                        "size_delta_bytes": 0,
                    },
                    "modified": {
                        "file_count": 0,
                        "before_size_bytes": 0,
                        "after_size_bytes": 0,
                        "size_delta_bytes": 0,
                    },
                    "unchanged": {
                        "file_count": 0,
                        "before_size_bytes": 0,
                        "after_size_bytes": 0,
                        "size_delta_bytes": 0,
                    },
                    "total_size_delta_bytes": 0,
                },
            }
        )
