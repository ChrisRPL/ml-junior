from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


CheckCategory = Literal[
    "execution",
    "data",
    "evaluation",
    "reproducibility",
    "reporting",
    "artifacts",
]
EvidenceRefType = Literal[
    "artifact",
    "claim",
    "config",
    "dataset",
    "evidence",
    "event",
    "experiment",
    "metric",
    "model_card",
    "seed",
]
VerifierCheckType = Literal["manual", "artifact", "metric", "command", "llm"]
VerifierCheckStatus = Literal["passed", "failed", "inconclusive"]

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
VerifierCheckId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=3,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
    ),
]


class VerifierCheckCatalogError(ValueError):
    """Raised when verifier check catalog entries are invalid or conflict."""


class VerifierCheckCatalogNotFoundError(VerifierCheckCatalogError):
    """Raised when a built-in verifier check id is unknown."""


class _CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VerifierCheckEvidenceRequirement(_CatalogModel):
    """Evidence reference expected in a future inert verifier verdict check."""

    ref_type: EvidenceRefType
    description: NonEmptyStr
    required: bool = True


class VerifierCheckCatalogEntry(_CatalogModel):
    """Closed built-in checklist entry for inert ML verifier verdicts."""

    check_id: VerifierCheckId
    name: NonEmptyStr
    description: NonEmptyStr
    category: CheckCategory
    check_type: VerifierCheckType
    order: int = Field(ge=0)
    evidence_requirements: tuple[VerifierCheckEvidenceRequirement, ...]
    verdict_statuses: tuple[VerifierCheckStatus, ...] = (
        "passed",
        "failed",
        "inconclusive",
    )
    metadata_keys: tuple[VerifierCheckId, ...] = Field(default_factory=tuple)
    required: bool = True


class VerifierCheckCatalogCount(_CatalogModel):
    """Deterministic count bucket for a verifier check catalog dimension."""

    value: NonEmptyStr
    count: int = Field(ge=0)


class VerifierCheckCatalogSummary(_CatalogModel):
    """Read-only summary of verifier checklist catalog coverage."""

    total_checks: int = Field(ge=0)
    required_checks: int = Field(ge=0)
    optional_checks: int = Field(ge=0)
    ordered_check_ids: tuple[VerifierCheckId, ...]
    category_counts: tuple[VerifierCheckCatalogCount, ...]
    check_type_counts: tuple[VerifierCheckCatalogCount, ...]
    verdict_status_counts: tuple[VerifierCheckCatalogCount, ...]


CHECK_CODE_EXECUTION_OBSERVED = "code-execution-observed"
CHECK_DATASET_LOADED = "dataset-loaded"
CHECK_SPLIT_CORRECTNESS = "split-correctness"
CHECK_BASELINE_RECORDED = "baseline-recorded"
CHECK_METRIC_PARSED_FROM_OUTPUT = "metric-parsed-from-output"
CHECK_CONFIGS_AND_SEEDS_RECORDED = "configs-and-seeds-recorded"
CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE = "final-claims-tied-to-evidence"
CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED = "model-card-generated-when-required"
CHECK_ARTIFACTS_AVAILABLE = "artifacts-available"

BUILTIN_VERIFIER_CHECK_IDS: tuple[str, ...] = (
    CHECK_CODE_EXECUTION_OBSERVED,
    CHECK_DATASET_LOADED,
    CHECK_SPLIT_CORRECTNESS,
    CHECK_BASELINE_RECORDED,
    CHECK_METRIC_PARSED_FROM_OUTPUT,
    CHECK_CONFIGS_AND_SEEDS_RECORDED,
    CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
    CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
    CHECK_ARTIFACTS_AVAILABLE,
)

_CHECK_CATEGORY_ORDER: tuple[CheckCategory, ...] = (
    "execution",
    "data",
    "evaluation",
    "reproducibility",
    "reporting",
    "artifacts",
)
_CHECK_TYPE_ORDER: tuple[VerifierCheckType, ...] = (
    "manual",
    "artifact",
    "metric",
    "command",
    "llm",
)
_VERDICT_STATUS_ORDER: tuple[VerifierCheckStatus, ...] = (
    "passed",
    "failed",
    "inconclusive",
)

