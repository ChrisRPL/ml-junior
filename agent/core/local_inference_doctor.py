"""Pure report model for planned local inference doctor output."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from collections.abc import Iterable
from urllib.parse import urlsplit

from agent.core.local_inference_endpoints import LocalInferenceRuntimeDescriptor
from agent.core.local_inference_probes import (
    LOCAL_INFERENCE_MODELS_PROBE,
    LOCAL_INFERENCE_PROBE_AVAILABLE,
    LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
    LOCAL_INFERENCE_PROBE_MALFORMED,
    LOCAL_INFERENCE_PROBE_MODEL_MISSING,
    LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN,
    LOCAL_INFERENCE_PROBE_UNAVAILABLE,
    LocalInferenceProbeClassification,
    LocalInferenceProbeDescriptor,
)
from agent.core.redaction import REDACTED, redact_string


@dataclass(frozen=True)
class LocalInferenceDoctorReport:
    runtime_id: str
    provider_kind: str
    model_alias: str | None
    host_class: str
    models_url: str | None
    status: str
    remediation_hints: tuple[str, ...]
    redacted_messages: tuple[str, ...]


LOCAL_INFERENCE_DOCTOR_PROVIDER_KIND = "local-openai-compatible"
LOCAL_INFERENCE_DOCTOR_STATUS_UNKNOWN = "unknown"

_CONTAINER_HOSTS = {"host.docker.internal", "host.containers.internal"}
_STATUS_PRIORITY = {
    LOCAL_INFERENCE_PROBE_CONFIG_ERROR: 60,
    LOCAL_INFERENCE_PROBE_UNAVAILABLE: 50,
    LOCAL_INFERENCE_PROBE_MALFORMED: 40,
    LOCAL_INFERENCE_PROBE_MODEL_MISSING: 30,
    LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN: 20,
    LOCAL_INFERENCE_PROBE_AVAILABLE: 10,
}
_SENSITIVE_BODY_RE = re.compile(
    r"(?im)(\b(?:prompt|request body|response body)\s*[:=]\s*).*$"
)


def build_local_inference_doctor_report(
    runtime: LocalInferenceRuntimeDescriptor,
    probes: Iterable[LocalInferenceProbeDescriptor],
    classifications: Iterable[LocalInferenceProbeClassification],
) -> LocalInferenceDoctorReport:
    """Build planned doctor output from already-supplied local metadata.

    This function deliberately only combines caller-provided descriptors and
    classifications. It does not probe daemons, call providers, mutate config,
    pull models, or perform budget accounting.
    """

    probe_list = tuple(probes)
    classification_list = tuple(classifications)
    models_probe = _select_models_probe(probe_list)
    models_url = _redact_optional(models_probe.url if models_probe else None)
    model_alias = _model_alias(models_probe, classification_list)
    status = _combined_status(classification_list)

    return LocalInferenceDoctorReport(
        runtime_id=runtime.runtime_id,
        provider_kind=LOCAL_INFERENCE_DOCTOR_PROVIDER_KIND,
        model_alias=model_alias,
        host_class=_host_class(models_probe.url if models_probe else None),
        models_url=models_url,
        status=status,
        remediation_hints=_remediation_hints(
            runtime.runtime_id,
            status,
            model_alias=model_alias,
            models_url=models_url,
        ),
        redacted_messages=_redacted_messages(runtime, classification_list),
    )


def _select_models_probe(
    probes: tuple[LocalInferenceProbeDescriptor, ...],
) -> LocalInferenceProbeDescriptor | None:
    for probe in probes:
        if probe.probe_type == LOCAL_INFERENCE_MODELS_PROBE:
            return probe
    return probes[0] if probes else None


def _combined_status(
    classifications: tuple[LocalInferenceProbeClassification, ...],
) -> str:
    if not classifications:
        return LOCAL_INFERENCE_DOCTOR_STATUS_UNKNOWN
    return max(
        (classification.status for classification in classifications),
        key=lambda status: _STATUS_PRIORITY.get(status, 0),
    )


def _model_alias(
    models_probe: LocalInferenceProbeDescriptor | None,
    classifications: tuple[LocalInferenceProbeClassification, ...],
) -> str | None:
    candidates = []
    if models_probe and models_probe.expected_model:
        candidates.append(models_probe.expected_model)
    candidates.extend(
        classification.model_id
        for classification in classifications
        if classification.model_id
    )

    for candidate in candidates:
        if candidate:
            parts = candidate.split("/", 2)
            if len(parts) == 3 and parts[0] == "local":
                return parts[2]
            if candidate.startswith("openai/"):
                return candidate.removeprefix("openai/")
            return candidate
    return None


def _host_class(models_url: str | None) -> str:
    if not models_url:
        return "unavailable"

    parsed = urlsplit(models_url)
    hostname = parsed.hostname
    if not hostname:
        return "invalid"

    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return "localhost"
    if host in _CONTAINER_HOSTS:
        return "container-host"

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "public-host"

    if ip.is_loopback:
        return "localhost"
    if ip.is_private or ip.is_link_local:
        return "private-ip"
    return "public-host"


def _remediation_hints(
    runtime_id: str,
    status: str,
    *,
    model_alias: str | None,
    models_url: str | None,
) -> tuple[str, ...]:
    if status == LOCAL_INFERENCE_PROBE_AVAILABLE:
        return ()
    if status == LOCAL_INFERENCE_PROBE_CONFIG_ERROR:
        return (
            f"Fix local/{runtime_id} base URL config or environment overrides.",
            "Use http(s), localhost/container-host/private-IP hosts, and an empty or /v1 path.",
        )
    if status == LOCAL_INFERENCE_PROBE_UNAVAILABLE:
        return (
            f"Start the {runtime_id} local inference daemon yourself.",
            _with_url("Verify the OpenAI-compatible /v1/models endpoint", models_url),
        )
    if status == LOCAL_INFERENCE_PROBE_MALFORMED:
        return (
            f"Configure {runtime_id} to expose an OpenAI-compatible /v1/models response.",
            "Check the local runtime version and API compatibility settings.",
        )
    if status == LOCAL_INFERENCE_PROBE_MODEL_MISSING:
        alias = model_alias or "the requested model"
        return (
            f"Load or pull model alias {alias!r} in {runtime_id}.",
            f"Or switch to a model id that {runtime_id} lists from /v1/models.",
        )
    if status == LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN:
        alias = model_alias or "the requested model"
        return (
            f"Verify whether {alias!r} supports tool calls in {runtime_id}.",
            "Use a local model/runtime that advertises tool-call support if tools are required.",
        )
    return ("Review the supplied local inference probe classification.",)


def _with_url(prefix: str, url: str | None) -> str:
    if not url:
        return f"{prefix}."
    return f"{prefix}: {url}."


def _redacted_messages(
    runtime: LocalInferenceRuntimeDescriptor,
    classifications: tuple[LocalInferenceProbeClassification, ...],
) -> tuple[str, ...]:
    messages: list[str] = []
    if runtime.configuration_error:
        messages.append(runtime.configuration_error)

    for classification in classifications:
        messages.append(classification.message)
        if classification.error and classification.error != classification.message:
            messages.append(classification.error)

    return tuple(_dedupe(_redact_message(message) for message in messages if message))


def _redact_message(message: str) -> str:
    redacted_body = _SENSITIVE_BODY_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED}", message
    )
    return redact_string(redacted_body).value


def _redact_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return redact_string(value).value


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
