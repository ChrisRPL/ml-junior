from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


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
    "dataset-audit": {
        "category": "data",
        "runtime_class": "data_audit",
        "tags": ["datasets", "lineage", "quality", "privacy"],
    },
    "fine-tune-model": {
        "category": "training",
        "runtime_class": "training",
        "tags": ["fine-tuning", "datasets", "evaluation", "hub"],
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
    path = BUILTIN_FLOW_TEMPLATE_DIR / f"{template.id}.json"
    try:
        relative_path = path.relative_to(Path(__file__).resolve().parent.parent)
    except ValueError:
        source_path = path.as_posix()
    else:
        source_path = relative_path.as_posix()

    return {
        "kind": "builtin",
        "path": source_path,
        "schema_version": SUPPORTED_SCHEMA_VERSION,
        "template_version": template.version,
    }


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


__all__ = [
    "ApprovalPoint",
    "ArtifactSpec",
    "FlowTemplate",
    "FlowTemplateError",
    "FlowTemplateNotFoundError",
    "RequiredOutput",
    "SUPPORTED_SCHEMA_VERSION",
    "TemplateBudgets",
    "TemplateInput",
    "TemplatePhase",
    "VerifierSpec",
    "build_flow_catalog_item",
    "build_flow_preview",
    "get_builtin_flow_template",
    "load_flow_template",
    "list_builtin_flow_templates",
    "parse_flow_template",
]
