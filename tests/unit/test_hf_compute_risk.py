"""HF Jobs compute-risk helper tests."""

from __future__ import annotations

from agent.core.hf_compute_risk import assess_hf_compute_risk


def test_cpu_run_is_medium_nominal_compute_risk() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "run", "hardware_flavor": "cpu-basic", "timeout": "30m"}
    )

    assert risk.hardware_flavor == "cpu-basic"
    assert risk.hardware_category == "cpu"
    assert risk.risk_tier == "medium"
    assert risk.spend_class == "nominal"
    assert risk.duration_source == "timeout"
    assert risk.is_scheduled is False
    assert risk.approval_metadata_visible is True
    assert risk.show_approval_metadata is True
    assert risk.estimated_cost_usd == 0.01
    assert risk.uncertainty_flags == ()


def test_single_gpu_run_is_high_low_compute_risk_with_default_duration() -> None:
    risk = assess_hf_compute_risk({"operation": "uv", "flavor": "a10g-large"})

    assert risk.hardware_flavor == "a10g-large"
    assert risk.hardware_category == "single_gpu"
    assert risk.risk_tier == "high"
    assert risk.spend_class == "low"
    assert risk.duration_estimate == "30m"
    assert risk.duration_source == "default_timeout"
    assert risk.estimated_cost_usd == 0.75
    assert "default_duration" in risk.uncertainty_flags
    assert "a10g-large" in risk.budget_impact


def test_multi_gpu_run_is_critical_high_compute_risk() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "run", "hardware": "a100x8", "timeout": "2h"}
    )

    assert risk.hardware_flavor == "a100x8"
    assert risk.hardware_category == "multi_gpu"
    assert risk.risk_tier == "critical"
    assert risk.spend_class == "high"
    assert risk.duration_source == "timeout"
    assert risk.estimated_cost_usd == 40.0
    assert "about $40.00" in risk.budget_impact


def test_multi_gpu_uses_corrected_local_price_for_listed_flavor() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "run", "hardware_flavor": "l40sx4", "timeout": "2h"}
    )

    assert risk.hardware_category == "multi_gpu"
    assert risk.estimated_cost_usd == 16.60
    assert "about $16.60" in risk.budget_impact


def test_specialized_hardware_is_critical_with_missing_price_uncertainty() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "run", "hardware_flavor": "inf2x6", "timeout": "1h"}
    )

    assert risk.hardware_flavor == "inf2x6"
    assert risk.hardware_category == "specialized"
    assert risk.risk_tier == "critical"
    assert risk.spend_class == "unknown"
    assert risk.estimated_cost_usd is None
    assert "missing_price" in risk.uncertainty_flags
    assert "pricing is unavailable" in risk.budget_impact


def test_scheduled_cpu_elevates_risk_and_marks_recurring_spend() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "scheduled run", "hardware_flavor": "cpu-upgrade"}
    )

    assert risk.hardware_category == "cpu"
    assert risk.risk_tier == "high"
    assert risk.spend_class == "medium"
    assert risk.is_scheduled is True
    assert "recurrence_multiplier_unknown" in risk.uncertainty_flags
    assert "Recurring schedule" in risk.budget_impact


def test_unknown_hardware_is_not_downgraded_to_cpu() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "run", "hardware_flavor": "future-h200x8", "timeout": "1h"}
    )

    assert risk.hardware_flavor == "future-h200x8"
    assert risk.hardware_category == "unknown"
    assert risk.risk_tier == "unknown"
    assert risk.spend_class == "unknown"
    assert risk.estimated_cost_usd is None
    assert "unknown_hardware" in risk.uncertainty_flags
    assert "Unknown HF compute spend" in risk.budget_impact


def test_missing_and_empty_flavor_are_unknown_for_creation_operations() -> None:
    missing = assess_hf_compute_risk({"operation": "run"})
    empty = assess_hf_compute_risk({"operation": "run", "hardware_flavor": "  "})

    for risk in (missing, empty):
        assert risk.hardware_flavor is None
        assert risk.hardware_category == "unknown"
        assert risk.risk_tier == "unknown"
        assert risk.spend_class == "unknown"
        assert "missing_hardware" in risk.uncertainty_flags
        assert "unknown_hardware" in risk.uncertainty_flags


def test_read_status_operation_is_read_only_and_hides_approval_metadata() -> None:
    risk = assess_hf_compute_risk(
        {"operation": "logs", "hardware_flavor": "a100x8", "timeout": "8h"}
    )

    assert risk.hardware_flavor == "a100x8"
    assert risk.hardware_category == "multi_gpu"
    assert risk.risk_tier == "read_only"
    assert risk.spend_class == "none"
    assert risk.budget_impact == "None."
    assert risk.duration_source == "unknown"
    assert risk.approval_metadata_visible is False
    assert risk.show_approval_metadata is False
    assert risk.estimated_cost_usd is None


def test_helper_is_pure_and_deterministic() -> None:
    args = {"operation": "run", "hardware_flavor": "t4-small", "timeout": "45m"}
    original = dict(args)

    first = assess_hf_compute_risk(args)
    second = assess_hf_compute_risk(args)

    assert args == original
    assert first == second
