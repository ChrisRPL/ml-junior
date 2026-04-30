from __future__ import annotations

import socket

from agent.core.local_inference import (
    LOCAL_INFERENCE_DOCTOR_PROVIDER_KIND,
    LOCAL_INFERENCE_PROBE_CONFIG_ERROR,
    LOCAL_INFERENCE_PROBE_MALFORMED,
    LOCAL_INFERENCE_PROBE_MODEL_MISSING,
    LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN,
    LOCAL_INFERENCE_PROBE_UNAVAILABLE,
    build_local_inference_doctor_report,
    build_local_inference_probe_descriptors,
    classify_local_inference_probe_result,
    describe_local_inference_runtime,
)


def test_doctor_report_builds_without_daemon_or_network_dependency(monkeypatch):
    def fail_socket(*_args, **_kwargs):
        raise AssertionError("doctor report builder must not open sockets")

    monkeypatch.setattr(socket, "socket", fail_socket)
    runtime = describe_local_inference_runtime("ollama", env={})
    probes = build_local_inference_probe_descriptors(
        runtime,
        expected_model="local/ollama/llama3.2:latest",
    )
    classification = classify_local_inference_probe_result(
        probes[0],
        error=TimeoutError(
            "Authorization: Bearer hf_doctorsecret123 "
            "prompt: /Users/krzysztof/private prompt"
        ),
    )

    report = build_local_inference_doctor_report(runtime, probes, [classification])

    assert report.runtime_id == "ollama"
    assert report.provider_kind == LOCAL_INFERENCE_DOCTOR_PROVIDER_KIND
    assert report.model_alias == "llama3.2:latest"
    assert report.host_class == "localhost"
    assert report.models_url == "http://localhost:11434/v1/models"
    assert report.status == LOCAL_INFERENCE_PROBE_UNAVAILABLE
    assert any("Start the ollama" in hint for hint in report.remediation_hints)
    assert "hf_doctorsecret123" not in str(report.redacted_messages)
    assert "/Users/krzysztof" not in str(report.redacted_messages)
    assert "prompt: [REDACTED]" in report.redacted_messages[0]


def test_doctor_report_covers_malformed_models_payload():
    runtime = describe_local_inference_runtime("llamacpp", env={})
    probes = build_local_inference_probe_descriptors(
        runtime,
        expected_model="local/llamacpp/qwen3-coder",
    )
    classification = classify_local_inference_probe_result(
        probes[1],
        {"data": {"id": "qwen3-coder"}},
    )

    report = build_local_inference_doctor_report(runtime, probes, [classification])

    assert report.runtime_id == "llamacpp"
    assert report.model_alias == "qwen3-coder"
    assert report.host_class == "localhost"
    assert report.models_url == "http://localhost:8080/v1/models"
    assert report.status == LOCAL_INFERENCE_PROBE_MALFORMED
    assert report.redacted_messages == (
        "/v1/models payload data must be a list",
    )
    assert "OpenAI-compatible /v1/models response" in report.remediation_hints[0]


def test_doctor_report_covers_missing_model():
    runtime = describe_local_inference_runtime("ollama", env={})
    probes = build_local_inference_probe_descriptors(
        runtime,
        expected_model="local/ollama/llama3.2:latest",
    )
    classification = classify_local_inference_probe_result(
        probes[1],
        {"data": [{"id": "other-model", "supports_tools": True}]},
    )

    report = build_local_inference_doctor_report(runtime, probes, [classification])

    assert report.status == LOCAL_INFERENCE_PROBE_MODEL_MISSING
    assert report.model_alias == "llama3.2:latest"
    assert report.redacted_messages == (
        "Model 'local/ollama/llama3.2:latest' was not listed by /v1/models",
    )
    assert "llama3.2:latest" in report.remediation_hints[0]


def test_doctor_report_covers_config_error_and_hides_untrusted_url_details():
    runtime = describe_local_inference_runtime(
        "ollama",
        env={
            "MLJ_LOCAL_OLLAMA_BASE_URL": (
                "https://api.openai.com/v1?token=hf_doctorsecret123"
            )
        },
    )
    probes = build_local_inference_probe_descriptors(
        runtime,
        expected_model="local/ollama/llama3.2:latest",
    )
    classification = classify_local_inference_probe_result(
        probes[1],
        {"data": [{"id": "llama3.2:latest"}]},
    )

    report = build_local_inference_doctor_report(runtime, probes, [classification])

    assert report.status == LOCAL_INFERENCE_PROBE_CONFIG_ERROR
    assert report.host_class == "unavailable"
    assert report.models_url is None
    assert any("Fix local/ollama base URL" in hint for hint in report.remediation_hints)
    assert "hf_doctorsecret123" not in str(report.redacted_messages)
    assert "[REDACTED]" in str(report.redacted_messages)


def test_doctor_report_covers_tool_support_unknown_on_private_ip():
    runtime = describe_local_inference_runtime(
        "llamacpp",
        env={"MLJ_LOCAL_LLAMACPP_BASE_URL": "http://192.168.1.42:9090"},
    )
    probes = build_local_inference_probe_descriptors(
        runtime,
        expected_model="local/llamacpp/qwen3-coder",
    )
    classification = classify_local_inference_probe_result(
        probes[1],
        {"data": [{"id": "qwen3-coder", "object": "model"}]},
    )

    report = build_local_inference_doctor_report(runtime, probes, [classification])

    assert report.status == LOCAL_INFERENCE_PROBE_TOOL_SUPPORT_UNKNOWN
    assert report.host_class == "private-ip"
    assert report.models_url == "http://192.168.1.42:9090/v1/models"
    assert report.model_alias == "qwen3-coder"
    assert "tool calls" in report.remediation_hints[0]
