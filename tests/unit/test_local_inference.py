from __future__ import annotations

from dataclasses import asdict
from types import SimpleNamespace

from agent.core.local_inference import (
    LOCAL_INFERENCE_HEALTH_PROBE,
    LOCAL_INFERENCE_MODELS_PROBE,
    LOCAL_INFERENCE_PROBE_AVAILABLE,
    LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
    LOCAL_INFERENCE_PROBE_MALFORMED,
    LOCAL_INFERENCE_PROBE_MODEL_MISSING,
    LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN,
    LOCAL_INFERENCE_PROBE_UNAVAILABLE,
    build_local_inference_probe_descriptors,
    classify_local_inference_probe_result,
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


def test_probe_descriptors_use_openai_compatible_models_endpoint():
    descriptor = describe_local_inference_runtime("ollama", env={})

    health_probe, models_probe = build_local_inference_probe_descriptors(
        descriptor,
        expected_model="local/ollama/llama3.2:latest",
    )

    assert health_probe.runtime_id == "ollama"
    assert health_probe.probe_type == LOCAL_INFERENCE_HEALTH_PROBE
    assert health_probe.method == "GET"
    assert health_probe.endpoint_path == "/models"
    assert health_probe.url == "http://localhost:11434/v1/models"
    assert health_probe.expected_model is None
    assert health_probe.configuration_error is None

    assert models_probe.runtime_id == "ollama"
    assert models_probe.probe_type == LOCAL_INFERENCE_MODELS_PROBE
    assert models_probe.method == "GET"
    assert models_probe.url == "http://localhost:11434/v1/models"
    assert models_probe.expected_model == "local/ollama/llama3.2:latest"
    assert models_probe.configuration_error is None


def test_probe_descriptors_preserve_configuration_errors_without_urls():
    descriptor = describe_local_inference_runtime(
        "llamacpp",
        env={"MLJ_LOCAL_LLAMACPP_BASE_URL": "https://api.openai.com/v1"},
    )

    health_probe, models_probe = build_local_inference_probe_descriptors(
        descriptor,
        expected_model="qwen3-coder",
    )

    assert health_probe.url is None
    assert health_probe.configuration_error == descriptor.configuration_error
    assert models_probe.url is None
    assert models_probe.configuration_error == descriptor.configuration_error

    classification = classify_local_inference_probe_result(
        models_probe,
        {"data": [{"id": "qwen3-coder"}]},
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_CONFIG_ERROR
    assert "host must be localhost or a private IP address" in (
        classification.message
    )


def test_health_probe_classifies_well_formed_models_payload_as_available():
    descriptor = describe_local_inference_runtime("ollama", env={})
    health_probe, _models_probe = build_local_inference_probe_descriptors(descriptor)

    classification = classify_local_inference_probe_result(
        health_probe,
        {"object": "list", "data": []},
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_AVAILABLE
    assert classification.probe_type == LOCAL_INFERENCE_HEALTH_PROBE


def test_probe_classifies_caller_supplied_errors_as_unavailable():
    descriptor = describe_local_inference_runtime("ollama", env={})
    health_probe, _models_probe = build_local_inference_probe_descriptors(descriptor)

    classification = classify_local_inference_probe_result(
        health_probe,
        error=TimeoutError("connection refused"),
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_UNAVAILABLE
    assert classification.error == "connection refused"


def test_models_probe_classifies_listed_model_with_tool_support_as_available():
    descriptor = describe_local_inference_runtime("ollama", env={})
    _health_probe, models_probe = build_local_inference_probe_descriptors(
        descriptor,
        expected_model="local/ollama/llama3.2:latest",
    )

    classification = classify_local_inference_probe_result(
        models_probe,
        {
            "object": "list",
            "data": [
                {
                    "id": "llama3.2:latest",
                    "object": "model",
                    "capabilities": {"tool_calling": "supported"},
                }
            ],
        },
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_AVAILABLE
    assert classification.model_id == "llama3.2:latest"
    assert classification.tool_calling == "supported"


def test_models_probe_classifies_missing_model():
    descriptor = describe_local_inference_runtime("llamacpp", env={})
    _health_probe, models_probe = build_local_inference_probe_descriptors(
        descriptor,
        expected_model="qwen3-coder",
    )

    classification = classify_local_inference_probe_result(
        models_probe,
        {"data": [{"id": "other-model", "supports_tools": True}]},
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_MODEL_MISSING
    assert classification.model_id == "qwen3-coder"


def test_models_probe_classifies_malformed_payloads():
    descriptor = describe_local_inference_runtime("ollama", env={})
    _health_probe, models_probe = build_local_inference_probe_descriptors(
        descriptor,
        expected_model="llama3.2:latest",
    )

    classification = classify_local_inference_probe_result(
        models_probe,
        {"data": {"id": "llama3.2:latest"}},
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_MALFORMED
    assert "/v1/models payload data must be a list" in classification.message


def test_models_probe_classifies_unknown_tool_support_separately():
    descriptor = describe_local_inference_runtime("ollama", env={})
    _health_probe, models_probe = build_local_inference_probe_descriptors(
        descriptor,
        expected_model="llama3.2:latest",
    )

    classification = classify_local_inference_probe_result(
        models_probe,
        {"data": [{"id": "llama3.2:latest", "object": "model"}]},
    )

    assert classification.status == LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN
    assert classification.model_id == "llama3.2:latest"
    assert classification.tool_calling == "unknown"
