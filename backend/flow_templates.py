from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from backend.flow_verifier_mapping import (
    FlowVerifierCoverageReport,
    build_flow_verifier_coverage_report,
    get_catalog_check_id_for_flow_verifier,
)
from backend.verifier_check_catalog import get_builtin_verifier_check


SUPPORTED_SCHEMA_VERSION = "v1"
BUILTIN_FLOW_TEMPLATE_DIR = Path(__file__).resolve().parent / "builtin_flow_templates"

InputType = Literal["string", "integer", "number", "boolean", "array", "object"]
PhaseStatus = Literal[
    "not_started",
    "pending",
    "active",
    "blocked",
    "complete",
    "failed",
]
VerifierType = Literal["manual", "metric", "artifact", "command", "llm"]
FlowTemplateSource = Literal["builtin", "custom", "community"]
SUPPORTED_FLOW_TEMPLATE_SOURCES: tuple[FlowTemplateSource, ...] = (
    "builtin",
    "custom",
    "community",
)


class FlowTemplateError(ValueError):
    """Raised when a flow template cannot be loaded or validated."""


class FlowTemplateNotFoundError(FlowTemplateError):
    """Raised when a requested built-in flow template does not exist."""


class _TemplateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TemplateInput(_TemplateModel):
    id: str
    type: InputType
    required: bool = False
    default: Any | None = None
    description: str | None = None


class TemplateBudgets(_TemplateModel):
    max_gpu_hours: float | None = Field(default=None, ge=0)
    max_runs: int | None = Field(default=None, ge=0)
    max_wall_clock_hours: float | None = Field(default=None, ge=0)
    max_llm_usd: float | None = Field(default=None, ge=0)


class ApprovalPoint(_TemplateModel):
    id: str
    risk: str
    action: str
    target: str
    description: str | None = None


class RequiredOutput(_TemplateModel):
    id: str
    type: str
    description: str | None = None
    required: bool = True


class ArtifactSpec(_TemplateModel):
    id: str
    type: str
    description: str | None = None
    required: bool = True


class VerifierSpec(_TemplateModel):
    id: str
    type: VerifierType
    description: str
    required: bool = True


class TemplatePhase(_TemplateModel):
    id: str
    name: str
    objective: str
    status: PhaseStatus
    order: int = Field(ge=0)
    required_outputs: list[str]
    approval_points: list[str]
    verifiers: list[str]


