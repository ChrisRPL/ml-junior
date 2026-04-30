import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agent.core.local_inference import LocalInferenceConfigError
from agent.core.llm_params import (
    UnsupportedEffortError,
    _PROVIDER_REGISTRY,
    _resolve_llm_params,
)
from agent.core.model_switcher import (
    SUGGESTED_MODELS,
    _format_switch_error,
    _print_hf_routing_info,
    is_valid_model_id,
    probe_and_switch_model,
)
from backend.routes.agent import AVAILABLE_MODELS, _require_openai_configured


_LOCAL_ENDPOINT_ENV_NAMES = (
    "MLJ_LOCAL_OLLAMA_BASE_URL",
    "MLJ_OLLAMA_BASE_URL",
    "OLLAMA_BASE_URL",
    "MLJ_LOCAL_LLAMACPP_BASE_URL",
    "MLJ_LOCAL_LLAMA_CPP_BASE_URL",
    "MLJ_LLAMACPP_BASE_URL",
    "LLAMACPP_BASE_URL",
    "LLAMA_CPP_BASE_URL",
)


@pytest.fixture(autouse=True)
def _clear_local_endpoint_env(monkeypatch):
    for name in _LOCAL_ENDPOINT_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


class _Console:
    def __init__(self):
        self.messages: list[str] = []

    def print(self, *parts):
        self.messages.append(" ".join(str(part) for part in parts))


def test_openai_direct_params_do_not_use_hf_router_or_tokens(monkeypatch):
    monkeypatch.setenv("INFERENCE_TOKEN", "hf-space-token")
    monkeypatch.setenv("HF_TOKEN", "hf-user-token")
    monkeypatch.setenv("HF_BILL_TO", "test-org")

    params = _resolve_llm_params(
        "openai/gpt-5.5",
        session_hf_token="hf-session-token",
        reasoning_effort="xhigh",
        strict=True,
    )

    assert params == {
        "model": "openai/gpt-5.5",
        "reasoning_effort": "xhigh",
    }


def test_openai_provider_registry_marks_direct_capability():
    provider = _PROVIDER_REGISTRY["openai"]

    assert provider.prefix == "openai/"
    assert provider.credential_env == "OPENAI_API_KEY"
    assert "none" in provider.efforts
    assert "xhigh" in provider.efforts
    assert provider.uses_hf_router is False
    assert provider.sends_hf_billing_headers is False


def test_local_ollama_params_use_dummy_key_and_ignore_remote_credentials(monkeypatch):
    monkeypatch.setenv("INFERENCE_TOKEN", "hf-space-token")
    monkeypatch.setenv("HF_TOKEN", "hf-user-token")
    monkeypatch.setenv("HF_BILL_TO", "test-org")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-remote")

    params = _resolve_llm_params(
        "local/ollama/llama3.2:latest",
        session_hf_token="hf-session-token",
        reasoning_effort="high",
    )

    assert params == {
        "model": "openai/llama3.2:latest",
        "api_base": "http://localhost:11434/v1",
        "api_key": "local-dummy-key",
    }


def test_local_llamacpp_params_use_openai_compatible_defaults():
    params = _resolve_llm_params("local/llamacpp/qwen3-coder")

    assert params == {
        "model": "openai/qwen3-coder",
        "api_base": "http://localhost:8080/v1",
        "api_key": "local-dummy-key",
    }


def test_local_ollama_env_base_url_override_is_normalized(monkeypatch):
    monkeypatch.setenv("MLJ_LOCAL_OLLAMA_BASE_URL", "http://127.0.0.1:9999/")

    params = _resolve_llm_params("local/ollama/llama3.2:latest")

    assert params["api_base"] == "http://127.0.0.1:9999/v1"


def test_local_llamacpp_config_base_url_is_normalized():
    config = SimpleNamespace(
        local_inference={
            "llamacpp": {"base_url": "http://192.168.1.42:9090/v1/"}
        }
    )

    params = _resolve_llm_params("local/llamacpp/qwen3-coder", config=config)

    assert params["api_base"] == "http://192.168.1.42:9090/v1"


def test_local_base_url_rejects_invalid_url(monkeypatch):
    monkeypatch.setenv("MLJ_LOCAL_OLLAMA_BASE_URL", "localhost:11434")

    with pytest.raises(LocalInferenceConfigError) as exc:
        _resolve_llm_params("local/ollama/llama3.2:latest")

    assert "scheme must be http or https" in str(exc.value)