_BUILTIN_VERIFIER_CHECKS: tuple[VerifierCheckCatalogEntry, ...] = (
    VerifierCheckCatalogEntry(
        check_id=CHECK_CODE_EXECUTION_OBSERVED,
        name="Code execution observed",
        description="Training, evaluation, or analysis code execution is recorded.",
        category="execution",
        check_type="command",
        order=10,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="event",
                description=(
                    "Command or job event that records the attempted execution."
                ),
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description="Captured stdout, stderr, log, or job status evidence.",
            ),
        ),
        metadata_keys=("run-id", "command-ref"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_DATASET_LOADED,
        name="Dataset loaded",
        description="Dataset source, revision, and load outcome are recorded.",
        category="data",
        check_type="artifact",
        order=20,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="dataset",
                description="Dataset identifier, source, revision, or fingerprint.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description=(
                    "Load log, row count, schema sample, or dataset card evidence."
                ),
            ),
        ),
        metadata_keys=("dataset-id", "dataset-revision"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_SPLIT_CORRECTNESS,
        name="Split correctness",
        description=(
            "Train, validation, and test split mapping is explicit and plausible."
        ),
        category="data",
        check_type="artifact",
        order=30,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="dataset",
                description="Split names, counts, and mapping used by the run.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description="Evidence that evaluation did not use training-only data.",
            ),
        ),
        metadata_keys=("train-split", "validation-split", "test-split"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_BASELINE_RECORDED,
        name="Baseline recorded",
        description="A baseline, prior result, or base-model comparison is recorded.",
        category="evaluation",
        check_type="metric",
        order=40,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="metric",
                description="Baseline metric value with split and task context.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="experiment",
                description="Experiment or run identifier for the baseline source.",
            ),
        ),
        metadata_keys=("baseline-run-id", "baseline-metric-name"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_METRIC_PARSED_FROM_OUTPUT,
        name="Metric parsed from actual output",
        description="Reported metric value is tied to captured run output.",
        category="evaluation",
        check_type="metric",
        order=50,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="metric",
                description="Parsed metric name, value, split, and step or epoch.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description="Raw log, artifact, or output that contains the metric.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="experiment",
                description="Experiment or run identifier for the metric source.",
            ),
        ),
        metadata_keys=("metric-name", "metric-value", "split"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_CONFIGS_AND_SEEDS_RECORDED,
        name="Configs and seeds recorded",
        description=(
            "Configuration, important hyperparameters, and random seeds are recorded."
        ),
        category="reproducibility",
        check_type="artifact",
        order=60,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="config",
                description="Training, preprocessing, evaluation, or inference config.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="seed",
                description=(
                    "Random seed values or explicit note that no seed was used."
                ),
            ),
        ),
        metadata_keys=("config-ref", "seed"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_FINAL_CLAIMS_TIED_TO_EVIDENCE,
        name="Final claims tied to evidence",
        description=(
            "Final claims cite experiment identifiers and evidence identifiers."
        ),
        category="reporting",
        check_type="llm",
        order=70,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="claim",
                description="Final report claim identifier or claim text reference.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="experiment",
                description="Experiment identifier supporting the claim.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description="Evidence identifier supporting the claim.",
            ),
        ),
        metadata_keys=("claim-id", "experiment-id", "evidence-id"),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_MODEL_CARD_GENERATED_WHEN_REQUIRED,
        name="Model card generated when required",
        description=(
            "Required model card or README artifact is generated and referenced."
        ),
        category="reporting",
        check_type="artifact",
        order=80,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="model_card",
                description="Model card artifact, path, or repository file reference.",
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description=(
                    "Evidence that required model-card sections were generated."
                ),
            ),
        ),
        metadata_keys=("model-card-ref",),
    ),
    VerifierCheckCatalogEntry(
        check_id=CHECK_ARTIFACTS_AVAILABLE,
        name="Artifacts available",
        description=(
            "Expected output artifacts are present and have retrievable references."
        ),
        category="artifacts",
        check_type="artifact",
        order=90,
        evidence_requirements=(
            VerifierCheckEvidenceRequirement(
                ref_type="artifact",
                description=(
                    "Artifact reference for model, metrics, report, or outputs."
                ),
            ),
            VerifierCheckEvidenceRequirement(
                ref_type="evidence",
                description=(
                    "Availability evidence such as path, URL, checksum, or listing."
                ),
            ),
        ),
        metadata_keys=("artifact-id", "artifact-ref"),
    ),
)


