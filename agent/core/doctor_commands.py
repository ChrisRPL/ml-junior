"""Read-only CLI renderers for diagnostic commands."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from agent.core.local_inference import (
    build_local_inference_doctor_report,
    build_local_inference_probe_descriptors,
    classify_local_inference_probe_result,
    describe_local_inference_runtime,
    supported_local_runtimes,
)


class DoctorCommandError(ValueError):
    """Raised when a doctor command cannot be rendered."""


@dataclass(frozen=True, slots=True)
class _LocalInferenceSelection:
    runtime_ids: tuple[str, ...]
    expected_models: dict[str, str]


def render_doctor_command(
    command: str,
    arguments: str = "",
    *,
    config: Any = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Render a supported read-only doctor command."""

    if command == "/doctor local-inference":
        return render_local_inference_doctor(arguments, config=config, env=env)
    raise ValueError(f"Unsupported doctor command: {command}")


def render_local_inference_doctor(
    arguments: str = "",
    *,
    config: Any = None,
    env: Mapping[str, str] | None = None,
) -> str:
    """Render local inference endpoint metadata without probing daemons."""

    try:
        selection = _parse_local_inference_arguments(arguments)
    except DoctorCommandError as exc:
        return f"{exc}\n{_usage()}"

    lines = [
        "Local inference doctor",
        "  mode: read-only metadata; no daemon probe",
    ]
    for runtime_id in selection.runtime_ids:
        runtime = describe_local_inference_runtime(runtime_id, config=config, env=env)
        expected_model = selection.expected_models.get(runtime_id)
        probes = build_local_inference_probe_descriptors(
            runtime,
            expected_model=expected_model,
        )
        classifications = ()
        if runtime.configuration_error:
            classifications = (classify_local_inference_probe_result(probes[1]),)
        report = build_local_inference_doctor_report(
            runtime,
            probes,
            classifications,
        )

        lines.extend(
            [
                "",
                report.runtime_id,
                f"  provider: {report.provider_kind}",
                f"  status: {report.status}",
                f"  host: {report.host_class}",
                f"  models: {report.models_url or '-'}",
                f"  model: {report.model_alias or '-'}",
            ]
        )
        if runtime.configuration_error:
            lines.extend(_format_list("messages", report.redacted_messages))
        lines.extend(_format_list("next", report.remediation_hints))

    return "\n".join(lines)


def _parse_local_inference_arguments(arguments: str) -> _LocalInferenceSelection:
    tokens = tuple(arguments.split())
    runtimes = supported_local_runtimes()
    if not tokens:
        return _LocalInferenceSelection(
            runtime_ids=tuple(sorted(runtimes)),
            expected_models={},
        )

    if len(tokens) > 2:
        raise DoctorCommandError("Too many arguments for /doctor local-inference.")

    first = tokens[0]
    runtime_from_model, model_alias = _parse_local_model_id(first)
    if runtime_from_model:
        if len(tokens) > 1:
            raise DoctorCommandError(
                "Pass either a local model id or runtime plus model alias, not both."
            )
        return _LocalInferenceSelection(
            runtime_ids=(runtime_from_model,),
            expected_models={runtime_from_model: first},
        )

    runtime_id = _normalize_runtime(first)
    if runtime_id not in runtimes:
        raise DoctorCommandError(f"Unknown local inference runtime: {first}")

    expected_models = {}
    if len(tokens) == 2:
        explicit_runtime, explicit_alias = _parse_local_model_id(tokens[1])
        if explicit_runtime and explicit_runtime != runtime_id:
            raise DoctorCommandError(
                "Runtime argument does not match the local model id runtime."
            )
        model_alias = explicit_alias or tokens[1]
        expected_models[runtime_id] = f"local/{runtime_id}/{model_alias}"

    return _LocalInferenceSelection(
        runtime_ids=(runtime_id,),
        expected_models=expected_models,
    )


def _parse_local_model_id(value: str) -> tuple[str | None, str | None]:
    parts = value.split("/", 2)
    if len(parts) == 3 and parts[0] == "local":
        runtime_id = _normalize_runtime(parts[1])
        return runtime_id, parts[2]
    return None, None


def _normalize_runtime(value: str) -> str:
    return value.strip().lower().replace("_", "").replace("-", "")


def _format_list(label: str, values: tuple[str, ...]) -> list[str]:
    if not values:
        return [f"  {label}: -"]
    head, *tail = values
    lines = [f"  {label}: {head}"]
    lines.extend(f"    - {value}" for value in tail)
    return lines


def _usage() -> str:
    return (
        "Usage: /doctor local-inference [ollama|llamacpp] "
        "[local/<runtime>/<model>|model]"
    )