class FlowTemplate(_TemplateModel):
    id: str
    name: str
    version: Literal["v1"]
    source: FlowTemplateSource = "builtin"
    description: str | None = None
    inputs: list[TemplateInput] = Field(default_factory=list)
    budgets: TemplateBudgets = Field(default_factory=TemplateBudgets)
    permissions: list[ApprovalPoint] = Field(default_factory=list)
    approval_points: list[ApprovalPoint] = Field(default_factory=list)
    phases: list[TemplatePhase]
    required_outputs: list[RequiredOutput] = Field(default_factory=list)
    artifacts: list[ArtifactSpec] = Field(default_factory=list)
    verifiers: list[VerifierSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_template(self) -> FlowTemplate:
        if not self.phases:
            raise ValueError("phases must contain at least one phase")

        _raise_on_duplicate_ids("input", [item.id for item in self.inputs])
        _raise_on_duplicate_ids("permission", [item.id for item in self.permissions])
        _raise_on_duplicate_ids("phase", [phase.id for phase in self.phases])
        _raise_on_duplicate_ids(
            "approval point",
            [item.id for item in self.approval_points],
        )
        _raise_on_duplicate_ids(
            "required output",
            [item.id for item in self.required_outputs],
        )
        _raise_on_duplicate_ids("artifact", [item.id for item in self.artifacts])
        _raise_on_duplicate_ids("verifier", [item.id for item in self.verifiers])

        approval_ids = {item.id for item in self.approval_points}
        output_ids = {item.id for item in self.required_outputs}
        verifier_ids = {item.id for item in self.verifiers}

        for phase in self.phases:
            _validate_references(
                label=f"phase {phase.id} approval_points",
                refs=phase.approval_points,
                known=approval_ids,
            )
            _validate_references(
                label=f"phase {phase.id} required_outputs",
                refs=phase.required_outputs,
                known=output_ids,
            )
            _validate_references(
                label=f"phase {phase.id} verifiers",
                refs=phase.verifiers,
                known=verifier_ids,
            )

        return self


_BUILTIN_FLOW_RESPONSE_METADATA: dict[str, dict[str, Any]] = {
    "build-evaluation-harness": {
        "category": "evaluation",
        "runtime_class": "evaluation_harness",
        "tags": ["evaluation", "benchmarks", "metrics", "reliability"],
    },
    "compare-models": {
        "category": "evaluation",
        "runtime_class": "model_comparison",
        "tags": ["evaluation", "models", "comparison", "metrics"],
    },
    "create-model-card": {
        "category": "documentation",
        "runtime_class": "model_card_creation",
        "tags": ["model-cards", "documentation", "metadata", "hub"],
    },
    "dataset-audit": {
        "category": "data",
        "runtime_class": "data_audit",
        "tags": ["datasets", "lineage", "quality", "privacy"],
    },
    "dataset-card-review": {
        "category": "data",
        "runtime_class": "dataset_card_review",
        "tags": ["datasets", "documentation", "cards", "quality"],
    },
    "debug-failed-training-run": {
        "category": "training",
        "runtime_class": "training_debug_review",
        "tags": ["training", "debugging", "logs", "reproducibility"],
    },
    "distill-model": {
        "category": "training",
        "runtime_class": "distillation_review",
        "tags": ["distillation", "models", "evaluation", "packaging"],
    },
    "fine-tune-model": {
        "category": "training",
        "runtime_class": "training",
        "tags": ["fine-tuning", "datasets", "evaluation", "hub"],
    },
    "hyperparameter-sweep": {
        "category": "training",
        "runtime_class": "hyperparameter_sweep",
        "tags": ["experiments", "sweeps", "metrics", "reproducibility"],
    },
    "implement-architecture": {
        "category": "implementation",
        "runtime_class": "code_implementation",
        "tags": ["architecture", "pytorch", "tests", "smoke-training"],
    },
    "literature-overview": {
        "category": "research",
        "runtime_class": "research_synthesis",
        "tags": ["literature", "papers", "synthesis", "citations"],
    },
    "metric-selection-review": {
        "category": "evaluation",
        "runtime_class": "metric_selection_review",
        "tags": ["evaluation", "metrics", "benchmarks", "review"],
    },
    "model-card-refresh": {
        "category": "documentation",
        "runtime_class": "model_card_refresh",
        "tags": ["model-cards", "documentation", "evaluation", "hub"],
    },
    "paper-to-implementation-plan": {
        "category": "research",
        "runtime_class": "implementation_planning",
        "tags": ["papers", "planning", "architecture", "evidence"],
    },
    "publish-to-hub": {
        "category": "packaging",
        "runtime_class": "hub_publication_review",
        "tags": ["hub", "packaging", "model-cards", "artifacts"],
    },
    "rag-evaluation": {
        "category": "evaluation",
        "runtime_class": "rag_evaluation",
        "tags": ["rag", "evaluation", "retrieval", "metrics"],
    },
    "reproduce-paper": {
        "category": "research",
        "runtime_class": "reproduction",
        "tags": ["papers", "reproduction", "experiments", "metrics"],
    },
}


def parse_flow_template(source: Mapping[str, Any] | str | Path) -> FlowTemplate:
    """Parse a flow template mapping or JSON/YAML file."""
    raw = _load_source(source)
    _preflight_template(raw)
    try:
        return FlowTemplate.model_validate(raw)
    except ValidationError as exc:
        raise FlowTemplateError(_format_validation_error(exc)) from exc


def load_flow_template(path: str | Path) -> FlowTemplate:
    """Load and validate a flow template file."""
    return parse_flow_template(path)


def list_builtin_flow_templates() -> list[FlowTemplate]:
    """Load all built-in flow templates in stable id order."""
    return [load_flow_template(path) for path in _builtin_template_paths()]


def list_flow_templates(source: str | None = None) -> list[FlowTemplate]:
    """Load read-only flow templates for a source.

    Custom and community sources are reserved for future catalog backends; they
    are intentionally empty here and do not load from user paths or remotes.
    """
    template_source = _normalize_template_source(source)
    if template_source in {None, "builtin"}:
        return list_builtin_flow_templates()
    return []


def list_flow_template_sources() -> list[dict[str, Any]]:
    """Return stable read-only metadata for supported template sources."""
    builtin_count = len(_builtin_template_paths())
    return [
        {
            "kind": "builtin",
            "label": "Built-in",
            "availability": "available",
            "trust_status": "trusted",
            "loading_status": "enabled",
            "template_count": builtin_count,
            "read_only": True,
            "supports_upload": False,
            "supports_remote_fetch": False,
            "source_path": _builtin_template_source_dir(),
            "description": (
                "Bundled templates loaded from the backend package only."
            ),
        },
        {
            "kind": "custom",
            "label": "Custom",
            "availability": "reserved",
            "trust_status": "untrusted",
            "loading_status": "disabled",
            "template_count": 0,
            "read_only": True,
            "supports_upload": False,
            "supports_remote_fetch": False,
            "source_path": None,
            "description": (
                "Reserved for user-provided templates; loading is disabled."
            ),
        },
        {
            "kind": "community",
            "label": "Community",
            "availability": "reserved",
            "trust_status": "untrusted",
            "loading_status": "disabled",
            "template_count": 0,
            "read_only": True,
            "supports_upload": False,
            "supports_remote_fetch": False,
            "source_path": None,
            "description": (
                "Reserved for curated shared templates; remote fetch is disabled."
            ),
        },
    ]


def get_builtin_flow_template(template_id: str) -> FlowTemplate:
    """Load one built-in flow template by id."""
    path = _builtin_template_path(template_id)
    if path is None:
        raise FlowTemplateNotFoundError(
            f"Unknown built-in flow template: {template_id}"
        )
    return load_flow_template(path)


def build_flow_catalog_item(template: FlowTemplate) -> dict[str, Any]:
    """Build the read-only catalog DTO payload for a template."""
    return {
        "id": template.id,
        "name": template.name,
        "version": template.version,
        "description": template.description,
        "metadata": _response_metadata(template.id),
        "template_source": _template_source_metadata(template),
        "phase_count": len(template.phases),
        "required_inputs": [
            input_.id
            for input_ in template.inputs
            if input_.required
        ],
        "approval_point_count": len(template.approval_points),
        "verifier_count": len(template.verifiers),
    }


def build_flow_preview(template: FlowTemplate) -> dict[str, Any]:
    """Build the read-only preview DTO payload for a template."""
    phase_ids_by_approval = _phase_ids_by_reference(template, "approval_points")
    phase_ids_by_output = _phase_ids_by_reference(template, "required_outputs")
    phase_ids_by_verifier = _phase_ids_by_reference(template, "verifiers")
    verifier_coverage = build_flow_verifier_coverage_report(
        verifier.id for verifier in template.verifiers
    )

    approval_points = [
        {
            **approval.model_dump(),
            "phase_ids": phase_ids_by_approval.get(approval.id, []),
        }
        for approval in template.approval_points
    ]
    required_outputs = [
        {
            **output.model_dump(),
            "phase_ids": phase_ids_by_output.get(output.id, []),
        }
        for output in template.required_outputs
    ]
    verifier_checks = [
        {
            **verifier.model_dump(),
            "phase_ids": phase_ids_by_verifier.get(verifier.id, []),
            **_verifier_catalog_metadata(verifier.id, verifier_coverage),
        }
        for verifier in template.verifiers
    ]

    return {
        "id": template.id,
        "name": template.name,
        "version": template.version,
        "description": template.description,
        "metadata": _response_metadata(template.id),
        "template_source": _template_source_metadata(template),
        "inputs": [input_.model_dump() for input_ in template.inputs],
        "required_inputs": [
            input_.model_dump()
            for input_ in template.inputs
            if input_.required
        ],
        "budgets": template.budgets.model_dump(),
        "phases": [
            phase.model_dump()
            for phase in sorted(template.phases, key=lambda phase: phase.order)
        ],
        "approval_points": approval_points,
        "required_outputs": required_outputs,
        "artifacts": [artifact.model_dump() for artifact in template.artifacts],
        "verifier_checks": verifier_checks,
        "verifier_catalog_coverage": {
            "verifier_count": verifier_coverage.verifier_count,
            "mapped_count": verifier_coverage.mapped_count,
            "unmapped_count": verifier_coverage.unmapped_count,
            "intentional_unmapped_verifier_ids": list(
                verifier_coverage.intentional_unmapped_verifier_ids
            ),
            "unknown_unmapped_verifier_ids": list(
                verifier_coverage.unknown_unmapped_verifier_ids
            ),
        },
        "risky_operations": _risky_operations(template, phase_ids_by_approval),
    }


def _load_source(source: Mapping[str, Any] | str | Path) -> Mapping[str, Any]:
    if isinstance(source, Mapping):
        return source

    path = Path(source)
    if path.suffix == ".json":
        try:
            loaded = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            raise FlowTemplateError(f"Invalid JSON flow template: {exc}") from exc
    elif path.suffix in {".yaml", ".yml"}:
        loaded = _load_yaml(path)
    else:
        raise FlowTemplateError(
            "Unsupported flow template file extension "
            f"{path.suffix!r}; use .json, .yaml, or .yml"
        )

    if not isinstance(loaded, Mapping):
        raise FlowTemplateError("Flow template root must be an object")
    return loaded


def _builtin_template_paths() -> list[Path]:
    paths = sorted(BUILTIN_FLOW_TEMPLATE_DIR.glob("*.json"))
    template_ids = {path.stem for path in paths}
    missing_metadata = template_ids - set(_BUILTIN_FLOW_RESPONSE_METADATA)
    if missing_metadata:
        raise FlowTemplateError(
            "Missing built-in flow response metadata for: "
            + ", ".join(sorted(missing_metadata))
        )
    stale_metadata = set(_BUILTIN_FLOW_RESPONSE_METADATA) - template_ids
    if stale_metadata:
        raise FlowTemplateError(
            "Built-in flow response metadata references missing templates: "
            + ", ".join(sorted(stale_metadata))
        )
    return paths


def _builtin_template_path(template_id: str) -> Path | None:
    if template_id not in _BUILTIN_FLOW_RESPONSE_METADATA:
        return None
    path = BUILTIN_FLOW_TEMPLATE_DIR / f"{template_id}.json"
    if not path.exists():
        raise FlowTemplateError(
            f"Built-in flow template file is missing: {path.name}"
        )
    return path


def _response_metadata(template_id: str) -> dict[str, Any]:
    metadata = _BUILTIN_FLOW_RESPONSE_METADATA.get(template_id)
    if metadata is None:
        raise FlowTemplateError(
            f"Missing built-in flow response metadata for: {template_id}"
        )
    return {
        "category": metadata["category"],
        "runtime_class": metadata["runtime_class"],
        "tags": list(metadata["tags"]),
    }


def _template_source_metadata(template: FlowTemplate) -> dict[str, str]:
    source_path = ""
    if template.source == "builtin":
        source_path = _builtin_template_source_path(template.id)

    return {
        "kind": template.source,
        "path": source_path,
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "template_version": template.version,
    }


def _builtin_template_source_path(template_id: str) -> str:
    path = BUILTIN_FLOW_TEMPLATE_DIR / f"{template_id}.json"
    return _relative_backend_path(path)


def _builtin_template_source_dir() -> str:
    return _relative_backend_path(BUILTIN_FLOW_TEMPLATE_DIR)


def _relative_backend_path(path: Path) -> str:
    try:
        relative_path = path.relative_to(Path(__file__).resolve().parent.parent)
    except ValueError:
        return path.as_posix()
    return relative_path.as_posix()


def _normalize_template_source(source: str | None) -> FlowTemplateSource | None:
    if source is None:
        return None
    if source in SUPPORTED_FLOW_TEMPLATE_SOURCES:
        return cast(FlowTemplateSource, source)
    supported = ", ".join(SUPPORTED_FLOW_TEMPLATE_SOURCES)
    raise FlowTemplateError(
        f"Unsupported flow template source {source!r}; "
        f"supported sources: {supported}"
    )


def _phase_ids_by_reference(
    template: FlowTemplate,
    reference_field: Literal["approval_points", "required_outputs", "verifiers"],
) -> dict[str, list[str]]:
    phase_ids: dict[str, list[str]] = {}
    for phase in sorted(template.phases, key=lambda item: item.order):
        for reference_id in getattr(phase, reference_field):
            phase_ids.setdefault(reference_id, []).append(phase.id)
    return phase_ids


def _risky_operations(
    template: FlowTemplate,
    phase_ids_by_approval: dict[str, list[str]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": approval.id,
            "risk": approval.risk,
            "action": approval.action,
            "target": approval.target,
            "description": approval.description,
            "source": "approval_point",
            "phase_ids": phase_ids_by_approval.get(approval.id, []),
        }
        for approval in template.approval_points
    ]


def _verifier_catalog_metadata(
    verifier_id: str,
    coverage_report: FlowVerifierCoverageReport,
) -> dict[str, Any]:
    catalog_check_id = get_catalog_check_id_for_flow_verifier(verifier_id)
    if catalog_check_id is None:
        intentional_unmapped = (
            verifier_id in coverage_report.intentional_unmapped_verifier_ids
        )
        return {
            "mapping_status": (
                "intentional_unmapped"
                if intentional_unmapped
                else "unknown_unmapped"
            ),
            "catalog_check_id": None,
            "catalog_check_name": None,
            "catalog_check_category": None,
            "catalog_check_type": None,
            "catalog_evidence_ref_types": [],
        }

    catalog_check = get_builtin_verifier_check(catalog_check_id)
    return {
        "mapping_status": "mapped",
        "catalog_check_id": catalog_check.check_id,
        "catalog_check_name": catalog_check.name,
        "catalog_check_category": catalog_check.category,
        "catalog_check_type": catalog_check.check_type,
        "catalog_evidence_ref_types": [
            requirement.ref_type
            for requirement in catalog_check.evidence_requirements
        ],
    }


def _load_yaml(path: Path) -> Any:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise FlowTemplateError(
            "YAML flow templates require PyYAML to be installed"
        ) from exc

    return yaml.safe_load(path.read_text())


def _preflight_template(raw: Mapping[str, Any]) -> None:
    if "version" not in raw:
        raise FlowTemplateError("Flow template version is required")
    if raw["version"] != SUPPORTED_SCHEMA_VERSION:
        raise FlowTemplateError(
            "Unsupported schema version "
            f"{raw['version']!r}; supported version: {SUPPORTED_SCHEMA_VERSION}"
        )


def _raise_on_duplicate_ids(label: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for item_id in ids:
        if item_id in seen:
            raise ValueError(f"duplicate {label} id: {item_id}")
        seen.add(item_id)


def _validate_references(label: str, refs: list[str], known: set[str]) -> None:
    for ref in refs:
        if ref not in known:
            raise ValueError(f"unknown {label} reference: {ref}")


def _format_validation_error(exc: ValidationError) -> str:
    errors: list[str] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"]) or "template"
        errors.append(f"{loc}: {error['msg']}")
    return "Invalid flow template: " + "; ".join(errors)


class FlowStartError(FlowTemplateError):
    """Raised when a flow cannot be started from a template."""


def start_flow(
    template: FlowTemplate,
    session_id: str,
    *,
    append_callable: Callable[[Any], Any],
    inputs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Initialize a workflow instance from a flow template.

    Creates the initial phase state, persists a phase.started event through
    the injected append callable, and returns a durable flow handle.

    Args:
        template: Parsed flow template.
        session_id: Target session id.
        append_callable: Event-store append callable (e.g., event_store.append).
        inputs: Optional user-supplied input values.

    Returns:
        Flow handle dictionary with flow_id, session_id, template_id,
        template_version, phase_id, phase_name, status, and started_at.
    """
    if not template.phases:
        raise FlowStartError("template has no phases")

    first_phase = min(template.phases, key=lambda phase: phase.order)
    flow_id = f"flow-{uuid.uuid4().hex}"
    started_at = datetime.now(timezone.utc).isoformat()

    event_data = {
        "session_id": session_id,
        "project_id": session_id,
        "template_id": template.id,
        "template_version": template.version,
        "phase_id": first_phase.id,
        "phase_name": first_phase.name,
        "phase_order": first_phase.order,
        "from_status": "not_started",
        "to_status": "active",
        "allowed": True,
        "flow_id": flow_id,
        "inputs": dict(inputs) if inputs else {},
        "started_at": started_at,
    }

    try:
        from agent.core.events import AgentEvent
    except Exception as exc:
        raise FlowStartError("AgentEvent not available") from exc

    event = AgentEvent(
        session_id=session_id,
        sequence=1,
        event_type="phase.started",
        data=event_data,
    )
    stored_event = append_callable(event)

    if not hasattr(stored_event, "data") or not isinstance(stored_event.data, dict):
        raise FlowStartError("append_callable did not return a valid event")

    return {
        "flow_id": flow_id,
        "session_id": session_id,
        "template_id": template.id,
        "template_version": template.version,
        "phase_id": first_phase.id,
        "phase_name": first_phase.name,
        "status": "active",
        "started_at": started_at,
    }


__all__ = [
    "ApprovalPoint",
    "ArtifactSpec",
    "FlowTemplateSource",
    "FlowTemplate",
    "FlowTemplateError",
    "FlowTemplateNotFoundError",
    "FlowStartError",
    "RequiredOutput",
    "SUPPORTED_SCHEMA_VERSION",
    "SUPPORTED_FLOW_TEMPLATE_SOURCES",
    "TemplateBudgets",
    "TemplateInput",
    "TemplatePhase",
    "VerifierSpec",
    "build_flow_catalog_item",
    "build_flow_preview",
    "get_builtin_flow_template",
    "load_flow_template",
    "list_builtin_flow_templates",
    "list_flow_template_sources",
    "list_flow_templates",
    "parse_flow_template",
    "start_flow",
]