def validate_verifier_check_catalog(
    entries: Sequence[VerifierCheckCatalogEntry | dict[str, object]],
) -> tuple[VerifierCheckCatalogEntry, ...]:
    """Validate and deterministically order inert verifier check catalog entries."""
    validated = tuple(
        entry
        if isinstance(entry, VerifierCheckCatalogEntry)
        else VerifierCheckCatalogEntry.model_validate(entry)
        for entry in entries
    )
    _reject_duplicate_check_ids(validated)
    return tuple(sorted(validated, key=lambda entry: (entry.order, entry.check_id)))


def list_builtin_verifier_checks() -> list[VerifierCheckCatalogEntry]:
    """Return built-in verifier checklist entries in deterministic catalog order."""
    return list(BUILTIN_VERIFIER_CHECK_CATALOG)


def get_builtin_verifier_check(check_id: str) -> VerifierCheckCatalogEntry:
    """Return one built-in verifier checklist entry by id."""
    for entry in BUILTIN_VERIFIER_CHECK_CATALOG:
        if entry.check_id == check_id:
            return entry
    raise VerifierCheckCatalogNotFoundError(
        f"Unknown built-in verifier check: {check_id}"
    )


def summarize_builtin_verifier_check_catalog() -> VerifierCheckCatalogSummary:
    """Return deterministic read-only summary counts for the built-in catalog."""
    return summarize_verifier_check_catalog(BUILTIN_VERIFIER_CHECK_CATALOG)


def summarize_verifier_check_catalog(
    entries: Sequence[VerifierCheckCatalogEntry | dict[str, object]],
) -> VerifierCheckCatalogSummary:
    """Summarize verifier check catalog entries without executing checks."""
    catalog = validate_verifier_check_catalog(entries)
    required_checks = sum(1 for entry in catalog if entry.required)

    return VerifierCheckCatalogSummary(
        total_checks=len(catalog),
        required_checks=required_checks,
        optional_checks=len(catalog) - required_checks,
        ordered_check_ids=tuple(entry.check_id for entry in catalog),
        category_counts=_count_entries(
            _CHECK_CATEGORY_ORDER,
            (entry.category for entry in catalog),
        ),
        check_type_counts=_count_entries(
            _CHECK_TYPE_ORDER,
            (entry.check_type for entry in catalog),
        ),
        verdict_status_counts=_count_entries(
            _VERDICT_STATUS_ORDER,
            (
                verdict_status
                for entry in catalog
                for verdict_status in entry.verdict_statuses
            ),
        ),
    )


def _reject_duplicate_check_ids(entries: Sequence[VerifierCheckCatalogEntry]) -> None:
    seen: set[str] = set()
    for entry in entries:
        if entry.check_id in seen:
            raise VerifierCheckCatalogError(
                f"duplicate verifier check id: {entry.check_id}"
            )
        seen.add(entry.check_id)


def _count_entries(
    ordered_values: Sequence[str],
    values: Iterable[str],
) -> tuple[VerifierCheckCatalogCount, ...]:
    observed = tuple(values)
    return tuple(
        VerifierCheckCatalogCount(
            value=value,
            count=sum(1 for item in observed if item == value),
        )
        for value in ordered_values
    )


BUILTIN_VERIFIER_CHECK_CATALOG: tuple[VerifierCheckCatalogEntry, ...] = (
    validate_verifier_check_catalog(_BUILTIN_VERIFIER_CHECKS)
)
