from __future__ import annotations

from agent.core.redaction import (
    REDACTED,
    REDACTED_DATASET_ROWS,
    REDACTION_NONE,
    REDACTION_PARTIAL,
    REDACTION_REDACTED,
    redact_string,
    redact_value,
)


def test_redacts_obvious_secret_patterns_in_strings():
    raw = (
        "HF_TOKEN=hf_testsecret123456789 and "
        "GITHUB_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456 "
        "Authorization: Bearer hf_bearersecret123456 "
        "https://huggingface.co/datasets/me/private?token=hf_querysecret123456 "
        "/Users/alice/project/file.py"
    )

    result = redact_string(raw)

    assert result.status == REDACTION_PARTIAL
    assert "hf_testsecret123456789" not in result.value
    assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in result.value
    assert "hf_bearersecret123456" not in result.value
    assert "hf_querysecret123456" not in result.value
    assert "/Users/alice" not in result.value
    assert "HF_TOKEN=[REDACTED]" in result.value
    assert "GITHUB_TOKEN=[REDACTED]" in result.value
    assert "Authorization: Bearer [REDACTED]" in result.value
    assert "token=[REDACTED]" in result.value
    assert "/Users/[USER]/project/file.py" in result.value


def test_redacts_secret_key_values_recursively_without_mutating_input():
    raw = {
        "env": {
            "HF_TOKEN": "hf_value_from_env",
            "GITHUB_TOKEN": "ghp_value_from_env",
            "token_count": 12,
        },
        "headers": {"Authorization": "Bearer hf_headersecret123456"},
        "note": "token_count=12 stays observable",
    }

    result = redact_value(raw)

    assert result.status == REDACTION_REDACTED
    assert result.value["env"]["HF_TOKEN"] == REDACTED
    assert result.value["env"]["GITHUB_TOKEN"] == REDACTED
    assert result.value["env"]["token_count"] == 12
    assert result.value["headers"]["Authorization"] == REDACTED
    assert result.value["note"] == "token_count=12 stays observable"
    assert raw["env"]["HF_TOKEN"] == "hf_value_from_env"
    assert raw["headers"]["Authorization"] == "Bearer hf_headersecret123456"


def test_private_dataset_row_examples_are_redacted_structurally():
    raw = {
        "dataset": "owner/private-dataset",
        "private": True,
        "schema": {"text": "string"},
        "rows": [
            {"row": {"text": "patient secret row", "label": "diagnosis"}},
        ],
    }

    result = redact_value(raw)

    assert result.status == REDACTION_REDACTED
    assert result.value["dataset"] == "owner/private-dataset"
    assert result.value["private"] is True
    assert result.value["schema"] == {"text": "string"}
    assert result.value["rows"] == REDACTED_DATASET_ROWS
    assert "patient secret row" not in str(result.value)


def test_noop_redaction_preserves_public_payload():
    raw = {"event_type": "turn_complete", "data": {"history_size": 4}}

    result = redact_value(raw)

    assert result.status == REDACTION_NONE
    assert result.value == raw
