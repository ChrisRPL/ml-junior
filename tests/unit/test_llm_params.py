from fastapi import HTTPException

from agent.core.llm_params import (
    UnsupportedEffortError,
    _PROVIDER_REGISTRY,
    _resolve_llm_params,
)
from agent.core.model_switcher import (
    SUGGESTED_MODELS,
    _format_switch_error,
)
from backend.routes.agent import AVAILABLE_MODELS, _require_openai_configured


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
