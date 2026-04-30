"""Deterministic Hugging Face Jobs compute-risk metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agent.tools.jobs_tool import CPU_FLAVORS, GPU_FLAVORS, SPECIALIZED_FLAVORS

HardwareCategory = Literal[
    "cpu",
    "single_gpu",
    "multi_gpu",
    "specialized",
    "unknown",
]
RiskTier = Literal["read_only", "medium", "high", "critical", "unknown"]
SpendClass = Literal["none", "nominal", "low", "medium", "high", "unknown"]
DurationSource = Literal["timeout", "default_timeout", "unknown"]

CREATE_OPERATIONS = {"run", "uv", "scheduled run", "scheduled uv"}
DEFAULT_TIMEOUT_HOURS = 0.5
DEFAULT_TIMEOUT_TEXT = "30m"

MULTI_GPU_FLAVORS = {
    flavor
    for flavor in GPU_FLAVORS
    if flavor.endswith(("x2", "x4", "x8"))
    or flavor.endswith(("largex2", "largex4"))
}
SINGLE_GPU_FLAVORS = set(GPU_FLAVORS) - MULTI_GPU_FLAVORS

# Local snapshot for risk copy only; live billing should use HF hardware APIs.
HOURLY_PRICE_USD = {
    "cpu-basic": 0.01,
    "cpu-upgrade": 0.03,
    "t4-small": 0.40,
    "t4-medium": 0.60,
    "a10g-small": 1.00,
    "a10g-large": 1.50,
    "a10g-largex2": 3.00,
    "a10g-largex4": 5.00,
    "a100-large": 2.50,
    "a100x4": 10.00,
    "a100x8": 20.00,
    "l4x1": 0.80,
    "l4x4": 3.80,
    "l40sx1": 1.80,
    "l40sx4": 8.30,
    "l40sx8": 23.50,
}


@dataclass(frozen=True)
class HfComputeRisk:
    """Normalized, local-only compute risk metadata for HF Jobs."""

    operation: str
    hardware_flavor: str | None
    hardware_category: HardwareCategory
    risk_tier: RiskTier
    spend_class: SpendClass
    budget_impact: str
    duration_estimate: str | None
    duration_source: DurationSource
    is_scheduled: bool
    uncertainty_flags: tuple[str, ...]
    approval_metadata_visible: bool
    estimated_cost_usd: float | None = None

    @property
    def show_approval_metadata(self) -> bool:
        """Compatibility alias for approval metadata visibility."""

        return self.approval_metadata_visible


def assess_hf_compute_risk(tool_args: dict[str, Any] | None) -> HfComputeRisk:
    """Return deterministic HF Jobs compute-risk metadata from local arguments."""

    args = tool_args or {}
    operation = _normalize_text(args.get("operation")) or ""
    is_create = operation in CREATE_OPERATIONS
    is_scheduled = operation.startswith("scheduled ")
    flavor, flavor_flags = _resolve_flavor(args)

    if not is_create:
        return HfComputeRisk(
            operation=operation,
            hardware_flavor=flavor,
            hardware_category=_classify_flavor(flavor),
            risk_tier="read_only",
            spend_class="none",
            budget_impact="None.",
            duration_estimate=None,
            duration_source="unknown",
            is_scheduled=is_scheduled,
            uncertainty_flags=flavor_flags,
            approval_metadata_visible=False,
        )

    category = _classify_flavor(flavor)
    duration_hours, duration_text, duration_source, duration_flags = (
        _resolve_duration(args)
    )
    risk_tier = _risk_tier(category, is_scheduled)
    spend_class = _spend_class(category, is_scheduled, duration_hours, flavor)
    estimated_cost = _estimated_cost(flavor, duration_hours)
    uncertainty_flags = _uncertainty_flags(
        flavor_flags,
        duration_flags,
        category,
        flavor,
        is_scheduled,
    )

    return HfComputeRisk(
        operation=operation,
        hardware_flavor=flavor,
        hardware_category=category,
        risk_tier=risk_tier,
        spend_class=spend_class,
        budget_impact=_budget_impact(
            flavor=flavor,
            category=category,
            duration_text=duration_text,
            duration_source=duration_source,
            estimated_cost=estimated_cost,
            is_scheduled=is_scheduled,
        ),
        duration_estimate=duration_text,
        duration_source=duration_source,
        is_scheduled=is_scheduled,
        uncertainty_flags=uncertainty_flags,
        approval_metadata_visible=True,
        estimated_cost_usd=estimated_cost,
    )


def _resolve_flavor(args: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    values = [
        _normalize_text(args.get(key))
        for key in ("hardware_flavor", "flavor", "hardware")
    ]
    nonempty = [value for value in values if value]
    flags: list[str] = []
    if not nonempty:
        flags.append("missing_hardware")
        return None, tuple(flags)
    if len(set(nonempty)) > 1:
        flags.append("hardware_alias_conflict")
    return nonempty[0], tuple(flags)


def _classify_flavor(flavor: str | None) -> HardwareCategory:
    if flavor in CPU_FLAVORS:
        return "cpu"
    if flavor in SINGLE_GPU_FLAVORS:
        return "single_gpu"
    if flavor in MULTI_GPU_FLAVORS:
        return "multi_gpu"
    if flavor in SPECIALIZED_FLAVORS:
        return "specialized"
    return "unknown"


def _resolve_duration(
    args: dict[str, Any],
) -> tuple[float, str, DurationSource, tuple[str, ...]]:
    timeout = _normalize_text(args.get("timeout"))
    if timeout:
        parsed = _parse_duration_hours(timeout)
        if parsed is not None:
            return parsed, timeout, "timeout", ()
        return DEFAULT_TIMEOUT_HOURS, timeout, "timeout", ("unparsed_timeout",)
    return (
        DEFAULT_TIMEOUT_HOURS,
        DEFAULT_TIMEOUT_TEXT,
        "default_timeout",
        ("default_duration",),
    )


def _risk_tier(category: HardwareCategory, is_scheduled: bool) -> RiskTier:
    if category == "cpu":
        return "high" if is_scheduled else "medium"
    if category == "single_gpu":
        return "high"
    if category in {"multi_gpu", "specialized"}:
        return "critical"
    return "unknown"


def _spend_class(
    category: HardwareCategory,
    is_scheduled: bool,
    duration_hours: float,
    flavor: str | None,
) -> SpendClass:
    if category == "unknown" or _known_flavor_without_price(flavor):
        return "high" if is_scheduled else "unknown"
    if category == "multi_gpu":
        return "high"
    if category == "specialized":
        return "high" if is_scheduled else "unknown"
    if category == "cpu":
        return "medium" if is_scheduled else "nominal"
    if is_scheduled:
        return "medium"
    return "medium" if duration_hours >= 1 else "low"


def _estimated_cost(flavor: str | None, duration_hours: float) -> float | None:
    hourly = HOURLY_PRICE_USD.get(flavor or "")
    if hourly is None:
        return None
    return round(hourly * duration_hours, 2)


def _uncertainty_flags(
    flavor_flags: tuple[str, ...],
    duration_flags: tuple[str, ...],
    category: HardwareCategory,
    flavor: str | None,
    is_scheduled: bool,
) -> tuple[str, ...]:
    flags = list(flavor_flags)
    flags.extend(duration_flags)
    if category == "unknown":
        flags.append("unknown_hardware")
    if _known_flavor_without_price(flavor):
        flags.append("missing_price")
    if is_scheduled:
        flags.append("recurrence_multiplier_unknown")
    return tuple(dict.fromkeys(flags))


def _budget_impact(
    *,
    flavor: str | None,
    category: HardwareCategory,
    duration_text: str,
    duration_source: DurationSource,
    estimated_cost: float | None,
    is_scheduled: bool,
) -> str:
    if category == "unknown":
        return (
            "Unknown HF compute spend; hardware is missing or not recognized in "
            "the local flavor list."
        )
    if estimated_cost is None:
        return (
            f"{flavor} is recognized as {category}, but local pricing is unavailable; "
            "confirm HF billing before launch."
        )

    estimate_note = (
        f"about ${estimated_cost:.2f} for {duration_text}"
        if duration_source == "timeout"
        else f"about ${estimated_cost:.2f} for the HF default {duration_text}"
    )
    recurrence = (
        " Recurring schedule may multiply spend until suspended or deleted."
        if is_scheduled
        else ""
    )
    return f"Estimated {flavor} {category} spend: {estimate_note}.{recurrence}"


def _known_flavor_without_price(flavor: str | None) -> bool:
    if flavor is None:
        return False
    known_flavors = set(CPU_FLAVORS) | set(GPU_FLAVORS) | set(SPECIALIZED_FLAVORS)
    return flavor in known_flavors and flavor not in HOURLY_PRICE_USD


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _parse_duration_hours(value: str) -> float | None:
    unit = value[-1:]
    amount_text = value[:-1] if unit.isalpha() else value
    try:
        amount = float(amount_text)
    except ValueError:
        return None

    if amount < 0:
        return None
    if unit == "s":
        return amount / 3600
    if unit == "m":
        return amount / 60
    if unit == "h" or not unit.isalpha():
        return amount
    if unit == "d":
        return amount * 24
    return None
