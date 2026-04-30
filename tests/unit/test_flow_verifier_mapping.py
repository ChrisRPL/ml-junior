from __future__ import annotations

import pytest

from backend.flow_templates import list_builtin_flow_templates
from backend.flow_verifier_mapping import (
    FLOW_VERIFIER_TO_CATALOG_CHECK_IDS,
    INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS,
    KNOWN_FLOW_VERIFIER_IDS,
    build_flow_verifier_coverage_report,
    get_catalog_check_id_for_flow_verifier,
    list_flow_verifier_catalog_mappings,
)
from backend.verifier_check_catalog import (
    BUILTIN_VERIFIER_CHECK_IDS,
    CHECK_BASELINE_RECORDED,
    CHECK_CODE_EXECUTION_OBSERVED,
    CHECK_CONFIGS_AND_SEEDS_RECORDED,
    CHECK_DATASET_LOADED,
    CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
    CHECK_METRIC_PARSED_FROM_OUTPUT,
    CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
    CHECK_SPLIT_CORRECTNESS,
)


EXPECTED_BUILTIN_FLOW_VERIFIER_IDS = [
    "baseline-compared",
    "claims-have-sources",
    "code-imports",
    "dataset-card-reviewed",
    "dataset-fingerprint-captured",
    "dry-run-passed",
    "environment-captured",
    "eval-goal-is-testable",
    "final-claims-have-evidence",
    "goal-is-testable",
    "interfaces-defined",
    "leakage-checked",
    "metric-recorded",
    "metric-spec-complete",
    "model-card-complete",
    "model-choice-justified",
    "reliability-checked",
    "schema-documented",
    "scope-is-specific",
    "scoring-code-runs",
    "shape-contract-complete",
    "shape-tests-pass",
    "smoke-metric-recorded",
    "sources-have-provenance",
    "training-config-complete",
]


def test_known_flow_verifier_ids_cover_builtin_templates_without_mutation() -> None:
    templates_before = [
        template.model_dump()
        for template in list_builtin_flow_templates()
    ]

    assert _builtin_flow_verifier_ids() == EXPECTED_BUILTIN_FLOW_VERIFIER_IDS
    assert list(KNOWN_FLOW_VERIFIER_IDS) == EXPECTED_BUILTIN_FLOW_VERIFIER_IDS

    templates_after = [
        template.model_dump()
        for template in list_builtin_flow_templates()
    ]
    assert templates_after == templates_before


def test_local_flow_verifier_ids_map_to_reusable_catalog_checks() -> None:
    assert get_catalog_check_id_for_flow_verifier("metric-recorded") == (
        CHECK_METRIC_PARSED_FROM_OUTPUT
    )
    assert get_catalog_check_id_for_flow_verifier("smoke-metric-recorded") == (
        CHECK_METRIC_PARSED_FROM_OUTPUT
    )
    assert get_catalog_check_id_for_flow_verifier("final-claims-have-evidence") == (
        CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE
    )
    assert get_catalog_check_id_for_flow_verifier("goal-is-testable") is None

    assert dict(FLOW_VERIFIER_TO_CATALOG_CHECK_IDS) == {
        "baseline-compared": CHECK_BASELINE_RECORDED,
        "claims-have-sources": CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
        "code-imports": CHECK_CODE_EXECUTION_OBSERVED,
        "dataset-fingerprint-captured": CHECK_DATASET_LOADED,
        "dry-run-passed": CHECK_CODE_EXECUTION_OBSERVED,
        "environment-captured": CHECK_CONFIGS_AND_SEEDS_RECORDED,
        "final-claims-have-evidence": CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
        "leakage-checked": CHECK_SPLIT_CORRECTNESS,
        "metric-recorded": CHECK_METRIC_PARSED_FROM_OUTPUT,
        "model-card-complete": CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
        "scoring-code-runs": CHECK_CODE_EXECUTION_OBSERVED,
        "shape-tests-pass": CHECK_CODE_EXECUTION_OBSERVED,
        "smoke-metric-recorded": CHECK_METRIC_PARSED_FROM_OUTPUT,
        "training-config-complete": CHECK_CONFIGS_AND_SEEDS_RECORDED,
    }


def test_mapped_catalog_ids_are_valid_builtin_catalog_ids() -> None:
    assert set(FLOW_VERIFIER_TO_CATALOG_CHECK_IDS.values()) <= set(
        BUILTIN_VERIFIER_CHECK_IDS
    )


def test_mapping_exports_are_read_only() -> None:
    with pytest.raises(TypeError):
        FLOW_VERIFIER_TO_CATALOG_CHECK_IDS["metric-recorded"] = (  # type: ignore[index]
            "other-check"
        )


def test_list_helper_preserves_local_ids_and_returns_deterministic_entries() -> None:
    mappings = list_flow_verifier_catalog_mappings(
        ["metric-recorded", "goal-is-testable", "metric-recorded"]
    )

    assert [item.flow_verifier_id for item in mappings] == [
        "goal-is-testable",
        "metric-recorded",
    ]
    assert [item.catalog_check_id for item in mappings] == [
        None,
        CHECK_METRIC_PARSED_FROM_OUTPUT,
    ]
    assert [item.mapped for item in mappings] == [False, True]


def test_coverage_report_allows_and_reports_unmapped_local_checks() -> None:
    report = build_flow_verifier_coverage_report(
        [
            "unknown-local-check",
            "goal-is-testable",
            "metric-recorded",
            "final-claims-have-evidence",
        ]
    )

    assert report.verifier_count == 4
    assert report.mapped_count == 2
    assert report.unmapped_count == 2
    assert [item.flow_verifier_id for item in report.mapped] == [
        "final-claims-have-evidence",
        "metric-recorded",
    ]
    assert report.intentional_unmapped_verifier_ids == ("goal-is-testable",)
    assert report.unknown_unmapped_verifier_ids == ("unknown-local-check",)


def test_default_coverage_report_is_stable_for_known_builtin_flow_verifiers() -> None:
    report = build_flow_verifier_coverage_report()

    assert report.verifier_count == len(EXPECTED_BUILTIN_FLOW_VERIFIER_IDS)
    assert report.mapped_count == len(FLOW_VERIFIER_TO_CATALOG_CHECK_IDS)
    assert report.intentional_unmapped_verifier_ids == (
        INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS
    )
    assert report.unknown_unmapped_verifier_ids == ()
    assert [item.flow_verifier_id for item in report.mapped] == sorted(
        FLOW_VERIFIER_TO_CATALOG_CHECK_IDS
    )


def _builtin_flow_verifier_ids() -> list[str]:
    return sorted(
        {
            verifier.id
            for template in list_builtin_flow_templates()
            for verifier in template.verifiers
        }
    )
