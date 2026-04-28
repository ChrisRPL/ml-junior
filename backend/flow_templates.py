from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


SUPPORTED_SCHEMA_VERSION = "v1"

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
    "RequiredOutput",
    "SUPPORTED_SCHEMA_VERSION",
    "TemplateBudgets",
    "TemplateInput",
    "TemplatePhase",
    "VerifierSpec",
    "load_flow_template",
    "parse_flow_template",
]
