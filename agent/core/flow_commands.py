"""Read-only CLI renderers for flow template commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class FlowCommandError(RuntimeError):
    """Raised when flow command data cannot be read safely."""


class FlowCommandBackendUnavailable(FlowCommandError):
    """Raised when backend flow helpers are not importable from the CLI."""


@dataclass(frozen=True, slots=True)
class _FlowHelpers:
    build_flow_catalog_item: Any
    build_flow_preview: Any
    flow_template_error: type[Exception]
    flow_template_not_found_error: type[Exception]
    get_builtin_flow_template: Any
    list_builtin_flow_templates: Any


def render_flow_command(command: str, arguments: str = "") -> str:
    """Render a supported read-only flow command."""

    if command == "/flows":
        return render_flow_catalog()
    if command == "/flow preview":
        return render_flow_preview(arguments)
    raise ValueError(f"Unsupported flow command: {command}")


def render_flow_catalog() -> str:
    """Render built-in flow templates and current flow command status."""

    helpers = _load_flow_helpers()
    try:
        catalog = [
            helpers.build_flow_catalog_item(template)
            for template in helpers.list_builtin_flow_templates()
        ]
    except helpers.flow_template_error as exc:
        return f"Unable to load built-in flows: {exc}"

    lines = ["Built-in flows"]
    for item in catalog:
        metadata = item["metadata"]
        required_inputs = ", ".join(item["required_inputs"]) or "-"
        lines.append(
            "  "
            f"{item['id']}  "
            f"{metadata['category']}  "
            f"phases:{item['phase_count']}  "
            f"inputs:{required_inputs}  "
            f"approvals:{item['approval_point_count']}  "
            f"verifiers:{item['verifier_count']}"
        )

    lines.extend(
        [
            "",
            "Flow commands",
            "  /flows                 implemented read-only",
            "  /flow preview <id>     implemented read-only",
            "  /flow start <id>       planned",
            "  /flow pause [id]       planned",
            "  /flow resume [id]      planned",
            "  /flow fork <id> [name] planned",
        ]
    )
    return "\n".join(lines)


def render_flow_preview(template_id: str) -> str:
    """Render a read-only preview for one built-in flow template."""

    template_id = template_id.strip()
    if not template_id:
        return "Usage: /flow preview <id>\nRun /flows to list built-in flow ids."

    helpers = _load_flow_helpers()
    try:
        template = helpers.get_builtin_flow_template(template_id)
        preview = helpers.build_flow_preview(template)
    except helpers.flow_template_not_found_error as exc:
        return _render_missing_flow(template_id, str(exc), helpers)
    except helpers.flow_template_error as exc:
        return f"Unable to load flow preview: {exc}"

    metadata = preview["metadata"]
    source = preview["template_source"]
    lines = [
        f"Flow: {preview['name']} ({preview['id']}, {preview['version']})",
        f"Category: {metadata['category']}  Runtime: {metadata['runtime_class']}",
        f"Tags: {', '.join(metadata['tags'])}",
        f"Source: {source['path']}",
    ]
    if preview.get("description"):
        lines.append(f"Description: {preview['description']}")

    lines.extend(["", "Inputs"])
    lines.extend(_format_inputs(preview["inputs"]))

    lines.extend(["", "Budgets", f"  {_format_budgets(preview['budgets'])}"])

    lines.extend(["", "Phases"])
    lines.extend(_format_phases(preview["phases"]))

    lines.extend(["", "Approvals"])
    lines.extend(_format_approvals(preview["approval_points"]))

    lines.extend(["", "Verifiers"])
    lines.extend(_format_verifiers(preview["verifier_checks"]))

    lines.extend(["", "Verifier catalog coverage"])
    lines.extend(
        _format_verifier_catalog_coverage(preview.get("verifier_catalog_coverage"))
    )

    return "\n".join(lines)


def _load_flow_helpers() -> _FlowHelpers:
    try:
        from backend.flow_templates import (
            FlowTemplateError,
            FlowTemplateNotFoundError,
            build_flow_catalog_item,
            build_flow_preview,
            get_builtin_flow_template,
            list_builtin_flow_templates,
        )
    except ModuleNotFoundError as exc:
        if exc.name in {"backend", "backend.flow_templates"}:
            raise FlowCommandBackendUnavailable(
                "Flow template helpers are unavailable from this CLI package. "
                "Run from the source tree or package backend.flow_templates with the CLI."
            ) from exc
        raise

    return _FlowHelpers(
        build_flow_catalog_item=build_flow_catalog_item,
        build_flow_preview=build_flow_preview,
        flow_template_error=FlowTemplateError,
        flow_template_not_found_error=FlowTemplateNotFoundError,
        get_builtin_flow_template=get_builtin_flow_template,
        list_builtin_flow_templates=list_builtin_flow_templates,
    )


def _render_missing_flow(template_id: str, message: str, helpers: _FlowHelpers) -> str:
    try:
        known_ids = [
            helpers.build_flow_catalog_item(template)["id"]
            for template in helpers.list_builtin_flow_templates()
        ]
    except helpers.flow_template_error:
        known_ids = []

    lines = [f"Flow not found: {template_id}", message]
    if known_ids:
        lines.append(f"Known flows: {', '.join(known_ids)}")
    return "\n".join(lines)


def _format_inputs(inputs: list[dict[str, Any]]) -> list[str]:
    if not inputs:
        return ["  -"]
    lines: list[str] = []
    for input_ in inputs:
        required = "required" if input_["required"] else "optional"
        default = _format_default(input_.get("default"))
        suffix = f", default:{default}" if default else ""
        description = input_.get("description")
        line = f"  {input_['id']} ({input_['type']}, {required}{suffix})"
        if description:
            line += f" - {description}"
        lines.append(line)
    return lines


def _format_budgets(budgets: dict[str, Any]) -> str:
    labels = {
        "max_gpu_hours": "gpu_h",
        "max_runs": "runs",
        "max_wall_clock_hours": "wall_h",
        "max_llm_usd": "llm_usd",
    }
    parts = [
        f"{label}:{_format_value(budgets.get(key))}"
        for key, label in labels.items()
        if budgets.get(key) is not None
    ]
    return ", ".join(parts) if parts else "-"


def _format_phases(phases: list[dict[str, Any]]) -> list[str]:
    if not phases:
        return ["  -"]
    lines: list[str] = []
    for phase in phases:
        lines.append(
            f"  {phase['order']}. {phase['id']} - {phase['name']} "
            f"[{phase['status']}]"
        )
        lines.append(f"     objective: {phase['objective']}")
        lines.append(
            "     outputs: "
            + _format_id_list(phase.get("required_outputs", []))
        )
        lines.append(
            "     approvals: "
            + _format_id_list(phase.get("approval_points", []))
        )
        lines.append(
            "     verifiers: "
            + _format_id_list(phase.get("verifiers", []))
        )
    return lines


def _format_approvals(approvals: list[dict[str, Any]]) -> list[str]:
    if not approvals:
        return ["  -"]
    lines: list[str] = []
    for approval in approvals:
        line = (
            f"  {approval['id']} ({approval['risk']}) "
            f"{approval['action']} {approval['target']}  "
            f"phases:{_format_id_list(approval.get('phase_ids', []))}"
        )
        if approval.get("description"):
            line += f" - {approval['description']}"
        lines.append(line)
    return lines


def _format_verifiers(verifiers: list[dict[str, Any]]) -> list[str]:
    if not verifiers:
        return ["  -"]
    lines: list[str] = []
    for verifier in verifiers:
        required = "required" if verifier.get("required") else "optional"
        lines.append(
            f"  {verifier.get('id', '-')} ({verifier.get('type', '-')}, {required}) "
            f"phases:{_format_id_list(verifier.get('phase_ids', []))} - "
            f"{verifier.get('description') or '-'}"
        )
        lines.append(f"     catalog: {_format_verifier_catalog_mapping(verifier)}")
    return lines


def _format_verifier_catalog_mapping(verifier: dict[str, Any]) -> str:
    status = verifier.get("mapping_status")
    if not status:
        return "metadata unavailable"

    catalog_check_id = verifier.get("catalog_check_id")
    if not catalog_check_id:
        return f"status:{status} id:-"

    parts = [
        f"status:{status}",
        f"id:{catalog_check_id}",
    ]
    name = verifier.get("catalog_check_name")
    if name:
        parts.append(f"name:{name}")
    category = verifier.get("catalog_check_category")
    check_type = verifier.get("catalog_check_type")
    if category or check_type:
        parts.append(
            "kind:"
            + "/".join(
                item
                for item in [
                    _format_optional_value(category),
                    _format_optional_value(check_type),
                ]
                if item != "-"
            )
        )
    evidence_ref_types = verifier.get("catalog_evidence_ref_types")
    if isinstance(evidence_ref_types, list):
        parts.append(f"evidence:{_format_id_list(evidence_ref_types)}")
    return "  ".join(parts)


def _format_verifier_catalog_coverage(coverage: dict[str, Any] | None) -> list[str]:
    if not coverage:
        return ["  metadata unavailable"]

    verifier_count = _format_optional_value(coverage.get("verifier_count"))
    mapped_count = _format_optional_value(coverage.get("mapped_count"))
    unmapped_count = _format_optional_value(coverage.get("unmapped_count"))
    intentional_ids = coverage.get("intentional_unmapped_verifier_ids")
    unknown_ids = coverage.get("unknown_unmapped_verifier_ids")
    return [
        (
            "  "
            f"mapped:{mapped_count}/{verifier_count}  "
            f"unmapped:{unmapped_count}  "
            f"intentional:{_format_id_list(_list_or_empty(intentional_ids))}  "
            f"unknown:{_format_id_list(_list_or_empty(unknown_ids))}"
        )
    ]


def _list_or_empty(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _format_id_list(ids: list[str]) -> str:
    return ", ".join(ids) if ids else "-"


def _format_default(default: Any) -> str:
    if default is None:
        return ""
    return _format_value(default)


def _format_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_optional_value(value: Any) -> str:
    if value is None:
        return "-"
    return _format_value(value)
