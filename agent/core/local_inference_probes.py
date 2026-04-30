"""Probe descriptors and classification metadata for local inference runtimes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from agent.core.local_inference_endpoints import (
    LocalInferenceConfigError,
    LocalInferenceRuntimeDescriptor,
    supported_local_runtimes,
)


@dataclass(frozen=True)
class LocalInferenceProbeDescriptor:
    runtime_id: str
    probe_type: str
    method: str
    endpoint_path: str
    url: str | None
    expected_model: str | None
    configuration_error: str | None


@dataclass(frozen=True)
class LocalInferenceProbeClassification:
    runtime_id: str
    probe_type: str
    status: str
    message: str
    model_id: str | None = None
    tool_calling: str = "unknown"
    error: str | None = None


LOCAL_INFERENCE_HEALTH_PROBE = "health"
LOCAL_INFERENCE_MODELS_PROBE = "models"
LOCAL_INFERENCE_PROBE_AVAILABLE = "available"
LOCAL_INFERENCE_PROBE_UNAVAILABLE = "unavailable"
LOCAL_INFERENCE_PROBE_CONFIG_ERROR = "config-error"
LOCAL_INFERENCE_PROBE_MODEL_MISSING = "model-missing"
LOCAL_INFERENCE_PROBE_MALFORMED = "malformed"
LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN = "tool-support-unknown"

_LOCAL_INFERENCE_PROBE_METHOD = "GET"
_LOCAL_INFERENCE_PROBE_MODELS_PATH = "/models"


def build_local_inference_probe_descriptors(
    descriptor: LocalInferenceRuntimeDescriptor,
    expected_model: str | None = None,
) -> tuple[LocalInferenceProbeDescriptor, LocalInferenceProbeDescriptor]:
    """Return health and models probe descriptors in stable order."""
    return (
        _build_local_inference_probe_descriptor(
            descriptor, LOCAL_INFERENCE_HEALTH_PROBE, None
        ),
        _build_local_inference_probe_descriptor(
            descriptor, LOCAL_INFERENCE_MODELS_PROBE, expected_model
        ),
    )


def classify_local_inference_probe_result(
    probe: LocalInferenceProbeDescriptor,
    models_payload: Mapping[str, Any] | None = None,
    error: BaseException | str | None = None,
) -> LocalInferenceProbeClassification:
    """Classify a caller-supplied ``/v1/models`` result without probing."""
    if probe.configuration_error:
        return _probe_classification(
            probe,
            LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
            probe.configuration_error,
            model_id=probe.expected_model,
        )
    if not probe.url:
        return _probe_classification(
            probe,
            LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
            "Local inference probe URL is unavailable",
            model_id=probe.expected_model,
        )
    if error is not None:
        message = _format_probe_error(error)
        status = (
            LOCAL_INFERENCE_PROBE_CONFIG_ERROR
            if isinstance(error, LocalInferenceConfigError)
            else LOCAL_INFERENCE_PROBE_UNAVAILABLE
        )
        return _probe_classification(
            probe, status, message, model_id=probe.expected_model, error=message
        )
    if models_payload is None:
        return _probe_classification(
            probe,
            LOCAL_INFERENCE_PROBE_UNAVAILABLE,
            "No /v1/models payload supplied",
            model_id=probe.expected_model,
        )

    entries, malformed = _parse_models_payload(models_payload)
    if malformed is not None:
        return _probe_classification(
            probe,
            LOCAL_INFERENCE_PROBE_MALFORMED,
            malformed,
            model_id=probe.expected_model,
        )

    if probe.probe_type == LOCAL_INFERENCE_HEALTH_PROBE:
        return _probe_classification(
            probe, LOCAL_INFERENCE_PROBE_AVAILABLE, "/v1/models payload is well formed"
        )

    expected_model = probe.expected_model
    if not expected_model:
        return _probe_classification(
            probe, LOCAL_INFERENCE_PROBE_AVAILABLE, "/v1/models payload is well formed"
        )

    model_entry = _find_model_entry(entries, expected_model)
    if model_entry is None:
        return _probe_classification(
            probe,
            LOCAL_INFERENCE_PROBE_MODEL_MISSING,
            f"Model {expected_model!r} was not listed by /v1/models",
            model_id=expected_model,
        )

    listed_model = model_entry["id"]
    tool_calling = _extract_tool_calling_state(model_entry)
    if tool_calling == "unknown":
        return _probe_classification(
            probe,
            LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN,
            (
                f"Model {listed_model!r} is listed, but /v1/models does not "
                "advertise tool-call support"
            ),
            model_id=listed_model,
            tool_calling=tool_calling,
        )

    return _probe_classification(
        probe,
        LOCAL_INFERENCE_PROBE_AVAILABLE,
        f"Model {listed_model!r} is listed by /v1/models",
        model_id=listed_model,
        tool_calling=tool_calling,
    )


def _build_local_inference_probe_descriptor(
    descriptor: LocalInferenceRuntimeDescriptor,
    probe_type: str,
    expected_model: str | None,
) -> LocalInferenceProbeDescriptor:
    url = None
    if descriptor.resolved_base_url and not descriptor.configuration_error:
        url = (
            f"{descriptor.resolved_base_url.rstrip('/')}"
            f"{_LOCAL_INFERENCE_PROBE_MODELS_PATH}"
        )

    return LocalInferenceProbeDescriptor(
        runtime_id=descriptor.runtime_id,
        probe_type=probe_type,
        method=_LOCAL_INFERENCE_PROBE_METHOD,
        endpoint_path=_LOCAL_INFERENCE_PROBE_MODELS_PATH,
        url=url,
        expected_model=expected_model,
        configuration_error=descriptor.configuration_error,
    )


def _probe_classification(
    probe: LocalInferenceProbeDescriptor,
    status: str,
    message: str,
    model_id: str | None = None,
    tool_calling: str = "unknown",
    error: str | None = None,
) -> LocalInferenceProbeClassification:
    return LocalInferenceProbeClassification(
        runtime_id=probe.runtime_id,
        probe_type=probe.probe_type,
        status=status,
        message=message,
        model_id=model_id,
        tool_calling=tool_calling,
        error=error,
    )


def _format_probe_error(error: BaseException | str) -> str:
    if isinstance(error, BaseException):
        return str(error) or error.__class__.__name__
    return str(error)


def _parse_models_payload(
    payload: Mapping[str, Any],
) -> tuple[tuple[Mapping[str, Any], ...], str | None]:
    if not isinstance(payload, Mapping):
        return (), "/v1/models payload must be an object"

    data = payload.get("data")
    if not isinstance(data, list):
        return (), "/v1/models payload data must be a list"

    entries: list[Mapping[str, Any]] = []
    for index, item in enumerate(data):
        if not isinstance(item, Mapping):
            return (), f"/v1/models payload data[{index}] must be an object"
        model_id = item.get("id")
        if not isinstance(model_id, str) or not model_id.strip():
            return (), f"/v1/models payload data[{index}].id must be a string"
        entries.append(item)
    return tuple(entries), None


def _find_model_entry(
    entries: tuple[Mapping[str, Any], ...],
    expected_model: str,
) -> Mapping[str, Any] | None:
    candidates = _model_id_candidates(expected_model)
    for entry in entries:
        model_id = entry["id"]
        if model_id in candidates:
            return entry
    return None


def _model_id_candidates(expected_model: str) -> frozenset[str]:
    candidates = {expected_model}
    parts = expected_model.split("/", 2)
    if (
        len(parts) == 3
        and parts[0] == "local"
        and parts[1] in supported_local_runtimes()
    ):
        candidates.add(parts[2])
    if expected_model.startswith("openai/"):
        candidates.add(expected_model.removeprefix("openai/"))
    return frozenset(candidates)


def _extract_tool_calling_state(model_entry: Mapping[str, Any]) -> str:
    mappings = [model_entry]
    for parent in ("capabilities", "metadata"):
        value = model_entry.get(parent)
        if isinstance(value, Mapping):
            mappings.append(value)

    for mapping in mappings:
        for key in (
            "supports_tools",
            "supports_tool_calls",
            "tool_calling",
            "tool_calls",
            "tools",
        ):
            if key in mapping:
                state = _normalize_tool_support_value(mapping[key])
                if state != "unknown":
                    return state
    return "unknown"


def _normalize_tool_support_value(value: Any) -> str:
    if isinstance(value, bool):
        return "supported" if value else "unsupported"
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "supported", "available", "enabled"}:
            return "supported"
        if normalized in {"false", "no", "unsupported", "unavailable", "disabled"}:
            return "unsupported"
        return "unknown"
    if isinstance(value, list):
        return "supported" if value else "unsupported"
    return "unknown"
