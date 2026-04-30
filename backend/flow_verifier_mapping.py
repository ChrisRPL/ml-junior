from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from backend.verifier_check_catalog import (
    CHECK_BASELINE_RECORDED,
    CHECK_CODE_EXECUTION_OBSERVED,
    CHECK_CONFIGS_AND_SEEDS_RECORDED,
    CHECK_DATASET_LOADED,
    CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
    CHECK_METRIC_PARSED_FROM_OUTPUT,
    CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
    CHECK_SPLIT_CORRECTNESS,
    get_builtin_verifier_check,
)


@dataclass(frozen=True, slots=True)
class FlowVerifierCatalogMapping:
    """Compatibility link from one flow-local verifier id to a catalog check."""

    flow_verifier_id: str
    catalog_check_id: str | None

    @property
    def mapped(self) -> bool:
        return self.catalog_check_id is not None


@dataclass(frozen=True, slots=True)
class FlowVerifierCoverageReport:
    """Deterministic mapping coverage for a flow verifier id set."""

    verifier_count: int
    mapped: tuple[FlowVerifierCatalogMapping, ...]
    intentional_unmapped_verifier_ids: tuple[str, ...]
    unknown_unmapped_verifier_ids: tuple[str, ...]

    @property
    def mapped_count(self) -> int:
        return len(self.mapped)

    @property
    def unmapped_count(self) -> int:
        return (
            len(self.intentional_unmapped_verifier_ids)
            + len(self.unknown_unmapped_verifier_ids)
        )


def _validate_catalog_check_ids(mapping: Mapping[str, str]) -> dict[str, str]:
    for catalog_check_id in mapping.values():
        get_builtin_verifier_check(catalog_check_id)
    return dict(mapping)


INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS: tuple[str, ...] = (
    "dataset-card-reviewed",
    "eval-goal-is-testable",
    "goal-is-testable",
    "interfaces-defined",
    "metric-spec-complete",
    "model-choice-justified",
    "reliability-checked",
    "schema-documented",
    "scope-is-specific",
    "shape-contract-complete",
    "sources-have-provenance",
)

FLOW_VERIFIER_TO_CATALOG_CHECK_IDS: Mapping[str, str] = MappingProxyType(
    _validate_catalog_check_ids(
        {
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
    )
)

KNOWN_FLOW_VERIFIER_IDS: tuple[str, ...] = tuple(
    sorted(
        {
            *FLOW_VERIFIER_TO_CATALOG_CHECK_IDS,
            *INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS,
        }
    )
)


def get_catalog_check_id_for_flow_verifier(flow_verifier_id: str) -> str | None:
    """Return the catalog check id for a local flow verifier id, if mapped."""
    return FLOW_VERIFIER_TO_CATALOG_CHECK_IDS.get(flow_verifier_id)


def list_flow_verifier_catalog_mappings(
    flow_verifier_ids: Iterable[str] | None = None,
) -> tuple[FlowVerifierCatalogMapping, ...]:
    """Return deterministic compatibility mappings, preserving local ids."""
    verifier_ids = _normalize_flow_verifier_ids(flow_verifier_ids)
    return tuple(
        FlowVerifierCatalogMapping(
            flow_verifier_id=verifier_id,
            catalog_check_id=get_catalog_check_id_for_flow_verifier(verifier_id),
        )
        for verifier_id in verifier_ids
    )


def build_flow_verifier_coverage_report(
    flow_verifier_ids: Iterable[str] | None = None,
) -> FlowVerifierCoverageReport:
    """Report mapped, intentional-unmapped, and unknown-unmapped verifier ids."""
    verifier_ids = _normalize_flow_verifier_ids(flow_verifier_ids)
    mappings = list_flow_verifier_catalog_mappings(verifier_ids)
    intentional_unmapped = tuple(
        verifier_id
        for verifier_id in verifier_ids
        if (
            verifier_id in INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS
            and verifier_id not in FLOW_VERIFIER_TO_CATALOG_CHECK_IDS
        )
    )
    unknown_unmapped = tuple(
        verifier_id
        for verifier_id in verifier_ids
        if (
            verifier_id not in FLOW_VERIFIER_TO_CATALOG_CHECK_IDS
            and verifier_id not in INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS
        )
    )

    return FlowVerifierCoverageReport(
        verifier_count=len(verifier_ids),
        mapped=tuple(mapping for mapping in mappings if mapping.mapped),
        intentional_unmapped_verifier_ids=intentional_unmapped,
        unknown_unmapped_verifier_ids=unknown_unmapped,
    )


def _normalize_flow_verifier_ids(
    flow_verifier_ids: Iterable[str] | None,
) -> tuple[str, ...]:
    if flow_verifier_ids is None:
        return KNOWN_FLOW_VERIFIER_IDS
    return tuple(sorted(set(flow_verifier_ids)))


__all__ = [
    "FLOW_VERIFIER_TO_CATALOG_CHECK_IDS",
    "INTENTIONAL_UNMAPPED_FLOW_VERIFIER_IDS",
    "KNOWN_FLOW_VERIFIER_IDS",
    "FlowVerifierCatalogMapping",
    "FlowVerifierCoverageReport",
    "build_flow_verifier_coverage_report",
    "get_catalog_check_id_for_flow_verifier",
    "list_flow_verifier_catalog_mappings",
]
