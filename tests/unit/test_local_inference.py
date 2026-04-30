from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

from agent.core.local_inference import (
    describe_local_inference_runtime,
    list_local_inference_runtime_descriptors,
)


EXPECTED_UNKNOWN_CAPABILITIES = {
    "chat_completions": "unknown",
    "streaming": "unknown",
    "tool_calling": "unknown",
    "structured_outputs": "unknown",
    "vision": "unknown",
    "embeddings": "unknown",
    "reasoning_effort": "unknown",
}


def test_runtime_descriptors_include_ids_env_defaults_and_unknown_capabilities():
    descriptors = list_local_inference_runtime_descriptors(env={})

    assert [descriptor.runtime_id for descriptor in descriptors] == [
        "ollama",
        "llamacpp",
    ]

    by_runtime = {descriptor.runtime_id: descriptor for descriptor in descriptors}
    assert by_runtime["ollama"].env_vars == (
        "MLJ_LOCAL_OLLAMA_BASE_URL",
        "MLJ_OLLAMA_BASE_URL",
        "OLLAMA_BASE_URL",
    )
    assert by_runtime["ollama"].default_base_url == "http://localhost:11434"
    assert by_runtime["ollama"].resolved_base_url == "http://localhost:11434/v1"
    assert by_runtime["ollama"].configuration_error is None

    assert by_runtime["llamacpp"].env_vars == (
        "MLJ_LOCAL_LLAMACPP_BASE_URL",
        "MLJ_LOCAL_LLAMA_CPP_BASE_URL",
        "MLJ_LLAMACPP_BASE_URL",
        "LLAMACPP_BASE_URL",
        "LLAMA_CPP_BASE_URL",
    )
    assert by_runtime["llamacpp"].default_base_url == "http://localhost:8080"
    assert by_runtime["llamacpp"].resolved_base_url == "http://localhost:8080/v1"
    assert by_runtime["llamacpp"].configuration_error is None

    for descriptor in descriptors:
        assert asdict(descriptor.capabilities) == EXPECTED_UNKNOWN_CAPABILITIES


def test_runtime_descriptors_apply_env_overrides_before_defaults():
    env = {
        "OLLAMA_BASE_URL": "http://127.0.0.1:7777",
        "MLJ_LOCAL_OLLAMA_BASE_URL": "http://127.0.0.1:9999/",
        "MLJ_LOCAL_LLAMA_CPP_BASE_URL": "http://192.168.1.42:9090/v1/",
    }

    ollama = describe_local_inference_runtime("ollama", env=env)
    llamacpp = describe_local_inference_runtime("llamacpp", env=env)

    assert ollama.resolved_base_url == "http://127.0.0.1:9999/v1"
    assert ollama.configuration_error is None
    assert llamacpp.resolved_base_url == "http://192.168.1.42:9090/v1"
    assert llamacpp.configuration_error is None


def test_runtime_descriptor_uses_config_when_env_is_missing():
    config = SimpleNamespace(
        local_inference_base_urls={
            "llama_cpp": "http://host.docker.internal:8081"
        }
    )

    descriptor = describe_local_inference_runtime(
        "llamacpp",
        config=config,
        env={},
    )

    assert descriptor.resolved_base_url == "http://host.docker.internal:8081/v1"
    assert descriptor.configuration_error is None


def test_runtime_descriptor_reports_invalid_configuration_without_raising():
    config = {
        "local_inference": {
            "ollama": {"base_url": "https://api.openai.com/v1"}
        }
    }

    descriptor = describe_local_inference_runtime(
        "ollama",
        config=config,
        env={},
    )

    assert descriptor.resolved_base_url is None
    assert descriptor.configuration_error is not None
    assert "host must be localhost or a private IP address" in (
        descriptor.configuration_error
    )
    assert asdict(descriptor.capabilities) == EXPECTED_UNKNOWN_CAPABILITIES


def test_runtime_descriptor_reports_unsupported_runtime_without_raising():
    descriptor = describe_local_inference_runtime("vllm", env={})

    assert descriptor.runtime_id == "vllm"
    assert descriptor.env_vars == ()
    assert descriptor.default_base_url is None
    assert descriptor.resolved_base_url is None
    assert descriptor.configuration_error is not None
    assert "Unsupported local inference runtime 'vllm'" in (
        descriptor.configuration_error
    )
    assert asdict(descriptor.capabilities) == EXPECTED_UNKNOWN_CAPABILITIES
