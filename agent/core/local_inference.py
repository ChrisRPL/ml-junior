"""Pure descriptors and endpoint resolution for local inference runtimes."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit


class LocalInferenceConfigError(ValueError):
    """Invalid local inference endpoint configuration."""


@dataclass(frozen=True)
class LocalInferenceRuntimeCapabilities:
    chat_completions: str = "unknown"
    streaming: str = "unknown"
    tool_calling: str = "unknown"
    structured_outputs: str = "unknown"
    vision: str = "unknown"
    embeddings: str = "unknown"
    reasoning_effort: str = "unknown"


@dataclass(frozen=True)
class LocalInferenceRuntimeDescriptor:
    runtime_id: str
    env_vars: tuple[str, ...]
    default_base_url: str | None
    resolved_base_url: str | None
    configuration_error: str | None
    capabilities: LocalInferenceRuntimeCapabilities


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

_LOCAL_DEFAULT_BASE_URLS = {
    "ollama": "http://localhost:11434",
    "llamacpp": "http://localhost:8080",
}

_LOCAL_ENV_NAMES = {
    "ollama": (
        "MLJ_LOCAL_OLLAMA_BASE_URL",
        "MLJ_OLLAMA_BASE_URL",
        "OLLAMA_BASE_URL",
    ),
    "llamacpp": (
        "MLJ_LOCAL_LLAMACPP_BASE_URL",
        "MLJ_LOCAL_LLAMA_CPP_BASE_URL",
        "MLJ_LLAMACPP_BASE_URL",
        "LLAMACPP_BASE_URL",
        "LLAMA_CPP_BASE_URL",
    ),
}

_TRUSTED_IPV4_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.168.0.0/16",
    )
)
_TRUSTED_IPV6_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in (
        "::1/128",
        "fc00::/7",
        "fe80::/10",
    )
)


def resolve_local_inference_base_url(runtime: str, config: Any = None) -> str:
    """Resolve and validate the OpenAI-compatible ``/v1`` base URL."""
    descriptor = describe_local_inference_runtime(runtime, config)
    if descriptor.configuration_error:
        raise LocalInferenceConfigError(descriptor.configuration_error)
    assert descriptor.resolved_base_url is not None
    return descriptor.resolved_base_url


def describe_local_inference_runtime(
    runtime: str,
    config: Any = None,
    env: Mapping[str, str] | None = None,
) -> LocalInferenceRuntimeDescriptor:
    """Describe a local runtime without probing providers or daemons."""
    if runtime not in _LOCAL_DEFAULT_BASE_URLS:
        allowed = ", ".join(sorted(_LOCAL_DEFAULT_BASE_URLS))
        return LocalInferenceRuntimeDescriptor(
            runtime_id=runtime,
            env_vars=(),
            default_base_url=None,
            resolved_base_url=None,
            configuration_error=(
                f"Unsupported local inference runtime {runtime!r}; "
                f"expected one of: {allowed}"
            ),
            capabilities=LocalInferenceRuntimeCapabilities(),
        )

    env_map = os.environ if env is None else env
    resolved_base_url = None
    configuration_error = None
    try:
        raw = _base_url_from_env(runtime, env_map)
        if raw is None:
            raw = _base_url_from_config(runtime, config)
        if raw is None:
            raw = _LOCAL_DEFAULT_BASE_URLS[runtime]
        resolved_base_url = _validate_and_normalize_base_url(runtime, raw)
    except LocalInferenceConfigError as exc:
        configuration_error = str(exc)

    return LocalInferenceRuntimeDescriptor(
        runtime_id=runtime,
        env_vars=_LOCAL_ENV_NAMES[runtime],
        default_base_url=_LOCAL_DEFAULT_BASE_URLS[runtime],
        resolved_base_url=resolved_base_url,
        configuration_error=configuration_error,
        capabilities=LocalInferenceRuntimeCapabilities(),
    )


def list_local_inference_runtime_descriptors(
    config: Any = None,
    env: Mapping[str, str] | None = None,
) -> tuple[LocalInferenceRuntimeDescriptor, ...]:
    """Return descriptors for supported local runtimes in stable order."""
    return tuple(
        describe_local_inference_runtime(runtime, config=config, env=env)
        for runtime in _LOCAL_DEFAULT_BASE_URLS
    )


def supported_local_runtimes() -> frozenset[str]:
    return frozenset(_LOCAL_DEFAULT_BASE_URLS)


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
            probe, LOCAL_INFERENCE_PROBE_CONFIG_ERROR, probe.configuration_error,
            model_id=probe.expected_model,
        )
    if not probe.url:
        return _probe_classification(
            probe, LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
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
            probe, LOCAL_INFERENCE_PROBE_UNAVAILABLE,
            "No /v1/models payload supplied",
            model_id=probe.expected_model,
        )

    entries, malformed = _parse_models_payload(models_payload)
    if malformed is not None:
        return _probe_classification(
            probe, LOCAL_INFERENCE_PROBE_MALFORMED, malformed,
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
            probe, LOCAL_INFERENCE_PROBE_MODEL_MISSING,
            f"Model {expected_model!r} was not listed by /v1/models",
            model_id=expected_model,
        )

    listed_model = model_entry["id"]
    tool_calling = _extract_tool_calling_state(model_entry)
    if tool_calling == "unknown":
        return _probe_classification(
            probe, LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN,
            (
                f"Model {listed_model!r} is listed, but /v1/models does not "
                "advertise tool-call support"
            ),
            model_id=listed_model,
            tool_calling=tool_calling,
        )

    return _probe_classification(
        probe, LOCAL_INFERENCE_PROBE_AVAILABLE,
        f"Model {listed_model!r} is listed by /v1/models",
        model_id=listed_model, tool_calling=tool_calling,
    )


def _base_url_from_env(runtime: str, env: Mapping[str, str]) -> str | None:
    for name in _LOCAL_ENV_NAMES[runtime]:
        if name in env:
            return env[name]
    return None


def _base_url_from_config(runtime: str, config: Any) -> str | None:
    if config is None:
        return None

    candidates = (
        ("local_inference_base_urls", runtime),
        ("local_inference_base_urls", f"{runtime}_base_url"),
        ("local_inference", runtime, "base_url"),
        ("local_inference", f"{runtime}_base_url"),
        (f"local_{runtime}_base_url",),
        (f"{runtime}_base_url",),
    )
    if runtime == "llamacpp":
        candidates += (
            ("local_inference_base_urls", "llama_cpp"),
            ("local_inference_base_urls", "llama_cpp_base_url"),
            ("local_inference", "llama_cpp", "base_url"),
            ("local_inference", "llama_cpp_base_url"),
            ("local_llama_cpp_base_url",),
            ("llama_cpp_base_url",),
        )

    for path in candidates:
        value = _get_config_path(config, path)
        if value is not None:
            return value
    return None


def _get_config_path(config: Any, path: tuple[str, ...]) -> str | None:
    current: Any = config
    for key in path:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return None
    if not isinstance(current, str):
        raise LocalInferenceConfigError(
            f"Local inference base URL at {'.'.join(path)} must be a string"
        )
    return current


def _validate_and_normalize_base_url(runtime: str, raw_url: str) -> str:
    raw = raw_url.strip()
    if not raw:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL: value is empty"
        )

    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"}:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL {raw_url!r}: scheme must be http or https"
        )
    if not parsed.hostname:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL {raw_url!r}: host is required"
        )
    if parsed.username or parsed.password:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL {raw_url!r}: credentials are not allowed"
        )
    if parsed.query or parsed.fragment:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL {raw_url!r}: query and fragment are not allowed"
        )
    try:
        parsed.port
    except ValueError as exc:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL {raw_url!r}: invalid port"
        ) from exc
    if not _is_trusted_local_host(parsed.hostname):
        raise LocalInferenceConfigError(
            f"Rejected local/{runtime} base URL {raw_url!r}: host must be localhost or a private IP address"
        )

    path = parsed.path.rstrip("/")
    if not path:
        path = "/v1"
    elif path == "/v1":
        path = "/v1"
    else:
        raise LocalInferenceConfigError(
            f"Invalid local/{runtime} base URL {raw_url!r}: path must be empty or /v1"
        )

    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _is_trusted_local_host(hostname: str) -> bool:
    host = hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    if host in {"host.docker.internal", "host.containers.internal"}:
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    networks = _TRUSTED_IPV4_NETWORKS if ip.version == 4 else _TRUSTED_IPV6_NETWORKS
    return any(ip in network for network in networks)


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
        and parts[1] in _LOCAL_DEFAULT_BASE_URLS
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
