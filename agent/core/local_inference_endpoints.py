"""Endpoint resolution for local inference runtimes."""

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
