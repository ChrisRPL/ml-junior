from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.flow_templates import (
    FlowTemplateError,
    load_flow_template,
    parse_flow_template,
)


FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "flow_templates"


def test_valid_template_fixture_parses() -> None:
    template = load_flow_template(FIXTURE_DIR / "valid_v1.json")

    assert template.id == "mnist-baseline"
    assert template.name == "MNIST Baseline"
    assert template.version == "v1"
    assert template.inputs[0].model_dump() == {
        "id": "metric",
        "type": "string",
        "required": True,
        "default": "accuracy",
        "description": "Primary validation metric.",
    }
    assert template.budgets.model_dump() == {
        "max_gpu_hours": 4.0,
        "max_runs": 2,
        "max_wall_clock_hours": 8.0,
        "max_llm_usd": 1.25,
    }
    assert template.permissions[0].model_dump() == {
        "id": "hf-token",
        "risk": "low",
        "action": "read",
        "target": "huggingface-profile",
        "description": "Read the configured Hugging Face identity.",
    }
    assert template.approval_points[0].model_dump() == {
        "id": "gpu-run",
        "risk": "medium",
        "action": "launch",
        "target": "huggingface-job",
        "description": "Start a remote GPU job.",
    }
    assert template.required_outputs[0].id == "metrics-json"
    assert template.artifacts[0].id == "model-card"
    assert template.verifiers[0].model_dump() == {
        "id": "accuracy-threshold",
        "type": "metric",
        "description": "Accuracy is present and above the configured threshold.",
        "required": True,
    }
    assert template.phases[0].model_dump() == {
        "id": "train",
        "name": "Train",
        "objective": "Train a baseline model and capture metrics.",
        "status": "pending",
        "order": 1,
        "required_outputs": ["metrics-json"],
        "approval_points": ["gpu-run"],
        "verifiers": ["accuracy-threshold"],
    }


def test_parser_accepts_dicts() -> None:
    raw = json.loads((FIXTURE_DIR / "valid_v1.json").read_text())

    template = parse_flow_template(raw)

    assert template.id == "mnist-baseline"
    assert template.phases[0].approval_points == ["gpu-run"]


@pytest.mark.parametrize(
    ("fixture_name", "expected_message"),
    [
        ("missing_version.json", "version is required"),
        ("unsupported_version.json", "Unsupported schema version 'v2'"),
        ("duplicate_input_ids.json", "duplicate input id: paper_url"),
        ("duplicate_phase_ids.json", "duplicate phase id: train"),
        (
            "unknown_approval_reference.json",
            "unknown phase train approval_points reference: gpu-run",
        ),
        ("empty_phases.json", "phases must contain at least one phase"),
    ],
)
def test_invalid_fixtures_fail_with_useful_errors(
    fixture_name: str,
    expected_message: str,
) -> None:
    with pytest.raises(FlowTemplateError, match=expected_message):
        load_flow_template(FIXTURE_DIR / fixture_name)