def test_local_base_url_rejects_remote_url(monkeypatch):
    monkeypatch.setenv("MLJ_LOCAL_LLAMACPP_BASE_URL", "https://api.openai.com/v1")

    with pytest.raises(LocalInferenceConfigError) as exc:
        _resolve_llm_params("local/llamacpp/qwen3-coder")

    assert "host must be localhost or a private IP address" in str(exc.value)


def test_local_strict_effort_is_rejected_before_provider_call():
    with pytest.raises(UnsupportedEffortError) as exc:
        _resolve_llm_params(
            "local/ollama/llama3.2:latest",
            reasoning_effort="high",
            strict=True,
        )

    assert "Local inference doesn't accept effort='high'" in str(exc.value)


def test_invalid_local_ids_are_rejected_before_hf_router():
    for model_id in ("local/ollama", "local/ollama/", "local/vllm/model"):
        assert is_valid_model_id(model_id) is False
        with pytest.raises(ValueError) as exc:
            _resolve_llm_params(model_id)

        assert "Invalid local model id" in str(exc.value)


def test_local_ids_skip_hf_router_catalog(monkeypatch):
    from agent.core import hf_router_catalog

    def fail_lookup(_model_id):
        raise AssertionError("local ids must not query HF router catalog")

    monkeypatch.setattr(hf_router_catalog, "lookup", fail_lookup)

    assert _print_hf_routing_info("local/ollama/llama3.2:latest", _Console())


def test_local_switch_skips_effort_probe(monkeypatch):
    async def fail_probe(*_args, **_kwargs):
        raise AssertionError("local ids must not probe daemon/provider")

    class Session:
        def __init__(self):
            self.model_effective_effort: dict[str, str | None] = {}
            self.model_id = None

        def update_model(self, model_id):
            self.model_id = model_id

    monkeypatch.setattr("agent.core.model_switcher.probe_effort", fail_probe)
    config = SimpleNamespace(model_name="openai/gpt-5.5", reasoning_effort="max")
    session = Session()
    console = _Console()

    asyncio.run(
        probe_and_switch_model(
            "local/llamacpp/qwen3-coder",
            config,
            session,
            console,
            hf_token=None,
        )
    )

    assert session.model_id == "local/llamacpp/qwen3-coder"
    assert session.model_effective_effort == {"local/llamacpp/qwen3-coder": None}
    assert all("checking" not in message for message in console.messages)


def test_openai_none_effort_is_forwarded_for_current_gpt_models():
    params = _resolve_llm_params(
        "openai/gpt-5.5",
        reasoning_effort="none",
        strict=True,
    )

    assert params == {
        "model": "openai/gpt-5.5",
        "reasoning_effort": "none",
    }


def test_openai_max_effort_is_rejected_in_strict_mode():
    try:
        _resolve_llm_params(
            "openai/gpt-5.4",
            reasoning_effort="max",
            strict=True,
        )
    except UnsupportedEffortError as exc:
        assert "OpenAI doesn't accept effort='max'" in str(exc)
    else:
        raise AssertionError("Expected UnsupportedEffortError for max effort")


def test_hf_router_rejects_openai_only_xhigh_effort_in_strict_mode():
    try:
        _resolve_llm_params(
            "moonshotai/Kimi-K2.6",
            reasoning_effort="xhigh",
            strict=True,
        )
    except UnsupportedEffortError as exc:
        assert "HF router doesn't accept effort='xhigh'" in str(exc)
    else:
        raise AssertionError("Expected UnsupportedEffortError for xhigh effort")


def test_openai_suggestions_are_visible_in_cli_and_backend_model_lists():
    suggested_ids = {model["id"] for model in SUGGESTED_MODELS}
    backend_ids = {model["id"] for model in AVAILABLE_MODELS}

    assert {"openai/gpt-5.5", "openai/gpt-5.4"} <= suggested_ids
    assert {"openai/gpt-5.5", "openai/gpt-5.4"} <= backend_ids


def test_openai_switch_auth_errors_point_to_openai_api_key():
    message = _format_switch_error(
        "openai/gpt-5.5",
        RuntimeError("authentication failed: invalid api_key"),
    )

    assert "OPENAI_API_KEY" in message
    assert "HF_TOKEN" not in message


def test_backend_openai_selection_requires_server_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    try:
        _require_openai_configured("openai/gpt-5.5")
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["error"] == "openai_api_key_missing"
        assert "OPENAI_API_KEY" in exc.detail["message"]
    else:
        raise AssertionError("Expected missing OPENAI_API_KEY to fail")

    _require_openai_configured("moonshotai/Kimi-K2.6")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-configured1234567890")
    _require_openai_configured("openai/gpt-5.5")
