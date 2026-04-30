"""Pure endpoint resolution for local OpenAI-compatible inference."""

from __future__ import annotations

import ipaddress
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class LocalInferenceConfigError(ValueError):
    """Invalid local inference endpoint configuration."""


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
    if runtime not in _LOCAL_DEFAULT_BASE_URLS:
        allowed = ", ".join(sorted(_LOCAL_DEFAULT_BASE_URLS))
        raise LocalInferenceConfigError(
            f"Unsupported local inference runtime {runtime!r}; expected one of: {allowed}"
        )

    raw = _base_url_from_env(runtime)
    if raw is None:
        raw = _base_url_from_config(runtime, config)
    if raw is None:
        raw = _LOCAL_DEFAULT_BASE_URLS[runtime]

    return _validate_and_normalize_base_url(runtime, raw)


def supported_local_runtimes() -> frozenset[str]:
    return frozenset(_LOCAL_DEFAULT_BASE_URLS)


def _base_url_from_env(runtime: str) -> str | None:
    for name in _LOCAL_ENV_NAMES[runtime]:
        if name in os.environ:
            return os.environ[name]
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
