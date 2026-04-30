from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.dataset_lineage import (
    DatasetExamplePolicy,
    DatasetLineageGraph,
    DatasetLineageNode,
    DatasetLineageRef,
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


def test_manifest_can_reference_inert_lineage_ids():
    manifest = make_manifest(
        "manifest-a",
        [make_file("train.jsonl", size_bytes=10)],
        lineage_refs=[
            {
                "lineage_id": "lineage-a",
                "node_id": "filter-train",
            }
        ],
    )

    assert manifest.lineage_refs == [
        DatasetLineageRef(lineage_id="lineage-a", node_id="filter-train")
    ]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatasetLineageRef.model_validate(
            {
                "lineage_id": "lineage-a",
                "producer": "runtime-job",
            }
        )


def test_lineage_graph_supports_closed_transform_filter_augment_merge_nodes():
    graph = DatasetLineageGraph.model_validate(
        {
            "lineage_id": "lineage-a",
            "manifest_refs": [{"manifest_id": "manifest-raw"}],
            "diff_refs": [
                {
                    "before_manifest_id": "manifest-raw",
                    "after_manifest_id": "manifest-clean",
                }
            ],
            "nodes": [
                {
                    "node_id": "transform-raw",
                    "kind": "transform",
                    "input_manifest_refs": [{"manifest_id": "manifest-raw"}],
                    "output_manifest_refs": [{"manifest_id": "manifest-shaped"}],
                    "parameters": {"columns": ["text", "label"]},
                },
                {
                    "node_id": "filter-train",
                    "kind": "filter",
                    "parent_refs": [{"node_id": "transform-raw"}],
                    "output_manifest_refs": [{"manifest_id": "manifest-clean"}],
                },
                {
                    "node_id": "augment-train",
                    "kind": "augment",
                    "parent_refs": [{"node_id": "filter-train"}],
                },
                {
                    "node_id": "merge-train",
                    "kind": "merge",
                    "parent_refs": [
                        {"node_id": "filter-train"},
                        {"node_id": "augment-train"},
                    ],
                },
            ],
        }
    )

    assert graph.lineage_id == "lineage-a"
    assert [node.kind for node in graph.nodes] == [
        "transform",
        "filter",
        "augment",
        "merge",
    ]
    assert graph.nodes[0].input_manifest_refs[0].manifest_id == "manifest-raw"
    assert graph.diff_refs[0].after_manifest_id == "manifest-clean"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        DatasetLineageNode.model_validate(
            {
                "node_id": "extra-node",
                "kind": "transform",
                "producer": "runtime-job",
            }
        )


def test_lineage_graph_rejects_duplicate_node_ids_deterministically():
    with pytest.raises(ValidationError, match="duplicate node ids: a-node"):
        DatasetLineageGraph.model_validate(
            {
                "lineage_id": "lineage-a",
                "nodes": [
                    {"node_id": "a-node", "kind": "transform"},
                    {"node_id": "b-node", "kind": "filter"},
                    {"node_id": "a-node", "kind": "augment"},
                ],
            }
        )


def test_lineage_nodes_reject_duplicate_parent_refs_deterministically():
    with pytest.raises(ValidationError, match="duplicate parent refs: parent-a"):
        DatasetLineageNode.model_validate(
            {
                "node_id": "child",
                "kind": "merge",
                "parent_refs": [
                    {"node_id": "parent-a"},
                    {"node_id": "parent-b"},
                    {"node_id": "parent-a"},
                ],
            }
        )


def test_lineage_graph_rejects_unknown_parent_refs_deterministically():
    with pytest.raises(
        ValidationError,
        match=r"unknown parent refs: child-a->missing-a, child-b->missing-b",
    ):
        DatasetLineageGraph.model_validate(
            {
                "lineage_id": "lineage-a",
                "nodes": [
                    {
                        "node_id": "child-b",
                        "kind": "filter",
                        "parent_refs": [{"node_id": "missing-b"}],
                    },
                    {
                        "node_id": "child-a",
                        "kind": "transform",
                        "parent_refs": [{"node_id": "missing-a"}],
                    },
                ],
            }
        )


def test_lineage_graph_rejects_cycles_deterministically():
    with pytest.raises(
        ValidationError,
        match=r"contains cycle: augment-a -> filter-a -> transform-a -> augment-a",
    ):
        DatasetLineageGraph.model_validate(
            {
                "lineage_id": "lineage-a",
                "nodes": [
                    {
                        "node_id": "transform-a",
                        "kind": "transform",
                        "parent_refs": [{"node_id": "augment-a"}],
                    },
                    {
                        "node_id": "filter-a",
                        "kind": "filter",
                        "parent_refs": [{"node_id": "transform-a"}],
                    },
                    {
                        "node_id": "augment-a",
                        "kind": "augment",
                        "parent_refs": [{"node_id": "filter-a"}],
                    },
                ],
            }
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
