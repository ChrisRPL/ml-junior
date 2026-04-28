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


def _assert_seeded_values_removed(value: object, seeded_values: list[str]) -> None:
    rendered = str(value)
    for seeded_value in seeded_values:
        assert seeded_value not in rendered


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


def test_redaction_marker_is_idempotent_for_env_assignments():
    raw = "HF_TOKEN=hf_testsecret123456789"
    once = redact_string(raw).value
    twice = redact_string(once).value

    assert once == "HF_TOKEN=[REDACTED]"
    assert twice == once


def test_redacts_openai_api_keys_in_strings_and_structures():
    raw = (
        "OPENAI_API_KEY=sk-proj-openai1234567890 and "
        "Authorization: Bearer sk-openai1234567890"
    )

    result = redact_string(raw)

    assert result.status == REDACTION_PARTIAL
    assert "sk-proj-openai1234567890" not in result.value
    assert "sk-openai1234567890" not in result.value
    assert "OPENAI_API_KEY=[REDACTED]" in result.value
    assert "Authorization: Bearer [REDACTED]" in result.value

    structured = redact_value({"OPENAI_API_KEY": "sk-proj-openai1234567890"})

    assert structured.status == REDACTION_REDACTED
    assert structured.value == {"OPENAI_API_KEY": REDACTED}


def test_redacts_job_logs_opaque_auth_keys_query_secrets_and_local_paths():
    seeded_values = [
        "hf_joblogsecret123456789",
        "sk-proj-joblogopaque123456789",
        "quoted-access-token-123456789",
        "flag-secret-value-123456789",
        "query-client-secret-123456789",
        "query-signature-123456789",
    ]
    raw = (
        "Job log:\n"
        "  export HF_TOKEN=hf_joblogsecret123456789\n"
        "  Authorization: token sk-proj-joblogopaque123456789\n"
        "  {'access_token': 'quoted-access-token-123456789'}\n"
        "  python train.py --token flag-secret-value-123456789 "
        "--epochs 3 --dataset owner/public\n"
        "  https://example.test/callback?client_secret=query-client-secret-123456789"
        "&signature=query-signature-123456789&dataset=owner/public\n"
        "  paths: /Users/alice/project /home/bob/.cache "
        r"C:\Users\carol\AppData C:/Users/dave/project"
    )

    result = redact_string(raw)

    assert result.status == REDACTION_PARTIAL
    _assert_seeded_values_removed(result.value, seeded_values)
    assert "HF_TOKEN=[REDACTED]" in result.value
    assert "Authorization: token [REDACTED]" in result.value
    assert "'access_token': '[REDACTED]'" in result.value
    assert "--token [REDACTED]" in result.value
    assert "client_secret=[REDACTED]" in result.value
    assert "signature=[REDACTED]" in result.value
    assert "/Users/[USER]/project" in result.value
    assert "/home/[USER]/.cache" in result.value
    assert r"C:\Users\[USER]\AppData" in result.value
    assert "C:/Users/[USER]/project" in result.value
    assert "--epochs 3" in result.value
    assert "dataset=owner/public" in result.value


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


def test_redacts_private_rows_without_hiding_public_metadata():
    seeded_values = [
        "patient secret row",
        "private example text",
        "private preview text",
    ]
    raw = {
        "dataset": "owner/private-dataset",
        "gated": True,
        "row_count": 3,
        "schema": {"text": "string"},
        "sample_rows": [{"text": "patient secret row"}],
        "examples": [{"text": "private example text"}],
        "preview": [{"text": "private preview text"}],
    }

    result = redact_value(raw)

    assert result.status == REDACTION_REDACTED
    _assert_seeded_values_removed(result.value, seeded_values)
    assert result.value["dataset"] == "owner/private-dataset"
    assert result.value["gated"] is True
    assert result.value["row_count"] == 3
    assert result.value["schema"] == {"text": "string"}
    assert result.value["sample_rows"] == REDACTED_DATASET_ROWS
    assert result.value["examples"] == REDACTED_DATASET_ROWS
    assert result.value["preview"] == REDACTED_DATASET_ROWS


def test_redacts_private_row_blocks_in_strings():
    seeded_values = ["raw private cell value", "another private value"]
    raw = (
        "dataset=owner/private private=true\n"
        "rows:\n"
        "[{'text': 'raw private cell value'}, {'text': 'another private value'}]"
    )

    result = redact_string(raw)

    assert result.status == REDACTION_PARTIAL
    _assert_seeded_values_removed(result.value, seeded_values)
    assert REDACTED_DATASET_ROWS in result.value


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
    raw = {
        "event_type": "turn_complete",
        "data": {
            "history_size": 4,
            "token_count": 12,
            "rows": [{"text": "public sample"}],
        },
    }

    result = redact_value(raw)

    assert result.status == REDACTION_NONE
    assert result.value == raw
