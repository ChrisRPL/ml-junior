from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.verifier_check_catalog import (
    BUILTIN_VERIFIER_CHECK_IDS,
    CHECK_ARTIFACTS_AVAILABLE,
    CHECK_BASELINE_RECORDED,
    CHECK_CONFIGS_AND_SEEDS_RECORDED,
    CHECK_CODE_EXECUTION_OBSERVED,
    CHECK_DATASET_LOADED,
    CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
    CHECK_METRIC_PARSED_FROM_OUTPUT,
    CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
    CHECK_SPLIT_CORRECTNESS,
    VerifierCheckCatalogEntry,
    VerifierCheckCatalogError,
    VerifierCheckCatalogNotFoundError,
    VerifierCheckEvidenceRequirement,
    get_builtin_verifier_check,
    list_builtin_verifier_checks,
    validate_verifier_check_catalog,
)


EXPECTED_BUILTIN_CHECK_IDS = [
    CHECK_CODE_EXECUTION_OBSERVED,
    CHECK_DATASET_LOADED,
    CHECK_SPLIT_CORRECTNESS,
    CHECK_BASELINE_RECORDED,
    CHECK_METRIC_PARSED_FROM_OUTPUT,
    CHECK_CONFIGS_AND_SEEDS_RECORDED,
    CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
    CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
    CHECK_ARTIFACTS_AVAILABLE,
]


def test_builtin_catalog_has_stable_order_and_verdict_check_shape() -> None:
    entries = list_builtin_verifier_checks()

    assert BUILTIN_VERIFIER_CHECK_IDS == tuple(EXPECTED_BUILTIN_CHECK_IDS)
    assert [entry.check_id for entry in entries] == EXPECTED_BUILTIN_CHECK_IDS
    assert [entry.order for entry in entries] == sorted(
        entry.order for entry in entries
    )
    assert len({entry.check_id for entry in entries}) == len(entries)

    for entry in entries:
        assert entry.required is True
        assert entry.name
        assert entry.description
        assert entry.evidence_requirements
        assert entry.verdict_statuses == ("passed", "failed", "inconclusive")


def test_list_helper_returns_copy_without_mutating_builtin_catalog() -> None:
    entries = list_builtin_verifier_checks()
    entries.pop()

    assert [entry.check_id for entry in list_builtin_verifier_checks()] == (
        EXPECTED_BUILTIN_CHECK_IDS
    )


def test_get_helper_returns_catalog_entry_and_unknown_id_fails() -> None:
    entry = get_builtin_verifier_check(CHECK_METRIC_PARSED_FROM_OUTPUT)

    assert entry.check_id == CHECK_METRIC_PARSED_FROM_OUTPUT
    assert entry.check_type == "metric"
    assert {item.ref_type for item in entry.evidence_requirements} == {
        "metric",
        "evidence",
        "experiment",
    }

    with pytest.raises(
        VerifierCheckCatalogNotFoundError,
        match="Unknown built-in verifier check: missing-check",
    ):
        get_builtin_verifier_check("missing-check")


def test_catalog_covers_ml_verifier_checklist_surfaces() -> None:
    final_claims = get_builtin_verifier_check(CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE)
    model_card = get_builtin_verifier_check(CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED)
    artifacts = get_builtin_verifier_check(CHECK_ARTIFACTS_AVAILABLE)
    configs = get_builtin_verifier_check(CHECK_CONFIGS_AND_SEEDS_RECORDED)

    assert {item.ref_type for item in final_claims.evidence_requirements} == {
        "claim",
        "experiment",
        "evidence",
    }
    assert "model_card" in {
        item.ref_type for item in model_card.evidence_requirements
    }
    assert "artifact" in {item.ref_type for item in artifacts.evidence_requirements}
    assert {item.ref_type for item in configs.evidence_requirements} == {
        "config",
        "seed",
    }


def test_catalog_validation_rejects_duplicate_ids_and_orders_entries() -> None:
    first = make_entry(check_id="synthetic-a", order=20)
    second = make_entry(check_id="synthetic-b", order=10)

    assert [
        entry.check_id
        for entry in validate_verifier_check_catalog([first, second])
    ] == ["synthetic-b", "synthetic-a"]

    with pytest.raises(VerifierCheckCatalogError, match="duplicate verifier check id"):
        validate_verifier_check_catalog(
            [first, make_entry(check_id="synthetic-a", order=30)]
        )


def test_catalog_models_are_closed_and_local() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VerifierCheckEvidenceRequirement(
            ref_type="evidence",
            description="Synthetic evidence.",
            unexpected=True,
        )

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VerifierCheckCatalogEntry(
            check_id="synthetic-check",
            name="Synthetic check",
            description="Synthetic catalog fixture.",
            category="execution",
            check_type="manual",
            order=1,
            evidence_requirements=(
                VerifierCheckEvidenceRequirement(
                    ref_type="evidence",
                    description="Synthetic evidence.",
                ),
            ),
            unexpected=True,
        )


def make_entry(*, check_id: str, order: int) -> VerifierCheckCatalogEntry:
    return VerifierCheckCatalogEntry(
        check_id=check_id,
        name=f"Synthetic {check_id}",
        description="Synthetic catalog entry.",
        category="execution",
        check_type="manual",
        order=order,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description="Synthetic evidence.",
            ),
        ),
    )
